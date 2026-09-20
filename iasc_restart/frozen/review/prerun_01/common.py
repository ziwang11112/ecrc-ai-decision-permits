"""Frozen inputs and source locations for a controlled, synthetic development run."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
S8 = ROOT / 'output/AIR-014_IASC_Reproducibility/end_to_end'
RAW = ROOT / 'research_pilots/raw_task_baseline_2026-09-14'
SCOPE = 'mixed-workflow-development-v1'
LIMIT = 2
T0 = '2026-09-12T12:00:10.000000Z'
TB = '2026-09-12T12:00:20.000000Z'
EXPIRY = '2026-09-12T13:00:30.000000Z'
TC = '2026-09-12T13:00:31.000000Z'
TD = '2026-09-12T13:00:32.000000Z'
TR = '2026-09-12T13:00:40.000000Z'
ARMS = ('raw', 'volatile_count', 'durable_count', 'ecrc')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')


def jobs():
    result = []
    for name in 'ABCD':
        hashed = digest({'synthetic_record': name, 'version': 1})
        result.append({'name': name, 'job_hash': hashed, 'decision_id': 'job-' + hashed})
    return result


def load_core():
    sys.path.insert(0, str(S8))
    from ecrc_e2e import Adapter
    import ecrc_e2e
    if Path(ecrc_e2e.__file__).resolve() != (S8 / 'ecrc_e2e.py').resolve():
        raise RuntimeError('unexpected ECRC source')
    return Adapter


def load_direct():
    sys.path.insert(0, str(RAW))
    from direct_client import DirectClient
    import direct_client
    if Path(direct_client.__file__).resolve() != (RAW / 'direct_client.py').resolve():
        raise RuntimeError('unexpected original direct source')
    return DirectClient


def request(job, at):
    # Reuse the S8 schema/configuration, with explicit new development identities.
    raw = deepcopy(read(S8 / 'inputs/distinct_contenders.json')['requests'][0])
    raw['policy']['policy_id'] = SCOPE
    raw['policy']['alert_capacity'] = LIMIT
    raw['policy']['review_capacity'] = 0
    raw['proposal'].update(decision_id=job['decision_id'], subject_id=SCOPE, session_id=SCOPE,
                           input_hash=digest(job), proposed_at=at)
    raw['evidence'].update(decision_id=job['decision_id'], created_at=at)
    for item in raw['evidence']['items']:
        item.update(evidence_id='e-' + job['job_hash'], observed_at=at, available_at=at,
                    provenance_hash=digest({'synthetic_job': job}))
    return raw
