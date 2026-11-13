"""Compare an original full-mix passage with estimated derivative stems.

By default Demucs runs only on the derivative candidate region. Each derivative
stem is compared with the timestamped original full-mix passage, avoiding the
requirement that Demucs classify both recordings in exactly the same way. Stem
labels and audio remain model estimates and are supporting evidence only.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from lastrada.alignment.dtw import (
    refine_candidate_dtw_details,
    refine_candidate_rhythm_details,
)
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval
from lastrada.separation.demucs import SeparatedRegion


@dataclass
class StemPairEvidence:
    source_stem: str
    derivative_stem: str
    accepted: bool
    reason: str
    mean_dtw_cost: float | None
    pitch_shift_semitones: int | None
    duration_ratio: float | None
    source_start: float
    source_end: float
    sony_new_start: float
    sony_new_end: float
    refined_new_start: float
    refined_new_end: float
    refined_duration: float
    same_label: bool
    sony_similarity: float | None

    def to_dict(self):
        return asdict(self)


@dataclass
class StemComparisonResult:
    source_region: object
    derivative_region: object
    evidence: list[StemPairEvidence]
    probe: Interval | None = None
    partial: bool = False
    supported_interval: Interval | None = None

    @property
    def accepted(self) -> list[StemPairEvidence]:
        return [item for item in self.evidence if item.accepted]

    @property
    def best(self) -> StemPairEvidence | None:
        # For listening, prefer a separated accepted pair over the full-mix
        # baseline. The complete table still shows every ordered pair.
        for item in self.evidence:
            if item.accepted and (
                item.source_stem != "full_mix"
                or item.derivative_stem != "full_mix"
            ):
                return item
        for item in self.evidence:
            if item.accepted:
                return item
        return self.evidence[0] if self.evidence else None


def candidate_stem_pairs(
    source_stems,
    derivative_stems,
    *,
    include_cross_other: bool = True,
    include_full_mix: bool = True,
    source_full_mix: bool = False,
):
    """Return conservative comparison labels without an all-by-all explosion.

    With ``source_full_mix=True``, the left-hand stem label is a logical
    instrument hypothesis for downstream compatibility. The actual source audio
    for every non-baseline pair is the same original full-mix crop.
    """

    source = set(source_stems)
    derivative = set(derivative_stems)
    ordered = []

    preferred_order = [
        "full_mix",
        "guitar",
        "piano",
        "bass",
        "drums",
        "vocals",
        "other",
    ]

    if source_full_mix:
        if "full_mix" not in source:
            return ordered
        for stem in preferred_order:
            if stem == "full_mix" and not include_full_mix:
                continue
            if stem in derivative:
                ordered.append((stem, stem))
        return ordered

    for stem in preferred_order:
        if stem == "full_mix" and not include_full_mix:
            continue
        if stem in source and stem in derivative:
            ordered.append((stem, stem))

    if include_cross_other:
        cross_pairs = [
            ("guitar", "other"),
            ("other", "guitar"),
            ("piano", "other"),
            ("other", "piano"),
        ]
        for pair in cross_pairs:
            if pair[0] in source and pair[1] in derivative and pair not in ordered:
                ordered.append(pair)

    return ordered


def bounded_stem_probe(interval, maximum=8.0):
    """Take a centered paired fraction; never expand or re-label the match."""

    if interval.original_start is None or interval.original_end is None:
        raise ValueError("Stem comparison requires source timestamps")
    if not 0 < maximum <= 8:
        raise ValueError("Stem probes must be at most eight seconds")
    widths = [
        interval.new_end - interval.new_start,
        interval.original_end - interval.original_start,
    ]
    fraction = min(1.0, maximum / max(widths))
    values = interval.model_dump()
    values.update(end_review=None, ending_review_context=None)
    for prefix, width in zip(("new", "original"), widths, strict=True):
        start = getattr(interval, prefix + "_start")
        end = getattr(interval, prefix + "_end")
        left = start + (width - width * fraction) / 2
        values[prefix + "_start"] = left
        values[prefix + "_end"] = end if fraction == 1 else left + width * fraction
    return Interval.model_validate(values)


def probe_is_partial(probe, interval):
    return any(
        getattr(probe, key) != getattr(interval, key)
        for key in ("new_start", "new_end", "original_start", "original_end")
    )


def _full_mix_region(audio, start: float, end: float, padding_seconds: float):
    if end <= start:
        raise ValueError("Candidate end must be after start")
    if padding_seconds < 0:
        raise ValueError("Stem-separation padding cannot be negative")

    crop_start = max(0.0, float(start) - padding_seconds)
    crop_end = min(float(audio.duration), float(end) + padding_seconds)
    left = max(0, int(round(crop_start * audio.sample_rate)))
    right = min(len(audio.samples), int(round(crop_end * audio.sample_rate)))
    if right <= left:
        raise ValueError("Original full-mix crop is empty")

    samples = np.asarray(audio.samples[left:right], dtype=np.float32).copy()
    crop = Audio(samples, int(audio.sample_rate), len(samples) / float(audio.sample_rate))
    return SeparatedRegion(
        stems={"full_mix": crop},
        offset_seconds=crop_start,
        candidate_start_local=max(0.0, float(start) - crop_start),
        candidate_end_local=max(0.0, float(end) - crop_start),
        crop_duration=crop.duration,
        model_name="original_full_mix",
        cache_path=Path("."),
    )


def compare_candidate_stems(
    original,
    new,
    interval: Interval,
    separator,
    *,
    separation_padding: float = 4.0,
    dtw_search_padding: float = 2.0,
    max_pitch_shift_semitones: int = 6,
    minimum_duration_ratio: float = 0.5,
    maximum_duration_ratio: float = 1.5,
    minimum_duration: float = 0.5,
    include_cross_other: bool = True,
    include_full_mix: bool = True,
    source_full_mix: bool = True,
    parallel_separation: bool = False,
    parallel_dtw: bool = False,
    dtw_workers: int = 2,
) -> StemComparisonResult:
    """Compare bounded crops and return their exact evidence scope.

    Production audio defaults to derivative-only Demucs. A defensive fallback to
    the legacy two-sided separator path remains for callers that supply test
    doubles without real ``Audio`` objects.
    """

    if interval.original_start is None or interval.original_end is None:
        raise ValueError("Stem comparison requires source timestamps")
    candidate = interval
    interval = bounded_stem_probe(candidate)

    def separate(audio, start, end):
        return separator.separate_region(
            audio,
            start,
            end,
            padding_seconds=separation_padding,
        )

    use_source_full_mix = bool(
        source_full_mix
        and hasattr(original, "samples")
        and hasattr(original, "sample_rate")
        and hasattr(original, "duration")
    )

    if use_source_full_mix:
        source_region = _full_mix_region(
            original,
            interval.original_start,
            interval.original_end,
            separation_padding,
        )
        derivative_region = separate(
            new,
            interval.new_start,
            interval.new_end,
        )
    elif parallel_separation:
        # Legacy compatibility for callers that explicitly provide a two-sided
        # separator test double. Production uses the derivative-only path above.
        with ThreadPoolExecutor(max_workers=2) as pool:
            source = pool.submit(
                separate,
                original,
                interval.original_start,
                interval.original_end,
            )
            derivative = pool.submit(
                separate,
                new,
                interval.new_start,
                interval.new_end,
            )
            source_region, derivative_region = source.result(), derivative.result()
    else:
        source_region = separate(
            original,
            interval.original_start,
            interval.original_end,
        )
        derivative_region = separate(
            new,
            interval.new_start,
            interval.new_end,
        )

    local_interval = Interval(
        new_start=derivative_region.candidate_start_local,
        new_end=derivative_region.candidate_end_local,
        original_start=source_region.candidate_start_local,
        original_end=source_region.candidate_end_local,
        source="stem_assisted_candidate",
        status="candidate",
        similarity=interval.similarity,
    )
    pairs = candidate_stem_pairs(
        source_region.stems,
        derivative_region.stems,
        include_cross_other=include_cross_other,
        include_full_mix=include_full_mix,
        source_full_mix=use_source_full_mix,
    )

    def compare_pair(pair):
        source_stem, derivative_stem = pair
        source_audio = (
            source_region.stems["full_mix"]
            if use_source_full_mix
            else source_region.stems[source_stem]
        )
        if derivative_stem == "drums":
            detail = refine_candidate_rhythm_details(
                source_audio,
                derivative_region.stems[derivative_stem],
                local_interval,
                search_padding=dtw_search_padding,
                minimum_duration_ratio=minimum_duration_ratio,
                maximum_duration_ratio=maximum_duration_ratio,
                minimum_duration=minimum_duration,
            )
        else:
            detail = refine_candidate_dtw_details(
                source_audio,
                derivative_region.stems[derivative_stem],
                local_interval,
                search_padding=dtw_search_padding,
                max_pitch_shift_semitones=max_pitch_shift_semitones,
                minimum_duration_ratio=minimum_duration_ratio,
                maximum_duration_ratio=maximum_duration_ratio,
                minimum_duration=minimum_duration,
            )

        local_refined = detail.interval
        refined_start = derivative_region.offset_seconds + local_refined.new_start
        refined_end = derivative_region.offset_seconds + local_refined.new_end
        reason = detail.reason
        if use_source_full_mix:
            reason = (
                f"original full-mix passage → derivative {derivative_stem}: "
                f"{detail.reason}"
            )
        return StemPairEvidence(
            source_stem=source_stem,
            derivative_stem=derivative_stem,
            accepted=detail.accepted,
            reason=reason,
            mean_dtw_cost=detail.mean_cost,
            pitch_shift_semitones=detail.pitch_shift_semitones,
            duration_ratio=detail.duration_ratio,
            source_start=interval.original_start,
            source_end=interval.original_end,
            sony_new_start=interval.new_start,
            sony_new_end=interval.new_end,
            refined_new_start=float(refined_start),
            refined_new_end=float(refined_end),
            refined_duration=float(refined_end - refined_start),
            same_label=source_stem == derivative_stem,
            sony_similarity=interval.similarity,
        )

    if parallel_dtw and len(pairs) > 1:
        worker_count = max(1, min(int(dtw_workers), len(pairs)))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            evidence = list(pool.map(compare_pair, pairs))
    else:
        evidence = [compare_pair(pair) for pair in pairs]

    # Accepted results first; among those, same-label evidence and lower DTW cost
    # rank higher. This is only an ordering rule, not a confidence calculation.
    evidence.sort(
        key=lambda item: (
            not item.accepted,
            not item.same_label,
            float("inf") if item.mean_dtw_cost is None else item.mean_dtw_cost,
            item.source_stem,
            item.derivative_stem,
        )
    )
    return StemComparisonResult(
        source_region,
        derivative_region,
        evidence,
        probe=interval,
        partial=probe_is_partial(interval, candidate),
    )
