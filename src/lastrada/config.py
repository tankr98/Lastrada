import json
from pathlib import Path
from pydantic import Field
from lastrada.schemas.models import StrictModel


class Settings(StrictModel):
    sample_rate: int = Field(default=8000, ge=8000, le=8000)
    reference_components: int = Field(default=8, ge=1, le=32)
    free_components: int = Field(default=8, ge=1, le=32)
    iterations: int = Field(default=80, ge=10, le=500)
    activation_threshold: float = Field(default=0.55, gt=0, lt=1)
    minimum_interval_seconds: float = Field(default=0.25, gt=0, le=10)
    max_duration_seconds: int = Field(default=600, ge=1, le=600)
    sampleid_chunk_seconds: float = Field(default=5.0, ge=1.0, le=10.0)
    sampleid_hop_seconds: float = Field(default=1.0, ge=0.5, le=5.0)
    # Rank + temporal consistency is the primary rule. -1 disables an absolute
    # cosine floor while keeping the field for backwards-compatible configs.
    sampleid_similarity_threshold: float = Field(default=-1.0, ge=-1, le=1)
    sampleid_batch_size: int = Field(default=4, ge=1, le=16)

    # Optional DTW refinement applied only after SampleID proposes a candidate.
    dtw_enabled: bool = True
    dtw_search_padding_seconds: float = Field(default=4.0, ge=0.0, le=30.0)
    dtw_max_pitch_shift_semitones: int = Field(default=6, ge=0, le=12)
    dtw_min_duration_ratio: float = Field(default=0.5, gt=0, le=1.0)
    dtw_max_duration_ratio: float = Field(default=1.5, ge=1.0, le=3.0)
    dtw_minimum_duration_seconds: float = Field(default=0.5, gt=0, le=10.0)


def load_settings(path="configs/default.json"):
    return (
        Settings.model_validate(json.loads(Path(path).read_text()))
        if Path(path).is_file()
        else Settings()
    )
