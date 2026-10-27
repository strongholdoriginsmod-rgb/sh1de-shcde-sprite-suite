"""Portable entry point; all asset work is delegated to the existing tools."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'src'))
from stronghold_europe_de.sdk_toolchain import resolve_dotnet_directory
from stronghold_europe_de.suite_setup import inspect_toolchain_hints, save_local_setup


def run(arguments: list[str]) -> int:
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'src')
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    settings, warnings = inspect_toolchain_hints(ROOT)
    for warning in warnings:
        print('WARNUNG: ' + warning, file=sys.stderr)
    if settings.get('unity_editor'):
        editor = Path(settings['unity_editor'])
        if editor.is_file():
            env['STRONGHOLD_EUROPE_UNITY_EDITOR'] = str(editor)
        else:
            print('WARNUNG: Gespeicherter Unity-Pfad ist nicht mehr vorhanden.', file=sys.stderr)
    if settings.get('dotnet_directory'):
        try:
            directory = resolve_dotnet_directory(Path(settings['dotnet_directory']))
        except (OSError, ValueError, RuntimeError) as exc:
            print(f'WARNUNG: Gespeicherter SDK-Pfad ist nicht nutzbar: {exc}', file=sys.stderr)
        else:
            env['PATH'] = str(directory) + os.pathsep + env.get('PATH', '')
    return subprocess.run([sys.executable, *arguments], cwd=ROOT, env=env).returncode


def configure(args: argparse.Namespace) -> int:
    """Save only supplied settings; do not reset the other configuration."""
    result = save_local_setup(
        ROOT, source=args.source, target=args.target, unity=args.unity,
        dotnet=args.dotnet, replace=args.replace,
        repair_toolchains=getattr(args, 'repair_toolchain', False),
    )
    if result["game_updated"]:
        print("Spielpfade gespeichert und gegen den Projektvertrag geprüft.")
    if result["tools_updated"]:
        print("Unity-/.NET-Werkzeugpfade separat gespeichert.")
    if result["unchanged"]:
        print("Einstellungen unverändert; vorhandene Pfade bleiben erhalten.")
    for backup in result["backup_files"]:
        print("Sicherung der vorherigen Einstellung:", backup)
    print("Vor dem BC7-Bau: Bauvoraussetzungen prüfen (noch keine Releasefreigabe).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    config = sub.add_parser('configure', help='Lokale Spiel- und Werkzeugpfade setzen')
    config.add_argument('--source', type=Path)
    config.add_argument('--target', type=Path)
    config.add_argument('--unity', type=Path)
    config.add_argument('--dotnet', type=Path)
    config.add_argument('--replace', action='store_true')
    config.add_argument('--repair-toolchain', action='store_true',
                        help='Beschädigte Werkzeugdatei nach Backup ausdrücklich neu schreiben')
    sub.add_parser('gui', help='Bestehende Modding-Oberflaeche starten')
    sub.add_parser('test', help='Regressionstests ausfuehren')
    for command in ['doctor','verify','fingerprint','inventory','map','build','validate','install','uninstall','runtime-validate']:
        sub.add_parser(command, add_help=False)
    tool = sub.add_parser('tool', help='Bestehendes Werkzeug aus tools/ ausfuehren', add_help=False)
    tool.add_argument('name')
    args, rest = parser.parse_known_args()
    if args.command == 'configure':
        if rest:
            parser.error('Unbekannte Optionen: ' + ' '.join(rest))
        return configure(args)
    if args.command == 'gui':
        return run(['tools/modding_host.py', *rest])
    if args.command == 'test':
        import tempfile
        (ROOT/'work').mkdir(exist_ok=True)
        base = Path(tempfile.mkdtemp(prefix='test-', dir=ROOT/'work'))
        return run(['-m','pytest','-p','no:cacheprovider','--basetemp',str(base), *rest])
    if args.command == 'tool':
        candidate = (ROOT/'tools'/args.name).resolve()
        if candidate.parent != ROOT/'tools' or candidate.suffix not in {'.py','.pyw'} or not candidate.is_file():
            parser.error('Werkzeug muss eine vorhandene Python-Datei direkt in tools/ sein.')
        return run([str(candidate), *rest])
    return run(['-m','stronghold_europe_de',args.command,*rest])


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as exc:
        print(f'Fehler: {exc}', file=sys.stderr)
        raise SystemExit(2)
