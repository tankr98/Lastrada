"""Grouped, bounded and parallel stem evidence for the deployed review flow.

The frontend still receives one row per suggested timestamp.  Internally, those
rows are grouped with the same loop-family logic used by the reviewer interface.
Only a small, diverse set of representative occurrences is separated.  A group
verdict is then propagated back to the existing rows without changing the UI
contract.
"""

from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import ExitStack
from dataclasses import dataclass
import math
import os
from pathlib import Path
from threading import Lock
from time import monotonic

from lastrada.alignment.stems import compare_candidate_stems, probe_is_partial
from lastrada.pipeline import _stem_evidence_records
from lastrada.reporting.loop_groups import LoopFamily, group_loop_families
from lastrada.schemas.models import InstrumentOccurrence
from lastrada.separation.demucs import DemucsSeparator, StemSeparationUnavailable
from lastrada.separation.occurrences import (
    EVIDENCE_VERSION,
    occurrence_id,
    occurrence_rows,
    stabilize_source_descriptions,
)
from lastrada.separation.presence import LABELS, context_probe, describe_region


MIN_PROBE_SECONDS = 2.0
EPSILON = 1e-9


@dataclass
class GroupPlan:
    family: LoopFamily
    members: list[InstrumentOccurrence]
    representatives: list[InstrumentOccurrence]


def _duration(start, end) -> float:
    if start is None or end is None:
        return 0.0
    return max(0.0, float(end) - float(start))


def _usable_duration(row: InstrumentOccurrence) -> float:
    interval = row.interval
    return min(
        _duration(interval.new_start, interval.new_end),
        _duration(interval.original_start, interval.original_end),
    )


def _source_priority(row: InstrumentOccurrence) -> int:
    source = row.interval.source.lower()
    if "expert" in source:
        return 6
    if "direct_waveform" in source:
        return 5
    if "dtw" in source:
        return 4
    if "sampleid" in source:
        return 3
    return 1


def _quality(row: InstrumentOccurrence) -> tuple[float, int, float, float]:
    interval = row.interval
    similarity = interval.similarity if interval.similarity is not None else -2.0
    source_duration = _duration(interval.original_start, interval.original_end)
    new_duration = _duration(interval.new_start, interval.new_end)
    balance = -abs(
        math.log(max(EPSILON, new_duration / max(EPSILON, source_duration)))
    )
    return similarity, _source_priority(row), balance, _usable_duration(row)


def _center(row: InstrumentOccurrence) -> float:
    return (row.interval.new_start + row.interval.new_end) / 2.0


def _select_representatives(
    family: LoopFamily,
    rows_by_id: dict[str, InstrumentOccurrence],
    limit: int,
) -> list[InstrumentOccurrence]:
    """Choose strongest, longest and temporally diverse occurrences."""

    candidates = []
    seen = set()
    for interval in family.occurrences:
        key = occurrence_id(interval)
        row = rows_by_id.get(key)
        if row is None or key in seen:
            continue
        if interval.original_start is None or interval.original_end is None:
            continue
        seen.add(key)
        candidates.append(row)

    if not candidates:
        return []

    eligible = [row for row in candidates if _usable_duration(row) >= MIN_PROBE_SECONDS]
    pool = eligible or candidates
    selected = [max(pool, key=_quality)]

    if len(selected) < limit:
        remaining = [row for row in pool if row not in selected]
        if remaining:
            selected.append(
                max(
                    remaining,
                    key=lambda row: (
                        _usable_duration(row),
                        _quality(row),
                    ),
                )
            )

    while len(selected) < limit:
        remaining = [row for row in pool if row not in selected]
        if not remaining:
            break
        selected.append(
            max(
                remaining,
                key=lambda row: (
                    min(abs(_center(row) - _center(old)) for old in selected),
                    _quality(row),
                ),
            )
        )
    return selected


def _plans(result, rows, settings) -> list[GroupPlan]:
    families = group_loop_families(
        [row.interval for row in rows],
        result.durations.get("new"),
    )
    rows_by_id = {row.occurrence_id: row for row in rows}
    plans = []
    for family in families:
        member_ids = {occurrence_id(interval) for interval in family.raw_candidates}
        members = [row for row in rows if row.occurrence_id in member_ids]
        representatives = _select_representatives(
            family,
            rows_by_id,
            settings.stem_group_max_representatives,
        )
        plans.append(GroupPlan(family, members, representatives))
    return plans


def _accepted_labels(row: InstrumentOccurrence) -> set[str]:
    if row.context_only or row.status != "checked":
        return set()
    return {
        LABELS[item.source_stem]
        for item in row.evidence
        if item.dtw_result == "accepted"
        and item.source_stem == item.new_song_stem
        and item.source_stem in LABELS
        and item.scope == "sample"
    }


def _check_representative(
    row,
    result,
    original,
    new,
    settings,
    separator,
):
    row.probe = context_probe(
        row.interval,
        result.durations["original"],
        result.durations["new"],
        min(8.0, settings.stem_probe_seconds),
    )
    row.context_only = any(
        getattr(row.probe, prefix + "_start")
        < getattr(row.interval, prefix + "_start") - 1e-6
        or getattr(row.probe, prefix + "_end")
        > getattr(row.interval, prefix + "_end") + 1e-6
        for prefix in ("original", "new")
    )
    row.evidence = []
    row.suggested_instruments = []

    comparison = compare_candidate_stems(
        original,
        new,
        row.probe,
        separator,
        separation_padding=1,
        dtw_search_padding=1,
        max_pitch_shift_semitones=2,
        minimum_duration_ratio=0.5,
        maximum_duration_ratio=2,
        minimum_duration=1,
        include_cross_other=False,
        include_full_mix=False,
        parallel_separation=False,
        parallel_dtw=settings.stem_dtw_workers > 1,
        dtw_workers=settings.stem_dtw_workers,
    )
    comparison.partial = probe_is_partial(row.probe, row.interval)
    row.evidence = _stem_evidence_records([comparison])
    row.source_sounds = describe_region(
        getattr(comparison, "source_region", None),
        row.interval.original_start,
        row.interval.original_end,
    )
    row.new_sounds = describe_region(
        getattr(comparison, "derivative_region", None),
        row.interval.new_start,
        row.interval.new_end,
    )
    for evidence in row.evidence:
        evidence.candidate_number = row.candidate_number
        if row.context_only:
            evidence.scope = "context"
            evidence.interpretation = (
                "Surrounding context only; sample reuse unconfirmed"
            )
    row.status = "checked"
    row.suggested_instruments = sorted(_accepted_labels(row))
    return row


def _group_reason(
    plan,
    verdict,
    processed,
    support_counts,
    negative_count,
    failure_count,
) -> str:
    total = len(plan.representatives)
    counts = ", ".join(
        f"{label}: {count}" for label, count in sorted(support_counts.items())
    )
    if verdict == "supported":
        return (
            f"Group {plan.family.family_number}: supported by {processed} representative "
            f"comparisons ({counts}); applied to {len(plan.members)} timing rows."
        )
    if verdict == "no_support":
        return (
            f"Group {plan.family.family_number}: no supporting same-stem match across "
            f"{negative_count} representative comparisons."
        )
    if verdict == "failed":
        return (
            f"Group {plan.family.family_number}: representative analysis failed "
            f"{failure_count} time(s); timestamp evidence is preserved."
        )
    if verdict == "incomplete":
        return (
            f"Group {plan.family.family_number}: {processed} of {total} representatives "
            "checked; continue the instrument check to finish the group."
        )
    return (
        f"Group {plan.family.family_number}: representative results were mixed or "
        f"insufficient ({processed} checked); treat the stem result as inconclusive."
    )


def _apply_group_result(
    plan,
    *,
    verdict,
    processed_rows,
    supported_labels,
    support_counts,
    negative_count,
    failure_count,
):
    processed_ids = {row.occurrence_id for row in processed_rows}
    reason = _group_reason(
        plan,
        verdict,
        len(processed_rows),
        support_counts,
        negative_count,
        failure_count,
    )
    final = verdict in {"supported", "no_support", "inconclusive", "failed"}

    for row in plan.members:
        if row.status == "no_source":
            continue
        representative = row.occurrence_id in processed_ids
        if not representative:
            row.probe = None
            row.evidence = []
            row.source_sounds = []
            row.new_sounds = []
            row.context_only = False

        if final:
            row.status = "failed" if verdict == "failed" else "checked"
            row.suggested_instruments = (
                list(supported_labels) if verdict == "supported" else []
            )
            row.reason = reason
        elif representative:
            row.reason = reason


def _process_group(
    plan,
    *,
    result,
    original,
    new,
    settings,
    separator,
    reserve_check,
):
    support_counts: Counter[str] = Counter()
    negative_count = 0
    failure_count = 0
    processed_rows = []

    positive_needed = (
        1
        if plan.family.occurrence_count == 1
        else settings.stem_group_positive_confirmations
    )
    negative_needed = (
        1
        if plan.family.occurrence_count == 1
        else settings.stem_group_negative_confirmations
    )

    for row in plan.representatives:
        if row.status == "checked":
            processed_rows.append(row)
        else:
            if not reserve_check():
                break
            try:
                _check_representative(
                    row,
                    result,
                    original,
                    new,
                    settings,
                    separator,
                )
            except (StemSeparationUnavailable, OSError, RuntimeError, ValueError) as exc:
                row.status = "failed"
                row.reason = str(exc)
            processed_rows.append(row)

        labels = _accepted_labels(row)
        if labels:
            support_counts.update(labels)
        elif row.status == "checked" and not row.context_only:
            negative_count += 1
        elif row.status == "failed":
            failure_count += 1

        if max(support_counts.values(), default=0) >= positive_needed:
            break
        if negative_count >= negative_needed:
            break

    supported_labels = sorted(
        label for label, count in support_counts.items() if count >= positive_needed
    )
    attempted_all = len(processed_rows) >= len(plan.representatives)

    if supported_labels:
        verdict = "supported"
    elif negative_count >= negative_needed:
        verdict = "no_support"
    elif failure_count and not any(row.status == "checked" for row in processed_rows):
        verdict = "failed"
    elif attempted_all:
        verdict = "inconclusive"
    else:
        verdict = "incomplete"

    _apply_group_result(
        plan,
        verdict=verdict,
        processed_rows=processed_rows,
        supported_labels=supported_labels,
        support_counts=support_counts,
        negative_count=negative_count,
        failure_count=failure_count,
    )
    return verdict


def run_grouped_instruments(
    result,
    original,
    new,
    settings,
    *,
    separator=None,
    on_progress=None,
    budget_seconds=1200,
    max_new_checks=100,
):
    """Run representative checks in parallel while preserving the current UI rows."""

    updated = result.model_copy(deep=True)
    updated.instrument_occurrences = occurrence_rows(
        updated,
        settings.stem_model_name,
    )
    began = monotonic()
    deadline = began + max(0, budget_seconds)
    rows = updated.instrument_occurrences
    grouped_method = "grouped_representatives" in updated.methods.get(
        "instruments",
        "",
    )
    if not grouped_method:
        # Existing analyses may contain completed per-timestamp checks from the
        # previous backend. Re-open those rows so the first grouped run does not
        # silently reuse a single-occurrence verdict as a group conclusion.
        for row in rows:
            if row.status == "no_source":
                continue
            row.status = "pending"
            row.reason = "Not checked yet"
            row.probe = None
            row.evidence = []
            row.suggested_instruments = []
            row.context_only = False
            row.source_sounds = []
            row.new_sounds = []
    plans = _plans(updated, rows, settings)
    work_lock = Lock()
    persist_lock = Lock()
    checks = 0
    source_descriptions = {}

    def reserve_check():
        nonlocal checks
        with work_lock:
            if checks >= max_new_checks or monotonic() >= deadline - 20:
                return False
            checks += 1
            return True

    def persist():
        with persist_lock:
            stabilize_source_descriptions(rows, source_descriptions)
            updated.methods["instruments"] = (
                f"demucs_{settings.stem_model_name}_grouped_representatives_v1; "
                f"workers={settings.stem_group_workers}; "
                f"max_representatives={settings.stem_group_max_representatives}"
            )
            updated.timings_seconds["instrument_checks"] = monotonic() - began
            updated.stem_evidence = [
                evidence for row in rows for evidence in row.evidence
            ]
            if on_progress:
                on_progress(updated)

    persist()
    if not plans or budget_seconds <= 0:
        return updated

    worker_count = (
        min(settings.stem_group_workers, len(plans))
        if settings.stem_device == "cpu"
        else 1
    )

    with ExitStack() as cleanup:
        if separator is None:
            separator = DemucsSeparator(
                model_name=settings.stem_model_name,
                device=settings.stem_device,
                cache_dir=Path(os.getenv("LASTRADA_CACHE_DIR", "cache"))
                / "demucs",
                segment_seconds=4,
                timeout_seconds=settings.stem_timeout_seconds,
                reuse_model=settings.stem_reuse_model,
                workers=worker_count,
            )
            cleanup.callback(getattr(separator, "close", lambda: None))

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(
                    _process_group,
                    plan,
                    result=updated,
                    original=original,
                    new=new,
                    settings=settings,
                    separator=separator,
                    reserve_check=reserve_check,
                ): plan
                for plan in plans
                if any(row.status not in {"checked", "no_source"} for row in plan.members)
            }
            for future in as_completed(futures):
                plan = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    _apply_group_result(
                        plan,
                        verdict="failed",
                        processed_rows=[],
                        supported_labels=[],
                        support_counts=Counter(),
                        negative_count=0,
                        failure_count=1,
                    )
                    for row in plan.members:
                        if row.status == "failed":
                            row.reason = (
                                f"Group {plan.family.family_number} failed: {exc}"
                            )
                persist()

    updated.methods["stems"] = (
        f"demucs_{settings.stem_model_name}_grouped; "
        "same-stem DTW; representative confirmation required"
    )
    persist()
    return updated
