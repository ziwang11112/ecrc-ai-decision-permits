"""Synthetic durability/admission QA; no business episodes or service effects."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from direct_adapter import DurableDirectCount, digest


def fixture_ack(job: dict, effect_id: int = 1) -> dict:
    payload = {"job_hash": job["job_hash"]}
    return {"idempotency_key": "direct:" + job["job_hash"],
            "payload": payload, "payload_hash": digest(payload),
            "effect_id": effect_id, "committed_at": "2026-09-15T00:00:00+00:00",
            "created": True}


class DurableDirectCountTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="direct-count-qa-")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "client.sqlite"
        self.client = DurableDirectCount(self.path, "fixed-budget", 2)
        self.a, self.b, self.c = ({"job_hash": item} for item in ("a", "b", "c"))

    def test_descriptor_matches_unmodified_raw_client(self):
        raw_path = Path(__file__).resolve().parent.parent / "raw_task_baseline_2026-09-14/direct_client.py"
        spec = importlib.util.spec_from_file_location("frozen_raw_direct_qa", raw_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        raw = module.DirectClient()
        self.assertIsNone(raw.limit)
        self.assertEqual(self.client.prepare(self.a), raw.submit_descriptor(self.a))

    def test_success_and_unknown_both_keep_cumulative_charge(self):
        self.client.prepare(self.a)
        self.client.finish(self.a, fixture_ack(self.a))
        self.client.prepare(self.b)  # no acknowledgement: outcome unknown
        self.assertIsNone(self.client.prepare(self.c))
        snap = self.client.snapshot()
        self.assertEqual((snap["reserved_count"], snap["acknowledged_count"], snap["pending_count"]), (2, 1, 1))

    def test_repeated_key_remains_retryable_at_limit_after_reopen(self):
        original = self.client.prepare(self.a)
        self.client.prepare(self.b)
        restarted = DurableDirectCount(self.path, "fixed-budget", 2)
        self.assertEqual(restarted.prepare(self.a), original)
        self.assertEqual(restarted.prepare(dict(self.a, queue_position=99)), original)
        self.assertEqual(restarted.snapshot()["reserved_count"], 2)
        self.assertIsNone(restarted.prepare(self.c))

    def test_new_process_recovers_pending_and_completed_binding(self):
        original_a = self.client.prepare(self.a)
        original_b = self.client.prepare(self.b)
        self.client.finish(self.a, fixture_ack(self.a))
        script = ("import json,sys; from direct_adapter import DurableDirectCount; "
                  "c=DurableDirectCount(sys.argv[1],'fixed-budget',2); "
                  "print(json.dumps({'pending':c.pending(),'snapshot':c.snapshot(),"
                  "'retry':c.prepare({'job_hash':'b'}),'new':c.prepare({'job_hash':'c'})}))")
        result = subprocess.run([sys.executable, "-B", "-c", script, str(self.path)],
                                cwd=Path(__file__).resolve().parent, capture_output=True,
                                text=True, check=True, timeout=15)
        value = json.loads(result.stdout)
        self.assertEqual(value["pending"], [original_b])
        self.assertEqual(value["retry"], original_b)
        self.assertIsNone(value["new"])
        self.assertEqual(value["snapshot"]["operations"][0]["descriptor"], original_a)
        self.assertEqual(value["snapshot"]["operations"][0]["ack"], fixture_ack(self.a))

    def test_concurrent_distinct_preparations_cannot_overspend(self):
        def submit(index):
            return DurableDirectCount(self.path, "fixed-budget", 2).prepare({"job_hash": str(index)})
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(submit, range(24)))
        self.assertEqual(sum(result is not None for result in results), 2)
        self.assertEqual(self.client.snapshot()["reserved_count"], 2)

    def test_concurrent_same_key_is_charged_once(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: self.client.prepare(self.a), range(24)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(self.client.snapshot()["reserved_count"], 1)

    def test_scope_limit_cannot_be_reset_by_new_constructor(self):
        self.client.prepare(self.a)
        with self.assertRaisesRegex(ValueError, "limit cannot change"):
            DurableDirectCount(self.path, "fixed-budget", 3)
        self.assertEqual(DurableDirectCount(self.path, "fixed-budget", 2).snapshot()["reserved_count"], 1)

    def test_scope_is_explicitly_separate(self):
        self.client.prepare(self.a)
        separate = DurableDirectCount(self.path, "another-budget", 1)
        self.assertEqual(separate.snapshot()["reserved_count"], 0)
        self.assertIsNotNone(separate.prepare(self.b))
        self.assertIsNone(separate.prepare(self.c))
        self.assertEqual(self.client.snapshot()["reserved_count"], 1)

    def test_mismatched_ack_fields_do_not_change_pending(self):
        self.client.prepare(self.a)
        ack = fixture_ack(self.a)
        bad_values = [dict(ack, idempotency_key="direct:b"),
                      dict(ack, payload={"job_hash": "b"}),
                      dict(ack, payload_hash="0" * 64),
                      dict(ack, effect_id=True), dict(ack, effect_id=0),
                      dict(ack, committed_at=""), dict(ack, error="unavailable")]
        for bad in bad_values:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.client.finish(self.a, bad)
        self.assertEqual(len(self.client.pending()), 1)
        self.assertEqual(self.client.snapshot()["acknowledged_count"], 0)

    def test_cannot_finish_unprepared_job(self):
        with self.assertRaisesRegex(ValueError, "not prepared"):
            self.client.finish(self.a, fixture_ack(self.a))
        self.assertEqual(self.client.snapshot()["reserved_count"], 0)

    def test_cached_ack_does_not_refund_and_preserves_first_ack(self):
        self.client.prepare(self.a)
        ack = fixture_ack(self.a)
        self.client.finish(self.a, ack)
        self.client.finish(self.a, dict(ack, created=False))
        self.assertEqual(self.client.snapshot()["operations"][0]["ack"], ack)
        self.assertEqual(self.client.snapshot()["reserved_count"], 1)
        self.assertEqual(self.client.pending(), [])

    def test_conflicting_effect_or_commit_time_cannot_overwrite_ack(self):
        self.client.prepare(self.a)
        ack = fixture_ack(self.a)
        self.client.finish(self.a, ack)
        for changed in (dict(ack, effect_id=2), dict(ack, committed_at="2026-09-16")):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "conflicting acknowledgement"):
                self.client.finish(self.a, changed)
        self.assertEqual(self.client.snapshot()["operations"][0]["ack"], ack)

    def test_persisted_content_conflict_fails_closed(self):
        self.client.prepare(self.a)
        # Simulate a damaged binding record, not a routine externally writable DB.
        con = sqlite3.connect(self.path)
        try:
            con.execute("UPDATE direct_operations SET payload_hash=?", ("different",))
            con.commit()
        finally:
            con.close()
        with self.assertRaisesRegex(ValueError, "different content"):
            self.client.prepare(self.a)
        with self.assertRaisesRegex(ValueError, "persisted request binding"):
            self.client.finish(self.a, fixture_ack(self.a))
        self.assertEqual(self.client.snapshot()["acknowledged_count"], 0)


if __name__ == "__main__":
    unittest.main()
