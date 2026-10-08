"""Offline controller fixtures only: no candidate execution or API calls.

The injected runner returns fabricated, clearly labelled unit results. These
fixtures test accounting/identity/visibility and must never count as study data.
"""
from copy import deepcopy
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from batch_backend import ARMS, Backend, InvalidRequest
from effect_service import IDENTITY_FIELDS, digest


TASKS = [
    {"task_id": f"UnitTask/{i}", "prompt": "Unit fixture, never executed.",
     "entry_point": "unit_only", "test": f"unit-only test marker {i}"}
    for i in range(4)
]
INERT_CODE = "UNIT FIXTURE ONLY; NOT EXECUTABLE PYTHON"


class UnitRunner:
    def __init__(self, statuses=()):
        self.statuses = list(statuses)
        self.calls = []

    def __call__(self, job, work_dir):
        self.calls.append({"job": deepcopy(job), "work_dir": str(work_dir)})
        index = len(self.calls) - 1
        status = self.statuses[index] if index < len(self.statuses) else "pass"
        return {
            **{key: job[key] for key in IDENTITY_FIELDS},
            "job_digest": job["job_hash"], "status": status,
            "actual_start_known": True, "actual_starts": 1,
            "cpu_seconds": 0.0, "wall_seconds": 0.0, "launcher_wall_seconds": 0.0,
            "unit_fixture_only": True,
        }


class BatchBackendTests(unittest.TestCase):
    def setUp(self):
        tests_root = (ROOT / "tests").resolve()
        self.temp_root = Path(tempfile.mkdtemp(prefix="u-", dir=tests_root)).resolve()
        self.addCleanup(self.cleanup_temp)
        self.backends = []

    def cleanup_temp(self):
        for backend in self.backends:
            backend.close()
        # Validate exact final target before any recursive temporary cleanup.
        target = self.temp_root.resolve()
        if not target.is_relative_to((ROOT / "tests").resolve()) or not target.name.startswith("u-"):
            raise AssertionError("Unsafe test cleanup target")
        shutil.rmtree(target)

    def backend(self, arm, condition="normal", statuses=()):
        runner = UnitRunner(statuses)
        directory = self.temp_root / str(len(self.backends))
        backend = Backend(directory, deepcopy(TASKS), arm, condition,
                          offline_test_runner=runner)
        self.backends.append(backend)
        return backend, runner

    def register(self, backend, index, suffix=""):
        return backend.register_candidate(TASKS[index]["task_id"], INERT_CODE + suffix)["candidate_id"]

    def test_normal_shared_quota_and_prompt_only_fourth_request(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm)
                feedback = [backend.verify(self.register(backend, i)) for i in range(4)]
                expected = 4 if arm == "prompt_only" else 3
                summary = backend.summary()
                self.assertEqual(len(runner.calls), expected)
                self.assertEqual(summary["actual_starts"], expected)
                self.assertEqual(summary["known_pass_count"], expected)
                self.assertEqual(summary["held"], 0)
                self.assertEqual(summary["proposed_overquota"], 1)
                self.assertEqual(summary["actual_jobs_over_budget"], int(arm == "prompt_only"))
                self.assertEqual(feedback[3]["status"], "completed" if arm == "prompt_only" else "denied")
                self.assertEqual(summary["denials"], int(arm != "prompt_only"))

    def test_relative_hidden_release_explicit_recovery_and_shared_held(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm, "hidden_first_result")
                candidates = [self.register(backend, i) for i in range(4)]
                backend.set_turn(4)
                first = backend.verify(candidates[0])
                self.assertEqual(first["status"], "unknown")
                operation = first["operation_id"]
                self.assertEqual(backend.summary()["hidden_release"]["release_turn"], 7)
                for turn in (5, 6):
                    backend.set_turn(turn)
                    self.assertEqual(backend.recover(operation)["status"], "unknown")
                    self.assertEqual(backend.verify(candidates[0])["status"], "unknown")
                    self.assertEqual(len(runner.calls), 1)
                backend.verify(candidates[1])
                backend.verify(candidates[2])
                before = backend.summary()
                self.assertEqual(before["known_pass_count"], 2)
                self.assertEqual(before["actual_starts"], 3)
                self.assertEqual(before["held"], 1)
                fourth = backend.verify(candidates[3])
                self.assertEqual(fourth["status"], "completed" if arm == "prompt_only" else "denied")
                backend.set_turn(7)
                # Expiry of the hidden interval does not reconcile automatically.
                self.assertEqual(backend.verify(candidates[0])["status"], "unknown")
                self.assertEqual(backend.summary()["held"], 1)
                actual_before_recover = len(runner.calls)
                recovered = backend.recover(operation)
                self.assertEqual((recovered["status"], recovered["result"]), ("completed", "pass"))
                self.assertEqual(len(runner.calls), actual_before_recover)
                after = backend.summary()
                self.assertEqual(after["held"], 0)
                self.assertEqual(after["recovered_loss_original"], 1)
                self.assertEqual(after["duplicate_starts"], 0)
                self.assertEqual(after["known_pass_count"], 4 if arm == "prompt_only" else 3)
                # Re-read remains the same result with no returned budget unit.
                backend.recover(operation)
                self.assertEqual(len(runner.calls), actual_before_recover)

    def test_hidden_obligation_and_quota_survive_backend_reopen(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm, "hidden_first_result")
                refs = [self.register(backend, i) for i in range(4)]
                backend.set_turn(2)
                operation = backend.verify(refs[0])["operation_id"]
                backend.verify(refs[1])
                backend.verify(refs[2])
                reopened = Backend(backend.run_dir, deepcopy(TASKS), arm, "hidden_first_result",
                                   offline_test_runner=runner)
                self.backends.append(reopened)
                self.assertEqual(reopened.batch_id, backend.batch_id)
                self.assertEqual(reopened.summary()["held"], 1)
                self.assertEqual(reopened.recover(operation)["status"], "unknown")
                expected_status = "completed" if arm == "prompt_only" else "denied"
                self.assertEqual(reopened.verify(refs[3])["status"], expected_status)
                reopened.set_turn(5)
                self.assertEqual(reopened.recover(operation)["status"], "completed")
                self.assertEqual(len(runner.calls), 4 if arm == "prompt_only" else 3)
                self.assertEqual(reopened.summary()["held"], 0)

    def test_identity_is_task_bound_and_pass_count_uses_distinct_tasks(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm)
                a = self.register(backend, 0)
                duplicate = backend.register_candidate(TASKS[0]["task_id"], INERT_CODE)
                b = self.register(backend, 1)
                revision = self.register(backend, 0, " REVISED")
                self.assertEqual(duplicate["candidate_id"], a)
                self.assertTrue(duplicate["deduplicated"])
                self.assertEqual(len({a, b, revision}), 3)
                self.assertNotEqual(backend.get_job(a)["job_hash"], backend.get_job(b)["job_hash"])
                for candidate in (a, b, revision):
                    backend.verify(candidate)
                backend.verify(a)
                summary = backend.summary()
                self.assertEqual(len(runner.calls), 3)
                self.assertEqual(summary["actual_pass_count"], 3)
                self.assertEqual(summary["known_pass_count"], 2)
                self.assertEqual(summary["actual_pass_task_count"], 2)

    def test_finish_keeps_unverified_candidates_separate_and_is_immutable(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm)
                refs = [self.register(backend, i) for i in range(4)]
                extra_same_task = self.register(backend, 0, " OTHER")
                backend.verify(refs[0])
                with self.assertRaises(InvalidRequest):
                    backend.finish([refs[0], extra_same_task])
                self.assertIsNone(backend.summary()["selected_candidate_ids"])
                result = backend.finish(refs)
                self.assertEqual(len(result["selected"]), 4)
                self.assertEqual([r["verified_pass"] for r in result["selected"]], [True, False, False, False])
                self.assertEqual(result["known_verified_pass_tasks"], [TASKS[0]["task_id"]])
                self.assertEqual(backend.summary()["known_pass_count"], 1)
                self.assertEqual(len(runner.calls), 1)
                self.assertEqual(backend.finish(refs), result)
                with self.assertRaises(InvalidRequest):
                    backend.finish([])
                with self.assertRaises(InvalidRequest):
                    backend.verify(refs[1])

    def test_unknown_requests_never_dispatch_and_empty_finish_is_allowed(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm)
                for method, args in (
                    (backend.recover, ("o999",)), (backend.verify, ("c999",)),
                    (backend.register_candidate, ("outside-batch", INERT_CODE)),
                    (backend.finish, (["c999"],)),
                ):
                    with self.assertRaises(InvalidRequest):
                        method(*args)
                self.assertEqual(len(runner.calls), 0)
                self.assertEqual(backend.summary()["jobs_attempted"], 0)
                self.assertEqual(backend.finish([])["selected"], [])

    def test_late_first_verification_retains_unobserved_completed_result(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm, "hidden_first_result")
                candidate = self.register(backend, 0)
                backend.set_turn(15)
                self.assertEqual(backend.verify(candidate)["status"], "unknown")
                summary = backend.summary()
                self.assertEqual(summary["hidden_release"]["release_turn"], 18)
                self.assertEqual(summary["actual_pass_task_count"], 1)
                self.assertEqual(summary["known_pass_count"], 0)
                self.assertEqual(summary["held"], 1)
                selected = backend.finish([candidate])
                self.assertFalse(selected["selected"][0]["verified_pass"])
                self.assertEqual(len(runner.calls), 1)

    def test_failed_and_timeout_jobs_consume_cumulative_budget(self):
        for arm in ("ordinary", "ecrc"):
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm, statuses=("fail", "timeout", "pass"))
                refs = [self.register(backend, i) for i in range(4)]
                for candidate, expected in zip(refs[:3], ("fail", "timeout", "pass")):
                    self.assertEqual(backend.verify(candidate)["result"], expected)
                self.assertEqual(backend.verify(refs[3])["status"], "denied")
                summary = backend.summary()
                self.assertEqual((len(runner.calls), summary["known_pass_count"], summary["held"]), (3, 1, 0))

    def test_wrong_result_binding_does_not_reconcile_unknown_operation(self):
        for arm in ARMS:
            with self.subTest(arm=arm):
                backend, runner = self.backend(arm, "hidden_first_result")
                candidate = self.register(backend, 0)
                operation = backend.verify(candidate)["operation_id"]
                backend.set_turn(3)
                original_get = backend.service.get

                def wrong_ack(key):
                    ack = deepcopy(original_get(key))
                    ack["job_result"]["task_id"] = "UnitTask/wrong"
                    ack["result_hash"] = digest(ack["job_result"])
                    return ack

                backend.service.get = wrong_ack
                with self.assertRaises(ValueError):
                    backend.recover(operation)
                self.assertEqual(backend.summary()["held"], 1)
                self.assertEqual(backend.summary()["known_pass_count"], 0)
                backend.service.get = original_get
                self.assertEqual(backend.recover(operation)["status"], "completed")
                self.assertEqual(len(runner.calls), 1)


if __name__ == "__main__":
    unittest.main()
