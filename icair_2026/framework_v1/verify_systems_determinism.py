#!/usr/bin/env python3
"""Compare timing-free ECRC benchmark structures from independent runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from agentic_eeg_dm.governance import canonical_hash


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("first", type=Path)
    parser.add_argument("second", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def compare_structures(first: dict[str, Any], second: dict[str, Any]) -> dict[str, Any]:
    first_digest = canonical_hash(first)
    second_digest = canonical_hash(second)
    return {
        "comparison_scope": (
            "Timing-free scenario structure, seeded input consequences, route and "
            "receipt counts, rejection classes, commit/release counts, and invariants."
        ),
        "timing_excluded": True,
        "first_structural_digest": first_digest,
        "second_structural_digest": second_digest,
        "structures_identical": first == second,
        "digests_identical": first_digest == second_digest,
        "passed": first == second and first_digest == second_digest,
    }


def main() -> int:
    args = parse_args()
    result = compare_structures(load_json(args.first), load_json(args.second))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True), encoding="utf-8"
    )
    return int(not result["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
