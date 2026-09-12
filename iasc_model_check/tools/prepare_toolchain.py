"""Fetch pinned official portable Java/TLC tools; never invoke a model."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent
JAVA_URL = 'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.12.1%2B1/OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip'
JAVA_SHA = 'd35f31e712f0fcf6ac5a093edc90204fbff22f720ba3950bd09d331d5e621636'
JAVA_CHECKSUM_URL = JAVA_URL + '.sha256.txt'
TLC_URL = 'https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar'
TLC_SHA = '936a262061c914694dfd669a543be24573c45d5aa0ff20a8b96b23d01e050e88'
USER_AGENT = 'IASC-local-toolchain-repro'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def download(url, path, maximum):
    if path.exists():
        return {'url':url,'path':path.name,'bytes':path.stat().st_size,'sha256':digest(path),'reused_existing_download':True}
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=90) as response, path.open('xb') as target:
        size = 0
        while block := response.read(1024 * 1024):
            size += len(block)
            if size > maximum:
                raise ValueError('Download exceeds declared size bound')
            target.write(block)
    return {'url':url, 'path':path.name, 'bytes':path.stat().st_size, 'sha256':digest(path)}

def save(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')

def main():
    metadata = {}
    for name, url in [
        ('tlaplus_release_metadata.json', 'https://api.github.com/repos/tlaplus/tlaplus/releases/tags/v1.7.4'),
        ('temurin_release_metadata.json', 'https://api.github.com/repos/adoptium/temurin21-binaries/releases/tags/jdk-21.0.12.1%2B1')]:
        if name == 'tlaplus_release_metadata.json' and (ROOT/name).exists():
            metadata[name] = {'url':url,'path':name,'bytes':(ROOT/name).stat().st_size,
                              'sha256':digest(ROOT/name),'reused_after_metadata_endpoint_404':True}
        else:
            metadata[name] = download(url, ROOT/name, 2_000_000)
    tlc_meta = json.loads((ROOT/'tlaplus_release_metadata.json').read_text(encoding='utf-8'))
    if tlc_meta['draft'] or tlc_meta['prerelease'] or tlc_meta['tag_name'] != 'v1.7.4':
        raise ValueError('TLC release is not the expected stable release')
    java_meta = json.loads((ROOT/'temurin_release_metadata.json').read_text(encoding='utf-8'))
    assert not java_meta['draft'] and not java_meta['prerelease']
    assert java_meta['tag_name'] == 'jdk-21.0.12.1+1'
    java_asset = next(x for x in java_meta['assets'] if x['name'] == 'OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip')
    assert java_asset['digest'] == 'sha256:' + JAVA_SHA
    jre_archive = ROOT / 'OpenJDK21U-jre_x64_windows_hotspot_21.0.12.1_1.zip'
    artifacts = [download(JAVA_CHECKSUM_URL, ROOT/'temurin.sha256.txt', 10_000)]
    expected_published_sha = (ROOT/'temurin.sha256.txt').read_text(encoding='utf-8').split()[0]
    assert expected_published_sha == JAVA_SHA
    artifacts.append(download(JAVA_URL, jre_archive, 55_000_000))
    assert digest(jre_archive) == JAVA_SHA
    artifacts.append(download(TLC_URL, ROOT/'tla2tools.jar', 3_000_000))
    assert digest(ROOT/'tla2tools.jar') == TLC_SHA
    license_url = 'https://raw.githubusercontent.com/tlaplus/tlaplus/v1.7.4/LICENSE'
    artifacts.append(download(license_url, ROOT/'TLAPLUS_LICENSE', 100_000))
    java_root = ROOT/'java'
    java_root.mkdir(exist_ok=True)
    with zipfile.ZipFile(jre_archive) as archive:
        if sum(member.file_size for member in archive.infolist()) > 200_000_000:
            raise ValueError('Unexpected expanded JRE size')
        for member in archive.infolist():
            destination = (java_root/member.filename).resolve()
            destination.relative_to(java_root.resolve())
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Unexpected symbolic link in Windows JRE ZIP')
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    assert destination.read_bytes() == archive.read(member)
                else:
                    with archive.open(member) as source, destination.open('xb') as target:
                        shutil.copyfileobj(source, target)
    java_exes = list(java_root.glob('*/bin/java.exe'))
    assert len(java_exes) == 1
    java_exe = java_exes[0]
    java_version = subprocess.run([str(java_exe), '-version'], capture_output=True, text=True, timeout=30,
                                  creationflags=subprocess.CREATE_NO_WINDOW)
    assert java_version.returncode == 0
    tlc_help = subprocess.run([str(java_exe), '-cp', str(ROOT/'tla2tools.jar'), 'tlc2.TLC', '-help'],
                              capture_output=True, text=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert tlc_help.returncode in (0, 1) and 'Version 2.19 of 08 August 2024' in tlc_help.stdout + tlc_help.stderr
    for name, result in [('java_version', java_version), ('tlc_help', tlc_help)]:
        for channel in ('stdout', 'stderr'):
            with (ROOT/f'{name}_{channel}.txt').open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(getattr(result, channel))
    with zipfile.ZipFile(ROOT/'tla2tools.jar') as archive:
        jar_manifest = archive.read('META-INF/MANIFEST.MF').decode('utf-8')
    with (ROOT/'tlc_jar_manifest.txt').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(jar_manifest)
    report = {'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'Portable toolchain only; no TLC model, candidate program or experiment executed.',
        'existing_java_probes': {'windows_path':'not found', 'windows_common_java_roots':'not found',
                                'wsl_distribution':'Ubuntu-24.04','wsl_path':'not found','wsl_usr_lib_jvm':'directory absent'},
        'java': {'distribution':'Eclipse Temurin', 'release':'jdk-21.0.12.1+1', 'platform':'windows-x64',
                 'image_type':'jre','portable':True,'archive_sha256':JAVA_SHA,'published_checksum_verified':True,
                 'checksum_verification':'Downloaded SHA256 text from same official release; no independent signature verification claimed.',
                 'official_release_url':java_meta['html_url'],'publisher_asset_digest':java_asset['digest'],
                 'java_executable':str(java_exe), 'java_executable_relative':java_exe.relative_to(ROOT).as_posix(),
                 'java_executable_sha256':digest(java_exe), 'version_returncode':java_version.returncode,
                 'version_stdout':java_version.stdout,'version_stderr':java_version.stderr},
        'tlc': {'release':'v1.7.4','official_release_url':tlc_meta['html_url'],
                'published_at':tlc_meta['published_at'],'draft':False,'prerelease':False,
                'jar':'tla2tools.jar','jar_sha256':digest(ROOT/'tla2tools.jar'),
                'publisher_asset_digest':next(x for x in tlc_meta['assets'] if x['name']=='tla2tools.jar').get('digest'),
                'verification':'HTTPS official release asset; locally recorded SHA256. No independent publisher jar checksum/signature is claimed if asset digest is null.',
                'help_returncode':tlc_help.returncode,
                'help_returncode_note':'This release prints normal help with exit code 1; the expected version/help text was checked. No model was invoked.',
                'version_and_help_stdout':tlc_help.stdout,
                'version_and_help_stderr':tlc_help.stderr, 'jar_manifest':jar_manifest},
        'downloads':artifacts, 'metadata_downloads':metadata,
        'system_installation_performed':False,'path_or_registry_modified':False,
        'preparation_note':'Initial Adoptium version-query URL returned HTTP 404 before any runtime download; fixed official GitHub release metadata was used instead. Initial finalization expected help exit code zero, but this TLC release returns one for help; its expected help/version output was verified. Existing downloads/extracted bytes were retained and checked against the archive.',
        'model_execution_performed':False, 'prepare_script_sha256':digest(Path(__file__))}
    save(ROOT/'TOOLCHAIN.json',report)
    print(json.dumps({'java_executable':str(java_exe),'java_version':java_version.stderr.strip(),
                      'tlc_jar_sha256':report['tlc']['jar_sha256'],
                      'tlc_help_first_lines':tlc_help.stdout.splitlines()[:6],
                      'model_execution_performed':False},indent=2))

if __name__ == '__main__':
    main()
