"""Local inventory and move verification; never reads environment/secret files."""
from __future__ import annotations

import hashlib
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "outputs/project_organization"


def transient(path):
    return any(part in {'node_modules', '__pycache__', '.git', '.vite', 'dist', 'coverage'} for part in path.parts) or path.suffix in {'.pyc', '.pyo', '.tsbuildinfo'}


def secret(path):
    return path.name.startswith('.env') or path.suffix.lower() in {'.key', '.pem', '.pfx'} or any(word in path.name.lower() for word in ('credential', 'secret', 'password'))


def category(path):
    if transient(path):
        return 'dependencies_build_cache'
    if secret(path):
        return 'local_secret_metadata_only'
    return path.parts[0] if len(path.parts) > 1 else 'root_files'


def scan():
    rows = []
    for directory, dirs, files in os.walk(ROOT, followlinks=False):
        dirs[:] = [d for d in dirs if d != '.git' and (Path(directory) / d).resolve() != AUDIT.resolve()]
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(ROOT)
            if path.is_symlink():
                rows.append({'path': relative.as_posix(), 'category': 'symlink_not_followed'})
                continue
            entry = {'path': relative.as_posix(), 'category': category(relative)}
            if not secret(relative):
                entry['size'] = path.stat().st_size
                if not transient(relative):
                    entry['sha256'] = hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
            rows.append(entry)
    return sorted(rows, key=lambda r: r['path'])


def main():
    mode = sys.argv[1]
    AUDIT.mkdir(parents=True, exist_ok=True)
    rows = scan()
    target = AUDIT / f'{mode}_inventory.json'
    if target.exists():
        raise SystemExit(f'Refusing to overwrite {target.name}')
    target.write_text(json.dumps({'file_count': len(rows), 'category_counts': dict(Counter(r['category'] for r in rows)), 'files': rows}, indent=2), encoding='utf-8')
    if mode == 'before':
        groups = defaultdict(list)
        for row in rows:
            if row.get('sha256'):
                groups[(row['size'], row['sha256'])].append(row['path'])
        duplicates = [group for group in groups.values() if len(group) > 1]
        (AUDIT / 'duplicate_files.json').write_text(json.dumps(duplicates, indent=2), encoding='utf-8')
        print(json.dumps({'file_count': len(rows), 'category_counts': dict(Counter(r['category'] for r in rows)), 'duplicate_groups': len(duplicates)}, indent=2))
        return
    before = json.loads((AUDIT / 'before_inventory.json').read_text(encoding='utf-8'))
    moves = json.loads((AUDIT / 'move_log.json').read_text(encoding='utf-8-sig'))
    mapping = {move['from']: move['to'] for move in moves}
    after = {row['path']: row for row in rows}
    permitted_edits = {'README.md', '.gitignore', 'PHASE_STATUS.md'}
    errors = []
    for row in before['files']:
        destination = mapping.get(row['path'], row['path'])
        current = after.get(destination)
        if not current:
            errors.append('Missing: ' + destination)
        elif row.get('sha256') and destination not in permitted_edits and current.get('sha256') != row['sha256']:
            errors.append('Changed contents: ' + destination)
    (AUDIT / 'verification.json').write_text(json.dumps({'errors': errors, 'moves': len(moves), 'before_count': before['file_count'], 'after_count': len(rows), 'before_categories': before['category_counts'], 'after_categories': dict(Counter(r['category'] for r in rows)), 'verified_original_files': len(before['files']), 'permitted_documentation_edits': sorted(permitted_edits)}, indent=2), encoding='utf-8')
    print(json.dumps({'errors': errors, 'moves': len(moves), 'before_count': before['file_count'], 'after_count': len(rows)}, indent=2))
    if errors:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
