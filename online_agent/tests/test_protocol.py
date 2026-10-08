"""Schedule and task-boundary checks; no candidate execution."""
from pathlib import Path
import json
import hashlib
import unittest

from schedule import ROOT, STUDIES, schedule, verify_schedule


class ProtocolTests(unittest.TestCase):
    def test_all_source_schedules_reconstruct_exactly(self):
        for study in STUDIES:
            rows = schedule(study)
            self.assertEqual(verify_schedule(study), 288 if study == 'claude_v2' else 576)
            keys = {(r['batch_id'], r['repeat'], r['provider'], r['arm'], r['condition']) for r in rows}
            self.assertEqual(len(keys), len(rows))

    def test_supplemental_studies_reuse_same_tasks(self):
        specs = [json.loads((ROOT / 'protocol' / (s + '_schedule_spec.json')).read_text()) for s in STUDIES]
        self.assertTrue(all(s['batches'] == specs[0]['batches'] for s in specs))

    def test_task_projection_has_no_canonical_solutions(self):
        batches = json.loads((ROOT / 'runtime/data/batches.json').read_text(encoding='utf-8'))
        self.assertEqual(len(batches), 24)
        tasks = [task for batch in batches for task in batch['tasks']]
        self.assertEqual(len({t['task_id'] for t in tasks}), 96)
        for task in tasks:
            self.assertEqual(set(task), {'task_id', 'prompt', 'entry_point', 'test'})

    def test_analysis_preserves_unknowns_and_adverse_outcome_rules(self):
        for study in STUDIES:
            plan = json.loads((ROOT / 'protocol' / (study + '_analysis_plan.json')).read_text())
            self.assertIn('unknown_execution_start', plan['failures'])
            self.assertIn('attempted_provider_failure', plan['failures'])
            self.assertEqual(plan['bootstrap']['replicates'], 10000)
            self.assertEqual(plan['bootstrap']['seed'], 20261007)

    def test_id_only_selection_reconstructs_all_115_ranks(self):
        data = ROOT / 'runtime/data'
        selection = json.loads((data / 'selection.json').read_text())
        excluded = set(json.loads((data / 'exclusions.json').read_text())['unique_excluded49'])
        self.assertEqual(len(excluded), 49)
        ranked = sorted((f'HumanEval/{i}' for i in range(164) if f'HumanEval/{i}' not in excluded),
                        key=lambda task: (hashlib.sha256((selection['selection_seed'] + '|' + task).encode()).hexdigest(), int(task.split('/')[1])))
        self.assertEqual(ranked, [r['task_id'] for r in selection['eligible_tasks_in_hash_order']])
        batches = json.loads((data / 'batches.json').read_text())
        self.assertEqual(ranked[:96], [t['task_id'] for b in batches for t in b['tasks']])
