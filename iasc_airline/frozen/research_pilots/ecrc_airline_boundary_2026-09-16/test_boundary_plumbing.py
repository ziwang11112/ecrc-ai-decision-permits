"""Integrity/reset QA, not comparative native episodes or outcome tests."""
from copy import deepcopy
import unittest
from boundary_common import ROOT, apply_patch, digest, fixture_environment, inherited, read, within


class PatchIntegrity(unittest.TestCase):
    def test_reject_absent_key_and_preserve_source(self):
        base = {"booking": {"state": None}}
        with self.assertRaises(KeyError):
            apply_patch(base, {"operations": [{"path": ["booking", "missing"], "before": None, "after": 1}]})
        self.assertEqual(base, {"booking": {"state": None}})

    def test_reject_stale_before_binding(self):
        with self.assertRaises(ValueError):
            apply_patch({"x": [1, 2]}, {"operations": [{"path": ["x", 1], "before": 3, "after": 7}]})

    def test_reject_repeated_path(self):
        with self.assertRaises(ValueError):
            apply_patch({"x": 1}, {"operations": [{"path": ["x"], "before": 1, "after": 2},
                                                    {"path": ["x"], "before": 2, "after": 3}]})

    def test_nested_replacement_is_detached(self):
        original = {"x": {"list": [{"amount": 9}]}}
        patch = {"operations": [{"path": ["x", "list"], "before": [{"amount": 9}], "after": [{"amount": -9}]}]}
        actual = apply_patch(original, patch)
        actual["x"]["list"][0]["amount"] = 123
        self.assertEqual(original["x"]["list"][0]["amount"], 9)
        self.assertEqual(patch["operations"][0]["after"][0]["amount"], -9)

    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            within(ROOT, "../outside.json")


class FixtureIsolation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        inherited.setup()

    def test_fresh_native_constructor_isolated_without_tools(self):
        before = read(ROOT / "fixtures/sole24_at/BEFORE_DB.json.gz")
        original_hash = digest(before)
        left, right = fixture_environment(before), fixture_environment(before)
        left.tools.db.reservations["9Z5X1D"].cabin = "business"
        self.assertEqual(right.tools.db.model_dump(mode="json"), before)
        self.assertEqual(digest(before), original_hash)
        self.assertNotEqual(left.tools.db.model_dump(mode="json"), before)

    def test_grid_actor_requests_exclude_predictions(self):
        cases = read(ROOT / "REQUESTS.json")["cases"]
        self.assertEqual(len(cases), 16)
        for case in cases:
            self.assertIsNone(case["task_id"])
            self.assertEqual(set(case["request"]), {"user_id", "user_statement", "cancellation"})
            self.assertEqual(set(case["request"]["cancellation"]), {"selector", "reason"})
            self.assertEqual(case["request"]["cancellation"]["selector"], {"kind": "ids", "ids": ["9Z5X1D"]})
            self.assertNotIn("predicted_category", repr(case))


if __name__ == "__main__":
    unittest.main()
