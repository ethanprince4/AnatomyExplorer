"""Promote only the exact 3.1.2 candidate tested by CI and Ethan.

This one-time publication path verifies successful source/frozen gates, unchanged
application source, pinned artifact ZIP digests and complete feed inventories.
It creates a draft, verifies every uploaded asset digest, then publishes. Using
the workflow's existing GITHUB_TOKEN avoids triggering a redundant tag rebuild.
No credentials, diagnostic artifacts or local model snapshots are distributed.
"""
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.updater import validate_manifest

REPO = 'ethanprince4/AnatomyExplorer'
TAG = 'v3.1.2'
SOURCE = 'b936315f63400891e12e9b8055fd7cb2c468e84a'
RUN = 36786980190
ARTIFACTS = (
    {'id': 11130274390, 'name': 'AnatomyExplorer-Setup-Windows.exe',
     'manifest': 'AnatomyExplorer-Windows-update.json', 'platform': 'windows-x64',
     'bytes': 2951728064,
     'sha256': 'abe8da7256aad83fc9390ad3a1b2e4332badeef31d8c47a8a00eea3409dd58f9'},
    {'id': 11130532741, 'name': 'AnatomyExplorer-macOS-AppleSilicon.dmg',
     'manifest': 'AnatomyExplorer-macOS-update.json', 'platform': 'macos-arm64',
     'bytes': 3156115669,
     'sha256': '96a83340966e1514a613b51ba78fb29310feac05221916d55873c244a79c4d61'},
)
REQUIRED_JOBS = {
    'Mac diagnostic gate / Native Mac GPU sentinel controls',
    'Mac diagnostic gate / Native Mac selected-tree accessibility controls',
    'Release safety gate / App regressions (windows-latest)',
    'Release safety gate / App regressions (macos-14)',
    'Release safety gate / updater (macos-14)',
    'Release safety gate / updater (ubuntu-latest)',
    'Release safety gate / updater (windows-latest)',
    'Build (Windows)', 'Build (macOS Apple silicon)',
}
PUBLICATION_FILES = {'.github/workflows/release.yml',
                     '.github/workflows/promote-3.1.2.yml',
                     'packaging/promote_3_1_2.py', 'tests/test_release_promotion.py'}
NOTES = """Repairs Mac structure picking, HTTPS updates and the native Cocoa tree-selection crash. Includes updater concurrency, shutdown and automatic retry improvements. Windows and Apple-silicon Mac installers are attached, along with the incremental update feeds.

These are the exact installers from the successful candidate run that Ethan tested on his Mac. Source safety tests, native GPU/tree controls, Windows first-install checks, frozen real GitHub HTTPS, final Cocoa identity/semantics, and signed Mac update/rollback checks passed. No application code was changed during publication.

Existing updater-enabled installations with working HTTPS can receive this through Updates; a Mac v3.1.1 installation with certificate verification errors may need this repaired installer once. Notes, progress, settings and the original installation are preserved. Updates do not restart an active study session.

Enable experimental stuff remains unchecked by default. No experimental model packages or local model freezes are published with this release. Check results appear inline in the Updates dialog; no preview is available to download yet. The remaining Mac lung/pathology protrusion is deferred to a later fix, as approved by Ethan.

Mac requires Apple silicon and macOS 13 or later. The matching Qt 6.11.2 Cocoa plugin includes the unreleased Gerrit 765434 patchset 1 ownership repair; corresponding source, patch, build recipe, provenance and licenses are included. Qt frameworks remain unchanged. Existing ad-hoc signing / Developer ID and notarization limitations remain as documented in the README.

Verified candidate: https://github.com/ethanprince4/AnatomyExplorer/actions/runs/36786980190
PR: https://github.com/ethanprince4/AnatomyExplorer/pull/7
"""


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def gh(*args, output=None):
    result = subprocess.run(['gh', *args], stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False)
    require(result.returncode == 0, 'GitHub operation failed: ' + args[0])
    return result.stdout


def api(endpoint):
    return json.loads(gh('api', f'repos/{REPO}/{endpoint}'))


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def verify_source():
    require(os.environ.get('GITHUB_REPOSITORY') == REPO, 'Wrong repository')
    require(os.environ.get('GITHUB_REF') == 'refs/heads/main', 'Promotion requires merged main')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    require(head == os.environ.get('GITHUB_SHA'), 'Checkout does not match dispatch')
    require(api('git/ref/heads/main')['object']['sha'] == head, 'Main changed during dispatch')
    subprocess.run(['git', 'merge-base', '--is-ancestor', SOURCE, head], check=True)
    changed = set(subprocess.check_output(
        ['git', 'diff', '--name-only', SOURCE, head], text=True).splitlines())
    require(changed <= PUBLICATION_FILES, 'Application or other source changed after tested candidate')
    original = subprocess.check_output(['git', 'show', f'{SOURCE}:.github/workflows/release.yml'], text=True)
    before = '        with:\n          path: assets\n          merge-multiple: true\n'
    after = ('        with:\n          name: AnatomyExplorer-Setup-Windows.exe\n          path: assets\n'
             '      - uses: actions/download-artifact@v4\n        with:\n'
             '          name: AnatomyExplorer-macOS-AppleSilicon.dmg\n          path: assets\n')
    require(original.count(before) == 1, 'Artifact filter baseline changed')
    require((ROOT / '.github/workflows/release.yml').read_text() == original.replace(before, after),
            'Release workflow changes exceed reviewed artifact filter')
    pull = api('pulls/7')
    require(pull['merged'] and pull['merge_commit_sha'] == head, 'PR7 must be merged at dispatch commit')
    return head, sorted(changed)


def verify_run():
    run = api(f'actions/runs/{RUN}')
    require(run['head_sha'] == SOURCE and run['conclusion'] == 'success'
            and run['status'] == 'completed' and run['event'] == 'pull_request'
            and run['head_repository']['full_name'] == REPO
            and run['workflow_id'] == 366254515, 'Candidate run identity/status differs')
    jobs = api(f'actions/runs/{RUN}/jobs?per_page=100')['jobs']
    passed = {job['name'] for job in jobs if job['conclusion'] == 'success'}
    require(REQUIRED_JOBS <= passed, 'Required source/native/frozen gate did not pass')
    return sorted(REQUIRED_JOBS)


def extract_verified(archive, item, output):
    require(archive.stat().st_size == item['bytes'] and digest(archive) == item['sha256'],
            'Artifact archive bytes differ from verified candidate')
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        names = [entry.filename for entry in entries]
        require(len(names) == len(set(names)) and all(
            name == Path(name).name and '\\' not in name and not entry.is_dir()
            and entry.file_size <= 2 * 1024**3
            for name, entry in zip(names, entries)), 'Artifact has unsafe/nonflat/oversized entries')
        require(item['manifest'] in names and item['name'] in names, 'Missing installer or manifest')
        manifest_entry = bundle.getinfo(item['manifest'])
        require(manifest_entry.file_size <= 16 * 1024**2, 'Manifest oversized')
        manifest = validate_manifest(json.loads(bundle.read(item['manifest'])))
        require(manifest['version'] == '3.1.2' and manifest.get('channel', 'stable') == 'stable'
                and manifest['platform'] == item['platform'] and manifest['release_tag'] == TAG,
                'Manifest version/platform/channel differs')
        require(set(names) == {item['name'], item['manifest'], *manifest['packs']},
                'Artifact contains nonrelease files or missing packs')
        for name, size in manifest['packs'].items():
            require(bundle.getinfo(name).file_size == size, 'Pack size differs from manifest')
        for entry in entries:
            require(not (output / entry.filename).exists(), 'Asset name collision')
            # Names have already been checked; zipfile verifies entry CRC while extracting.
            bundle.extract(entry, output)
    return manifest


def main():
    head, changed = verify_source()
    gates = verify_run()
    releases = api('releases?per_page=100')
    existing = [release for release in releases if release['tag_name'] == TAG]
    require(not existing or (len(existing) == 1 and existing[0]['draft']),
            'Existing public release must never be replaced')
    work = ROOT / 'packaging/build/promote-3.1.2'
    work.mkdir(parents=True, exist_ok=False)
    assets = work / 'assets'
    assets.mkdir()
    manifests = {}
    for item in ARTIFACTS:
        artifact = api(f"actions/artifacts/{item['id']}")
        require(artifact['name'] == item['name'] and not artifact['expired']
                and artifact['size_in_bytes'] == item['bytes']
                and artifact['digest'] == 'sha256:' + item['sha256']
                and artifact['workflow_run']['id'] == RUN
                and artifact['workflow_run']['head_sha'] == SOURCE,
                'Artifact metadata differs from pinned candidate')
        archive = work / f"{item['id']}.zip"
        print('Downloading verified artifact:', item['name'], flush=True)
        with archive.open('xb') as stream:
            gh('api', f"repos/{REPO}/actions/artifacts/{item['id']}/zip", output=stream)
        manifests[item['platform']] = extract_verified(archive, item, assets)
        archive.unlink()
    inventory = {path.name: {'bytes': path.stat().st_size, 'sha256': digest(path)}
                 for path in sorted(assets.iterdir())}
    provenance = {'version': '3.1.2', 'tag': TAG, 'tested_source': SOURCE,
                  'release_commit': head, 'publication_only_changes': changed,
                  'verified_run': RUN, 'artifacts': ARTIFACTS, 'successful_jobs': gates,
                  'assets': inventory, 'no_application_changes_after_testing': True,
                  'actual_mac_check_authorized_publication': True}
    provenance_path = assets / 'AnatomyExplorer-3.1.2-provenance.json'
    provenance_path.write_text(json.dumps(provenance, indent=2) + '\n')
    inventory[provenance_path.name] = {'bytes': provenance_path.stat().st_size,
                                      'sha256': digest(provenance_path)}
    notes = work / 'notes.txt'
    notes.write_text(NOTES)
    if not existing:
        gh('release', 'create', TAG, '--repo', REPO, '--target', head, '--draft',
           '--title', 'Anatomy Explorer v3.1.2', '--notes-file', str(notes))
    else:
        require(existing[0]['target_commitish'] == head, 'Draft belongs to another commit')
        require(not existing[0]['assets'], 'Existing draft has assets; preserve and inspect manually')
    paths = sorted(assets.iterdir())
    for start in range(0, len(paths), 8):
        print('Uploading release assets:', start + 1, 'of', len(paths), flush=True)
        gh('release', 'upload', TAG, '--repo', REPO, *map(str, paths[start:start + 8]))
    release = api(f'releases/tags/{TAG}')
    actual = {asset['name']: asset for asset in release['assets']}
    require(set(actual) == set(inventory), 'Published asset inventory differs')
    for name, expected in inventory.items():
        require(actual[name]['size'] == expected['bytes']
                and actual[name].get('digest') == 'sha256:' + expected['sha256'],
                'Uploaded asset size/hash differs: ' + name)
    # This is the first public operation, after all immutable artifacts and uploads passed.
    gh('release', 'edit', TAG, '--repo', REPO, '--draft=false', '--latest')
    release = api(f'releases/tags/{TAG}')
    latest = api('releases/latest')
    require(not release['draft'] and not release['prerelease']
            and latest['tag_name'] == TAG, 'Release publication/latest confirmation failed')
    require(api(f'git/ref/tags/{TAG}')['object']['sha'] == head, 'Release tag points elsewhere')
    print(json.dumps({'published': release['html_url'], 'release_commit': head,
                      'assets': len(actual), 'verified_exact_candidate': True,
                      'installers': {item['platform']: actual[item['name']]['browser_download_url']
                                     for item in ARTIFACTS}}, indent=2), flush=True)


if __name__ == '__main__':
    main()
