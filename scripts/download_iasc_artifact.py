"""Download the fixed release artifact, verify its hash, and safely extract it."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts/iasc')
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists():
        raise SystemExit(f'Choose a fresh output directory: {destination}')
    record = json.loads((ROOT / 'iasc/RELEASE_ARTIFACT.json').read_text())
    with tempfile.TemporaryDirectory(prefix='ecrc-iasc-download-') as temp:
        archive = Path(temp) / record['filename']
        request = urllib.request.Request(record['url'], headers={'User-Agent': 'ECRC-artifact-downloader'})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open('wb') as target:
            shutil.copyfileobj(response, target)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != record['sha256'] or archive.stat().st_size != record['bytes']:
            raise SystemExit('Release artifact size/hash mismatch; nothing extracted.')
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:
                raise SystemExit('ZIP CRC failure; nothing extracted.')
            manifest = json.loads(z.read('MANIFEST.json'))
            expected = {row['path'] for row in manifest['files']} | {'MANIFEST.json'}
            if len(z.namelist()) != len(expected) or set(z.namelist()) != expected:
                raise SystemExit('ZIP inventory mismatch; nothing extracted.')
            for name in z.namelist():
                if not (destination / name).resolve().is_relative_to(destination):
                    raise SystemExit('Unsafe archive path; nothing extracted.')
            for row in manifest['files']:
                data = z.read(row['path'])
                if len(data) != row['bytes'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                    raise SystemExit(f"Member hash mismatch: {row['path']}")
            destination.mkdir(parents=True)
            z.extractall(destination)
    print(f"Verified {len(expected)} files from {record['tag']}: {destination}")


if __name__ == '__main__':
    main()
