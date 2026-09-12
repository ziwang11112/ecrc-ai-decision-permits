"""Rebind after the pre-freeze infrastructure start-state correction."""
import hashlib
import json
from pathlib import Path
from job_runner import digest_for, runner_manifest, runner_sha256

root = Path(__file__).resolve().parent
catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
old_hash = catalog['runner_sha256']
new_hash = runner_sha256()
catalog['runner_manifest'] = runner_manifest()
catalog['runner_sha256'] = new_hash
for job in catalog['jobs']:
    job['runner_sha256'] = new_hash
    digest = digest_for(job)
    job.update({'job_digest': digest, 'decision_id': 'verify:' + digest, 'used_evidence_ids': ['job:' + digest]})
with open(root / 'catalog.json', 'w', encoding='utf-8', newline='\n') as stream:
    json.dump(catalog, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write('\n')
manifest['pre_freeze_runner_revisions'] = [manifest.pop('pre_freeze_runner_revision'),
    {'previous_bundle': old_hash, 'reason': 'Missing trusted child start after successful host launch is unknown, including outer-controller timeout.',
     'previous_files': 'qa_revision_v2/', 'previous_qa': ['qa_reference_v2/', 'qa_selftest_v2/', 'qa_development_serial_v1/']}]
manifest.update({'runner_manifest': runner_manifest(), 'runner_sha256': new_hash,
                 'catalog_sha256': hashlib.sha256((root / 'catalog.json').read_bytes()).hexdigest()})
with open(root / 'manifest.json', 'w', encoding='utf-8', newline='\n') as stream:
    json.dump(manifest, stream, ensure_ascii=False, sort_keys=True, indent=2)
    stream.write('\n')
print(json.dumps({'runner_sha256': new_hash, 'catalog_sha256': manifest['catalog_sha256']}))
