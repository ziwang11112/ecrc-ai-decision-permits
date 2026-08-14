#!/usr/bin/env python3
"""E7: deterministic benchmark of genuinely sequence-only trace faults.

The benchmark reads the archived held-out claim-licence trace without changing
it.  Every injected row is required to pass both the existing primitive
presence/type baseline and the existing independently written row-conditional
validator.  Detection therefore requires information from two or more rows or
from a participant-segment boundary.

The benchmark is deliberately narrow.  Perfect detection on the prespecified
faults demonstrates coverage of these sequence invariants only; it is not a
security, semantic-correctness, or unknown-fault benchmark.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

SCRIPT_VERSION = "1.0.0"
DEFAULT_SEED = 20260813
DEFAULT_CASES_PER_FAMILY = 100

HERE = Path(__file__).resolve().parent
ICAIR_DIR = HERE.parent
DEFAULT_CLEAN_TRACE = ICAIR_DIR / "evidence" / "heldout_claim_license_trace.csv"
DEFAULT_OUTPUT_DIR = HERE / "evidence"

# Import the exact existing baselines.  The E7 code does not alter either file.
if str(ICAIR_DIR) not in sys.path:
    sys.path.insert(0, str(ICAIR_DIR))

import run_conditional_validator_baseline as row_baseline  # noqa: E402
import run_end_to_end_claim_license_audit as reference_audit  # noqa: E402

SAFE_COUNTER_INDEPENDENT_REASONS = {
    "uncertainty_gate",
    "risk_below_prompt_threshold",
}
NO_COUNTER_INCREMENT_ROUTES = {"abstain", "no_action"}

FAMILY_ORDER = (
    "adjacent_auto_counter_discontinuity",
    "adjacent_review_counter_discontinuity",
    "segment_start_nonzero",
    "duplicate_decision_index",
    "missing_decision_index",
    "participant_boundary_not_reset",
)

FAMILY_EXPECTED_CODES = {
    "adjacent_auto_counter_discontinuity": "SEQ_AUTO_COUNTER_DISCONTINUITY",
    "adjacent_review_counter_discontinuity": "SEQ_REVIEW_COUNTER_DISCONTINUITY",
    "segment_start_nonzero": "SEQ_SEGMENT_START_NONZERO",
    "duplicate_decision_index": "SEQ_DUPLICATE_DECISION_INDEX",
    "missing_decision_index": "SEQ_MISSING_DECISION_INDEX",
    "participant_boundary_not_reset": "SEQ_PARTICIPANT_BOUNDARY_NOT_RESET",
}

FAMILY_DESCRIPTIONS = {
    "adjacent_auto_counter_discontinuity": (
        "Raise the final row's automated-alert before/after counters together by "
        "one.  The row transition remains valid, but its count-before no longer "
        "equals the preceding row's count-after."
    ),
    "adjacent_review_counter_discontinuity": (
        "Raise the final row's review before/after counters together by one.  "
        "The row transition remains valid, but adjacent review state is broken."
    ),
    "segment_start_nonzero": (
        "Offset a standalone participant's complete automated-alert counter path "
        "by one.  All local and adjacent transitions remain valid, but the "
        "segment no longer starts at zero."
    ),
    "duplicate_decision_index": (
        "Duplicate one interior no-increment record.  Each copy is row-valid and "
        "counter continuity is preserved, but the participant index is repeated."
    ),
    "missing_decision_index": (
        "Remove one interior no-increment record.  Remaining rows are row-valid "
        "and counters remain continuous, but the participant index has a gap."
    ),
    "participant_boundary_not_reset": (
        "Carry a nonzero terminal counter from one participant into the first "
        "row of the next participant, preserving the new row's local transition."
    ),
}


@dataclass(frozen=True)
class Finding:
    """One sequence-level violation and its exact row/boundary location."""

    code: str
    anchor_position: int
    related_position: int | None
    subject_id: str
    decision_index: int
    expected_decision_index: int | None = None
    field: str = ""
    expected_value: str = ""
    observed_value: str = ""

    def locator_key(self) -> str:
        related = "" if self.related_position is None else str(self.related_position)
        expected_index = (
            "" if self.expected_decision_index is None else str(self.expected_decision_index)
        )
        return (
            f"{self.code}|anchor={self.anchor_position}|related={related}|"
            f"subject={self.subject_id}|decision={self.decision_index}|"
            f"expected_decision={expected_index}|field={self.field}"
        )


@dataclass
class FaultCase:
    case_id: str
    family: str
    rows: list[dict[str, str]]
    source_subject_ids: tuple[str, ...]
    expected_finding: Finding
    mutation_detail: str
    source_row_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", type=Path, default=DEFAULT_CLEAN_TRACE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--cases-per-family", type=int, default=DEFAULT_CASES_PER_FAMILY
    )
    return parser.parse_args()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def case_rows_sha256(rows: Sequence[Mapping[str, Any]]) -> str:
    """Hash a reconstructed case independently of dictionary insertion order."""
    payload = json.dumps(
        [dict(row) for row in rows],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing clean trace: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        fieldnames = list(reader.fieldnames or [])
    if not rows or not fieldnames:
        raise ValueError(f"Empty clean trace: {path}")
    return fieldnames, rows


def as_int(row: Mapping[str, Any], field: str) -> int:
    value = row.get(field)
    try:
        numeric = float(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Non-numeric {field}: {value!r}") from exc
    if not numeric.is_integer():
        raise ValueError(f"Non-integer {field}: {value!r}")
    return int(numeric)


def participant_blocks(
    rows: Sequence[Mapping[str, str]],
) -> list[tuple[str, list[dict[str, str]]]]:
    """Return contiguous participant blocks without silently regrouping rows."""
    blocks: list[tuple[str, list[dict[str, str]]]] = []
    seen: set[str] = set()
    for row in rows:
        subject = str(row.get("subject_id", ""))
        if not blocks or blocks[-1][0] != subject:
            if subject in seen:
                raise ValueError(f"Participant reappears non-contiguously: {subject}")
            seen.add(subject)
            blocks.append((subject, []))
        blocks[-1][1].append(dict(row))
    return blocks


def sequence_findings(rows: Sequence[Mapping[str, Any]]) -> tuple[Finding, ...]:
    """Validate ordering, resets, and counter continuity without fault metadata.

    The decision uses only archived trace fields.  In particular, it never reads
    case IDs, fault-family labels, expected codes, or target locations.
    """
    findings: list[Finding] = []
    seen_subjects: set[str] = set()
    previous: Mapping[str, Any] | None = None
    previous_position: int | None = None

    for position, row in enumerate(rows):
        subject = str(row.get("subject_id", ""))
        decision_index = as_int(row, "decision_index")
        auto_before = as_int(row, "runtime_auto_alert_count_before")
        review_before = as_int(row, "runtime_review_count_before")

        starts_block = previous is None or str(previous.get("subject_id", "")) != subject
        if starts_block:
            if subject in seen_subjects:
                findings.append(
                    Finding(
                        code="SEQ_PARTICIPANT_NONCONTIGUOUS",
                        anchor_position=position,
                        related_position=previous_position,
                        subject_id=subject,
                        decision_index=decision_index,
                    )
                )
            seen_subjects.add(subject)

            nonzero_fields = []
            if auto_before != 0:
                nonzero_fields.append("runtime_auto_alert_count_before")
            if review_before != 0:
                nonzero_fields.append("runtime_review_count_before")

            if nonzero_fields:
                field = "+".join(nonzero_fields)
                observed = "+".join(
                    str(auto_before if name.startswith("runtime_auto") else review_before)
                    for name in nonzero_fields
                )
                boundary_carry = False
                if previous is not None:
                    previous_auto_after = as_int(
                        previous, "runtime_auto_alert_count_after"
                    )
                    previous_review_after = as_int(
                        previous, "runtime_review_count_after"
                    )
                    boundary_carry = (
                        auto_before != 0 and auto_before == previous_auto_after
                    ) or (
                        review_before != 0
                        and review_before == previous_review_after
                    )
                findings.append(
                    Finding(
                        code=(
                            "SEQ_PARTICIPANT_BOUNDARY_NOT_RESET"
                            if boundary_carry
                            else "SEQ_SEGMENT_START_NONZERO"
                        ),
                        anchor_position=position,
                        related_position=(previous_position if boundary_carry else None),
                        subject_id=subject,
                        decision_index=decision_index,
                        field=field,
                        expected_value="0",
                        observed_value=observed,
                    )
                )
        else:
            assert previous is not None and previous_position is not None
            previous_index = as_int(previous, "decision_index")
            if decision_index == previous_index:
                findings.append(
                    Finding(
                        code="SEQ_DUPLICATE_DECISION_INDEX",
                        anchor_position=position,
                        related_position=previous_position,
                        subject_id=subject,
                        decision_index=decision_index,
                        expected_decision_index=previous_index + 1,
                        field="decision_index",
                        expected_value=str(previous_index + 1),
                        observed_value=str(decision_index),
                    )
                )
            elif decision_index > previous_index + 1:
                findings.append(
                    Finding(
                        code="SEQ_MISSING_DECISION_INDEX",
                        anchor_position=position,
                        related_position=previous_position,
                        subject_id=subject,
                        decision_index=decision_index,
                        expected_decision_index=previous_index + 1,
                        field="decision_index",
                        expected_value=str(previous_index + 1),
                        observed_value=str(decision_index),
                    )
                )
            elif decision_index < previous_index:
                findings.append(
                    Finding(
                        code="SEQ_DECISION_ORDER",
                        anchor_position=position,
                        related_position=previous_position,
                        subject_id=subject,
                        decision_index=decision_index,
                        expected_decision_index=previous_index + 1,
                        field="decision_index",
                        expected_value=f">={previous_index + 1}",
                        observed_value=str(decision_index),
                    )
                )

            previous_auto_after = as_int(
                previous, "runtime_auto_alert_count_after"
            )
            if auto_before != previous_auto_after:
                findings.append(
                    Finding(
                        code="SEQ_AUTO_COUNTER_DISCONTINUITY",
                        anchor_position=position,
                        related_position=previous_position,
                        subject_id=subject,
                        decision_index=decision_index,
                        field="runtime_auto_alert_count_before",
                        expected_value=str(previous_auto_after),
                        observed_value=str(auto_before),
                    )
                )

            previous_review_after = as_int(previous, "runtime_review_count_after")
            if review_before != previous_review_after:
                findings.append(
                    Finding(
                        code="SEQ_REVIEW_COUNTER_DISCONTINUITY",
                        anchor_position=position,
                        related_position=previous_position,
                        subject_id=subject,
                        decision_index=decision_index,
                        field="runtime_review_count_before",
                        expected_value=str(previous_review_after),
                        observed_value=str(review_before),
                    )
                )

        previous = row
        previous_position = position

    return tuple(findings)


def primitive_failures(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Run the existing primitive presence/type baseline unchanged."""
    return tuple(reference_audit.structural_audit_row(pd.Series(dict(row))))


def row_conditional_failures(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Run the existing independent row-conditional validator unchanged."""
    return tuple(row_baseline.validate_record(dict(row)))


def stable_rank(seed: int, family: str, key: str) -> str:
    return hashlib.sha256(f"{seed}|{family}|{key}".encode()).hexdigest()


def select_cases(
    candidates: Iterable[tuple[str, Any]],
    *,
    family: str,
    seed: int,
    count: int,
) -> list[tuple[str, Any]]:
    ranked = sorted(
        candidates,
        key=lambda item: (stable_rank(seed, family, item[0]), item[0]),
    )
    if len(ranked) < count:
        raise ValueError(
            f"Only {len(ranked)} eligible cases for {family}; need {count}"
        )
    return ranked[:count]


def safe_independent_row(row: Mapping[str, str]) -> bool:
    return (
        str(row.get("primary_route", "")) in NO_COUNTER_INCREMENT_ROUTES
        and str(row.get("reason_code", "")) in SAFE_COUNTER_INDEPENDENT_REASONS
    )


def expected_finding(
    *,
    code: str,
    anchor: int,
    related: int | None,
    rows: Sequence[Mapping[str, str]],
    field: str,
    expected_value: str,
    observed_value: str,
    expected_decision_index: int | None = None,
) -> Finding:
    row = rows[anchor]
    return Finding(
        code=code,
        anchor_position=anchor,
        related_position=related,
        subject_id=str(row["subject_id"]),
        decision_index=as_int(row, "decision_index"),
        expected_decision_index=expected_decision_index,
        field=field,
        expected_value=expected_value,
        observed_value=observed_value,
    )


def build_fault_cases(
    clean_rows: Sequence[Mapping[str, str]],
    *,
    seed: int = DEFAULT_SEED,
    cases_per_family: int = DEFAULT_CASES_PER_FAMILY,
) -> list[FaultCase]:
    """Construct isolated, deterministic sequence-only cases in memory."""
    blocks = participant_blocks(clean_rows)
    block_map = {subject: rows for subject, rows in blocks}
    cases: list[FaultCase] = []

    def add_case(
        family: str,
        ordinal: int,
        rows: list[dict[str, str]],
        subjects: tuple[str, ...],
        expected: Finding,
        detail: str,
        source_row_count: int,
    ) -> None:
        cases.append(
            FaultCase(
                case_id=f"E7-{FAMILY_ORDER.index(family) + 1:02d}-{ordinal:03d}",
                family=family,
                rows=rows,
                source_subject_ids=subjects,
                expected_finding=expected,
                mutation_detail=detail,
                source_row_count=source_row_count,
            )
        )

    for field_prefix, family in (
        ("runtime_auto_alert", "adjacent_auto_counter_discontinuity"),
        ("runtime_review", "adjacent_review_counter_discontinuity"),
    ):
        candidates: list[tuple[str, tuple[str, int]]] = []
        for subject, rows in blocks:
            target = rows[-1]
            before = as_int(target, f"{field_prefix}_count_before")
            after = as_int(target, f"{field_prefix}_count_after")
            cap = as_int(target, f"{field_prefix}_cap")
            if (
                len(rows) >= 2
                and safe_independent_row(target)
                and before == after
                and after < cap
            ):
                candidates.append((subject, (subject, len(rows) - 1)))
        selected = select_cases(
            candidates,
            family=family,
            seed=seed,
            count=cases_per_family,
        )
        for ordinal, (_, (subject, target_position)) in enumerate(selected, 1):
            rows = [dict(row) for row in block_map[subject]]
            target = rows[target_position]
            previous = rows[target_position - 1]
            before_field = f"{field_prefix}_count_before"
            after_field = f"{field_prefix}_count_after"
            old_before = as_int(target, before_field)
            target[before_field] = str(old_before + 1)
            target[after_field] = str(old_before + 1)
            code = FAMILY_EXPECTED_CODES[family]
            expected = expected_finding(
                code=code,
                anchor=target_position,
                related=target_position - 1,
                rows=rows,
                field=before_field,
                expected_value=str(as_int(previous, after_field)),
                observed_value=str(old_before + 1),
            )
            add_case(
                family,
                ordinal,
                rows,
                (subject,),
                expected,
                f"incremented {before_field} and {after_field} together on final row",
                len(block_map[subject]),
            )

    family = "segment_start_nonzero"
    start_candidates: list[tuple[str, tuple[str, int]]] = []
    for subject, rows in blocks:
        first = rows[0]
        if (
            as_int(first, "runtime_auto_alert_count_before") == 0
            and as_int(rows[-1], "runtime_auto_alert_count_after")
            < as_int(rows[-1], "runtime_auto_alert_cap")
        ):
            start_candidates.append((subject, (subject, 0)))
    selected = select_cases(
        start_candidates,
        family=family,
        seed=seed,
        count=cases_per_family,
    )
    for ordinal, (_, (subject, _)) in enumerate(selected, 1):
        rows = [dict(row) for row in block_map[subject]]
        # Shift the entire participant counter path, not only its first row.
        # This preserves every within-row transition and every adjacent equality;
        # the sole contradiction is the missing reset to zero at segment start.
        for row in rows:
            row["runtime_auto_alert_count_before"] = str(
                as_int(row, "runtime_auto_alert_count_before") + 1
            )
            row["runtime_auto_alert_count_after"] = str(
                as_int(row, "runtime_auto_alert_count_after") + 1
            )
        expected = expected_finding(
            code=FAMILY_EXPECTED_CODES[family],
            anchor=0,
            related=None,
            rows=rows,
            field="runtime_auto_alert_count_before",
            expected_value="0",
            observed_value="1",
        )
        add_case(
            family,
            ordinal,
            rows,
            (subject,),
            expected,
            "shifted the complete automated-alert counter path by one",
            len(block_map[subject]),
        )

    for family in ("duplicate_decision_index", "missing_decision_index"):
        index_candidates: list[tuple[str, tuple[str, int]]] = []
        for subject, rows in blocks:
            eligible_positions = [
                position
                for position in range(1, len(rows) - 1)
                if str(rows[position].get("primary_route", ""))
                in NO_COUNTER_INCREMENT_ROUTES
                and as_int(rows[position], "runtime_auto_alert_count_before")
                == as_int(rows[position], "runtime_auto_alert_count_after")
                and as_int(rows[position], "runtime_review_count_before")
                == as_int(rows[position], "runtime_review_count_after")
            ]
            if eligible_positions:
                position = min(
                    eligible_positions,
                    key=lambda value: stable_rank(
                        seed, family, f"{subject}|{value}"
                    ),
                )
                index_candidates.append((subject, (subject, position)))
        selected = select_cases(
            index_candidates,
            family=family,
            seed=seed,
            count=cases_per_family,
        )
        for ordinal, (_, (subject, target_position)) in enumerate(selected, 1):
            source = block_map[subject]
            rows = [dict(row) for row in source]
            if family == "duplicate_decision_index":
                duplicate = dict(rows[target_position])
                rows.insert(target_position + 1, duplicate)
                anchor = target_position + 1
                related = target_position
                observed_index = as_int(rows[anchor], "decision_index")
                expected_index = observed_index + 1
                detail = f"duplicated no-increment row at decision {observed_index}"
            else:
                removed = rows.pop(target_position)
                anchor = target_position
                related = target_position - 1
                expected_index = as_int(removed, "decision_index")
                observed_index = as_int(rows[anchor], "decision_index")
                detail = f"removed no-increment row at decision {expected_index}"
            expected = expected_finding(
                code=FAMILY_EXPECTED_CODES[family],
                anchor=anchor,
                related=related,
                rows=rows,
                field="decision_index",
                expected_value=str(expected_index),
                observed_value=str(observed_index),
                expected_decision_index=expected_index,
            )
            add_case(
                family,
                ordinal,
                rows,
                (subject,),
                expected,
                detail,
                len(source),
            )

    family = "participant_boundary_not_reset"
    boundary_candidates: list[
        tuple[str, tuple[str, str, str, int]]
    ] = []
    for (previous_subject, previous_rows), (next_subject, next_rows) in zip(
        blocks, blocks[1:], strict=False
    ):
        previous_last = previous_rows[-1]
        next_first = next_rows[0]
        if not safe_independent_row(next_first):
            continue
        auto_value = as_int(previous_last, "runtime_auto_alert_count_after")
        review_value = as_int(previous_last, "runtime_review_count_after")
        if 0 < auto_value <= as_int(next_first, "runtime_auto_alert_cap"):
            counter = "runtime_auto_alert"
            carried_value = auto_value
        elif 0 < review_value <= as_int(next_first, "runtime_review_cap"):
            counter = "runtime_review"
            carried_value = review_value
        else:
            continue
        key = f"{previous_subject}->{next_subject}"
        boundary_candidates.append(
            (
                key,
                (
                    previous_subject,
                    next_subject,
                    counter,
                    carried_value,
                ),
            )
        )
    selected = select_cases(
        boundary_candidates,
        family=family,
        seed=seed,
        count=cases_per_family,
    )
    for ordinal, (_, candidate) in enumerate(selected, 1):
        previous_subject, next_subject, counter, carried_value = candidate
        previous_rows = block_map[previous_subject]
        next_rows = block_map[next_subject]
        # Use the complete preceding segment plus the first row of the next
        # segment as a boundary window.  Ending the window at that first row
        # prevents a reset fault from being confounded with a second, downstream
        # counter discontinuity.  No endpoint-completeness field exists in the
        # archived schema, so the benchmark does not claim to test truncation.
        rows = [dict(row) for row in previous_rows] + [dict(next_rows[0])]
        boundary_position = len(previous_rows)
        before_field = f"{counter}_count_before"
        after_field = f"{counter}_count_after"
        rows[boundary_position][before_field] = str(carried_value)
        rows[boundary_position][after_field] = str(carried_value)
        expected = expected_finding(
            code=FAMILY_EXPECTED_CODES[family],
            anchor=boundary_position,
            related=boundary_position - 1,
            rows=rows,
            field=before_field,
            expected_value="0",
            observed_value=str(carried_value),
        )
        add_case(
            family,
            ordinal,
            rows,
            (previous_subject, next_subject),
            expected,
            (
                f"carried {carried_value} from {previous_subject}'s terminal "
                f"{counter} state into {next_subject}'s first row"
            ),
            len(previous_rows) + 1,
        )

    expected_total = len(FAMILY_ORDER) * cases_per_family
    if len(cases) != expected_total:
        raise AssertionError(f"Built {len(cases)} cases; expected {expected_total}")
    return cases


def union_codes(rows: Sequence[Mapping[str, Any]], validator: str) -> tuple[str, ...]:
    if validator == "primitive":
        function = primitive_failures
    elif validator == "row_conditional":
        function = row_conditional_failures
    else:
        raise ValueError(f"Unknown row validator: {validator}")
    codes = {code for row in rows for code in function(row)}
    return tuple(sorted(codes))


def finding_to_row(case_id: str, finding: Finding, expected: Finding) -> dict[str, Any]:
    return {
        "case_id": case_id,
        "detected_code": finding.code,
        "anchor_position": finding.anchor_position,
        "related_position": (
            "" if finding.related_position is None else finding.related_position
        ),
        "subject_id": finding.subject_id,
        "decision_index": finding.decision_index,
        "expected_decision_index": (
            ""
            if finding.expected_decision_index is None
            else finding.expected_decision_index
        ),
        "field": finding.field,
        "expected_value": finding.expected_value,
        "observed_value": finding.observed_value,
        "locator_key": finding.locator_key(),
        "is_expected_localisation": finding.locator_key()
        == expected.locator_key(),
    }


def evaluate_benchmark(
    clean_rows: Sequence[Mapping[str, str]],
    cases: Sequence[FaultCase],
) -> dict[str, Any]:
    blocks = participant_blocks(clean_rows)

    primitive_clean_codes = [primitive_failures(row) for row in clean_rows]
    row_clean_codes = [row_conditional_failures(row) for row in clean_rows]
    sequence_clean_findings = sequence_findings(clean_rows)

    clean_rows_flagged_primitive = sum(bool(codes) for codes in primitive_clean_codes)
    clean_rows_flagged_row = sum(bool(codes) for codes in row_clean_codes)
    clean_subjects_flagged_primitive = 0
    clean_subjects_flagged_row = 0
    offset = 0
    for _, rows in blocks:
        length = len(rows)
        clean_subjects_flagged_primitive += int(
            any(primitive_clean_codes[offset : offset + length])
        )
        clean_subjects_flagged_row += int(
            any(row_clean_codes[offset : offset + length])
        )
        offset += length
    clean_subjects_flagged_sequence = len(
        {finding.subject_id for finding in sequence_clean_findings}
    )

    clean_results = [
        {
            "validator": "primitive_presence_type",
            "clean_rows": len(clean_rows),
            "clean_rows_flagged": clean_rows_flagged_primitive,
            "clean_row_false_positive_rate": clean_rows_flagged_primitive
            / len(clean_rows),
            "clean_participant_segments": len(blocks),
            "clean_segments_flagged": clean_subjects_flagged_primitive,
            "clean_segment_false_positive_rate": clean_subjects_flagged_primitive
            / len(blocks),
        },
        {
            "validator": "independent_row_conditional",
            "clean_rows": len(clean_rows),
            "clean_rows_flagged": clean_rows_flagged_row,
            "clean_row_false_positive_rate": clean_rows_flagged_row
            / len(clean_rows),
            "clean_participant_segments": len(blocks),
            "clean_segments_flagged": clean_subjects_flagged_row,
            "clean_segment_false_positive_rate": clean_subjects_flagged_row
            / len(blocks),
        },
        {
            "validator": "sequence_aware",
            "clean_rows": len(clean_rows),
            "clean_rows_flagged": len(
                {finding.anchor_position for finding in sequence_clean_findings}
            ),
            "clean_row_false_positive_rate": len(
                {finding.anchor_position for finding in sequence_clean_findings}
            )
            / len(clean_rows),
            "clean_participant_segments": len(blocks),
            "clean_segments_flagged": clean_subjects_flagged_sequence,
            "clean_segment_false_positive_rate": clean_subjects_flagged_sequence
            / len(blocks),
        },
    ]

    case_results: list[dict[str, Any]] = []
    finding_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []

    for case in cases:
        primitive_codes = union_codes(case.rows, "primitive")
        row_codes = union_codes(case.rows, "row_conditional")
        findings = sequence_findings(case.rows)
        expected_locator = case.expected_finding.locator_key()
        exact_matches = [
            finding for finding in findings if finding.locator_key() == expected_locator
        ]

        # This is the central benchmark contract.  A case that is not row-valid,
        # or that introduces multiple sequence contradictions, is rejected rather
        # than credited as evidence for a sequence-aware advantage.
        if primitive_codes:
            raise AssertionError(
                f"{case.case_id} is not primitive-valid: {primitive_codes}"
            )
        if row_codes:
            raise AssertionError(
                f"{case.case_id} is not row-conditionally valid: {row_codes}"
            )
        if len(findings) != 1:
            raise AssertionError(
                f"{case.case_id} has {len(findings)} sequence findings, expected 1: "
                f"{[finding.locator_key() for finding in findings]}"
            )
        if len(exact_matches) != 1:
            raise AssertionError(
                f"{case.case_id} was not exactly localised: expected {expected_locator}, "
                f"observed {[finding.locator_key() for finding in findings]}"
            )

        manifest_rows.append(
            {
                "case_id": case.case_id,
                "fault_family": case.family,
                "source_subject_ids": "|".join(case.source_subject_ids),
                "source_row_count": case.source_row_count,
                "mutated_row_count": len(case.rows),
                "mutated_case_sha256": case_rows_sha256(case.rows),
                "expected_sequence_code": case.expected_finding.code,
                "expected_locator_key": expected_locator,
                "mutation_detail": case.mutation_detail,
                "all_rows_pass_primitive": True,
                "all_rows_pass_independent_row_conditional": True,
            }
        )

        validator_payloads = (
            ("primitive_presence_type", primitive_codes, False, False, 0),
            ("independent_row_conditional", row_codes, False, False, 0),
            (
                "sequence_aware",
                tuple(sorted({finding.code for finding in findings})),
                bool(findings),
                bool(exact_matches),
                len(findings),
            ),
        )
        for validator, codes, detected, localised, n_findings in validator_payloads:
            case_results.append(
                {
                    "case_id": case.case_id,
                    "fault_family": case.family,
                    "validator": validator,
                    "detected": detected,
                    "detected_codes": "|".join(codes),
                    "exact_localisation": localised,
                    "n_findings": n_findings,
                }
            )
        finding_rows.extend(
            finding_to_row(case.case_id, finding, case.expected_finding)
            for finding in findings
        )

    family_summary: list[dict[str, Any]] = []
    validators = (
        "primitive_presence_type",
        "independent_row_conditional",
        "sequence_aware",
    )
    for family in FAMILY_ORDER:
        for validator in validators:
            rows = [
                row
                for row in case_results
                if row["fault_family"] == family and row["validator"] == validator
            ]
            detected = sum(bool(row["detected"]) for row in rows)
            localised = sum(bool(row["exact_localisation"]) for row in rows)
            family_summary.append(
                {
                    "fault_family": family,
                    "validator": validator,
                    "n_cases": len(rows),
                    "n_detected": detected,
                    "sensitivity": detected / len(rows),
                    "n_exactly_localised": localised,
                    "exact_localisation_rate": localised / len(rows),
                    "mean_findings_per_case": sum(
                        int(row["n_findings"]) for row in rows
                    )
                    / len(rows),
                    "expected_sequence_code": FAMILY_EXPECTED_CODES[family],
                }
            )

    if any(int(row["clean_rows_flagged"]) for row in clean_results):
        raise AssertionError(f"A validator flagged clean rows: {clean_results}")
    if any(int(row["clean_segments_flagged"]) for row in clean_results):
        raise AssertionError(f"A validator flagged clean segments: {clean_results}")

    return {
        "clean_results": clean_results,
        "manifest_rows": manifest_rows,
        "case_results": case_results,
        "finding_rows": finding_rows,
        "family_summary": family_summary,
    }


def csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    if not rows:
        raise ValueError("Refusing to serialize an empty CSV")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=list(rows[0].keys()),
        lineterminator="\n",
    )
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def bundle_hash(payloads: Mapping[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name in sorted(payloads):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(payloads[name])
        digest.update(b"\0")
    return digest.hexdigest()


def build_artifact_payloads(
    *,
    clean_path: Path,
    clean_rows: Sequence[Mapping[str, str]],
    cases: Sequence[FaultCase],
    evaluation: Mapping[str, Any],
    seed: int,
    cases_per_family: int,
) -> dict[str, bytes]:
    source_hash = sha256_file(clean_path)
    summary = {
        "benchmark": "E7_sequence_only_fault_benchmark",
        "script_version": SCRIPT_VERSION,
        "seed": seed,
        "source_trace": {
            "path_role": "existing_read_only_heldout_claim_licence_trace",
            "sha256": source_hash,
            "rows": len(clean_rows),
            "participant_segments": len(participant_blocks(clean_rows)),
        },
        "fault_contract": {
            "families": list(FAMILY_ORDER),
            "family_descriptions": FAMILY_DESCRIPTIONS,
            "cases_per_family": cases_per_family,
            "total_cases": len(cases),
            "all_injected_rows_must_pass_existing_primitive": True,
            "all_injected_rows_must_pass_existing_independent_row_conditional": True,
            "each_case_must_have_exactly_one_sequence_finding": True,
            "sequence_validator_uses_fault_metadata": False,
            "unique_mutated_case_hashes": len(
                {case_rows_sha256(case.rows) for case in cases}
            ),
        },
        "clean_false_positive_results": evaluation["clean_results"],
        "interpretation": [
            "Primitive and row-conditional sensitivity is expected to be zero because every injected row preserves their observable invariants.",
            "Sequence-aware sensitivity and localisation apply only to the six prespecified sequence families.",
            "The benchmark does not establish unknown-fault, adversarial, security, semantic-correctness, or deployment coverage.",
            "decision_index is an absolute task index in the archived trace, so segment-start validation concerns counter reset rather than requiring decision_index zero.",
            "Participant-boundary cases use a complete preceding segment plus the first next-participant row; the schema declares no segment endpoint, so this is not presented as a truncation test.",
        ],
        "artifacts": {
            "fault_manifest": "sequence_fault_manifest.csv",
            "case_results": "validator_case_results.csv",
            "sequence_findings": "sequence_findings.csv",
            "family_summary": "validator_family_summary.csv",
            "clean_results": "clean_false_positive_results.csv",
        },
    }
    payloads = {
        "sequence_fault_manifest.csv": csv_bytes(evaluation["manifest_rows"]),
        "validator_case_results.csv": csv_bytes(evaluation["case_results"]),
        "sequence_findings.csv": csv_bytes(evaluation["finding_rows"]),
        "validator_family_summary.csv": csv_bytes(evaluation["family_summary"]),
        "clean_false_positive_results.csv": csv_bytes(evaluation["clean_results"]),
        "benchmark_summary.json": json_bytes(summary),
    }
    return payloads


def run_benchmark(
    *,
    clean_path: Path = DEFAULT_CLEAN_TRACE,
    seed: int = DEFAULT_SEED,
    cases_per_family: int = DEFAULT_CASES_PER_FAMILY,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    if cases_per_family <= 0:
        raise ValueError("cases_per_family must be positive")
    _, clean_rows = read_csv_rows(clean_path)
    cases = build_fault_cases(
        clean_rows,
        seed=seed,
        cases_per_family=cases_per_family,
    )
    evaluation = evaluate_benchmark(clean_rows, cases)
    payloads = build_artifact_payloads(
        clean_path=clean_path,
        clean_rows=clean_rows,
        cases=cases,
        evaluation=evaluation,
        seed=seed,
        cases_per_family=cases_per_family,
    )
    return payloads, evaluation


def write_outputs(output_dir: Path, payloads: Mapping[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        (output_dir / name).write_bytes(payload)


def main() -> None:
    args = parse_args()
    payloads, evaluation = run_benchmark(
        clean_path=args.clean,
        seed=args.seed,
        cases_per_family=args.cases_per_family,
    )

    # Rebuild and re-evaluate every case independently; all core artifacts must
    # then be byte-identical.  This checks selection, mutation, validation,
    # localisation, aggregation, and serialization in the executed run.
    repeated, repeated_evaluation = run_benchmark(
        clean_path=args.clean,
        seed=args.seed,
        cases_per_family=args.cases_per_family,
    )
    if payloads != repeated or evaluation != repeated_evaluation:
        raise AssertionError("Independent E7 rebuild was not byte-deterministic")

    determinism = {
        "passed": True,
        "method": "independent_full_benchmark_rebuild_and_byte_comparison",
        "seed": args.seed,
        "cases_per_family": args.cases_per_family,
        "core_artifact_count": len(payloads),
        "core_bundle_sha256": bundle_hash(payloads),
    }
    payloads_with_check = dict(payloads)
    payloads_with_check["determinism_check.json"] = json_bytes(determinism)
    artifact_hashes = {
        "source_trace_sha256": sha256_file(args.clean),
        "artifacts": {
            name: sha256_bytes(payload)
            for name, payload in sorted(payloads_with_check.items())
        },
        "artifact_bundle_sha256": bundle_hash(payloads_with_check),
    }
    payloads_with_check["artifact_hashes.json"] = json_bytes(artifact_hashes)
    write_outputs(args.output_dir, payloads_with_check)

    print(
        f"E7: {len(evaluation['manifest_rows'])} sequence-only cases across "
        f"{len(FAMILY_ORDER)} families"
    )
    print("clean FPR: 0 for primitive, row-conditional, and sequence-aware")
    for row in evaluation["family_summary"]:
        if row["validator"] == "sequence_aware":
            print(
                f"{row['fault_family']}: sensitivity={row['sensitivity']:.3f}, "
                f"exact_localisation={row['exact_localisation_rate']:.3f}"
            )
    print(f"output: {args.output_dir}")


if __name__ == "__main__":
    main()
