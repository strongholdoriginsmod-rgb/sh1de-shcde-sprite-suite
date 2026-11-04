"""Compact, portable HUD baseline files while preserving legacy 64-hex names.

These tests use only temporary project trees, never an installed game.
"""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
import sys
from zipfile import ZipFile

from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "src")]

import hud_menu_workspace as hud
import hud_menu_project_transfer as transfer


def _png(color: tuple[int, int, int, int]) -> bytes:
    memory = BytesIO()
    Image.new("RGBA", (48, 32), color).save(memory, format="PNG")
    return memory.getvalue()


def test_compact_baseline_and_revision_survive_editable_project_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "First Suite Installation"
    work = first / "work"
    work.mkdir(parents=True)
    monkeypatch.setattr(hud, "ROOT", first)
    monkeypatch.setattr(hud, "WORK", work)
    monkeypatch.setattr(hud, "DEFAULT", work / "hud-menu-werkstatt")

    project = work / "my-project"
    source = tmp_path / "emblem.png"
    original = _png((20, 60, 130, 255))
    source.write_bytes(original)
    imported = hud.import_image(source, project=project)
    relative = imported.relative_to(project).as_posix()
    baseline, record = hud._baseline(project, relative)
    assert re.fullmatch(r"[0-9a-f]{32}\.png", baseline.name)
    assert re.fullmatch(r"[0-9a-f]{32}\.json", record.name)
    assert baseline.read_bytes() == original
    assert hud.list_assets(project)[0].status == "Unverändert"

    edited = _png((220, 45, 15, 240))
    hud.write_png(relative, edited, project=project,
                  expected_sha256=sha256(imported.read_bytes()).hexdigest())
    assert hud.list_assets(project)[0].status == "Bearbeitet"
    hud.restore_image(relative, project=project)
    assert imported.read_bytes() == original
    history = list((hud._metadata_dir(project) / "revisions").glob("*.png"))
    assert len(history) == 1
    assert re.fullmatch(r"[0-9a-f]{32}-[0-9a-f]{16}\.png", history[0].name)
    assert history[0].read_bytes() == edited

    archive = tmp_path / "editable.zip"
    backup = transfer.create_archive(project, archive)
    assert backup["files"] >= 4
    with ZipFile(archive) as reader:
        paths = reader.namelist()
        assert "metadata/import-baselines/" + baseline.name in paths
        assert "metadata/import-baselines/" + record.name in paths
        assert "metadata/revisions/" + history[0].name in paths

    second = tmp_path / "Relocated Second Suite"
    second_work = second / "work"
    second_work.mkdir(parents=True)
    monkeypatch.setattr(hud, "ROOT", second)
    monkeypatch.setattr(hud, "WORK", second_work)
    monkeypatch.setattr(hud, "DEFAULT", second_work / "hud-menu-werkstatt")
    restored = transfer.restore_archive(archive, project_name="ReopenedProject")
    moved = Path(restored["project"])
    assert hud.list_assets(moved)[0].status == "Unverändert"
    assert hud._baseline(moved, relative)[0].read_bytes() == original
    assert list((hud._metadata_dir(moved) / "revisions").glob("*.png"))[0].read_bytes() == edited
    assert source.read_bytes() == original


def test_existing_full_sha_baseline_is_read_without_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Use a short synthetic metadata root so the old full name remains
    # accessible even on Windows without the long-path policy.
    folder = tmp_path / "old-baselines"
    relative = "Override/Assets/GUI/Images/Shield.png"
    token = sha256(relative.encode("utf8")).hexdigest()
    location = folder / "import-baselines"
    location.mkdir(parents=True)
    legacy = location / (token + ".png")
    meta = location / (token + ".json")
    legacy.write_bytes(_png((4, 5, 6, 255)))
    meta.write_text('{"resource":"legacy"}', encoding="utf8")
    monkeypatch.setattr(hud, "_metadata_dir", lambda _: folder)

    assert hud._baseline(Path("unused"), relative) == (legacy, meta)
    assert legacy.is_file() and meta.is_file()


@pytest.mark.parametrize("length", [31, 33, 48, 63])
def test_archive_rejects_ambiguous_metadata_hash_lengths(length: int) -> None:
    for section, suffix in (("import-baselines", ".png"),
                            ("revisions", "-" + "b" * 16 + ".png")):
        with pytest.raises(hud.WorkshopError):
            transfer._safe_member(
                "metadata/" + section + "/" + "a" * length + suffix
            )
