from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import shutil
import subprocess
import tempfile
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

MAX_BYTES = 100 * 1024 * 1024
MAX_SECONDS = 600


@dataclass
class Audio:
    samples: np.ndarray
    sample_rate: int
    duration: float


def normalize(samples):
    y = np.asarray(samples, dtype=np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    if y.ndim != 1 or not len(y) or not np.isfinite(y).all():
        raise ValueError("Audio must be nonempty and finite")
    y = y - y.mean()
    peak = np.max(np.abs(y))
    if peak > 1e-8:
        y = y / peak
    return y


def prepare(samples, sample_rate, target_rate=16000):
    if sample_rate <= 0 or target_rate <= 0:
        raise ValueError("Invalid sample rate")
    y = normalize(samples)
    duration = len(y) / sample_rate
    if duration < 0.5 or duration > MAX_SECONDS:
        raise ValueError(f"Use recordings between 0.5 and {MAX_SECONDS} seconds")
    if sample_rate != target_rate:
        divisor = math.gcd(sample_rate, target_rate)
        y = resample_poly(y, target_rate // divisor, sample_rate // divisor).astype(np.float32)
    return Audio(y, target_rate, duration)


def decode(raw: bytes, target_rate=16000):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("Provide a nonempty audio file of at most 100 MB")
    try:
        # Inspect before allocating a full decoded recording.
        info = sf.info(BytesIO(raw))
        if info.duration > MAX_SECONDS or info.channels > 8:
            raise ValueError("Recording too long or has more than eight channels")
        y, sr = sf.read(BytesIO(raw), dtype="float32", always_2d=True)
    except (sf.LibsndfileError, RuntimeError):
        if not shutil.which("ffmpeg"):
            raise ValueError("Unsupported audio format; install FFmpeg or use WAV/FLAC")
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "input.audio"
            source.write_bytes(raw)
            result = subprocess.run(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(source),
                    "-t",
                    str(MAX_SECONDS + 1),
                    "-f",
                    "f32le",
                    "-ac",
                    "1",
                    "-ar",
                    str(target_rate),
                    "pipe:1",
                ],
                capture_output=True,
                timeout=60,
            )
            if result.returncode:
                raise ValueError("Audio decoding failed; use a valid WAV, FLAC, MP3 or M4A")
            y, sr = np.frombuffer(result.stdout, dtype="<f4"), target_rate
    return prepare(y, sr, target_rate)


def wav_bytes(audio):
    buffer = BytesIO()
    sf.write(buffer, audio.samples, audio.sample_rate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()
