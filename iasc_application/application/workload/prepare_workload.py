"""Fetch pinned official HumanEval inputs and build a label-blind job catalog."""
import gzip
import hashlib
import json
from pathlib import Path
import urllib.request
from job_runner import canonical, digest_for, runner_manifest, runner_sha256, save_json

ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[2]
COMMIT = '6d43fb980f9fee3c892a914eda09951f772ad10d'
SOURCE_SHA = '4ef4b6b65e77ba2b1f44b6f890ac5d1f7e82b817bbdb7492b71fa1f825ef3522'
SOURCE = WORKSPACE / 'research_pilots/failure_first_screen_2026-09-11/published_result/llama31_8b_humaneval_eval_results.json'
HUMANEVAL_SHA = 'b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef'


def fetch(name, remote_path):
    path = ROOT / 'sources' / name
    url = f'https://raw.githubusercontent.com/openai/human-eval/{COMMIT}/{remote_path}'
    if path.exists():
        raise FileExistsError('refusing to overwrite source ' + str(path))
    with urllib.request.urlopen(url, timeout=30) as response:
        blob = response.read(2_000_000)
    path.write_bytes(blob)
    return blob, {'path': str(path.relative_to(ROOT)), 'url': url, 'commit': COMMIT,
                  'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}


def main():
    raw_data, data_record = fetch('HumanEval.jsonl.gz', 'data/HumanEval.jsonl.gz')
    if hashlib.sha256(raw_data).hexdigest() != HUMANEVAL_SHA:
        raise RuntimeError('official HumanEval hash mismatch')
    _, license_record = fetch('HUMANEVAL_LICENSE', 'LICENSE')
    official = {item['task_id']: item for item in map(json.loads, gzip.decompress(raw_data).decode('utf-8').splitlines())}
    if len(official) != 164:
        raise RuntimeError('official task inventory mismatch')
    source_bytes = SOURCE.read_bytes()
    if hashlib.sha256(source_bytes).hexdigest() != SOURCE_SHA:
        raise RuntimeError('published candidate hash mismatch')
    # JSON parsing loads the archive, but selection accesses only the eval task
    # keys and record.solution. No status/failure-label field is inspected.
    by_task = json.loads(source_bytes)['eval']
    if set(by_task) != set(official):
        raise RuntimeError('candidate and official task IDs differ')
    ordered_tasks = sorted(official, key=lambda task: hashlib.sha256(('iasc-app-task-order-v1|' + task).encode()).hexdigest())
    bundle_manifest = runner_manifest()
    bundle_hash = runner_sha256()
    jobs, tasks, batches = [], [], {}
    for task_rank, task_id in enumerate(ordered_tasks, 1):
        partition = 'development' if task_rank <= 20 else 'evaluation'
        local_rank = task_rank - 1 if partition == 'development' else task_rank - 21
        batch = ('development_' if partition == 'development' else 'evaluation_') + f'{local_rank // 8 + 1:02d}'
        indices = sorted(range(len(by_task[task_id])), key=lambda index: hashlib.sha256(f'iasc-app-20260912-v1|{task_id}|{index}'.encode()).hexdigest())[:4]
        tasks.append({'task_id': task_id, 'task_rank': task_rank, 'partition': partition, 'batch': batch,
                      'source_record_count': len(by_task[task_id]), 'source_indices': indices})
        batches.setdefault(batch, {'batch': batch, 'batch_id': batch, 'partition': partition, 'task_ids': [], 'candidate_ids': []})['task_ids'].append(task_id)
        for rank, index in enumerate(indices, 1):
            solution = by_task[task_id][index]['solution']
            test = official[task_id]['test']
            job = {'candidate_id': f'{task_id}::{index}', 'task_id': task_id, 'source_array_index': index,
                   'solution': solution, 'solution_sha256': hashlib.sha256(solution.encode('utf-8')).hexdigest(),
                   'test': test, 'test_sha256': hashlib.sha256(test.encode('utf-8')).hexdigest(),
                   'entry_point': official[task_id]['entry_point'], 'rank': rank, 'task_rank': task_rank,
                   'partition': partition, 'batch': batch, 'batch_id': batch, 'runner_sha256': bundle_hash}
            digest = digest_for(job)
            job.update({'job_digest': digest, 'decision_id': 'verify:' + digest, 'used_evidence_ids': ['job:' + digest]})
            jobs.append(job)
            batches[batch]['candidate_ids'].append(job['candidate_id'])
    catalog = {'schema_version': 1, 'jobs': jobs, 'tasks': tasks, 'batches': list(batches.values()),
               'source_archive_sha256': SOURCE_SHA,
               'runner_manifest': bundle_manifest, 'runner_sha256': bundle_hash,
               'exposure': 'All 164 tasks were previously exposed; development/evaluation are engineering partitions and all application results remain exploratory.',
               'candidate_source_license': 'Unspecified in inspected archive; local use and public download recipe only. Do not mark candidate source MIT.',
               'test_source_license': 'MIT', 'official_commit': COMMIT}
    save_json(ROOT / 'catalog.json', catalog)
    save_json(ROOT / 'batches.json', {'tasks': tasks, 'batches': list(batches.values())})
    manifest = {'schema_version': 1, 'task_count': 164, 'candidate_count': len(jobs),
                'development_tasks': 20, 'development_candidates': 80, 'evaluation_tasks': 144,
                'evaluation_candidates': 576, 'evaluation_batches': 18, 'tasks_per_evaluation_batch': 8,
                'selection': "first four source record indices by SHA256('iasc-app-20260912-v1|task_id|source_array_index'); retain empty/duplicate source records",
                'task_order': "SHA256('iasc-app-task-order-v1|task_id'); first20 development, remaining144 evaluation",
                'candidate_fields_accessed': ['task_id map key', 'source array index', 'solution'],
                'historical_result_labels_used': False, 'candidate_execution_performed': False,
                'candidate_source': {'path': str(SOURCE), 'sha256': SOURCE_SHA, 'bytes': len(source_bytes),
                                     'license': 'unspecified', 'redistribution': 'exclude full raw candidate source from a future public bundle; supply exact source URL/member/hash/download recipe'},
                'official_sources': [data_record, license_record], 'runner_manifest': bundle_manifest,
                'runner_sha256': bundle_hash, 'catalog_sha256': hashlib.sha256((ROOT / 'catalog.json').read_bytes()).hexdigest(),
                'builder_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'empty_selected_programs': sum(job['solution'] == '' for job in jobs),
                'within_task_duplicate_selected_texts': sum(4 - len({job['solution_sha256'] for job in jobs if job['task_id'] == task}) for task in ordered_tasks),
                'all_tasks_previously_exposed': True}
    save_json(ROOT / 'manifest.json', manifest)
    print(json.dumps({key: manifest[key] for key in ('task_count', 'candidate_count', 'development_candidates', 'evaluation_candidates', 'evaluation_batches', 'runner_sha256', 'catalog_sha256', 'empty_selected_programs', 'within_task_duplicate_selected_texts')}, indent=2))


if __name__ == '__main__':
    main()
