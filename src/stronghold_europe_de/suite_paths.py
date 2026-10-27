"""Portable defaults for the original standalone tools; no asset processing."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def portable_path(role: str, suffix: str = '') -> str:
    if role == 'suite':
        base = ROOT
    elif role == 'atlas_contract':
        base = ROOT / 'extras/atlas-contract'
    else:
        config = ROOT / 'config/installations.local.toml'
        settings = tomllib.loads(config.read_text(encoding='utf-8')) if config.is_file() else {}
        section, key = {'source_data': ('source', 'data_dir'),
                        'target_game': ('target', 'game_dir')}[role]
        value = settings.get(section, {}).get(key)
        base = Path(value) if value else ROOT / 'work/unconfigured' / role
        if not base.is_absolute():
            base = ROOT / base
    relative = Path(suffix)
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('Expected a relative tool resource path')
    return str(base / relative)
