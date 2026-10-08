#!/usr/bin/env python3
"""Check Git's selected publication files; report locations, never secret values."""
import re
import subprocess
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED = {
    '.gitignore', 'README.md', 'requirements.txt', 'ribbon_analyzer.py',
    'evaluate_detector.py', 'setup.sh', 'setup_windows.bat', 'start.sh', 'start.bat',
    'examples/create_demo.py', 'scripts/check_release.py',
    'docs/USAGE.md', 'docs/RELEASE.md', 'docs/manual-annotation.png',
    '.github/workflows/tests.yml',
    '.github/dependabot.yml', 'CONTRIBUTING.md', 'SECURITY.md', 'CITATION.cff',
    'docs/REPOSITORY.md', 'LICENSE',
}
PATTERNS = {
    'credential': re.compile(r'(?:sk-ant-|sk-|ghp_|github_pat_|AIza)[A-Za-z0-9_-]{20,}'),
    'private key': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'personal home path': re.compile(r'(?:/' + r'(?:Users|home)/[A-Za-z0-9_.-]+/|[A-Z]:[\\/]+Users[\\/]+[A-Za-z0-9_.-]+[\\/]+)'),
}


def allowed(name):
    path = Path(name)
    if name in ALLOWED:
        return True
    return len(path.parts) == 2 and (
        path.parts[0] == 'src' and path.suffix == '.py' or
        path.parts[0] == 'tests' and path.name.startswith('test_') and path.suffix == '.py')


def check_files(files):
    findings = []
    for name, data in files:
        if not allowed(name):
            findings.append(f'{name}: outside the publication allowlist')
        if Path(name).suffix == '.png':
            continue
        try:
            content = data.decode('utf-8')
        except UnicodeDecodeError:
            findings.append(f'{name}: unexpected binary content')
            continue
        for line, text in enumerate(content.splitlines(), 1):
            for label, pattern in PATTERNS.items():
                if pattern.search(text):
                    findings.append(f'{name}:{line}: possible {label}')
    return findings


def check_repository(root):
    """Check the index and every reachable commit, without following symlinks."""
    executable = shutil.which('git')
    if executable is None:
        raise FileNotFoundError('Git is required for the publication check.')
    def git(*args):
        return subprocess.check_output([executable, *args], cwd=root)

    cache = {}
    def check_entries(entries, label='', index=False):
        files = []
        problems = []
        for entry in entries:
            header, name = entry.decode('utf-8').split('\t', 1)
            fields = header.split()
            mode, object_id = (fields[0], fields[1]) if index else (fields[0], fields[2])
            if mode not in ('100644', '100755'):
                problems.append(f'{label}{name}: symlink or unsupported Git entry')
                continue
            if index and fields[2] != '0':
                problems.append(f'{label}{name}: unresolved Git index conflict')
                continue
            if object_id not in cache:
                cache[object_id] = git('cat-file', 'blob', object_id)
            files.append((name, cache[object_id]))
        problems.extend(label + item for item in check_files(files))
        return problems

    entries = [entry for entry in git('ls-files', '--stage', '-z').split(b'\0') if entry]
    findings = check_entries(entries, index=True)
    commits = git('rev-list', '--all').decode().splitlines()
    for commit in commits:
        tree = [entry for entry in git('ls-tree', '-rz', '--full-tree', commit).split(b'\0') if entry]
        findings.extend(check_entries(tree, f'commit {commit[:12]}: '))
    return len(entries), len(commits), findings


def main():
    try:
        count, commits, findings = check_repository(ROOT)
        if not count:
            sys.exit('No publication files selected in Git.')
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit('Cannot read Git publication files and history.')
    if findings:
        print('\n'.join(findings))
        sys.exit(1)
    print(f'Checked {count} selected files and {commits} reachable commits: '
          'no credential, home-path, symlink or allowlist findings.')


if __name__ == '__main__':
    main()
