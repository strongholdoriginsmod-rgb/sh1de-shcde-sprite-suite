"""Pack or import the exact artwork inputs referenced by the production profiles."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def safe_relative(value):
    p = PurePosixPath(value)
    if not p.parts or p.is_absolute() or p.parts[0] not in {'assets', 'work'} or '..' in p.parts or '\\' in value or ':' in value:
        raise ValueError('Invalid project input path: ' + value)
    return p


def inputs(project, profile_root=None):
    profile_root = project if profile_root is None else profile_root
    found = set()
    def visit(value):
        if isinstance(value, dict):
            for item in value.values(): visit(item)
        elif isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, str) and value.startswith(('assets/', 'work/')):
            relative = safe_relative(value)
            path = project.joinpath(*relative.parts).resolve()
            if not path.is_relative_to(project): raise ValueError('Input escapes project')
            if not path.exists(): raise FileNotFoundError(value)
            for file in ([path] if path.is_file() else path.rglob('*')):
                if file.is_file():
                    resolved = file.resolve()
                    if not resolved.is_relative_to(project): raise ValueError('Input escapes project')
                    found.add(resolved)
    for profile in sorted((profile_root/'profiles').glob('*.json')):
        visit(json.loads(profile.read_text(encoding='utf-8-sig')))
    visit(json.loads((profile_root/'config/ui-textures-bc7-v1.json').read_text(encoding='utf-8-sig')))
    return sorted(found)


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def pack(project, output, profile_root=None):
    project = project.resolve(strict=True)
    files = inputs(project, profile_root)
    records = [{'path':p.relative_to(project).as_posix(), 'bytes':p.stat().st_size, 'sha256':digest(p)} for p in files]
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('PROJECT-INPUTS.json', json.dumps({'schema':1, 'files':records}, indent=2)+'\n')
        for p, record in zip(files, records): archive.write(p, record['path'])
    return {'files':len(files), 'bytes':sum(r['bytes'] for r in records), 'sha256':digest(output)}


def install(archive_path, destination, write=False):
    destination = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read('PROJECT-INPUTS.json'))
        if manifest.get('schema') != 1: raise ValueError('Unsupported project input manifest')
        records = manifest['files']
        names = [r['path'] for r in records]
        if len(set(names)) != len(names) or set(archive.namelist()) != set(names)|{'PROJECT-INPUTS.json'}:
            raise ValueError('Duplicate or unlisted archive members')
        if len(archive.namelist()) != len(names)+1: raise ValueError('Duplicate archive members')
        plan = []
        # Validate every member and every destination before writing anything.
        for record in records:
            relative = safe_relative(record['path'])
            target = destination.joinpath(*relative.parts).resolve()
            if not target.is_relative_to(destination): raise ValueError('Destination escapes suite')
            with archive.open(record['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != record['sha256']:
                    raise ValueError('Archive checksum mismatch: '+record['path'])
            if archive.getinfo(record['path']).file_size != record['bytes']: raise ValueError('Archive size mismatch')
            if target.exists():
                if not target.is_file() or digest(target) != record['sha256']:
                    raise ValueError('Existing modified input: '+record['path'])
            else: plan.append((record['path'],target))
        if write:
            for name,target in plan:
                target.parent.mkdir(parents=True,exist_ok=True)
                with tempfile.NamedTemporaryFile(dir=target.parent,delete=False) as temp:
                    temporary=Path(temp.name)
                    try:
                        with archive.open(name) as source: shutil.copyfileobj(source,temp)
                    except BaseException:
                        temp.close();temporary.unlink(missing_ok=True);raise
                temporary.replace(target)
        return {'checked':len(records),'new_files':len(plan),'written':len(plan) if write else 0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    build=sub.add_parser('pack',help='Collect the exact inputs from an existing production project')
    build.add_argument('--source-project',type=Path,required=True)
    build.add_argument('--output',type=Path,required=True)
    apply=sub.add_parser('install',help='Verify and optionally import the accompanying project inputs')
    apply.add_argument('--archive',type=Path,required=True)
    apply.add_argument('--write',action='store_true',help='Import verified missing inputs; changed files are never overwritten')
    args=parser.parse_args()
    result=pack(args.source_project,args.output,ROOT) if args.command=='pack' else install(args.archive,ROOT,args.write)
    print(json.dumps(result))


if __name__=='__main__': main()
