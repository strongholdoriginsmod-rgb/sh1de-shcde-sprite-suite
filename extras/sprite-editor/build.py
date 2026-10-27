#!/usr/bin/env python3
"""Build the offline HTML from the audited source files; no package downloads."""
from pathlib import Path
import argparse

def build(destination: Path | None = None) -> Path:
    root = Path(__file__).resolve().parent
    target = destination or root / 'Stronghold_Sprite_Editor.html'
    html = (root / 'src/shell.html').read_text(encoding='utf-8')
    for marker, file in [('CSS', 'style.css'), ('CORE', 'core.js'), ('CODEC', 'codec.js'), ('IO', 'io.js'), ('APP', 'app.js')]:
        content = (root / 'src' / file).read_text(encoding='utf-8')
        if file.endswith('.js') and '</script' in content.lower():
            raise ValueError(f'Unsafe embedded script terminator: {file}')
        token = '/*__' + marker + '__*/'
        if html.count(token) != 1:
            raise ValueError(f'Missing or duplicate template marker: {marker}')
        html = html.replace(token, content)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(html, encoding='utf-8', newline='\n')
    return target

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(build(args.output))
