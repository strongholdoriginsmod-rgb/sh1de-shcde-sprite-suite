"""Stronghold specialist navigation and full SHA matrix are passive and exact."""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / "tools"))

from suite_tool_inventory import (  # noqa: E402
    InventoryError, SCHEMA, build_matrix, main, markdown, scan,
)
from suite_tool_registry import (  # noqa: E402
    SPECIALISTS, available_specialists, open_specialist,
)
from suite_command_search import build_navigation_targets, find_targets  # noqa: E402


def fixture(tmp_path):
    latest = tmp_path / "latest"
    earlier = tmp_path / "earlier"
    for root in (latest, earlier):
        (root / "tools").mkdir(parents=True)
    (latest / "tools" / "same.py").write_text(
        "if __name__ == '__main__':\n    print('safe')\n", encoding="utf-8")
    (earlier / "tools" / "same.py").write_bytes(
        (latest / "tools" / "same.py").read_bytes())
    (latest / "tools" / "changed.py").write_text("VALUE = 2\n", encoding="utf-8")
    (earlier / "tools" / "changed.py").write_text("VALUE = 1\n", encoding="utf-8")
    (latest / "tools" / "new.py").write_text("VALUE = 1\n", encoding="utf-8")
    (earlier / "tools" / "legacy.py").write_text("VALUE = 3\n", encoding="utf-8")
    return latest, earlier


def test_comparison_is_sha_based_deterministic_and_read_only(tmp_path):
    latest, earlier = fixture(tmp_path)
    original = {str(p): p.read_bytes() for root in (latest, earlier)
                for p in (root / "tools").iterdir()}
    a = build_matrix(latest, [earlier])
    b = build_matrix(latest, [earlier])
    assert a == b
    assert a["schema"] == SCHEMA
    rows = {r["name"]: r for r in a["comparisons"][0]["tools"]}
    assert rows["same.py"]["status"] == "identisch"
    assert rows["changed.py"]["status"] == "abweichend"
    assert rows["new.py"]["status"] == "nur_aktuell"
    assert rows["legacy.py"]["status"] == "nur_historisch"
    assert rows["same.py"]["current_sha256"] == hashlib.sha256(
        (latest / "tools" / "same.py").read_bytes()).hexdigest()
    assert a["current"]["tools"]["same.py"]["entrypoint"] is True
    assert a["current"]["tools"]["changed.py"]["entrypoint"] is False
    assert {str(p): p.read_bytes() for root in (latest, earlier)
            for p in (root / "tools").iterdir()} == original
    assert not list(tmp_path.rglob("__pycache__"))


def test_scanner_does_not_import_or_execute_dangerous_legacy_code(tmp_path):
    latest, earlier = fixture(tmp_path)
    marker = tmp_path / "bad.txt"
    payload = "from pathlib import Path\nPath(%r).write_text('BAD')\n" % str(marker)
    (earlier / "tools" / "malicious.py").write_text(payload, encoding="utf-8")
    (earlier / "tools" / "bad_syntax.py").write_text(
        "if False print('broken')\n", encoding="utf-8")
    rows = scan(earlier)["tools"]
    assert rows["malicious.py"]["entrypoint"] is False
    assert rows["bad_syntax.py"]["entrypoint"] is None
    assert rows["malicious.py"]["risk"] == "unknown"
    assert not marker.exists()


def test_multiple_historical_sources_and_cli_stdout(tmp_path, capsys):
    latest, earlier = fixture(tmp_path)
    third = tmp_path / "third"
    (third / "tools").mkdir(parents=True)
    (third / "tools" / "old_only.ps1").write_text("# old\n", encoding="utf-8")
    result = build_matrix(latest, [earlier, third])
    assert len(result["comparisons"]) == 2
    assert result["comparisons"][1]["counts"]["nur_historisch"] == 1
    assert "old_only.ps1" in markdown(result)
    assert main(["--root", str(latest), "--compare", str(earlier),
                 "--format", "markdown"]) == 0
    printed = capsys.readouterr().out
    assert "Stronghold/SpriteSuite" in printed
    assert "nur_historisch" in printed
    assert not list(tmp_path.rglob("*.json"))


def test_invalid_missing_duplicate_or_same_source_is_rejected(tmp_path):
    latest, earlier = fixture(tmp_path)
    with pytest.raises(InventoryError):
        scan(tmp_path / "absent")
    with pytest.raises(InventoryError):
        scan(tmp_path)
    with pytest.raises(InventoryError):
        build_matrix(latest, [latest])
    with pytest.raises(InventoryError):
        build_matrix(latest, [earlier, earlier])
    assert main(["--root", str(latest), "--compare", str(latest)]) == 2


def test_zero_length_and_junction_file_safety(tmp_path):
    latest, earlier = fixture(tmp_path)
    (latest / "tools" / "zero.py").touch()
    assert scan(latest)["tools"]["zero.py"]["status"] == "ungültige_größe"
    target = earlier / "tools" / "legacy.py"
    link = latest / "tools" / "linked.py"
    try:
        link.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks nicht zulässig auf diesem Testkonto")
    row = scan(latest)["tools"]["linked.py"]
    assert row["status"] == "unsicherer_link"
    assert row["sha256"] is None
    with pytest.raises(InventoryError):
        scan(link.parent.parent / "tools" / "linked.py")


def fake_app(catalog_paths):
    visits = []
    loaded = []
    executed = []
    state = SimpleNamespace(value=None)
    state.set = lambda val: setattr(state, "value", val)
    root = SimpleNamespace(
        _navigation_entries=(),
        exchange_tab=SimpleNamespace(section_targets=()),
        sandbox_tab=SimpleNamespace(
            show_game_map=lambda: None,
            show_game_hud=lambda: None,
            show_animation=lambda: None,
            choose_folder=lambda: None,
            compare=lambda: None,
        ),
        diagnose_tab=object(),
        bc7_page=object(),
        catalog_page=object(),
        catalog_paths=catalog_paths,
        catalog_tool=state,
        open_tab=lambda page: visits.append(page),
        load_catalog=lambda: loaded.append(state.value),
        run=lambda *args: executed.append(args),
    )
    return root, visits, loaded, executed


def test_specialists_reuse_existing_catalog_and_never_run():
    assert len(SPECIALISTS) >= 15
    assert len({s.filename for s in SPECIALISTS}) == len(SPECIALISTS)
    paths = {s.filename: PROJECT / "tools" / s.filename for s in SPECIALISTS}
    assert all(p.is_file() for p in paths.values())
    app, visited, loaded, executed = fake_app(paths)
    assert len(available_specialists(app)) == len(SPECIALISTS)
    targets = build_navigation_targets(app)
    assert {t.key for t in targets if t.key.startswith("tool:")} == {
        "tool:" + s.filename for s in SPECIALISTS}
    selected = find_targets(targets, "GM1 tile")
    assert any(t.key == "tool:kachelraster_gm1.py" for t in selected)
    chosen = next(t for t in targets if t.key == "tool:kachelraster_gm1.py")
    chosen.navigate()
    assert visited == [app.catalog_page]
    assert loaded == ["kachelraster_gm1.py"]
    assert app.catalog_tool.value == "kachelraster_gm1.py"
    assert not executed


def test_missing_unknown_or_external_catalog_entries_are_not_exposed(tmp_path):
    correct = PROJECT / "tools" / "sprites.py"
    wrong = tmp_path / "sprites.py"
    wrong.write_text("print('WRONG')\n", encoding="utf-8")
    app, visited, loaded, executed = fake_app({
        "sprites.py": wrong,
        "suite_unified_project.py": PROJECT / "tools" / "suite_unified_project.py",
    })
    targets = build_navigation_targets(app)
    assert not [t for t in targets if t.key.startswith("tool:")]
    with pytest.raises(FileNotFoundError):
        open_specialist(app, "sprites.py")
    with pytest.raises(ValueError):
        open_specialist(app, "suite_unified_project.py")
    assert not visited and not loaded and not executed
    app.catalog_paths["sprites.py"] = correct
    assert [s.filename for s in available_specialists(app)] == ["sprites.py"]
    assert "tool:sprites.py" in {t.key for t in build_navigation_targets(app)}


def test_building_damage_cli_has_precise_read_write_network_risk():
    from suite_tool_policy import classify
    from suite_tool_registry import SPECIALISTS
    names = {tool.filename for tool in SPECIALISTS}
    assert "building_damage_runtime_preflight.py" in names
    assert "building_damage_codex.py" in names
    assert classify("building_damage_runtime_preflight.py", ["--dry-run"]).category == "read"
    assert classify("building_damage_runtime_preflight.py", []).category == "read"
    assert classify("building_damage_runtime_preflight.py", ["--prepare"]).category == "workspace"
    assert classify("building_damage_runtime_preflight.py", ["--help"]).category == "read"
    assert classify("building_damage_codex.py", ["--dry-run"]).category == "read"
    assert classify("building_damage_codex.py", []).category == "read"
    assert classify("building_damage_codex.py", ["--execute"]).category == "external"
    assert classify("building_damage_codex.py", ["--help"]).category == "read"

def test_building_damage_footprint_compiler_is_discoverable_and_read_only():
    from suite_tool_registry import SPECIALISTS
    from suite_tool_policy import classify
    names = [tool.filename for tool in SPECIALISTS]
    assert "qa_building_damage_runtime.py" in names
    assert len(set(names)) == len(names)
    assert classify("qa_building_damage_runtime.py", []).category == "workspace"
    assert classify("qa_building_damage_runtime.py",
                    ["--verify-shcdese", "E:\\test\\SHCDESE.dll"]).category == "workspace"

def test_building_damage_live_qa_has_strict_risk_and_registry():
    from suite_tool_registry import SPECIALISTS
    from suite_tool_policy import classify
    names = [item.filename for item in SPECIALISTS]
    assert "qa_building_damage_live.py" in names
    assert len(names) == len(set(names))
    assert classify("qa_building_damage_live.py", []).category == "workspace"
    assert classify("qa_building_damage_live.py", ["--build-only"]).category == "workspace"
    assert classify("qa_building_damage_live.py", ["--verify-log", "qa.log"]).category == "read"
    assert classify("qa_building_damage_live.py", ["--install-qa"]).category == "game"
    assert classify("qa_building_damage_live.py", ["--remove-qa"]).category == "game"



def test_building_damage_layer_census_has_distinct_read_and_workspace_risk():
    from suite_tool_registry import SPECIALISTS
    from suite_tool_policy import classify

    names = [specialist.filename for specialist in SPECIALISTS]
    assert names.count("building_damage_layer_audit.py") == 1
    assert classify("building_damage_layer_audit.py", []).category == "read"
    assert classify("building_damage_layer_audit.py",
                    ["--log", "qa.log", "--expected-sha256", "a" * 64]).category == "read"
    assert classify("building_damage_layer_audit.py",
                    ["--log", "qa.log", "--output", "audit.json"]).category == "workspace"
    assert classify("building_damage_layer_audit.py",
                    ["--help"]).category == "read"


def test_recursive_tool_inventory_is_opt_in_and_relative_path_safe(tmp_path):
    """Nested tool sources are read without becoming executable GUI entries."""
    current, earlier = fixture(tmp_path)
    internal = current / "tools" / "blender"
    internal.mkdir()
    nested = internal / "helper.py"
    marker = tmp_path / "UNWANTED_EXECUTION.txt"
    nested.write_text(
        "from pathlib import Path\n"
        + f"Path({str(marker)!r}).write_text('executed')\n",
        encoding="utf-8")
    (earlier / "tools" / "blender").mkdir()
    (earlier / "tools" / "blender" / "helper.py").write_bytes(nested.read_bytes())
    (current / "tools" / "vendor").mkdir()
    (current / "tools" / "vendor" / "third_party.py").write_text("UNRELATED=1\n")

    assert "blender/helper.py" not in scan(current)["tools"]
    rows = scan(current, recursive=True)["tools"]
    assert "blender/helper.py" in rows
    assert rows["blender/helper.py"]["risk"] == "unknown"
    assert rows["blender/helper.py"]["specialist"] is False
    assert "vendor/third_party.py" not in rows
    assert not marker.exists()
    summary = build_matrix(current, [earlier], recursive=True)
    assert summary["recursive"] is True
    assert next(row for row in summary["comparisons"][0]["tools"]
                if row["name"] == "blender/helper.py")["status"] == "identisch"
    assert not marker.exists()


def test_recursive_scan_does_not_follow_linked_directories(tmp_path):
    current, _ = fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "malicious.py").write_text("VALUE=10\n")
    link = current / "tools" / "unsafe-symlink"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Verzeichnis-Symlinks nicht zugelassen")
    sources = scan(current, recursive=True)["tools"]
    assert not any("malicious.py" in name for name in sources)
    assert not (current / "tools" / "unsafe-symlink" / "generated.txt").exists()


def test_recursive_cli_works_for_deep_older_source(tmp_path, capsys):
    current, earlier = fixture(tmp_path)
    (earlier / "tools" / "native").mkdir()
    (earlier / "tools" / "native" / "Probe.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"></Project>\n', encoding="utf-8")
    assert main(["--root", str(current), "--compare", str(earlier),
                 "--recursive", "--format", "markdown"]) == 0
    output = capsys.readouterr().out
    assert "native/Probe.csproj" in output
    assert "nur_historisch" in output
