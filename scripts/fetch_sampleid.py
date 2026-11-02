"""Download authoritative weights over verified HTTPS and verify provider checksum.
Optional; no client recordings or metadata are transmitted. Supports bounded parallel ranges.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import tempfile
from urllib.request import Request, urlopen

RECORD = "https://zenodo.org/api/records/17413869"
URL = "https://zenodo.org/records/17413869/files/sampleid-best.ckpt?download=1"
EXPECTED_MD5 = "c50d08e54b37e49fbcf8904b1f0f5ca3"


def md5_file(path):
    digest = hashlib.md5(usedforsecurity=False)
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(output, workers=8):
    with urlopen(RECORD, timeout=30) as response:
        files = json.load(response)["files"]
    metadata = next(f for f in files if f["key"] == "sampleid-best.ckpt")
    if metadata["checksum"] != f"md5:{EXPECTED_MD5}":
        raise RuntimeError("Authoritative checksum changed; investigate before installing")
    size = metadata["size"]
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_file() and output.stat().st_size == size and md5_file(output) == EXPECTED_MD5:
        print("Existing checkpoint verified.")
        return
    if output.exists():
        raise RuntimeError("Existing checkpoint failed verification; preserve and investigate it")
    # Each range is retained only after protocol and exact-length verification.
    # Overall authoritative checksum is verified before moving into the installed location.
    with tempfile.TemporaryDirectory(dir=output.parent, prefix="download-") as directory:
        folder = Path(directory)
        chunk_size = (size + workers - 1) // workers
        ranges = [
            (i, start, min(size - 1, start + chunk_size - 1))
            for i, start in enumerate(range(0, size, chunk_size))
        ]

        def part(item):
            index, start, end = item
            request = Request(URL, headers={"Range": f"bytes={start}-{end}"})
            target = folder / str(index)
            with urlopen(request, timeout=60) as response, target.open("wb") as file:
                if (
                    response.status != 206
                    or response.headers.get("Content-Range") != f"bytes {start}-{end}/{size}"
                ):
                    raise RuntimeError("Server did not honor requested byte range")
                while block := response.read(1024 * 1024):
                    file.write(block)
            if target.stat().st_size != end - start + 1:
                raise RuntimeError("Incomplete checkpoint range")
            return index

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(part, item) for item in ranges]
            for completed, future in enumerate(as_completed(futures), 1):
                future.result()
                print(f"Checkpoint ranges complete: {completed}/{len(ranges)}", flush=True)
        combined = folder / "verified.ckpt"
        with combined.open("wb") as file:
            for index, _, _ in ranges:
                with (folder / str(index)).open("rb") as source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        file.write(block)
        if combined.stat().st_size != size or md5_file(combined) != EXPECTED_MD5:
            raise RuntimeError("Checkpoint integrity verification failed")
        combined.replace(output)
    print("Checkpoint verified against authoritative Zenodo checksum.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="checkpoints/sampleid-best.ckpt")
    parser.add_argument("--workers", type=int, default=8, choices=range(1, 33))
    args = parser.parse_args()
    fetch(Path(args.output), args.workers)
