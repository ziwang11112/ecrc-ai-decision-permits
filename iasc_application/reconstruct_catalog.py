"""Reconstruct the private catalog from a separately obtained author archive.

Reads source as data only. No model/candidate code is imported or executed.
The generated catalog is private and MUST NOT be added to the public bundle.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import zipfile

RUNNER_SHA = 'e05cebc18c2dab444215fb826377edb0480db72e2bf33ed776afbbc2a1d7f150'
CATALOG_SHA = 'bbd28484d9f10143b1d5db9d80740996b49a43987e5f737ce659114a3b87a9c8'
SOURCE_SHA = '4ef4b6b65e77ba2b1f44b6f890ac5d1f7e82b817bbdb7492b71fa1f825ef3522'
SOURCE_BYTES = 73874142
MEMBER = 'humaneval/meta-llama--Meta-Llama-3.1-8B-Instruct_openai_temp_0.8-sanitized/eval_results.json'
OFFICIAL_SHA = 'b796127e635a67f93fb35c04f4cb03cf06f38c8072ee7cee8833d7bee06979ef'

def sha(blob):
    return hashlib.sha256(blob).hexdigest()

def canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def reconstruct(bundle, source):
    bundle = Path(bundle).resolve()
    source = Path(source).resolve()
    if zipfile.is_zipfile(source):
        with zipfile.ZipFile(source) as archive:
            member = archive.getinfo(MEMBER)
            if member.file_size != SOURCE_BYTES:
                raise ValueError('Unexpected uncompressed member size')
            raw = archive.read(member)  # Never extract arbitrary archive paths.
    else:
        raw = source.read_bytes()
    if len(raw) != SOURCE_BYTES or sha(raw) != SOURCE_SHA:
        raise ValueError('Published sanitized JSON member hash/size mismatch')
    archived = json.loads(raw)['eval']
    catalog = json.loads((bundle / 'metadata/catalog_template.json').read_text(encoding='utf-8'))
    official_blob = (bundle / 'application/workload/sources/HumanEval.jsonl.gz').read_bytes()
    if sha(official_blob) != OFFICIAL_SHA:
        raise ValueError('Official task data hash mismatch')
    official = {r['task_id']: r for r in map(json.loads, gzip.decompress(official_blob).decode('utf-8').splitlines())}
    actual_manifest = {}
    for relative, expected in catalog['runner_manifest'].items():
        path = (bundle / 'application/workload' / relative).resolve()
        path.relative_to((bundle / 'application/workload').resolve())
        actual_manifest[relative] = sha(path.read_bytes())
        if actual_manifest[relative] != expected:
            raise ValueError('Frozen runner file differs: ' + relative)
    if sha(canonical(actual_manifest)) != RUNNER_SHA or catalog['runner_sha256'] != RUNNER_SHA:
        raise ValueError('Frozen runner bundle hash mismatch')
    ordered = sorted(official, key=lambda task: sha(('iasc-app-task-order-v1|' + task).encode('utf-8')))
    if len(ordered) != 164 or set(archived) != set(official):
        raise ValueError('Task inventory mismatch')
    if [t['task_id'] for t in catalog['tasks']] != ordered:
        raise ValueError('Independent task ordering mismatch')
    selected = {task: sorted(range(len(archived[task])), key=lambda index: sha(f'iasc-app-20260912-v1|{task}|{index}'.encode('utf-8')))[:4] for task in ordered}
    for job in catalog['jobs']:
        task = job['task_id']
        index = job['source_array_index']
        if selected[task][job['rank'] - 1] != index:
            raise ValueError('Label-independent source selection mismatch')
        # Only the selected solution is accessed; no historical label is read.
        job['solution'] = archived[task][index]['solution']
        job['test'] = official[task]['test']
        if sha(job['solution'].encode('utf-8')) != job['solution_sha256']:
            raise ValueError('Selected program hash mismatch')
        if sha(job['test'].encode('utf-8')) != job['test_sha256']:
            raise ValueError('Official suite hash mismatch')
    blob = (json.dumps(catalog, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    if sha(blob) != CATALOG_SHA:
        raise ValueError('Complete catalog byte hash mismatch')
    return blob

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--source', type=Path, required=True, help='Verified author ZIP or uncompressed exact JSON member')
    parser.add_argument('--out', type=Path, help='Private destination outside public bundle; omitted in verify-only mode')
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    blob = reconstruct(args.bundle, args.source)
    if not args.verify_only:
        if args.out is None:
            parser.error('--out is required unless --verify-only')
        destination = args.out.resolve()
        try:
            destination.relative_to(args.bundle.resolve())
        except ValueError:
            pass
        else:
            raise ValueError('Private reconstructed catalog must be outside public bundle')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as handle:
            handle.write(blob)
    print(json.dumps({'catalog_sha256': sha(blob), 'runner_sha256': RUNNER_SHA,
                      'catalog_bytes': len(blob), 'candidate_code_executed': False,
                      'private_catalog_written': not args.verify_only}, sort_keys=True))

if __name__ == '__main__':
    main()
