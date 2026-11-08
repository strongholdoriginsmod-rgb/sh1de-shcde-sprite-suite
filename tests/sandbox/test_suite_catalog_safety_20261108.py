"""Safety regression for unified Stronghold/SpriteSuite expert workflows.

2026-11-08: Navigation/help must never execute scripts with top-level effects.
Writing/installation actions require explicit risk-aware confirmation.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
from suite_catalog import describe, format_static_help
from suite_tool_policy import classify
from suite_tool_registry import open_specialist


@pytest.fixture(scope="module")
def center():
    loader = importlib.machinery.SourceFileLoader(
        "suite_center_catalog_safety", str(ROOT / "tools" / "suite_center.pyw"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def malicious_tool(tmp_path):
    marker = tmp_path / "executed.txt"
    source = tmp_path / "some_tool.py"
    source.write_text(
        "from pathlib import Path\n"
        + f"Path({str(marker)!r}).write_text('UNEXPECTED')\n"
        + "import argparse\n"
        + "parser=argparse.ArgumentParser(description='sample CLI')\n"
        + "cmd=parser.add_subparsers(dest='action')\n"
        + "go=cmd.add_parser('go')\n"
        + "go.add_argument('--output', required=True, help='Target file')\n"
        + "if __name__ == '__main__': parser.parse_args()\n",
        encoding="utf-8")
    return source, marker


def test_static_help_does_not_import_or_execute_malicious_script(tmp_path):
    source, marker = malicious_tool(tmp_path)
    meta = describe(source)
    assert "go" in (" ".join(parts) for parts in meta["commands"])
    content = format_static_help(meta, ("go",))
    assert "ohne Import/Ausführung" in content
    assert "--output" in content
    assert "Pflichtfeld" in content
    assert "sample CLI" in content
    assert not marker.exists()


def test_static_help_limits_untrusted_text(tmp_path):
    source, marker = malicious_tool(tmp_path)
    meta = describe(source)
    meta["description"] = "X" * 10000
    help_text = format_static_help(meta, (), limit=500)
    assert len(help_text) <= 500
    assert "gekürzt" in help_text
    assert not marker.exists()
    with pytest.raises(ValueError):
        format_static_help(meta, limit=5)


def test_gui_help_button_does_not_call_runner(center, monkeypatch, tmp_path):
    source, marker = malicious_tool(tmp_path)
    shown, launched = [], []
    monkeypatch.setattr(center.messagebox, "showinfo",
                        lambda *args, **kwargs: shown.append(args))
    fake = SimpleNamespace(
        catalog=describe(source),
        active_command=("go",),
        run_catalog=lambda *_: launched.append("unexpected"),
    )
    center.Center.catalog_help(fake)
    assert len(shown) == 1
    assert "--output" in shown[0][1]
    assert not launched
    assert not marker.exists()


def test_entered_help_argument_stays_static(center, monkeypatch):
    helped, launched, confirmations = [], [], []
    monkeypatch.setattr(center.messagebox, "askyesno",
                        lambda *a, **k: confirmations.append(a) or False)
    fake = SimpleNamespace(
        catalog_tool=SimpleNamespace(get=lambda: "unreviewed.py"),
        active_command=(),
        active_fields=[],
        field_values=[],
        extra=SimpleNamespace(get=lambda: "--help"),
        catalog_help=lambda: helped.append(True),
        run_catalog=lambda argv: launched.append(argv),
    )
    center.Center.catalog_run(fake)
    assert helped == [True]
    assert not launched and not confirmations
    center.Center.run_catalog(fake, ["--help"])
    assert helped == [True, True]
    assert not launched


@pytest.mark.parametrize("tool,args,needs_confirmation", [
    ("suite_tool_inventory.py", (), False),
    ("se_asset_package.py", (), False),
    ("ziel_se211.py", ("installieren",), True),
    ("unreviewed.py", (), True),
    ("building_damage_codex.py", ("--execute",), True),
])
def test_sensitive_actions_are_confirmed_by_default(
        center, monkeypatch, tool, args, needs_confirmation):
    confirmations, executed = [], []
    monkeypatch.setattr(center.messagebox, "askyesno",
                        lambda _name, prompt, **kw:
                        confirmations.append((prompt, kw)) or False)
    fake = SimpleNamespace(
        catalog_tool=SimpleNamespace(get=lambda: tool),
        active_command=tuple(args),
        active_fields=[],
        field_values=[],
        extra=SimpleNamespace(get=lambda: ""),
        run_catalog=lambda argv: executed.append(argv),
    )
    center.Center.catalog_run(fake)
    if needs_confirmation:
        assert len(confirmations) == 1
        assert confirmations[0][1].get("default") == "no"
        assert tool in confirmations[0][0]
        assert not executed
    else:
        assert not confirmations
        assert executed == [list(args)]
    assert classify(tool, list(args)).requires_confirmation == needs_confirmation


def test_catalog_search_reuses_de_en_aliases_without_execution(center):
    configurations, executed = [], []
    state = SimpleNamespace(value="sprites.py")
    fake = SimpleNamespace(
        catalog_search=SimpleNamespace(get=lambda: "gebaeudeschaden"),
        catalog_all_names=["Pipeline", "sprites.py",
                           "building_damage_runtime_preflight.py"],
        catalog_picker=SimpleNamespace(
            configure=lambda **kw: configurations.append(kw)),
        catalog_tool=state,
        run=lambda *a: executed.append(a),
    )
    choices = center.Center.filter_catalog(fake)
    assert choices == ["building_damage_runtime_preflight.py"]
    assert configurations[-1]["values"] == choices
    assert state.value == "sprites.py"
    assert not executed


def test_registry_navigation_reopens_filtered_catalog_without_execution():
    chosen, visited, loaded, executed = [], [], [], []
    path = ROOT / "tools" / "sprites.py"
    fake = SimpleNamespace(
        catalog_paths={"sprites.py": path},
        catalog_page=object(),
        catalog_tool=SimpleNamespace(set=lambda value: chosen.append(value)),
        catalog_search=SimpleNamespace(set=lambda value: chosen.append("filter:" + value)),
        open_tab=lambda page: visited.append(page),
        load_catalog=lambda: loaded.append(True),
        run=lambda *a: executed.append(a),
    )
    open_specialist(fake, "sprites.py")
    assert chosen == ["filter:", "sprites.py"]
    assert visited == [fake.catalog_page] and loaded == [True]
    assert not executed


def test_portable_suite_tool_help_never_launches_side_effectful_source(
        tmp_path, monkeypatch, capsys):
    """The public python suite.py tool ... --help entrypoint must also be static."""
    source, marker = malicious_tool(tmp_path)
    project = tmp_path / "isolated_suite"
    (project / "tools").mkdir(parents=True)
    copied = project / "tools" / source.name
    copied.write_bytes(source.read_bytes())
    loader = importlib.machinery.SourceFileLoader(
        "suite_entrypoint_static_help", str(ROOT / "suite.py"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", project)
    monkeypatch.setattr(sys, "argv",
                        ["suite.py", "tool", copied.name, "--help"])
    assert module.main() == 0
    text = capsys.readouterr().out
    assert "--output" in text
    assert "kein Skript gestartet" in text
    assert not marker.exists()
