"""Integration and adversarial tests for the unified SHCDE expansion."""
from __future__ import annotations

from pathlib import Path
import hashlib
import json
import sys
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import shcde_api_native_index as api
import shcde_aiv_lord_studio as aiv
import shcde_gameplay_rules as gameplay
import shcde_game_inspector as inspector
import shcde_managed_builder as builder
import shcde_mod_composer as composer
import shcde_mod_project as project
import shcde_mod_settings as moddata
import shcde_pathing_report as pathing
import shcde_qa_suite as qa
import shcde_scenario_graph as scenario
import shcde_workbench as workbench
from suite_tool_registry import SPECIALISTS
from suite_tool_policy import classify


def sample_mods(tmp_path):
    left = tmp_path / "linke mod"
    right = tmp_path / "rechte mod"
    (left / "Scripts").mkdir(parents=True)
    (right / "Scripts").mkdir(parents=True)
    (right / "Audio").mkdir()
    (left / "Scripts" / "init.lua").write_text("return 'alt'", encoding="utf-8")
    (right / "Scripts" / "init.lua").write_text("return 'neu'", encoding="utf-8")
    (right / "Audio" / "eigene datei.custom").write_bytes(b"\0\xfffoo")
    return left, right


def test_composer_accepts_unrestricted_custom_assets_and_provenance(tmp_path):
    left, right = sample_mods(tmp_path)
    report, chosen = composer.plan_sources([left, right], policy="last")
    assert len(chosen) == 2
    assert len(report["conflicts"]) == 1
    assert report["conflicts"][0]["winner"] == "last"
    assert not report["requiresCreativeApproval"]
    output = tmp_path / "mixed.zip"
    result = composer.compose([left, right], output)
    assert result["files"] == 2
    assert output.exists()
    with ZipFile(output) as archive:
        assert archive.read("Scripts/init.lua") == b"return 'neu'"
        assert archive.read("Audio/eigene datei.custom") == b"\0\xfffoo"
        assert archive.testzip() is None
        assert ".spritesuite/composition.json" in archive.namelist()
    assert not composer.inspect(output)["integrityErrors"]
    assert (left / "Scripts" / "init.lua").read_text() == "return 'alt'"


def test_composer_first_and_reject_conflicts(tmp_path):
    a, b = sample_mods(tmp_path)
    report, chosen = composer.plan_sources([a, b], policy="first")
    assert report["conflicts"][0]["winner"] == "first"
    output = tmp_path / "first.zip"
    composer.compose([a, b], output, policy="first")
    with ZipFile(output) as z:
        assert z.read("Scripts/init.lua") == b"return 'alt'"
    with pytest.raises(ValueError, match="Conflicting"):
        composer.plan_sources([a, b], policy="error")


@pytest.mark.parametrize("bad", [
    "../outside", "C:/absolute.txt", "/root/exploit", "a//b",
    "a/./b", "a/../b", "a\\..\\b", "", "nul\0bad",
])
def test_composer_rejects_unsafe_archive_paths(bad):
    with pytest.raises(ValueError):
        composer.entry_name(bad)


def test_composer_keeps_casing_collisions_explicit(tmp_path):
    a, b = sample_mods(tmp_path)
    # Windows cannot hold INIT.lua and init.lua in the same directory.
    # An external ZIP can; it must not silently bypass collision checks.
    conflicting_zip = tmp_path / "case-variants.zip"
    with ZipFile(conflicting_zip, "x") as archive:
        archive.writestr("Scripts/INIT.lua", "other")
    report, _ = composer.plan_sources([a, b, conflicting_zip], policy="last")
    assert len(report["conflicts"]) == 2
    assert any(row["type"] == "case_or_unicode" for row in report["conflicts"])


def test_composer_never_overwrites_finished_mod(tmp_path):
    a, b = sample_mods(tmp_path)
    output = tmp_path / "release.zip"
    composer.compose([a, b], output)
    original = output.read_bytes()
    with pytest.raises(FileExistsError):
        composer.compose([a, b], output)
    assert output.read_bytes() == original


def test_composer_reuses_its_verified_exports_and_records_upstream_receipt(tmp_path):
    left, right = sample_mods(tmp_path)
    original = tmp_path / "first.zip"
    composer.compose([left], original)
    merged = tmp_path / "merged.zip"
    composer.compose([original, right], merged)
    with ZipFile(original) as source, ZipFile(merged) as archive:
        receipt = json.loads(archive.read(composer.PROVENANCE_PATH))
        assert archive.namelist().count(composer.PROVENANCE_PATH) == 1
        assert receipt["upstreamCompositions"] == [{
            "sourceIndex": 0,
            "receiptSHA256": hashlib.sha256(source.read(composer.PROVENANCE_PATH)).hexdigest(),
        }]
        assert archive.read("Scripts/init.lua") == b"return 'neu'"
    assert not composer.inspect(merged)["integrityErrors"]
    bad = tmp_path / "bad.zip"
    with ZipFile(original) as source, ZipFile(bad, "x") as archive:
        for item in source.infolist():
            archive.writestr(item, b"tampered" if item.filename == "Scripts/init.lua"
                             else source.read(item))
    with pytest.raises(ValueError, match="verification"):
        composer.compose([bad], tmp_path / "must-not-exist.zip")
    assert not (tmp_path / "must-not-exist.zip").exists()


def test_unified_project_roundtrip_arbitrary_version_assets_and_domains(tmp_path):
    root = tmp_path / "Mein neues Mod"
    data = project.make_project(root, name="Mein Mod", guid="self.my-own",
                                version="99.5-alpha+custom")
    assert len(data["domains"]) == 16
    artwork = tmp_path / "sound.dll"
    artwork.write_bytes(b"freely-authored-dll")
    imported = project.add_asset(root, artwork, "Override/Assets/Custom/audio.dll")
    assert imported["sha256"] == hashlib.sha256(artwork.read_bytes()).hexdigest()
    project.edit_domain(root, "units", "custom.units", [20, 35, 100000])
    project.edit_domain(root, "economy", "market.prices", {"grain": 0.25})
    saved = project.load_project(root)
    assert saved["domains"]["units"]["custom"]["units"] == [20, 35, 100000]
    assert saved["domains"]["economy"]["market"]["prices"] == {"grain": 0.25}
    assert saved["identity"]["Version"] == "99.5-alpha+custom"
    summary = project.inspect_project(root)
    assert summary["domainsWithData"] == ["economy", "units"]
    assert not summary["assetIntegrityIssues"]
    archive = tmp_path / "all-shcde-assets.zip"
    result = project.export_project(root, archive)
    assert result["files"] == 2
    with ZipFile(archive) as z:
        assert z.read("Override/Assets/Custom/audio.dll") == artwork.read_bytes()
        assert json.loads(z.read("info.json"))["Version"] == "99.5-alpha+custom"


def test_project_detects_mutated_assets_before_export(tmp_path):
    folder = tmp_path / "mod"
    project.make_project(folder, name="M", guid="org.m")
    source = tmp_path / "original.lua"
    source.write_bytes(b"print('a')")
    project.add_asset(folder, source, "Scripts/init.lua")
    (folder / "Payload" / "Scripts" / "init.lua").write_bytes(b"print('changed')")
    assert project.inspect_project(folder)["assetIntegrityIssues"]
    with pytest.raises(ValueError, match="Changed"):
        project.export_project(folder, tmp_path / "corrupt.zip")
    assert source.read_bytes() == b"print('a')"


def test_project_preserves_creative_authoring_and_version_independence(tmp_path):
    root = tmp_path / "custom"
    project.make_project(root, name="Custom", guid="org.my-expansion")
    project.edit_domain(root, "scenario", "arbitrary", {"hook": "unknown future API", "value": 9})
    assert project.load_project(root)["domains"]["scenario"]["arbitrary"]["value"] == 9
    assert not project.load_project(root)["gameVersionRequirements"]


def test_lua_scenario_compiles_all_supported_triggers_as_callback_module():
    spec = {"events": [
        {"id": "begin", "trigger": {"kind": "start"},
         "actions": [{"type": "notify", "text": "Grüße \n \"Herr\""}]},
        {"id": "wave", "trigger": {"kind": "interval", "ticks": 900},
         "actions": [{"type": "spawn", "unit": "archer", "count": 12}]},
        {"id": "castle", "trigger": {"kind": "flag", "name": "my-building", "equals": True},
         "actions": [{"type": "resource", "wood": -30}]},
        {"id": "area", "trigger": {"kind": "signal", "name": "unit_enter",
                                  "match": {"region": "north"}},
         "actions": [{"type": "reinforcement", "amount": 5}]},
        {"id": "manual", "trigger": {"kind": "custom", "luaExpression": "ctx ~= nil"},
         "actions": [{"type": "custom_action", "arg": [1, 2, 3]}]},
    ]}
    code = scenario.compile_lua(spec)
    assert "function M.Tick(ctx, tick)" in code
    assert "function M.Signal(ctx, name, payload)" in code
    assert "state.fired[\"begin\"]" in code
    assert "tick % 900 == 0" in code
    assert "region" in code
    assert 'ctx:perform(typ, payload)' in code
    assert 'Grüße' in code
    assert 'error(' in code
    assert "unverified hook" in code


def test_lua_scenario_rejects_duplicate_ids_and_bad_intervals():
    with pytest.raises(ValueError, match="duplicated"):
        scenario.compile_lua({"events": [
            {"id": "a", "actions": []},
            {"id": "a", "actions": []},
        ]})
    with pytest.raises(ValueError, match="positive integer"):
        scenario.compile_lua({"events": [
            {"id": "tick", "trigger": {"kind": "interval", "ticks": 0},
             "actions": []},
        ]})


def test_lua_quote_and_float_consistency():
    assert scenario.lua_string('back\\slash"') == '"back\\\\slash\\""'
    assert scenario.lua_value({"fire": True, "hp": 0.5, "skip": None}).startswith("{")
    with pytest.raises(ValueError):
        scenario.lua_value(float("nan"))


def test_baseline_query_contains_real_build_identity_and_per_record_provenance(tmp_path):
    root = tmp_path / "baseline"
    claim_dir = root / "sem" / "evidence" / "knowledge"
    claim_dir.mkdir(parents=True)
    hash_ = "fbcB93195fc7EfCa9bdac5204852efdd76f9818f59a6711750d77c9cef2831e2".lower()
    (root / "CURRENT.md").write_text(
        "# Current\n\nCurrent canonical DLL SHA-256:\n\n`" + hash_ + "`\n")
    evidence = [{"function": "market.price", "rva": "CEB10", "confidence": "reviewed"},
                {"function": "unit.pathing", "rva": "0x119F90", "confidence": "candidate"}]
    with (claim_dir / "function-claims.jsonl").open("w", encoding="utf-8") as file:
        for row in evidence:
            file.write(json.dumps(row) + "\n")
    report = api.query_baseline(root, "pathing")
    assert report["available"]
    assert report["canonicalDLLSHA256"] == hash_
    assert len(report["matches"]) == 1
    assert not report["matches"][0]["verifiedForOtherVersions"]
    assert not report["memoryPatchProposed"]


def test_aiv_castle_can_preview_actual_coordinate_entries():
    doc = {"BuildingSteps": [
        {"x": 100, "y": 101, "type": "Gatehouse", "step": 1},
        {"x": 101, "y": 101, "buildingType": 40, "phase": 2},
    ]}
    layout = aiv.aiv_layout(doc)
    assert layout["count"] == 2
    assert not layout["nativeAivGridFormatDecoded"]
    svg = aiv.layout_svg(layout)
    assert svg.startswith("<?xml")
    assert "Gatehouse" in svg
    assert "<polygon" in svg


def test_aiv_castle_does_not_invent_unknown_binary_grid():
    layout = aiv.aiv_layout({"someEncodedAiv": "AABBCC"})
    assert layout["placements"] == []
    with pytest.raises(ValueError, match="No drawable"):
        aiv.layout_svg(layout)


def test_custom_lord_pack_authoring_and_listing(tmp_path):
    folder = tmp_path / "My Lord"
    folder.mkdir()
    (folder / "lord.lordjson").write_text("{}", encoding="utf-8")
    (folder / "lord.aivjson").write_text("{}", encoding="utf-8")
    meta = {"LocalizedDisplayName": {"de-DE": "Wächter", "en-US": "Gatekeeper"}}
    report = aiv.prepare_lord(folder, name="Gatekeeper", guid="org.creator.gatekeeper",
                              author="Creator", version="beta", metadata=meta)
    assert len(report["created"]) == 2
    content = aiv.index_lord(folder)
    assert content["baseLordConfigs"] == 1
    assert content["baseCastles"] == 1
    assert content["hasExtendedLordMetadata"]
    assert not content["compatibilityFindings"]
    assert json.loads((folder / "info.json").read_text(encoding="utf-8"))["AssetMode"] == "Local"
    assert json.loads((folder / "lordmeta.json").read_text(encoding="utf-8")) == meta


def test_modlord_edits_preserve_foreign_namespaces(tmp_path):
    lord = tmp_path / "multi.part.lordjson"
    lord.write_text("{}", encoding="utf-8")
    sidecar = tmp_path / "multi.part.modlord.json"
    old = {"org.other": {"unknown": {"feature": ["value"]}}}
    sidecar.write_text(json.dumps(old), encoding="utf-8")
    target = moddata.namespace_file(lord=lord)
    assert target == sidecar
    report = moddata.update_namespace(sidecar, "org.mine", {"aggression": 1.25})
    assert report["foreignNamespacesPreserved"] == 1
    assert moddata.read_document(sidecar)["org.other"] == old["org.other"]
    assert moddata.read_document(sidecar)["org.mine"]["aggression"] == 1.25
    backup = list(tmp_path.glob("multi.part.modlord.json.backup.*"))
    assert len(backup) == 1
    assert json.loads(backup[0].read_text()) == old


def test_modmap_data_is_namespaced_and_preserves_existing_keys(tmp_path):
    content = tmp_path / "map-append-archive"
    content.mkdir()
    sidecar = moddata.namespace_file(map_archive_folder=content)
    moddata.update_namespace(sidecar, "a.mod", {"waves": [1, 2]})
    moddata.update_namespace(sidecar, "b.mod", {"pathing": {"cost": 3}})
    assert len(moddata.read_document(sidecar)) == 2
    assert moddata.read_document(sidecar)["a.mod"]["waves"] == [1, 2]


def test_modsettings_contract_records_api_shared_preset_roles():
    catalog = moddata.settings_contract({"settings": [
        {"name": "CostMultiplier", "role": "host", "defaultValue": 1.25},
        {"name": "Colour", "role": "per_player", "defaultValue": "blue"},
        {"name": "Preview", "role": "local", "defaultValue": True},
    ]})
    assert [row["apiSharedAttribute"] for row in catalog["settings"]] == [
        "SyncHostOnly", "SyncPerPlayer", "PresetLocal"
    ]
    assert catalog["apiSharedRuntimeCompiled"] is False
    with pytest.raises(ValueError):
        moddata.settings_contract({"settings": [{"name": "x", "role": "any"}]})


def test_path_profiler_only_uses_measured_times_and_can_group():
    events = "\n".join([
        "[Info] SHCDESE|event=FindNextComponent|duration_ms=30.5|pathing=true",
        "[Info] SHCDESE|event=FindNextComponent|duration_ms=15.0|pathing=true",
        "[Info] SHCDESE|event=FindNextComponent|duration_ms=48.2|pathing=true",
        "[Info] Native path result no timing measured",
    ])
    values = pathing.parse_measurements(events)
    result = pathing.summarize(values, threshold=20)
    assert result["totalTimingRecords"] == 3
    assert len(result["operations"]) == 1
    assert result["operations"][0]["maxMs"] == 48.2
    assert result["operations"][0]["slowCalls"] == 2
    assert not result["nativeFunctionHookWasInstalled"]


def test_path_profiler_does_not_invent_missing_measurements():
    assert pathing.summarize([])["totalTimingRecords"] == 0


def test_gameplay_rules_syntax_allows_real_api_values_but_not_invalid_widths():
    rows = gameplay.parse_rules("unit-hp\t12\t1000\n"
                                "building-hp\t55\t4900\n"
                                "unit-range\t12\t18\n")
    assert len(rows) == 3
    assert rows[0]["value"] == 1000
    assert gameplay.manifest({"rules": rows}).count("\n") >= 3
    with pytest.raises(ValueError):
        gameplay.parse_rules("unit-range\t3\t4294967295\n")
    assert gameplay.parse_rules(gameplay.TEMPLATE) == []
    assert len(gameplay.TEMPLATE.splitlines()) == 4


def test_inspector_installer_reuses_linked_game_path_rejection(tmp_path, monkeypatch):
    # No installed game is involved. Both installers must refuse a linked
    # plugin parent before creating files in this isolated scratch tree.
    plugins = tmp_path / "BepInEx" / "plugins"
    plugins.mkdir(parents=True)
    dll = tmp_path / "test.dll"
    dll.write_bytes(b"compiler-output-fixture")
    monkeypatch.setattr(builder, "is_link_or_reparse", lambda path: path == plugins)
    with pytest.raises(ValueError, match="linked"):
        inspector.install_inspector(tmp_path, dll)
    assert list(plugins.iterdir()) == []


def test_qa_check_uses_this_checkouts_source_package(tmp_path, monkeypatch):
    monkeypatch.delenv("PYTHONPATH", raising=False)
    check = qa.run_check([sys.executable, "-c",
                          "import stronghold_europe_de.asset_inspector as a; print(a.__file__)"],
                         tmp_path)
    assert check["passed"], check
    assert str(ROOT / "src") in check["stdoutTail"]


def test_object_inspector_qa_log_has_no_gameplay_write_claims(tmp_path):
    path = tmp_path / "inspector.log"
    path.write_text(
        "SHCDE_INSPECT|event=building|global_id=99|id=4|hp=30|read_only=true\n"
        "SHCDE_INSPECT|event=unit|global_id=3|id=6|hp=10|read_only=true\n",
        encoding="utf-8")
    result = inspector.parse_log(path)
    assert result["buildings"] == 1 and result["units"] == 1
    assert result["gameStateWriteClaimed"] is False


def test_shared_managed_builder_uses_real_game_sdk_paths_not_fake_executions():
    assert any("SHCDESE.dll" in path for path in builder.REQUIRED_REFS)
    assert builder.RECEIPT.endswith(".json")
    assert (ROOT / "runtime" / "SpriteSuite.ShcdeInspector" /
            "SpriteSuiteInspector.cs").is_file()


def test_qa_snapshot_reports_real_project_and_zip_integrity(tmp_path):
    folder = tmp_path / "mod"
    project.make_project(folder, name="QA", guid="a.qa")
    archive = tmp_path / "package.zip"
    project.export_project(folder, archive)
    report = qa.run_qa(project=folder, archive=archive,
                       include_pytest=False)
    assert report["passed"]
    assert len(report["checks"]) == 2
    assert not report["visualInGameAbnahmeProved"]


def test_workbench_connects_all_sixteen_real_or_declared_workspaces():
    catalog = workbench.catalog()
    assert catalog["domainCount"] == 16
    assert len(catalog["domains"]) == 16
    assert all(domain["tools"] for domain in catalog["domains"])
    assert all(domain["id"] in project.DOMAINS for domain in catalog["domains"])
    assert any(spec.filename == "shcde_workbench.py" for spec in SPECIALISTS)
    assert classify("shcde_game_inspector.py", ["build", "--install"]).category == "game"
    assert classify("shcde_game_inspector.py", ["build"]).category == "workspace"
    assert classify("shcde_mod_composer.py", ["inspect"]).category == "read"



def test_composer_failure_preserves_new_target_and_receipt_checks_member_hashes(tmp_path, monkeypatch):
    left, right = sample_mods(tmp_path)
    output = tmp_path / "unchanged.zip"
    original_stream = composer._file_stream
    reads = 0

    def failing(member, opened):
        nonlocal reads
        reads += 1
        if reads > 2:
            raise OSError("simulated input read failure")
        return original_stream(member, opened)

    monkeypatch.setattr(composer, "_file_stream", failing)
    with pytest.raises(OSError, match="simulated"):
        composer.compose([left, right], output)
    assert not output.exists()
    monkeypatch.setattr(composer, "_file_stream", original_stream)
    composer.compose([left, right], output)
    with ZipFile(output) as old:
        entries = {name: old.read(name) for name in old.namelist()}
    entries["Scripts/init.lua"] = b"tampered"
    damaged = tmp_path / "tampered.zip"
    with ZipFile(damaged, "w") as zipped:
        for name, raw in entries.items():
            zipped.writestr(name, raw)
    assert any("changed" in error for error in composer.inspect(damaged)["integrityErrors"])


def test_workbench_links_main_project_assets_without_importing_a_second_copy(tmp_path, monkeypatch):
    import hud_menu_workspace as hud
    home = tmp_path / "suite"
    work = home / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(hud, "ROOT", home)
    monkeypatch.setattr(hud, "WORK", work)
    shared = work / "primary"
    shared.mkdir()
    source = tmp_path / "user.lua"
    source.write_bytes(b"return 1")
    installed = hud.import_mod_file(source, "Scripts/custom.lua", project=shared)
    adapter = tmp_path / "game-settings"
    project.make_project(adapter, name="Shared", guid="org.shared")
    project.link_suite_project(adapter, shared)
    assert "Scripts/custom.lua" in project.inspect_project(adapter)["sharedSuiteAssets"]
    installed.write_bytes(b"return 2")
    archive = tmp_path / "current.zip"
    project.export_project(adapter, archive)
    with ZipFile(archive) as zipped:
        assert zipped.read("Scripts/custom.lua") == b"return 2"
    assert not (adapter / project.ASSETS / "Scripts/custom.lua").exists()


def test_workbench_navigates_all_domains_and_launches_with_local_sources(monkeypatch):
    pytest.importorskip("tkinter")
    import shcde_workbench_gui as gui
    from types import SimpleNamespace
    window = gui.WorkbenchWindow()
    window.withdraw()
    invoked = []

    class ImmediateWorker:
        def __init__(self, *, target, daemon):
            self.target = target

        def start(self):
            self.target()

    def run(command, **kwargs):
        invoked.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="offline-help", stderr="")

    monkeypatch.setattr(gui.threading, "Thread", ImmediateWorker)
    monkeypatch.setattr(gui.subprocess, "run", run)
    try:
        for domain in project.DOMAINS:
            window._select_domain(domain)
            assert window.current_domain.get() == domain
            assert window.tool_selected.get() in project.EDITORS[domain]
        assert window.domains.size() == 16
        assert not invoked
        window._run("shcde_mod_composer.py", ["--help"])
        window._consume()
        command, kwargs = invoked[0]
        assert command[-1] == "--help"
        assert str(ROOT / "src") in kwargs["env"]["PYTHONPATH"]
        assert kwargs["cwd"] == ROOT
        assert window.status.get() == "Erfolg / Passed"
        assert not window._busy
    finally:
        for after in window.tk.splitlist(window.tk.call("after", "info")):
            window.after_cancel(after)
        window.destroy()


@pytest.mark.parametrize("text_scale", [1.25, 1.5])
@pytest.mark.parametrize("window_size", [(1020, 680), (820, 560)])
def test_workbench_lower_actions_and_status_are_scroll_reachable_at_small_size(text_scale, window_size):
    pytest.importorskip("tkinter")
    import tkinter.font as font
    import shcde_workbench_gui as gui
    window = gui.WorkbenchWindow()
    window.geometry(f"{window_size[0]}x{window_size[1]}+30+30")
    fonts = {name: font.nametofont(name).cget("size") for name in font.names()}
    try:
        for name, size in fonts.items():
            font.nametofont(name).configure(size=round(size * text_scale))
        window.notebook.select(1)
        window.update()
        scroll = window.form_scroll
        canvas = scroll.canvas

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        actions = [widget for widget in descendants(window)
                   if isinstance(widget, gui.ttk.Button)]
        assert any(widget.cget("text") == "Suite-Projekt verbinden" for widget in actions)
        for widget in [*actions, window.status_label]:
            if not widget.winfo_ismapped():
                continue
            if isinstance(widget, gui.ttk.Button):
                assert widget.winfo_width() + 2 >= widget.winfo_reqwidth()
            scroll.reveal(widget)
            window.update_idletasks()
            assert canvas.winfo_rootx() - 2 <= widget.winfo_rootx()
            assert widget.winfo_rootx() + min(widget.winfo_width(), canvas.winfo_width()) <= (
                canvas.winfo_rootx() + canvas.winfo_width() + 2)
            assert canvas.winfo_rooty() - 2 <= widget.winfo_rooty()
            assert widget.winfo_rooty() + widget.winfo_height() <= (
                canvas.winfo_rooty() + canvas.winfo_height() + 2)
        assert scroll.vertical.winfo_ismapped() and scroll.horizontal.winfo_ismapped()
        assert window.minsize()[1] < 680
    finally:
        for name, size in fonts.items():
            font.nametofont(name).configure(size=size)
        for after in window.tk.splitlist(window.tk.call("after", "info")):
            window.after_cancel(after)
        window.destroy()
