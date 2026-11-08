"""Navigation-only bridge to shared geometry, AI and damage inspector."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("editor_bruecke_nav", ROOT / "tools" / "editor_bruecke.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_open_geometry_deep_link_does_not_modify_files(tmp_path, monkeypatch):
    html = tmp_path / "Stronghold_Sprite_Editor.html"
    html.write_text("<title>fake fixture</title>", encoding="utf-8")
    monkeypatch.setattr(module, "EDITOR_HTML", html)
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", opened.append)
    assert module.cmd_oeffnen(SimpleNamespace(sprache="de", bereich="geometry", offline=True)) == 0
    assert opened == [html.as_uri() + "#geometry"]
    assert html.read_text(encoding="utf-8") == "<title>fake fixture</title>"


def test_ai_shortcut_english_and_invalid_route_fail_closed(tmp_path, monkeypatch):
    html = tmp_path / "Stronghold_Sprite_Editor.html"
    english = html.with_name("Stronghold_Sprite_Editor_EN.html")
    html.write_text("DE", encoding="utf-8")
    english.write_text("EN", encoding="utf-8")
    monkeypatch.setattr(module, "EDITOR_HTML", html)
    monkeypatch.delenv("SEDE_SPRACHE", raising=False)
    opened = []
    monkeypatch.setattr(module.webbrowser, "open", opened.append)
    assert module.cmd_oeffnen(SimpleNamespace(sprache="en", bereich="ai", offline=True)) == 0
    assert opened == [english.as_uri() + "#ai"]
    import pytest
    with pytest.raises(ValueError, match="Unbekannter Editorbereich"):
        module.cmd_oeffnen(SimpleNamespace(sprache="de", bereich="install"))
    assert len(opened) == 1


def test_legacy_bridge_api_keeps_default_without_fragment(tmp_path, monkeypatch):
    html = tmp_path / "Stronghold_Sprite_Editor.html"
    html.write_text("legacy")
    monkeypatch.setattr(module, "EDITOR_HTML", html)
    monkeypatch.delenv("SEDE_SPRACHE", raising=False)
    urls = []
    monkeypatch.setattr(module.webbrowser, "open", urls.append)
    assert module.cmd_oeffnen(SimpleNamespace(sprache="de", offline=True)) == 0
    assert urls == [html.as_uri()]
