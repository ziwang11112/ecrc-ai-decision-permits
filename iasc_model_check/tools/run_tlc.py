"""Run pinned TLC with the local portable JRE; forward all TLC arguments."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
manifest = json.loads((root/'TOOLCHAIN.json').read_text(encoding='utf-8'))
java = root/manifest['java']['java_executable_relative']
jar = root/manifest['tlc']['jar']
for path, expected in [(java, manifest['java']['java_executable_sha256']), (jar, manifest['tlc']['jar_sha256'])]:
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise SystemExit('Toolchain file hash mismatch: ' + str(path))
args = sys.argv[1:]
if args and args[0] == '--':
    args = args[1:]
if not args:
    raise SystemExit('Supply TLC arguments, such as -- -help, or -- -workers 1 -config Model.cfg Model.tla')
completed = subprocess.run([str(java), '-Xmx2g', '-cp', str(jar), 'tlc2.TLC', *args],
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
raise SystemExit(completed.returncode)
