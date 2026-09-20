"""Bounded static QA and optional one-toy unchanged-service integration.

Never execute selected application candidates here. No network/model API.
"""
from __future__ import annotations
import ast
import gzip
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
import context_catalog as subject
from run_correction import preserved, validate_inputs


class ContextChecks(unittest.TestCase):
    def test_missing_public_helper_and_required_import_are_added(self):
        prompt = "import math\n\ndef helper(x):\n    return math.floor(x)\n\ndef answer(x):\n    '''Public task.'''\n"
        source = "def answer(x):\n    return helper(x)\n"
        assembled, context, helpers, status = subject.assemble(source, prompt, "answer")
        self.assertEqual(status, "public_helpers_added")
        self.assertEqual(helpers, ["helper"])
        self.assertTrue(assembled.endswith(source))
        self.assertEqual(assembled, context + source)
        self.assertEqual([n.name for n in ast.parse(assembled).body if isinstance(n, ast.FunctionDef)], ["helper", "answer"])
        self.assertNotIn("Public task", assembled)
        self.assertIn("import math", context)

    def test_candidate_binding_is_never_replaced(self):
        prompt = "def helper(x):\n    return x\ndef answer(x):\n    '''Task.'''\n"
        for source in ("def helper(x):\n    return 999\ndef answer(x):\n    return helper(x)\n", "helper = 999\ndef answer(x):\n    return helper(x)\n"):
            with self.subTest(source=source):
                assembled, context, _, _ = subject.assemble(source, prompt, "answer")
                self.assertEqual(assembled, source)
                self.assertEqual(context, "")

    def test_empty_and_syntax_invalid_programs_do_not_gain_entry_stub(self):
        prompt = "def helper(x):\n    return x\ndef answer(x):\n    '''Task.'''\n"
        for source in ("", " \n", "def answer(:\n"):
            with self.subTest(source=source):
                assembled, context, helpers, _ = subject.assemble(source, prompt, "answer")
                self.assertEqual(assembled, source)
                self.assertEqual((context, helpers), ("", []))

    def test_future_import_is_not_silently_rewritten(self):
        prompt = "def helper(x):\n    return x\ndef answer(x):\n    '''Task.'''\n"
        with self.assertRaisesRegex(ValueError, "future import"):
            subject.assemble("from __future__ import annotations\ndef answer(x):\n    return helper(x)\n", prompt, "answer")

    def test_public_projection_discards_test_and_reference(self):
        row = {"task_id": "toy", "prompt": "def f():\n    '''public'''\n", "entry_point": "f",
               "test": "DO_NOT_USE_TEST", "canonical_solution": "DO_NOT_USE_REFERENCE"}
        with tempfile.TemporaryDirectory(dir=subject.HERE) as directory:
            path = Path(directory) / "toy.gz"
            path.write_bytes(gzip.compress((json.dumps(row) + "\n").encode()))
            public = subject.load_public_records(path)
        self.assertEqual(set(public["toy"]), {"task_id", "prompt", "entry_point"})
        self.assertNotIn("DO_NOT_USE", json.dumps(public))

    def test_real_catalog_has_exact_eleven_changes_and_stable_test_runner_order(self):
        before = subject.read(subject.ORIGINAL / "bound_catalog.json")
        after = subject.read(subject.HERE / "corrected_catalog.json")
        self.assertEqual(after["batches"], before["batches"])
        changed = 0
        for old, new in zip(before["jobs"], after["jobs"], strict=True):
            provenance = new["context_correction"]
            self.assertEqual(provenance["original_solution"], old["solution"])
            self.assertEqual(provenance["original_solution_sha256"], old["solution_sha256"])
            self.assertEqual(new["solution"], provenance["context_source"] + old["solution"])
            self.assertEqual(new["solution_sha256"], subject.sha_bytes(new["solution"].encode()))
            for field in ("task_id", "candidate_id", "rank", "source_array_index", "test", "test_sha256", "runner_sha256", "entry_point", "batch_id"):
                self.assertEqual(new[field], old[field])
            expected = subject.digest({key: new[key] for key in subject.FIELDS})
            self.assertEqual((new["job_hash"], new["job_digest"], new["decision_id"], new["used_evidence_ids"]),
                             (expected, expected, "verify:" + expected, ["job:" + expected]))
            if new["solution"] != old["solution"]:
                changed += 1
                self.assertIn(new["task_id"], subject.TASK_HELPERS)
                self.assertNotIn(new["entry_point"], provenance["added_helper_names"])
            else:
                self.assertEqual(new["decision_id"], old["decision_id"])
        self.assertEqual(changed, 11)
        self.assertEqual(len(before["jobs"]) - changed, 645)

    def test_original_protection_and_grid_subsequence(self):
        self.assertEqual(preserved()["changed"], [])
        plan = validate_inputs()
        self.assertEqual([c["original_run_index"] for c in plan["cells"]],
                         list(range(1, 9)) + list(range(73, 81)) + list(range(105, 121)))


def load_service():
    sys.path.insert(0, str(subject.ORIGINAL / "service"))
    path = subject.ORIGINAL / "service/verification_service.py"
    spec = importlib.util.spec_from_file_location("context_qa_original_service", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def integration():
    """One fresh synthetic job, then same-key cache retrieval; never eval input."""
    out = subject.HERE / "qa_integration"
    out.mkdir(exist_ok=False)
    service = load_service()
    runner = subject.ORIGINAL / "workload/job_runner.py"
    # Static compatibility check of the real corrected catalog starts no job.
    _, catalog_jobs, _, _ = service.load_catalog(subject.HERE / "corrected_catalog.json", runner)
    original = subject.read(subject.ORIGINAL / "bound_catalog.json")
    prompt = "import math\n\ndef helper(x):\n    return math.floor(x)\n\ndef answer(x):\n    '''Return floor through public helper.'''\n"
    candidate = "def answer(x):\n    return helper(x)\n"
    source, context, _, _ = subject.assemble(candidate, prompt, "answer")
    test = "def check(candidate):\n    assert candidate(2.75) == 2\n    assert candidate(-1.25) == -2\n"
    job = {"task_id": "ContextCorrectionToy", "candidate_id": "ContextCorrectionToy::1", "solution": source,
           "solution_sha256": subject.sha_bytes(source.encode()), "test": test,
           "test_sha256": subject.sha_bytes(test.encode()), "runner_sha256": original["runner_sha256"], "entry_point": "answer"}
    hashed = subject.digest({k: job[k] for k in subject.FIELDS})
    job.update(job_hash=hashed, decision_id="verify:" + hashed, used_evidence_ids=["job:" + hashed])
    catalog = {"runner_manifest": original["runner_manifest"], "runner_sha256": original["runner_sha256"],
               "jobs": [job], "permitted_claim_ids": ["run_verification"]}
    subject.write_new(out / "toy_catalog.json", catalog)
    ledger = service.VerificationLedger(out / "sink.sqlite", out / "toy_catalog.json", runner, out / "service_runs")
    payload = {"decision_id": job["decision_id"], "route": "alert", "permitted_claim_ids": ["run_verification"],
               "used_evidence_ids": job["used_evidence_ids"]}
    body, payload_hash = service.canonical_payload(payload)
    code1, ack1 = ledger.post("context-correction-toy-key", body, payload_hash)
    code2, ack2 = ledger.post("context-correction-toy-key", body, payload_hash)
    assert code1 in (200, 201) and code2 == 200
    assert ack1["job_result"]["status"] == "pass" and ack1["job_result"]["actual_starts"] == 1
    assert ack1["effect_id"] == ack2["effect_id"] and ack1["result_hash"] == ack2["result_hash"]
    events = [json.loads(line) for line in (out / "service_runs/service_events.jsonl").read_text().splitlines()]
    assert sum(e["event"] == "runner_invoked" for e in events) == 1
    assert sum(e["event"] == "cache_hit" for e in events) == 1
    report = {"passed": True, "scope": "One synthetic helper-dependent program; no selected candidate or formal trajectory executed",
              "corrected_catalog_jobs_validated_without_execution": len(catalog_jobs),
              "first_status": code1, "duplicate_status": code2, "original_candidate_sha256": subject.sha_bytes(candidate.encode()),
              "context_sha256": subject.sha_bytes(context.encode()), "assembled_solution_sha256": job["solution_sha256"],
              "ack": ack1, "duplicate_ack": ack2, "preservation": preserved()}
    subject.write_new(out / "INTEGRATION_QA.json", report)
    print(subject.canonical({"passed": True, "actual_starts": 1, "cache_hits": 1, "catalog_jobs_validated": len(catalog_jobs)}))


if __name__ == "__main__":
    if sys.argv[1:] == ["--integration"]:
        integration()
    else:
        unittest.main(verbosity=2)
