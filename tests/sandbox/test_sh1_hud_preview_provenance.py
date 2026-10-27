"""Preview-mode provenance: SH1 and Crusader indexes must not be confused."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_sh1_hud_roundtrip import sh1, _export
from suite_ui_atlas_preview import (
    UiPreviewIndexError, read_ui_preview_index, validate_sh1_hud_preview,
)


def test_sh1_preview_matches_source_manifest_and_three_atlases(sh1):
    export, _ = _export(sh1)
    entries = read_ui_preview_index(export)
    assert len(entries) == 6
    validate_sh1_hud_preview(export, entries)

    metadata_path = export / "sh1_hud_source.json"
    original = metadata_path.read_bytes()
    metadata = json.loads(original)
    metadata["source_globalgamemanagers_sha256"] = "0" * 64
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(UiPreviewIndexError, match="widersprüchlich"):
        validate_sh1_hud_preview(export, entries)

    metadata_path.write_bytes(original)
    index_path = export / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["atlases"][1]["directory"] = "UI-MasterAtlas"
    index_path.write_text(json.dumps(index), encoding="utf-8")
    with pytest.raises(UiPreviewIndexError):
        read_ui_preview_index(export)


def test_sh1_gui_mode_refuses_build_id_without_source_provenance(
    sh1, monkeypatch
):
    import importlib.machinery
    import importlib.util
    import tkinter as tk
    from types import SimpleNamespace

    export, _ = _export(sh1)
    root = Path(__file__).resolve().parents[2]
    loader = importlib.machinery.SourceFileLoader(
        "sh1_gui_provenance_check", str(root / "tools" / "suite.pyw")
    )
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT_ROOT", sh1[0])

    tk_root = tk.Tk()
    tk_root.geometry("1020x680+20+20")
    class DummyApp:
        def __init__(self):
            self.runner = SimpleNamespace(busy=False)
            self.done_hooks = []
        def run(self, *_):
            raise AssertionError("Read-only preview must not run a converter")

    panel = module.UiTab(tk_root, DummyApp())
    panel.pack(fill="both", expand=True)
    try:
        tk_root.update()
        panel.workflow_tabs.select(panel.sh1_controls)
        panel._workflow_changed()
        tk_root.update()
        assert panel._sh1_mode
        assert len(panel._entries) == 6
        assert "Stronghold 1 DE" in panel.preview_state.get()
        assert panel.preview_import_button.instate(["disabled"])
        assert not panel.stage_import_button.winfo_ismapped()
        assert "work/sh1-hud-editierbar" in panel.folder.get()

        panel.workflow_tabs.select(panel.crusader_controls)
        panel._workflow_changed()
        tk_root.update()
        assert not panel._sh1_mode
        assert panel.folder.get() == "work/ui"
        assert panel.preview_import_button.instate(["!disabled"])
        assert panel.stage_import_button.winfo_ismapped()
        assert not panel._entries

        panel.workflow_tabs.select(panel.sh1_controls)
        panel._workflow_changed()
        tk_root.update()
        assert panel._sh1_mode
        assert len(panel._entries) == 6
        (export / "sh1_hud_source.json").unlink()
        panel.load_export()
        assert not panel._sh1_mode
        assert not panel._entries
        assert "Herkunft" in panel.preview_state.get()
    finally:
        tk_root.destroy()
