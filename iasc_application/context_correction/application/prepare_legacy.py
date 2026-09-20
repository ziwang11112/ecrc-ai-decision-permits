from pathlib import Path
import hashlib,json,shutil
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
BASE=ROOT/'qa/iasc_restructure_2026-09-12/anonymous_download_verified/end_to_end'
dest=HERE/'legacy/end_to_end';dest.mkdir(parents=True,exist_ok=True)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
files=[BASE/'ecrc_e2e.py',BASE/'ordinary_e2e.py']+sorted(p for p in (BASE/'legacy_snapshot').rglob('*') if p.is_file())
rows=[]
for src in files:
    rel=src.relative_to(BASE);out=dest/rel;out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists():assert sha(out)==sha(src),out
    else:shutil.copy2(src,out)
    rows.append({'path':rel.as_posix(),'sha256':sha(out),'source_relative_to_fixed_archive':'end_to_end/'+rel.as_posix()})
fixture=HERE/'legacy/request_template.json'
request=json.loads((BASE/'inputs/distinct_contenders.json').read_text(encoding='utf-8'))['requests'][0]
fixture.write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
(HERE/'legacy/SOURCE_MANIFEST.json').write_text(json.dumps({'fixed_release':'iasc-restructured-2026-09-12','unchanged_files':rows,'request_template_source':'end_to_end/inputs/distinct_contenders.json requests[0]'},indent=2)+'\n',encoding='utf-8')
Q=ROOT/'qa/iasc_application_pilot_2026-09-12';before=Q/'before';before.mkdir(parents=True,exist_ok=True)
baseline={}
for name in ['AIR-014_IASC_Manuscript.pdf','AIR-014_IASC_Overleaf.zip','AIR-014_IASC_Supplementary_Figures.pdf']:
    src=ROOT/'output'/name;out=before/name
    if out.exists():assert sha(out)==sha(src)
    else:shutil.copy2(src,out)
    baseline[name]=sha(out)
(before/'BASELINE.json').write_text(json.dumps(baseline,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'copied_frozen_source_files':len(rows),'before_artifacts':baseline},indent=2))
