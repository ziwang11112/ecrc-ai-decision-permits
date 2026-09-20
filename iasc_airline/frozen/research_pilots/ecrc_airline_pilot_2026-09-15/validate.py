"""Archive the finite offline checks and exact source hashes, without actors."""
import argparse
import io
import json
from pathlib import Path
import unittest

from runner import local_sources


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    from bootstrap import install
    isolation = install()
    from loguru import logger
    logger.remove()
    before = local_sources()
    log = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        "test_ordinary", "test_native_evaluation", "test_policy_audit",
    ])
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    (args.out / "TEST_LOG.txt").write_text(log.getvalue(), encoding="utf-8")
    summary = {
        "tests": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "passed": result.wasSuccessful(), "source_sha256": before,
        "sources_unchanged": before == local_sources(),
        "model_calls": 0, "isolation": isolation,
        "scope": "Synthetic ordinary-rule tests, evaluator integrity controls (including private reference wiring) and independent policy-check controls. No ordinary native episodes.",
    }
    (args.out / "RESULTS.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in summary.items() if k not in {"source_sha256", "isolation"}}, indent=2))
    if not result.wasSuccessful() or not summary["sources_unchanged"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
