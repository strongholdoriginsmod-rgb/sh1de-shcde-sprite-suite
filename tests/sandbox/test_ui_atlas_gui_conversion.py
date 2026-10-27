"""GUI-driven UI conversion: fake graphics, actual atlas CLI, safe callbacks.

No real Unity, original XAML, game installation, production package, or
profiles are read/written by these tests.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]

import ui_atlas
from suite_ui_atlas_preview import UiPreviewIndexError, read_ui_preview_index


@pytest.fixture
def sample(tmp_path, monkeypatch):
    project = tmp_path / "isolated-ui-project"
    for part in ("work", "profiles", "config", "assets/ui/derived", "sprites"):
        (project / part).mkdir(parents=True, exist_ok=True)
    texture = project / "globalgamemanagers.assets"
    texture.write_bytes(b"SYNTHETIC-UNITY-BUILD-DO-NOT-INSTALL")
    dictionary = project / "sprites" / "UI-MasterAtlas.xaml"
    dictionary.write_text(
        '<ResourceDictionary xmlns="http://schemas.microsoft.com/'
        'winfx/2006/xaml/presentation" '
        'xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml">'
        '<BitmapImage x:Key="Master" UriSource="UI-MasterAtlas.png"/>'
        '<CroppedBitmap x:Key="Button A" SourceRect="1,1,4,4"/>'
        '<CroppedBitmap x:Key="Button B" SourceRect="8,8,3,3"/>'
        '</ResourceDictionary>',
        encoding="utf-8",
    )
    pixels = Image.new("RGBA", (16, 16), (30, 40, 50, 255))
    original = pixels.tobytes()
    monkeypatch.setattr(ui_atlas, "PROJECT_ROOT", project)
    monkeypatch.setattr(
        ui_atlas, "_resolve_sources",
        lambda args: (project / "sprites", texture, "synthetic-SHCDE-build"),
    )
    monkeypatch.setattr(ui_atlas, "load_sheets",
                        lambda asset, wanted: {
                            "UI-MasterAtlas": pixels.copy()
                        })
    monkeypatch.setattr(ui_atlas, "UI_SHEET_DIMENSIONS",
                        {"UI-MasterAtlas.png": (16, 16)})
    (project / "profiles" / "synthetic.json").write_text(
        '{"name":"synthetic-only","authored_ui_atlases":[]}\n',
        encoding="utf-8",
    )
    return project, dictionary, texture, pixels, original


def _export(project):
    args = argparse.Namespace(out="work/ui", atlas=None, replace=False)
    assert ui_atlas.cmd_export(args) == 0
    return project / "work" / "ui"


def _check():
    return ui_atlas.cmd_check(
        argparse.Namespace(atlas=None, **{"from": "work/ui"})
    )


def _import(*, replace=False):
    return ui_atlas.cmd_import(argparse.Namespace(
        atlas=None, store="synthetic-ui", out="dist/ui-override",
        replace=replace, **{"from": "work/ui"}
    ))


def test_real_cli_roundtrip_crop_pixels_and_profile_manifest(sample):
    project, dictionary, texture, pixels, before = sample
    export = _export(project)
    preview = read_ui_preview_index(export)
    assert len(preview) == 2
    assert all(item["preview_only"] is True for item in preview)
    assert {item["key"] for item in preview} == {"Button A", "Button B"}
    assert all(item["path"].is_file() for item in preview)
    assert _check() == 0
    original_texture_hash = sha256(texture.read_bytes()).hexdigest()

    selected = next(item for item in preview if item["key"] == "Button A")
    edited = Image.new("RGBA", (4, 4), (220, 15, 30, 255))
    edited.save(selected["path"])
    assert _check() == 0
    assert _import() == 0
    target = project / "assets" / "ui" / "derived" / "synthetic-ui"
    converted = target / "UI-MasterAtlas.png"
    with Image.open(converted) as img:
        assert img.size == (16, 16)
        assert img.getpixel((1, 1)) == (220, 15, 30, 255)
        assert img.getpixel((9, 9)) == (30, 40, 50, 255)
    manifest = json.loads((target / "store-manifest.json").read_text(encoding="utf-8"))
    assert manifest["sheets"][0]["sha256"] == sha256(converted.read_bytes()).hexdigest()

    profile = project / "profiles" / "synthetic.json"
    assert ui_atlas.cmd_profile_add(argparse.Namespace(
        set="synthetic-ui", profile="profiles/synthetic.json",
        write=True, verdraengen=False
    )) == 0
    section = json.loads(profile.read_text(encoding="utf-8"))["authored_ui_atlases"][0]
    assert section["source"] == "assets/ui/derived/synthetic-ui/UI-MasterAtlas.png"
    assert section["expected_sha256"] == manifest["sheets"][0]["sha256"]
    assert sha256(texture.read_bytes()).hexdigest() == original_texture_hash
    assert pixels.tobytes() == before


def test_broken_crop_rejects_import_without_overwriting_prior_store(sample):
    project, dictionary, texture, pixels, before = sample
    export = _export(project)
    edited = export / "UI-MasterAtlas" / "Button A.png"
    Image.new("RGBA", (4, 4), (220, 20, 10, 255)).save(edited)
    assert _import() == 0
    store = project / "assets/ui/derived/synthetic-ui"
    prior = {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in store.iterdir()
    }
    # A misplaced rectangle would look plausible in the rebuilt atlas.
    # The converter must never resample/accept it silently.
    Image.new("RGBA", (5, 4), (200, 200, 200, 255)).save(edited)
    assert _check() == 1
    assert _import(replace=True) == 1
    assert {
        path.name: sha256(path.read_bytes()).hexdigest()
        for path in store.iterdir()
    } == prior
    assert pixels.tobytes() == before


@pytest.mark.parametrize("mutation", [
    lambda obj: obj["atlases"][0]["crops"][0].update(file="../../secret.png"),
    lambda obj: obj["atlases"][0].update(directory="../outside"),
    lambda obj: obj["atlases"][0]["crops"][0].update(width=99999),
    lambda obj: obj["atlases"][0]["crops"][0].update(
        file="Button B.png"
    ),
    lambda obj: obj["atlases"][0]["crops"][0].update(
        baseline_pixels_sha256="not-a-digest"
    ),
    lambda obj: obj.update(schema_version="untrusted"),
    lambda obj: obj["atlases"][0]["crops"].append(
        dict(obj["atlases"][0]["crops"][0])
    ),
])
def test_gui_preview_rejects_untrusted_or_inconsistent_index(
    sample, mutation
):
    project = sample[0]
    export = _export(project)
    path = export / "index.json"
    idx = json.loads(path.read_text(encoding="utf-8"))
    mutation(idx)
    original = json.dumps(idx, ensure_ascii=False).encode()
    path.write_bytes(original)
    with pytest.raises(UiPreviewIndexError):
        read_ui_preview_index(export)
    assert path.read_bytes() == original


def test_preview_rejects_link_outside_export(sample):
    project = sample[0]
    export = _export(project)
    path = export / "UI-MasterAtlas" / "Button A.png"
    external = project / "outside-secret.png"
    external.write_bytes(b"DO NOT READ")
    path.unlink()
    try:
        path.symlink_to(external)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"No privilege to create a symlink on Windows: {exc}")
    with pytest.raises(UiPreviewIndexError):
        read_ui_preview_index(export)
    assert external.read_bytes() == b"DO NOT READ"


def _suite_gui_module():
    loader = importlib.machinery.SourceFileLoader(
        "suite_gui_atlas_conversion_test", str(ROOT / "tools" / "suite.pyw")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


@pytest.fixture
def gui(sample, monkeypatch):
    import tkinter as tk
    import tkinter.ttk as ttk

    project = sample[0]
    module = _suite_gui_module()
    monkeypatch.setattr(module, "PROJECT_ROOT", project)
    monkeypatch.setattr(module, "TOOLS", ROOT / "tools")
    root = tk.Tk()
    root.geometry("1020x680+50+50")
    class FakeApp:
        def __init__(self):
            self.done_hooks = []
            self.runner = SimpleNamespace(busy=False)
            self.tasks = []
            self.messages = []
            self.accept = True
        def run(self, args, label):
            self.tasks.append((list(args), label))
            return self.accept
        def after(self, ms, callback):
            callback()
        def log(self, line, tag=""):
            self.messages.append((line, tag))
    app = FakeApp()
    tab = module.UiTab(root, app)
    tab.pack(fill="both", expand=True)
    root.update()
    try:
        yield root, tab, app, module
    finally:
        root.destroy()


def test_gui_export_completion_is_bound_to_its_own_job(
    gui, sample, monkeypatch
):
    root, tab, app, module = gui
    monkeypatch.setattr(module.messagebox, "askyesno",
                        lambda *args, **kwargs: True)
    # Only an actually accepted and successfully completed export may
    # refresh the selected folder and preview.
    tab.folder.delete(0, "end")
    tab.folder.insert(0, "previous-selected-folder")
    app.accept = False
    tab.export()
    assert app.done_hooks == []
    assert tab.folder.get() == "previous-selected-folder"

    app.accept = True
    tab.export()
    assert len(app.done_hooks) == 1
    app.done_hooks[0](17)
    assert app.done_hooks == []
    assert tab.folder.get() == "previous-selected-folder"

    _export(sample[0])
    tab.export()
    assert len(app.done_hooks) == 1
    app.done_hooks[0](0)
    assert app.done_hooks == []
    assert tab.folder.get() == "work/ui"
    assert len(tab._entries) == 2
    assert "Nicht freigegeben" in tab.preview_state.get()


def test_gui_store_stage_order_safe_name_and_profile_target(gui, monkeypatch):
    root, tab, app, module = gui
    root.update()
    assert (
        tab.stage_import_button.winfo_rootx()
        < tab.stage_profile_button.winfo_rootx()
        < tab.stage_preview_button.winfo_rootx()
    )
    assert (
        tab.stage_preview_button.winfo_rootx()
        + tab.stage_preview_button.winfo_width()
        <= tab.winfo_rootx() + tab.winfo_width()
    )
    warnings = []
    monkeypatch.setattr(module.messagebox, "showwarning",
                        lambda title, body, **kw: warnings.append((title, body)))
    monkeypatch.setattr(module.messagebox, "askyesno",
                        lambda *args, **kwargs: True)
    tab.store.delete(0, "end")
    tab.store.insert(0, "../../outside")
    before = len(app.tasks)
    tab.store_import()
    tab.profile_write()
    assert len(app.tasks) == before
    assert len(warnings) == 2

    tab.store.delete(0, "end")
    tab.store.insert(0, "synthetic-ui")
    tab.profile_show()
    assert app.tasks[-1][0][-2:] == [
        "--profile", "profiles/europe-production.json"
    ]
    tab.profile_write()
    assert app.tasks[-1][0][-3:] == [
        "--profile", "profiles/europe-production.json", "--write"
    ]


def test_gui_sh1_hud_export_button_uses_safe_runner_contract(
    gui, sample, monkeypatch
):
    """Button must not crash or trigger follow-on loading after a failed job."""
    root, tab, app, module = gui
    game_asset = sample[0] / "Stronghold 1 Definitive Edition_Data" / "globalgamemanagers.assets"
    game_asset.parent.mkdir(exist_ok=True)
    game_asset.write_bytes(b"synthetic path only; command is intercepted")
    monkeypatch.setattr(
        module.filedialog, "askopenfilename",
        lambda **kwargs: str(game_asset),
    )
    tab.sh1_hud_export()
    assert len(app.tasks) == 1
    args = app.tasks[0][0]
    assert args[0].endswith("ui_sh1_hud.py")
    assert args[1:3] == ["export", "--source"]
    assert args[3] == str(game_asset)
    assert len(app.done_hooks) == 1
    app.done_hooks[0](9)
    assert app.done_hooks == []
    assert tab.folder.get() == "work/ui"

    app.accept = False
    tab.sh1_hud_export()
    assert app.done_hooks == []
    assert tab.folder.get() == "work/ui"


def test_gui_sh1_hud_build_requires_explicit_replacement_consent(
    gui, sample, monkeypatch
):
    root, tab, app, module = gui
    tab._sh1_mode = True
    tab.folder.delete(0, "end")
    tab.folder.insert(0, "work/sh1-hud-editierbar")
    destination = sample[0] / "dist" / "sh1-hud-editierte-atlanten"
    destination.mkdir(parents=True)
    sentinel = destination / "existing.png"
    sentinel.write_bytes(b"keep old work")
    decisions = iter([True, False])
    monkeypatch.setattr(
        module.messagebox, "askyesno",
        lambda *args, **kwargs: next(decisions),
    )
    tab.sh1_hud_build()
    assert not app.tasks
    assert sentinel.read_bytes() == b"keep old work"
