#!/usr/bin/env python3
"""Verify the deterministic build, recorded browser result, and package hashes."""
from pathlib import Path
import hashlib
import json
import tempfile
from build import build


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify() -> None:
    root = Path(__file__).resolve().parent
    html = root / 'Stronghold_Sprite_Editor.html'
    with tempfile.TemporaryDirectory() as directory:
        rebuilt = build(Path(directory) / 'rebuilt.html')
        if rebuilt.read_bytes() != html.read_bytes():
            raise ValueError('The delivered HTML does not match its source files.')

    report = json.loads((root / 'tests/results/browser-report.json').read_text(encoding='utf-8'))
    if report.get('passed') != 49 or len(report.get('checks', [])) != 49:
        raise ValueError('Unexpected browser-check count.')
    if not all(check['passed'] for check in report['checks']):
        raise ValueError('A browser check failed.')
    if report['pageErrors'] or report['networkRequests']:
        raise ValueError('Unexpected browser errors or application network requests.')
    if report.get('htmlSHA256') != sha256(html):
        raise ValueError('Browser results do not describe the delivered HTML.')

    manifest = root / 'SHA256SUMS.txt'
    checked = 0
    for line in manifest.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        digest, relative = line.split('  ', 1)
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise ValueError(f'Unsafe or missing package path: {relative}')
        if sha256(path) != digest:
            raise ValueError(f'Checksum mismatch: {relative}')
        checked += 1
    print(f'PASS: deterministic HTML build, 49 browser checks, {checked} file hashes.')
    print('This verifies package integrity, not game compatibility or native local storage.')


if __name__ == '__main__':
    verify()
