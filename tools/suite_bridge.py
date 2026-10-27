"""Setup and diagnostics for the graphical suite; no asset implementation."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    config = commands.add_parser('configure')
    config.add_argument('--source', type=Path)
    config.add_argument('--target', type=Path)
    config.add_argument('--unity', type=Path)
    config.add_argument('--dotnet', type=Path)
    config.add_argument('--replace', action='store_true')
    config.add_argument('--repair-toolchain', action='store_true')
    commands.add_parser('preflight')
    commands.add_parser('verify-package')
    args = parser.parse_args()
    if args.action == 'configure':
        spec = importlib.util.spec_from_file_location('suite_entry', ROOT/'suite.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.configure(args)
    if args.action == 'verify-package':
        manifest = ROOT/'PACKAGE-MANIFEST.json'
        if not manifest.is_file():
            raise RuntimeError('Paketmanifest fehlt. Quellcheckout: Release zuerst bauen.')
        records = json.loads(manifest.read_text(encoding='utf-8'))['files']
        failures = []
        for record in records:
            path = (ROOT/record['path']).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file():
                failures.append(record['path'])
                continue
            with path.open('rb') as stream:
                h = hashlib.file_digest(stream, 'sha256').hexdigest()
            if h != record['sha256']:
                failures.append(record['path'])
        print(json.dumps({'checked':len(records),'failures':failures},ensure_ascii=False))
        return 1 if failures else 0
    import PIL
    import UnityPy
    import numpy
    print(f'Python {sys.version.split()[0]}; Pillow {PIL.__version__}; UnityPy {UnityPy.__version__}; NumPy {numpy.__version__}')
    from stronghold_europe_de.asset_stream_builder import AssetStreamBuildError, _resolve_toolchain
    try:
        _resolve_toolchain(ROOT, None)
        valid_editor = True
        print('Unity 2021.3.45f2:', 'OK')
    except AssetStreamBuildError as exc:
        valid_editor = False
        print('Unity 2021.3.45f2:', str(exc))
    from stronghold_europe_de.sdk_toolchain import find_dotnet_sdk, sdk_supported, sdk_requirement
    sdk = find_dotnet_sdk(ROOT)
    dotnet = (str(sdk / ('dotnet.exe' if (sdk/'dotnet.exe').is_file() else 'dotnet'))
              if sdk else None)
    result = subprocess.run([dotnet,'--version'],cwd=ROOT,capture_output=True,text=True) if dotnet else None
    valid_sdk = result is not None and result.returncode == 0 and sdk_supported(result.stdout.strip())
    print(sdk_requirement() + ':', ('OK: ' + result.stdout.strip()) if valid_sdk else 'FEHLT/ABWEICHEND')
    if not valid_sdk:
        print('SDK (Windows x64): https://dotnet.microsoft.com/download/dotnet/10.0')
        if result is not None:
            print((result.stderr or result.stdout).strip())
    print('Arbeitsordner:',ROOT)
    if len(str(ROOT)) > 65:
        print(
            'WARNUNG: Langer Arbeitsordner kann bei tiefen Unity-Projektpfaden '
            'Probleme verursachen. Falls der Builder scheitert, Projekt '
            'in einen kürzeren Pfad verschieben.'
        )
    # Path length alone is a compatibility risk, not proof of an impossible
    # build. The actual Unity builder and post-validation retain their gates.
    return 0 if valid_editor and valid_sdk else 1


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f'Fehler: {exc}',file=sys.stderr)
        raise SystemExit(2)
