"""Optional local CPU SampleID inference, never an automatic legal detection.
Uses the inspected upstream API, pinned in setup docs. No implicit downloads.
"""

from dataclasses import dataclass
import hashlib
import importlib.util
from pathlib import Path
import numpy as np
from scipy.signal import resample_poly
from lastrada.schemas.models import Interval


class SampleIDUnavailable(RuntimeError):
    pass


@dataclass
class Embeddings:
    values: np.ndarray
    starts: np.ndarray
    ends: np.ndarray


def chunks(audio, seconds=5.0, hop=1.0):
    if seconds <= 0 or hop <= 0 or hop > seconds:
        raise ValueError("Chunk/hop must be positive and hop must not exceed chunk length")
    divisor = np.gcd(audio.sample_rate, 16000)
    samples = resample_poly(audio.samples, 16000 // divisor, audio.sample_rate // divisor)
    length, step = int(seconds * 16000), int(hop * 16000)
    starts = list(range(0, max(1, len(samples) - length + step), step))
    pieces, valid = [], []
    for start in starts:
        segment = samples[start : start + length]
        if np.sqrt(np.mean(segment**2)) < 1e-6:
            continue
        pieces.append(np.pad(segment, (0, length - len(segment))).astype(np.float32))
        valid.append(start / 16000)
    return pieces, np.asarray(valid), np.minimum(np.asarray(valid) + seconds, audio.duration)


def group_candidates(original, new, threshold=0.8, top_k=2, offset_tolerance=1.1):
    if not -1 <= threshold <= 1 or top_k < 1:
        raise ValueError("Invalid similarity configuration")
    if not len(original.values) or not len(new.values):
        return []
    a = original.values / np.maximum(np.linalg.norm(original.values, axis=1, keepdims=True), 1e-12)
    b = new.values / np.maximum(np.linalg.norm(new.values, axis=1, keepdims=True), 1e-12)
    similarity = b @ a.T
    raw = []
    for j, scores in enumerate(similarity):
        for i in np.argsort(scores)[-top_k:][::-1]:
            if scores[i] < threshold:
                continue
            raw.append(
                [
                    float(new.starts[j]),
                    float(new.ends[j]),
                    float(original.starts[i]),
                    float(original.ends[i]),
                    float(np.clip(scores[i], -1, 1)),
                ]
            )
    groups = []
    for candidate in sorted(raw):
        start, end, source_start, source_end, score = candidate
        offset = source_start - start
        compatible = [
            g
            for g in groups
            if start <= g[1]
            and end >= g[0]
            and abs((g[2] - g[0]) - offset) <= offset_tolerance
            and source_start <= g[3]
            and source_end >= g[2]
        ]
        if compatible:
            g = compatible[-1]
            g[0], g[1] = min(g[0], start), max(g[1], end)
            g[2], g[3], g[4] = min(g[2], source_start), max(g[3], source_end), max(g[4], score)
        else:
            groups.append(candidate)
    intervals = [
        Interval(
            new_start=g[0],
            new_end=g[1],
            original_start=g[2],
            original_end=g[3],
            source="sampleid_chunk_cosine",
            status="candidate",
            similarity=g[4],
        )
        for g in groups
    ]
    return sorted(intervals, key=lambda x: (-x.similarity, x.new_start))


class SampleIDAdapter:
    def __init__(self, checkpoint, cache_dir="cache/sampleid", batch_size=4):
        if not checkpoint or not Path(checkpoint).is_file():
            raise SampleIDUnavailable(
                "SampleID checkpoint is not installed. PF-NMF remains available."
            )
        if not importlib.util.find_spec("torch") or not importlib.util.find_spec("sampleid"):
            raise SampleIDUnavailable("Install CPU PyTorch and the pinned Sony SampleID package.")
        if batch_size < 1:
            raise ValueError("Batch size must be positive")
        self.checkpoint = Path(checkpoint)
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        # Content identity ensures a new checkpoint never reuses stale embeddings.
        digest = hashlib.sha256()
        with self.checkpoint.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        self.model_hash = digest.hexdigest()
        self._model = None

    def _load(self):
        if self._model is None:
            import torch
            from sampleid import SampleID

            torch.set_num_threads(2)
            try:
                self._model = SampleID.load_checkpoint(
                    str(self.checkpoint), device=torch.device("cpu")
                )
            except Exception as exc:
                raise SampleIDUnavailable(
                    f"SampleID checkpoint could not load ({type(exc).__name__})."
                ) from exc
        return self._model

    def embed(self, audio, seconds=5.0, hop=1.0):
        key = hashlib.sha256(
            audio.samples.tobytes()
            + f"{audio.sample_rate}:{seconds}:{hop}:{self.model_hash}:v1".encode()
        ).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / f"{key}.npz"
        if cached.is_file():
            with np.load(cached, allow_pickle=False) as data:
                return Embeddings(data["values"], data["starts"], data["ends"])
        pieces, starts, ends = chunks(audio, seconds, hop)
        if not pieces:
            return Embeddings(np.empty((0, 0)), starts, ends)
        import torch

        model = self._load()
        result = []
        try:
            with torch.inference_mode():
                for start in range(0, len(pieces), self.batch_size):
                    batch = torch.from_numpy(np.stack(pieces[start : start + self.batch_size]))
                    result.append(model(batch, audio=True).cpu().numpy().reshape(len(batch), -1))
        except Exception as exc:
            raise SampleIDUnavailable(f"SampleID inference failed ({type(exc).__name__}).") from exc
        values = np.concatenate(result)
        if not np.isfinite(values).all():
            raise SampleIDUnavailable("SampleID produced non-finite embeddings")
        temporary = cached.with_suffix(".tmp")
        with temporary.open("wb") as file:
            np.savez_compressed(file, values=values, starts=starts, ends=ends)
        temporary.replace(cached)
        return Embeddings(values, starts, ends)

    def match(self, original, new, threshold=0.8, seconds=5.0, hop=1.0):
        return group_candidates(
            self.embed(original, seconds, hop), self.embed(new, seconds, hop), threshold=threshold
        )
