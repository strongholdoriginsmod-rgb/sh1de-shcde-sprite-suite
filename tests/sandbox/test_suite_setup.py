"""Local setup retains settings, validates before publishing, and repairs safely."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import pytest

import stronghold_europe_de.suite_setup as setup
from stronghold_europe_de.config import load_config

PROJECT = Path(__file__).resolve().parents[2]


@pytest.fixture
def local(tmp_path):
    (tmp_path / "config").mkdir()
    games = tmp_path / "fake-games"
    first_root = games / "Source"
    second_root = games / "Crusader"
    first = first_root / setup.SOURCE_DIR
    second = second_root / setup.TARGET_DIR
    for folder in (first, second):
        folder.mkdir(parents=True)
        (folder / "resources.assets").write_bytes(b"synthetic, no original game")
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / "Unity.exe").write_bytes(b"fake unity")
    dotnet = tools / "dotnet"
    dotnet.mkdir()
    (dotnet / "dotnet.exe").write_bytes(b"fake SDK")
    return tmp_path, first_root, second_root, tools / "Unity.exe", dotnet


def test_toolchain_only_before_games_and_editor_folder_accepted(local):
    root, source, target, unity, dotnet = local
    outcome = setup.save_local_setup(
        root, unity=unity.parent, dotnet=dotnet / "dotnet.exe"
    )
    assert outcome["tools_updated"] and not outcome["game_updated"]
    assert not (root / "config/installations.local.toml").exists()
    saved = json.loads((root / "config/toolchains.local.json").read_text(encoding="utf-8"))
    assert saved == {
        "unity_editor": str(unity.resolve()),
        "dotnet_directory": str(dotnet.resolve()),
    }


def test_partial_toolchain_update_preserves_other_tools_and_extra_fields(local):
    root, _, _, unity, dotnet = local
    settings = root / "config/toolchains.local.json"
    settings.write_text(
        json.dumps({"unity_editor": str(unity), "other_setting": "preserve"}),
        encoding="utf-8",
    )
    before = settings.read_bytes()
    report = setup.save_local_setup(root, dotnet=dotnet)
    saved = json.loads(settings.read_text(encoding="utf-8"))
    assert saved["unity_editor"] == str(unity)
    assert saved["dotnet_directory"] == str(dotnet.resolve())
    assert saved["other_setting"] == "preserve"
    assert len(report["backup_files"]) == 1
    assert Path(report["backup_files"][0]).read_bytes() == before
    assert not (root / "config/installations.local.toml").exists()


def test_game_only_never_resets_toolchain_and_accepts_install_data_root(local):
    root, source, target, unity, dotnet = local
    tools = root / "config/toolchains.local.json"
    tools.write_text(json.dumps({"unity_editor": str(unity)}), encoding="utf-8")
    before = tools.read_bytes()
    report = setup.save_local_setup(
        root, source=source, target=target / setup.TARGET_DIR
    )
    assert report["game_updated"] and not report["tools_updated"]
    saved = load_config(root / "config/installations.local.toml")
    assert saved.source.data_dir == (source / setup.SOURCE_DIR).resolve()
    assert saved.target.game_dir == target.resolve()
    assert tools.read_bytes() == before
    assert not report["backup_files"]


def test_same_game_paths_are_noop_without_replace(local):
    root, source, target, _, _ = local
    setup.save_local_setup(root, source=source, target=target)
    game = root / "config/installations.local.toml"
    previous = game.read_bytes()
    report = setup.save_local_setup(
        root, source=source / setup.SOURCE_DIR,
        target=target / setup.TARGET_DIR,
    )
    assert report["unchanged"] and not report["backup_files"]
    assert game.read_bytes() == previous
    assert list((root / "config").glob("*.bak-*")) == []


def test_existing_game_selection_requires_consent_and_preserves_custom_output(local):
    root, source, target, _, _ = local
    setup.save_local_setup(root, source=source, target=target)
    game = root / "config/installations.local.toml"
    old = game.read_text(encoding="utf-8")
    customized = old.replace(
        'dist_dir = "dist"', 'dist_dir = "custom-dist"'
    ).replace(
        "[output]", '# still your configuration\n[output]'
    ).replace(
        'game_dir = ', 'runtime_reference_root = "work/refs"\ngame_dir = ', 1
    )
    game.write_text(customized, encoding="utf-8")
    assert load_config(game).target.reference_root == (root / "work/refs").resolve()
    next_target = root / "fake-games" / "Crusader-2"
    (next_target / setup.TARGET_DIR).mkdir(parents=True)
    old_bytes = game.read_bytes()
    with pytest.raises(ValueError, match="--replace"):
        setup.save_local_setup(root, target=next_target)
    assert game.read_bytes() == old_bytes
    report = setup.save_local_setup(root, target=next_target, replace=True)
    assert report["game_updated"] and not report["tools_updated"]
    updated = game.read_text(encoding="utf-8")
    assert "custom-dist" in updated
    assert "# still your configuration" in updated
    assert "runtime_reference_root" in updated
    assert load_config(game).target.game_dir == next_target.resolve()
    assert Path(report["backup_files"][0]).read_bytes() == old_bytes


def test_bad_new_game_path_never_changes_saved_game_or_tools(local):
    root, source, target, unity, dotnet = local
    setup.save_local_setup(root, source=source, target=target, unity=unity)
    paths = [
        root / "config/installations.local.toml",
        root / "config/toolchains.local.json",
    ]
    before = [p.read_bytes() for p in paths]
    with pytest.raises((ValueError, OSError)):
        setup.save_local_setup(
            root, target=root / "does-not-exist", dotnet=dotnet, replace=True
        )
    assert [p.read_bytes() for p in paths] == before
    assert not list((root / "config").glob(".suite-setup-*.tmp"))


def test_corrupt_existing_game_can_be_repaired_with_explicit_backup(local):
    root, source, target, _, _ = local
    game = root / "config/installations.local.toml"
    game.write_bytes(b"broken existing game config")
    with pytest.raises(ValueError, match="ungültig"):
        setup.save_local_setup(root, source=source, target=target)
    assert game.read_bytes() == b"broken existing game config"
    fixed = setup.save_local_setup(
        root, source=source, target=target, replace=True
    )
    assert load_config(game).target.game_dir == target.resolve()
    assert Path(fixed["backup_files"][0]).read_bytes() == b"broken existing game config"


def test_invalid_toolchain_json_does_not_modify_game_config(local):
    root, source, target, unity, _ = local
    tools = root / "config/toolchains.local.json"
    tools.write_text('{"unity_editor":"old","unity_editor":"duplicate"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Doppelter Eintrag"):
        setup.save_local_setup(root, source=source, target=target, unity=unity)
    assert not (root / "config/installations.local.toml").exists()
    assert "duplicate" in tools.read_text(encoding="utf-8")


def test_failed_second_publish_rolls_back_first(local, monkeypatch):
    root, source, target, unity, dotnet = local
    setup.save_local_setup(root, source=source, target=target, unity=unity)
    game = root / "config/installations.local.toml"
    tools = root / "config/toolchains.local.json"
    originals = (game.read_bytes(), tools.read_bytes())
    new_target = root / "fake-games" / "Crusader-2"
    (new_target / setup.TARGET_DIR).mkdir(parents=True)
    actual_replace = setup.os.replace
    injected = {"done": False}

    def fail_tools_once(src, dst):
        if Path(dst) == tools and not injected["done"]:
            injected["done"] = True
            raise OSError("synthetic second replace failure")
        return actual_replace(src, dst)

    monkeypatch.setattr(setup.os, "replace", fail_tools_once)
    with pytest.raises(OSError, match="wiederhergestellt"):
        setup.save_local_setup(
            root, target=new_target, dotnet=dotnet, replace=True
        )
    assert injected["done"]
    assert (game.read_bytes(), tools.read_bytes()) == originals
    assert not list((root / "config").glob(".suite-setup-*.tmp"))


def test_invalid_unity_selection_does_not_create_settings(local):
    root, _, _, _, _ = local
    with pytest.raises(ValueError, match="Unity-Auswahl"):
        setup.save_local_setup(root, unity=root / "config")
    assert not (root / "config/toolchains.local.json").exists()


def test_unset_inputs_are_actionable_without_creating_files(local):
    root, _, _, _, _ = local
    with pytest.raises(ValueError, match="Keine Pfade"):
        setup.save_local_setup(root)
    assert list((root / "config").iterdir()) == []


def test_suite_cli_configure_supports_tools_only_without_real_project_writes(
    local, monkeypatch, capsys
):
    root, _, _, _, dotnet = local
    spec = importlib.util.spec_from_file_location("suite_setup_cli_test", PROJECT / "suite.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "ROOT", root)
    args = argparse.Namespace(
        source=None, target=None, unity=None, dotnet=dotnet, replace=False
    )
    assert cli.configure(args) == 0
    assert "separat gespeichert" in capsys.readouterr().out
    assert not (root / "config/installations.local.toml").exists()


def test_saved_install_roots_match_readiness_hints(local):
    """Choosing the enclosing game root must not look like an unsaved edit."""
    root, source, target, _, _ = local
    import stronghold_europe_de.suite_build_readiness as ready

    assert ready._same_game_choice(
        str(source), source / setup.SOURCE_DIR, "source"
    )
    assert ready._same_game_choice(
        str(source / setup.SOURCE_DIR), source / setup.SOURCE_DIR, "source"
    )
    assert ready._same_game_choice(
        str(target / setup.TARGET_DIR), target, "target"
    )
    assert ready._same_game_choice(str(target), target, "target")
    different = root / "fake-games" / "Other"
    different.mkdir(parents=True)
    assert not ready._same_game_choice(str(different), source / setup.SOURCE_DIR, "source")
    assert not ready._same_game_choice(str(different), target, "target")


def _gui_setup_handler(monkeypatch, local, *, source="", target="", unity="", dotnet=""):
    import importlib.machinery
    from types import SimpleNamespace

    root = local[0]
    loader = importlib.machinery.SourceFileLoader(
        "suite_setup_gui_handler", str(PROJECT / "tools/suite_center.pyw")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    gui = importlib.util.module_from_spec(spec)
    loader.exec_module(gui)
    monkeypatch.setattr(gui, "ROOT", root)
    class Var:
        def __init__(self, value=""):
            self.value = value
        def get(self):
            return self.value
        def set(self, text):
            self.value = text
    commands = []
    fake = SimpleNamespace(
        runner=SimpleNamespace(busy=False),
        source=Var(source), target=Var(target),
        unity=Var(unity), dotnet=Var(dotnet),
        setup_save_status=Var(""),
        tool=lambda name, args: commands.append((name, args)),
    )
    return gui, fake, commands


def test_gui_tool_only_save_does_not_request_missing_game_paths(local, monkeypatch):
    root, source, target, unity, dotnet = local
    gui, fake, commands = _gui_setup_handler(
        monkeypatch, local, dotnet=str(dotnet)
    )
    monkeypatch.setattr(
        gui.messagebox, "askyesno", lambda *a, **kw: pytest.fail("No prompt needed")
    )
    gui.Center.save_config(fake)
    assert commands == [("suite_bridge.py", ["configure", "--dotnet", str(dotnet)])]
    assert not (root / "config/installations.local.toml").exists()


def test_gui_game_change_requires_confirmation_without_calling_cli(local, monkeypatch):
    root, source, target, unity, dotnet = local
    setup.save_local_setup(root, source=source, target=target)
    revised = root / "fake-games" / "Crusader-2"
    (revised / setup.TARGET_DIR).mkdir(parents=True)
    gui, fake, commands = _gui_setup_handler(
        monkeypatch, local, source=str(source), target=str(revised)
    )
    prompted = []
    monkeypatch.setattr(
        gui.messagebox, "askyesno",
        lambda title, body, **kw: prompted.append((title, body, kw)) or False,
    )
    gui.Center.save_config(fake)
    assert not commands
    assert "beibehalten" in fake.setup_save_status.get()
    assert "gespeicherten Spielpfade" in prompted[0][1]
    assert prompted[0][2]["default"] == "no"
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: True)
    gui.Center.save_config(fake)
    assert len(commands) == 1
    args = commands[0][1]
    assert "--replace" in args
    assert args[args.index("--target") + 1] == str(revised)
    # GUI only submits a command; no configuration is modified until it runs.
    assert load_config(root / "config/installations.local.toml").target.game_dir == target.resolve()


def test_gui_incomplete_games_can_save_selected_tools_only(local, monkeypatch):
    root, source, target, unity, dotnet = local
    gui, fake, commands = _gui_setup_handler(
        monkeypatch, local, source=str(source), dotnet=str(dotnet)
    )
    calls = []
    monkeypatch.setattr(
        gui.messagebox, "askyesno",
        lambda title, *a, **kw: calls.append(title) or True
    )
    gui.Center.save_config(fake)
    assert calls == ["Nur Werkzeugpfade speichern?"]
    assert commands == [("suite_bridge.py", ["configure", "--dotnet", str(dotnet)])]
    assert not (root / "config/installations.local.toml").exists()


def test_failed_staged_validation_leaves_previous_settings_intact(local, monkeypatch):
    root, source, target, unity, dotnet = local
    setup.save_local_setup(root, source=source, target=target, unity=unity)
    game = root / "config/installations.local.toml"
    tools = root / "config/toolchains.local.json"
    previous = (game.read_bytes(), tools.read_bytes())
    newer = root / "fake-games" / "new-location"
    (newer / setup.TARGET_DIR).mkdir(parents=True)
    actual_loader = setup.load_config

    def refuse_unvalidated_file(path):
        if path.name.startswith(".suite-setup-"):
            raise ValueError("synthetic validation failure")
        return actual_loader(path)

    monkeypatch.setattr(setup, "load_config", refuse_unvalidated_file)
    with pytest.raises(ValueError, match="synthetic validation"):
        setup.save_local_setup(
            root, target=newer, dotnet=dotnet, replace=True
        )
    assert (game.read_bytes(), tools.read_bytes()) == previous
    assert not list((root / "config").glob(".suite-setup-*.tmp"))


def test_gui_same_selection_needs_no_extra_confirmation(local, monkeypatch):
    root, source, target, unity, dotnet = local
    setup.save_local_setup(root, source=source, target=target)
    gui, fake, commands = _gui_setup_handler(
        monkeypatch, local, source=str(source), target=str(target / setup.TARGET_DIR)
    )
    monkeypatch.setattr(
        gui.messagebox, "askyesno",
        lambda *a, **kw: pytest.fail("unchanged selection must not prompt"),
    )
    gui.Center.save_config(fake)
    assert len(commands) == 1
    assert "--replace" not in commands[0][1]


@pytest.mark.parametrize("damaged", [
    b"{broken",
    b'{"unity_editor":"one","unity_editor":"two"}',
    b'{"dotnet_directory":NaN}',
    b'[]',
    b'{"dotnet_directory":123}',
    b'{"unity_editor":"' + b"x" * 2050 + b'"}',
    b"\xff\xfe",
])
def test_bad_toolchain_hints_are_read_only_warnings(local, damaged):
    root, _, _, _, dotnet = local
    path = root / "config/toolchains.local.json"
    path.write_bytes(damaged)
    inspected, warnings = setup.inspect_toolchain_hints(root)
    assert inspected == {}
    assert len(warnings) == 1
    assert "Andere Suite-Funktionen bleiben nutzbar" in warnings[0]
    assert path.read_bytes() == damaged
    assert not list(path.parent.glob("*.bak-*"))
    with pytest.raises(ValueError, match="--repair-toolchain"):
        setup.save_local_setup(root, dotnet=dotnet)
    assert path.read_bytes() == damaged


def test_toolchain_repair_preserves_corrupt_original_and_keeps_games(local):
    root, source, target, _, dotnet = local
    setup.save_local_setup(root, source=source, target=target)
    game = root / "config/installations.local.toml"
    old_game = game.read_bytes()
    bad = root / "config/toolchains.local.json"
    bad.write_bytes(b"{not a json object")
    report = setup.save_local_setup(root, dotnet=dotnet, repair_toolchains=True)
    assert report["tools_updated"] and not report["game_updated"]
    assert game.read_bytes() == old_game
    assert setup.inspect_toolchain_hints(root)[1] == ()
    stored = json.loads(bad.read_text(encoding="utf-8"))
    assert stored["dotnet_directory"] == str(dotnet.resolve())
    assert len(report["backup_files"]) == 1
    assert Path(report["backup_files"][0]).read_bytes() == b"{not a json object"


def test_valid_game_config_is_independent_of_corrupt_toolchain(local):
    root, source, target, _, _ = local
    bad = root / "config/toolchains.local.json"
    bad.write_bytes(b"{broken")
    report = setup.save_local_setup(root, source=source, target=target)
    assert report["game_updated"] and not report["tools_updated"]
    assert bad.read_bytes() == b"{broken"
    assert load_config(root / "config/installations.local.toml").target.game_dir == target.resolve()


def test_repair_flag_needs_explicit_tool_selection(local):
    root, source, target, _, _ = local
    with pytest.raises(ValueError, match="benötigt einen gewählten"):
        setup.save_local_setup(root, source=source, target=target, repair_toolchains=True)


def test_launcher_does_not_overwrite_corrupt_local_tools(local, monkeypatch, capsys):
    root, _, _, _, dotnet = local
    damaged = root / "config/toolchains.local.json"
    damaged.write_bytes(b"{broken")
    spec = importlib.util.spec_from_file_location(
        "suite_start_corrupt_test", PROJECT / "tools/suite_start.py"
    )
    starter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(starter)
    monkeypatch.setattr(starter, "PROJECT", root)
    monkeypatch.setattr(starter, "find_dotnet_sdk", lambda _: dotnet)
    starter.fix_toolchains()
    assert damaged.read_bytes() == b"{broken"
    assert "WARNUNG:" in capsys.readouterr().err
    assert not list(damaged.parent.glob("*.bak-*"))


def test_suite_cli_run_ignores_bad_tools_but_reports_warning(local, monkeypatch, capsys):
    root, _, _, _, _ = local
    damaged = root / "config/toolchains.local.json"
    damaged.write_bytes(b'{"unity_editor":false}')
    spec = importlib.util.spec_from_file_location(
        "suite_cli_corrupt_test", PROJECT / "suite.py"
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, "ROOT", root)
    from types import SimpleNamespace
    spawned = []
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda command, **kwargs: spawned.append((command, kwargs))
        or SimpleNamespace(returncode=0),
    )
    assert cli.run(["-m", "pytest", "--version"]) == 0
    assert spawned and spawned[0][0][-2:] == ["pytest", "--version"]
    assert damaged.read_bytes() == b'{"unity_editor":false}'
    assert "WARNUNG:" in capsys.readouterr().err


def test_gui_recovery_requires_confirm_and_never_invokes_tool_on_no(local, monkeypatch):
    root, _, _, _, dotnet = local
    damaged = root / "config/toolchains.local.json"
    damaged.write_bytes(b"invalid tools")
    gui, fake, calls = _gui_setup_handler(
        monkeypatch, local, dotnet=str(dotnet)
    )
    prompts = []
    monkeypatch.setattr(
        gui.messagebox, "askyesno",
        lambda title, body, **kw: prompts.append((title, body, kw)) or False
    )
    gui.Center.save_config(fake)
    assert not calls
    assert len(prompts) == 1
    assert prompts[0][2]["default"] == "no"
    assert damaged.read_bytes() == b"invalid tools"
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: True)
    gui.Center.save_config(fake)
    assert calls == [(
        "suite_bridge.py",
        ["configure", "--dotnet", str(dotnet), "--repair-toolchain"],
    )]
    # Only command submission; no actual local repair until executed.
    assert damaged.read_bytes() == b"invalid tools"


def test_gui_declined_tool_repair_still_allows_game_setup(local, monkeypatch):
    root, source, target, _, dotnet = local
    damaged = root / "config/toolchains.local.json"
    damaged.write_bytes(b"invalid tools")
    gui, fake, calls = _gui_setup_handler(
        monkeypatch, local, source=str(source), target=str(target),
        dotnet=str(dotnet)
    )
    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **kw: False)
    gui.Center.save_config(fake)
    assert calls == [(
        "suite_bridge.py",
        ["configure", "--source", str(source), "--target", str(target)],
    )]
    assert damaged.read_bytes() == b"invalid tools"


def test_gui_environment_drops_obsolete_toolchain_paths(local, monkeypatch):
    root, _, _, unity, dotnet = local
    gui, fake, _ = _gui_setup_handler(monkeypatch, local)
    fake._original_path = "base-path"
    fake._original_unity = None
    toolfile = root / "config/toolchains.local.json"
    toolfile.write_text(json.dumps({
        "unity_editor": str(unity),
        "dotnet_directory": str(dotnet)
    }), encoding="utf-8")
    monkeypatch.setenv("PATH", "previous-path")
    monkeypatch.setenv("STRONGHOLD_EUROPE_UNITY_EDITOR", "old-editor")
    assert not gui.Center.load_environment(fake)
    assert gui.os.environ["PATH"].startswith(str(dotnet))
    assert gui.os.environ["STRONGHOLD_EUROPE_UNITY_EDITOR"] == str(unity)
    toolfile.write_bytes(b"{broken")
    warnings = gui.Center.load_environment(fake)
    assert warnings and "Werkzeugkonfiguration" in warnings[0]
    assert gui.os.environ["PATH"] == "base-path"
    assert "STRONGHOLD_EUROPE_UNITY_EDITOR" not in gui.os.environ
    assert "Andere Suite-Funktionen" in fake.setup_save_status.get()


def test_readonly_setup_diagnostics_never_creates_files(local):
    root, _, _, _, _ = local
    before = sorted(root.rglob("*"))
    report = setup.diagnose_local_setup(root)
    assert report["no_changes_made"] is True
    assert report["build_executed"] is False
    assert report["release_certified"] is False
    assert report["schema"].endswith(".v1")
    assert [item["name"] for item in report["checks"]] == [
        "Spielpfade", "Werkzeug-Einstellungen", "Unity", ".NET-SDK",
    ]
    assert sorted(root.rglob("*")) == before


def test_diagnostics_separates_good_games_from_corrupted_tools(local, monkeypatch):
    root, source, target, _, _ = local
    setup.save_local_setup(root, source=source, target=target)
    bad = root / "config/toolchains.local.json"
    bad.write_bytes(b'{"unity_editor":NaN}')
    before = {p: p.read_bytes() for p in (bad, root / "config/installations.local.toml")}
    monkeypatch.setattr(setup, "find_dotnet_sdk", lambda root: None)
    report = setup.diagnose_local_setup(root)
    by_name = {row["name"]: row for row in report["checks"]}
    assert by_name["Spielpfade"]["state"] == "ok"
    assert by_name["Werkzeug-Einstellungen"]["state"] == "warnung"
    assert "Backup" in by_name["Werkzeug-Einstellungen"]["next_step"]
    assert report["warning_count"] >= 1
    assert {p: p.read_bytes() for p in before} == before


def test_diagnostics_bad_game_file_is_warning_not_blocking_tools(local, monkeypatch):
    root, _, _, _, dotnet = local
    (dotnet / "sdk" / "8.0.100").mkdir(parents=True)
    game = root / "config/installations.local.toml"
    game.write_bytes(b"not TOML at all")
    setup.save_local_setup(root, dotnet=dotnet)
    data = {p: p.read_bytes() for p in (game, root / "config/toolchains.local.json")}
    monkeypatch.setattr(setup, "find_dotnet_sdk", lambda root: dotnet)
    report = setup.diagnose_local_setup(root)
    assert report["checks"][0]["state"] == "warnung"
    assert report["checks"][1]["state"] == "ok"
    assert report["checks"][3]["state"] == "hinweis" or report["checks"][3]["state"] == "ok"
    assert {p: p.read_bytes() for p in data} == data


def test_readonly_diagnostics_cli_json_reports_without_writing(local, monkeypatch, capsys):
    root, _, _, _, dotnet = local
    spec = importlib.util.spec_from_file_location(
        "qa_setup_readonly_test", PROJECT / "tools/qa_suite_local_setup.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(setup, "find_dotnet_sdk", lambda root: None)
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    assert module.main(["--root", str(root), "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["no_changes_made"] is True
    assert result["release_certified"] is False
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before


def test_gui_diagnostics_works_with_corrupt_tools_and_never_runs_cli(local, monkeypatch):
    root, _, _, _, _ = local
    toolchain = root / "config/toolchains.local.json"
    toolchain.write_bytes(b"{broken")
    gui, fake, calls = _gui_setup_handler(monkeypatch, local)
    shown = []
    monkeypatch.setattr(
        gui.messagebox, "showinfo",
        lambda title, body, **kw: shown.append((title, body))
    )
    monkeypatch.setattr(gui, "find_dotnet_sdk", lambda root: None)
    gui.Center.show_setup_diagnostics(fake)
    assert not calls
    assert shown and "Werkzeug-Einstellungen" in shown[0][1]
    assert "nur lesend" in shown[0][0].lower()
    assert toolchain.read_bytes() == b"{broken"
    assert "Keine Dateien verändert" in fake.setup_save_status.get()


@pytest.mark.parametrize("broken", [
    b"not TOML at all",
    b'source = "not a section"',
    b'[source]\nname="Wrong"\ndata_dir = 123',
    b'[source]\nname="Wrong"\ndata_dir = []',
    b'[source]\nname = "Wrong"\ndata_dir = "x"\n[target]\ngame_dir = 4',
    b"\xff\xfe",
])
def test_corrupt_game_configuration_is_readonly_startup_warning(local, broken):
    root, _, _, _, _ = local
    game = root / "config/installations.local.toml"
    game.write_bytes(broken)
    fields, notices = setup.read_game_path_hints(root)
    assert fields == {}
    assert len(notices) == 1
    assert "Datei bleibt unangetastet" in notices[0]
    assert game.read_bytes() == broken
    assert not list((root / "config").glob("*.bak-*"))


def test_saved_valid_game_paths_read_back_for_setup_fields(local):
    root, source, target, _, _ = local
    assert setup.read_game_path_hints(root) == ({}, ())
    setup.save_local_setup(root, source=source, target=target)
    original = (root / "config/installations.local.toml").read_bytes()
    fields, warnings = setup.read_game_path_hints(root)
    assert not warnings
    assert fields == {
        "source": str((source / setup.SOURCE_DIR).resolve()),
        "target": str(target.resolve()),
    }
    assert (root / "config/installations.local.toml").read_bytes() == original


def test_independent_game_setup_warning_does_not_break_toolchain_reader(local):
    root, _, _, unity, dotnet = local
    game = root / "config/installations.local.toml"
    game.write_bytes(b'source = "invalid"')
    setup.save_local_setup(root, unity=unity, dotnet=dotnet)
    paths, notices = setup.read_game_path_hints(root)
    tools, warnings = setup.inspect_toolchain_hints(root)
    assert paths == {} and notices
    assert not warnings
    assert tools["unity_editor"] == str(unity.resolve())
    assert tools["dotnet_directory"] == str(dotnet.resolve())
    assert game.read_bytes() == b'source = "invalid"'
