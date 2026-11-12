"""Bounded reusable Demucs CLI processes, with the same per-crop timeouts."""

import contextlib
import json
import os
from queue import Queue
import select
import subprocess
import sys
import tempfile
from types import SimpleNamespace


class DemucsProcess:
    def __init__(self, command=None):
        self.command = command or [sys.executable, "-m", __name__]
        self.process = None
        self.log = None

    def run(self, arguments, *, env, timeout):
        if self.process is None:
            self.log = tempfile.TemporaryFile()
            self.process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.log,
                env=env,
                # Remain in the analysis process group so the outer job timeout
                # also kills this child. Only trusted, internally built CLI args
                # travel over this private pipe.
            )
        self.log.seek(0)
        self.log.truncate()
        try:
            self.process.stdin.write((json.dumps(arguments) + "\n").encode())
            self.process.stdin.flush()
            ready, _, _ = select.select([self.process.stdout], [], [], timeout)
            if not ready:
                raise subprocess.TimeoutExpired(self.command, timeout)
            line = self.process.stdout.readline()
            response = json.loads(line) if line else {"returncode": 1}
            self.log.seek(0, os.SEEK_END)
            self.log.seek(max(0, self.log.tell() - 2000))
            result = SimpleNamespace(
                returncode=response["returncode"],
                stdout="",
                stderr=self.log.read().decode(errors="replace"),
            )
            if result.returncode:
                self.close()
            return result
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None
        if self.log is not None:
            self.log.close()
            self.log = None


class DemucsProcessPool:
    """Small process pool with one cached Demucs model per worker."""

    def __init__(self, workers=1):
        if not 1 <= workers <= 8:
            raise ValueError("Demucs process workers must be between one and eight")
        self.workers = [DemucsProcess() for _ in range(workers)]
        self.idle = Queue()
        for worker in self.workers:
            self.idle.put(worker)

    def run(self, arguments, *, env, timeout):
        worker = self.idle.get(timeout=timeout)
        try:
            return worker.run(arguments, env=env, timeout=timeout)
        finally:
            self.idle.put(worker)

    def close(self):
        for worker in self.workers:
            worker.close()


def main():
    # Use the upstream CLI for decoding, normalization, inference and output
    # quantization. Only reuse its Separator instance for identical parameters.
    with contextlib.redirect_stdout(sys.stderr):
        from demucs import separate
    constructor = separate.Separator
    cached_key, cached = None, None

    def separator(*args, **kwargs):
        nonlocal cached_key, cached
        key = (args, tuple(sorted(kwargs.items())))
        if key != cached_key:
            cached = None
            cached = constructor(*args, **kwargs)
            cached_key = key
        return cached

    separate.Separator = separator
    for line in sys.stdin:
        code = 0
        try:
            arguments = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                separate.main(arguments)
        except BaseException as error:
            print(f"Demucs failed: {error}", file=sys.stderr, flush=True)
            code = 1
        print(json.dumps({"returncode": code}), flush=True)
        if code:
            break


if __name__ == "__main__":
    main()
