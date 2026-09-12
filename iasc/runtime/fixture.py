"""Shared, preissued ECRC fixture; issuance is outside timed delivery."""
from pathlib import Path
import sys,sqlite3,json,hashlib
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE/'source_snapshot'))
from agentic_eeg_dm.governance import ClaimRule,EvidenceEnvelope,EvidenceItem,EvidenceRule,ModelBinding,OrderedAdjudicator,PolicyManifest,ProposalEnvelope,SQLiteCapacityLedger,canonical_hash
ARM_AT='2026-09-11T12:00:10Z'
DONE_AT='2026-09-11T12:00:11Z'
EXPIRED_AT='2031-01-01T00:00:00Z'

def make_fixture(folder,n=1,capacity=None,include_nonaction=False,warmup=False):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    db=folder/'issuance.sqlite';assert not db.exists()
    k=n if capacity is None else capacity
    policy=PolicyManifest(policy_id='local-service-protocol',revision=1,issuer_id='trusted-test-issuer',effective_from='2026-09-11T00:00:00Z',expires_at='2030-01-01T00:00:00Z',approved_models=(ModelBinding('fixed-proposer','a'*64),),evidence_rules=(EvidenceRule(evidence_type='test_record',allowed_sources=('local-fixture',),allowed_schema_versions=('1.0',),max_age_seconds=60,use_allowed=True),),score_threshold=.60,uncertainty_threshold=.90,review_band_width=.03,alert_capacity=k,review_capacity=0,capacity_scope='subject_session',claim_rules=(ClaimRule('record_action',('alert',),required_evidence_types=('test_record',)),ClaimRule('record_review',('review',),required_evidence_types=('test_record',)),ClaimRule('record_no_action',('no_action',))),blocked_claim_ids=('clinical_benefit',))
    ledger=SQLiteCapacityLedger(db);ledger.register_policy(policy)
    adjudicator=OrderedAdjudicator(ledger,permit_ttl_seconds=86400)
    items=[]
    for i in range(n+int(include_nonaction)+int(warmup)):
        warm=warmup and i==n+int(include_nonaction)
        decision=f'warmup-{i}' if warm else f'op-{i:04d}'
        score=.1 if include_nonaction and i==n else .8
        proposal=ProposalEnvelope(decision_id=decision,subject_id='warm' if warm else 'shared-scope',session_id='delivery',model_id='fixed-proposer',model_version='1',model_hash='a'*64,score=score,uncertainty=.4,proposed_action='alert',proposed_at='2026-09-11T12:00:05Z',input_hash=canonical_hash({'decision':decision,'score':score}),validation_scope_id='synthetic-loopback-service')
        evidence=EvidenceEnvelope(decision_id=decision,created_at='2026-09-11T12:00:04Z',items=(EvidenceItem(evidence_id='e-'+decision,evidence_type='test_record',source='local-fixture',schema_version='1.0',observed_at='2026-09-11T12:00:03Z',available_at='2026-09-11T12:00:04Z',provenance_hash=canonical_hash({'decision':decision}),requested_for_use=True),))
        items.append(adjudicator.adjudicate(policy,proposal,evidence,at=ARM_AT).to_dict())
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row
        data={'policy':policy.to_dict(),'permits':items}
        for table in ['reservations','capacity_state','issued_permits']:data[table]=[dict(r) for r in c.execute(f'SELECT * FROM {table}')]
    path=folder/'fixture.json';path.write_text(json.dumps(data,sort_keys=True,indent=2)+'\n')
    return data

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--n',type=int,default=1);a=p.parse_args();make_fixture(a.out,a.n,include_nonaction=True)
