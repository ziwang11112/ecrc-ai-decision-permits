"""Record the reviewed code/input version before formal execution."""
from datetime import datetime,timezone
import json
from run_e2e import HERE,source_manifest
def main():
    path=HERE/'CODE_FREEZE.json'
    if path.exists():raise FileExistsError('a freeze already exists; retain versions rather than silently replacing it')
    value={'frozen_at_utc':datetime.now(timezone.utc).isoformat(),
           'scope':'36 primary runs; later fresh executions are reproduction checks, not additional primary samples',
           'files':source_manifest()}
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'files':len(value['files']),'path':str(path)}))
if __name__=='__main__':main()
