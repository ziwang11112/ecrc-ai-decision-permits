"""Regression and adversarial checks for public scalar reanalysis."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np

import verify


class PublicReanalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.evidence = json.loads((verify.HERE / "EVIDENCE_INDEX.json").read_text())
        cls.raw = verify.read_csv(verify.HERE / "external_trajectory_scalars.csv")
        cls.binding = cls.evidence["numeric_projections"]["external_trajectory_scalars.csv"]

    def test_frozen_all_provider_reanalysis(self):
        report, _ = verify.verify()
        self.assertEqual(sum(s["rows"] for s in report["studies"].values()), 1440)
        self.assertEqual(sum(s["numeric_values_compared"] for s in report["studies"].values()), 2298)
        self.assertEqual(sum(s["paired_contrasts_recomputed"] for s in report["studies"].values()), 60)
        self.assertFalse(report["raw_execution_audit_performed"])

    def test_blank_raw_outcomes_are_not_zero_imputed(self):
        rows = verify.validate_rows(self.raw, "external", self.binding)
        unknown = [r for r in rows if not r["actual_start_count_known"]]
        self.assertEqual(len(unknown), 4)
        self.assertTrue(all(r["actual_starts"] is None for r in unknown))
        self.assertTrue(all(np.isnan(verify.metric_value(r, "raw_verified_yield")) for r in unknown))
        self.assertTrue(all(verify.metric_value(r, "compliant_verified_yield") == 0 for r in unknown))
        # Equal batch weighting differs from pooling available repetitions.
        batch = verify.finite_mean([[1, np.nan], [0, 0]], axis=1)
        self.assertEqual(float(verify.finite_mean(batch)), .5)
        self.assertNotEqual(float(verify.finite_mean(batch)), 1/3)

    def test_missing_or_duplicate_assignment_rejected(self):
        bad = copy.deepcopy(self.raw)
        bad[0] = bad[1].copy()
        with self.assertRaisesRegex(ValueError, "planned trajectory"):
            verify.validate_rows(bad, "external", self.binding)

    def test_unknown_execution_cannot_claim_positive_compliant_yield(self):
        bad = copy.deepcopy(self.raw)
        row = next(r for r in bad if r["actual_start_count_known"] == "False")
        row["budget_compliant_verified_yield"] = "0.75"
        with self.assertRaisesRegex(ValueError, "compliant score rule"):
            verify.validate_rows(bad, "external", self.binding)

    def test_frozen_byte_tampering_rejected_before_reanalysis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(verify.HERE, root, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("_generated", "__pycache__", "figures"))
            path = root / "external_trajectory_scalars.csv"
            path.write_bytes(path.read_bytes() + b"\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify.verify(root)

    def test_pairing_requires_common_estimable_batches(self):
        left, right = np.array([1, np.nan, .5]), np.array([0, 1, np.nan])
        difference = left - right
        point, low, high, valid = verify.interval(difference, np.array([[0, 0], [1, 2]]))
        self.assertEqual((point, low, high, valid), (1, 1, 1, 1))
        self.assertTrue(np.isnan(verify.finite_mean([np.nan, np.nan])))


if __name__ == "__main__":
    unittest.main()
