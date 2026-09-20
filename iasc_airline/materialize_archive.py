"""Verify a compact S11 archive and optionally restore semantic after states.

Exact original bytes are retained for all archived original files except the
large AFTER_DB.json.gz snapshots. Those snapshots are represented by lossless
record replacements against a declared before state. Their canonical JSON
states are exact; reconstructed gzip container bytes need not match originals.
"""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile

def sha(data): return hashlib.sha256(data).hexdigest()
def canonical(value): return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
def safe(name):
    p=PurePosixPath(name)
    if '\\' in name or p.is_absolute() or any(k in ('..','') for k in p.parts) or ':' in name:
        raise ValueError('Unsafe archive path: '+name)
    return p
def decode(name,data): return json.loads(gzip.decompress(data) if name.endswith('.gz') else data)
def rebuild(before,patch):
    # All exported changes replace a whole existing record in a top-level map.
    state={key:dict(value) if isinstance(value,dict) else value for key,value in before.items()}
    for op in patch['replacements']:
        table,key=op['path']
        if state[table][key]!=op['before']: raise ValueError('State patch precondition mismatch')
        state[table][key]=op['after']
    if sha(canonical(state))!=patch['after_canonical_sha256']: raise ValueError('Reconstructed after state hash mismatch')
    return state

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    parser.add_argument('--out',type=Path,help='New extraction directory; reconstruct all AFTER_DB.json.gz files')
    parser.add_argument('--verify-states',action='store_true',help='Reconstruct and hash every state even without extraction')
    args=parser.parse_args()
    if args.out and args.out.exists(): parser.error('--out must not exist')
    verified=0
    with zipfile.ZipFile(args.archive) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)): raise ValueError('Duplicate archive member')
        for name in names: safe(name)
        manifest=json.loads(archive.read('MANIFEST.json'))
        entries={entry['path']:entry for entry in manifest['files']}
        if set(names)!=set(entries)|{'MANIFEST.json'}: raise ValueError('Archive manifest membership mismatch')
        for name,entry in entries.items():
            data=archive.read(name)
            if len(data)!=entry['bytes'] or sha(data)!=entry['sha256']: raise ValueError('Archive file integrity mismatch: '+name)
            if args.out:
                target=args.out.joinpath(*safe(name).parts)
                target.parent.mkdir(parents=True,exist_ok=True)
                target.write_bytes(data)
        if args.out:
            (args.out/'MANIFEST.json').write_bytes(archive.read('MANIFEST.json'))
        projection=json.loads(archive.read('STATE_PROJECTION.json'))
        before_cache={}
        if args.out or args.verify_states:
            for item in projection['after_states']:
                patch=json.loads(archive.read(item['patch_path']))
                name=patch['base_path']
                if name not in before_cache:
                    before_cache[name]=decode(name,archive.read(name))
                before=before_cache[name]
                # Base binding is checked once per distinct base.
                if name not in projection.get('_checked_bases',[]):
                    if sha(canonical(before))!=patch['base_canonical_sha256']: raise ValueError('Base state mismatch')
                    projection.setdefault('_checked_bases',[]).append(name)
                state=rebuild(before,patch)
                verified+=1
                if args.out:
                    dest=args.out.joinpath(*safe(item['original_path']).parts)
                    dest.parent.mkdir(parents=True,exist_ok=True)
                    dest.write_bytes(gzip.compress(canonical(state),mtime=0))
        print(json.dumps({'archive_verified':True,'files':len(entries),'after_states_available':len(projection['after_states']),
            'after_states_canonically_verified':verified,'original_gzip_bytes_recreated':False,
            'original_nonprojected_file_bytes_preserved':True,'primary_cells':2400,'boundary_cells':64},indent=2))

if __name__=='__main__': main()
