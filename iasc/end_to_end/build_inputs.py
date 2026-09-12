"""Declarative shared raw inputs; no adjudicator/issuance is invoked."""
from pathlib import Path
import hashlib,json,sys
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'legacy_snapshot/source_snapshot'))
from agentic_eeg_dm.governance import PolicyManifest,ModelBinding,EvidenceRule,ClaimRule,ProposalEnvelope,EvidenceEnvelope,EvidenceItem,canonical_hash
AT='2026-09-12T12:00:10.000000Z'
LATER='2026-09-12T13:00:10.000000Z'
EARLY='2026-09-12T12:00:30.000000Z'
SCENARIOS=('distinct_contenders','mixed_claim_fallback','kill_during_issuance','kill_after_issue_resume','expired_unarmed_cleanup','accepted_timeout_cleanup_recovery')
def policy():
    return PolicyManifest(policy_id='e2e-limited-policy',revision=1,issuer_id='trusted-local-experiment',
        effective_from='2026-09-12T00:00:00Z',expires_at='2030-01-01T00:00:00Z',
        approved_models=(ModelBinding('fixed-proposal','a'*64),),
        evidence_rules=(EvidenceRule('signal',('local-fixture',),('1.0',),60,True),EvidenceRule('context',('local-fixture',),('1.0',),60,True)),
        score_threshold=.6,uncertainty_threshold=.9,review_band_width=.03,alert_capacity=2,review_capacity=1,capacity_scope='subject_session',
        claim_rules=(ClaimRule('notify',('alert',),required_evidence_types=('signal',)),ClaimRule('review_request',('review',),required_evidence_types=('signal',))),
        blocked_claim_ids=('clinical_benefit',)).to_dict()
def request(decision,kind='alert'):
    p=ProposalEnvelope(decision_id=decision,subject_id='shared-person',session_id='shared-episode',model_id='fixed-proposal',model_version='1',model_hash='a'*64,
        score=.6 if kind=='review' else .8,uncertainty=.2,proposed_action='alert',proposed_at='2026-09-12T12:00:05Z',input_hash=canonical_hash({'decision':decision,'kind':kind}),validation_scope_id='synthetic-end-to-end')
    e=EvidenceEnvelope(decision_id=decision,created_at='2026-09-12T12:00:04Z',items=(EvidenceItem(evidence_id='e-'+decision,evidence_type='context' if kind=='unsupported' else 'signal',source='local-fixture',schema_version='1.0',observed_at='2026-09-12T12:00:03Z',available_at='2026-09-12T12:00:04Z',provenance_hash=canonical_hash({'decision':decision,'kind':kind,'record':1}),requested_for_use=True),))
    return {'policy':policy(),'proposal':p.to_dict(),'evidence':e.to_dict()}
def build():
    folder=HERE/'inputs';folder.mkdir(exist_ok=True)
    hashes=[]
    for name in SCENARIOS:
        if name=='mixed_claim_fallback':
            rows=[request('unsupported','unsupported')]+[request(f'alert-{i}') for i in range(4)]+[request(f'review-{i}','review') for i in range(4)]
        elif name=='expired_unarmed_cleanup': rows=[request('target')]+[request(f'contender-{i}') for i in range(8)]
        else: rows=[request('target')]+[request(f'contender-{i}') for i in range(7)]
        path=folder/f'{name}.json';path.write_text(json.dumps({'scenario':name,'requests':rows},sort_keys=True,indent=2)+'\n',encoding='utf-8')
        hashes.append({'path':str(path.relative_to(HERE)).replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'requests':len(rows)})
    (folder/'MANIFEST.json').write_text(json.dumps(hashes,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(hashes,indent=2))
if __name__=='__main__':build()
