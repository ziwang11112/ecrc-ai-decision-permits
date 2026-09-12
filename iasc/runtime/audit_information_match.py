"""Compare both arms' actual preissued fixture information, read-only."""
from pathlib import Path
import argparse
import hashlib
import json

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(suite, report_path):
    pairs = []
    paths = sorted(p for category in ("recovery", "boundary", "performance") for p in (suite / category).glob("*/fixture/fixture.json"))
    for left in paths:
        case = left.parent.parent.name
        if "ordinary" not in case:
            continue
        right = left.parent.parent.parent / case.replace("ordinary", "ecrc") / "fixture/fixture.json"
        same = sha(left) == sha(right)
        x, y = json.loads(left.read_text()), json.loads(right.read_text())
        fields = {key: x[key] == y[key] for key in ("policy", "permits", "issued_permits", "reservations", "capacity_state")}
        assert same and all(fields.values()), case
        pairs.append({"case_pair": str(left.parent.parent.relative_to(suite)).replace("ordinary", "ARM"),
                      "byte_identical_fixture": same, "sha256": sha(left), "equal_information_fields": fields})
    assert len(pairs) == 66, len(pairs)
    report = {"suite": str(suite.resolve()), "n_arm_pairs": len(pairs), "all_byte_identical_fixtures": True,
              "scope": "same trusted issuance/policy/reservation/capacity information, not general equivalence of arbitrary malformed-state behavior",
              "pairs": pairs, "auditor_sha256": sha(Path(__file__))}
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"n_arm_pairs": len(pairs), "all_byte_identical_fixtures": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--suite", type=Path, required=True); parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(); main(args.suite, args.report)
