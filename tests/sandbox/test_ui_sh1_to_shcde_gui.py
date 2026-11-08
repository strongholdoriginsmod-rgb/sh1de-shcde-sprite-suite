"""Native direct SH1 transfer; synthetic exports, no game or approval dialogs."""
from pathlib import Path
import time

from PIL import Image
import pytest

from test_ui_sh1_to_shcde_bridge import projects, create_plan
import ui_sh1_to_shcde_bridge as core
from ui_sh1_to_shcde_gui import CrossGameHudBridge


def settle(window):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        window.update()
        if not window._busy:
            return
        time.sleep(.01)
    pytest.fail("SH1 transfer did not finish: " + window.status.get())


@pytest.fixture
def view(projects):
    plan, _ = create_plan(projects)
    window = CrossGameHudBridge()
    window.geometry("950x630+20+20")
    window.vars["plan"].set(str(plan))
    window.vars["output"].set(str(projects[2] / "work" / "direct-output"))
    assert window.open_plan()
    settle(window)
    yield window
    settle(window)
    window.close()


def test_multi_selection_transfers_without_reason_approval_or_game_paths(view, projects):
    source, target, scratch = projects
    originals = {path: path.read_bytes() for root in (source, target) for path in root.rglob("*") if path.is_file()}
    assert str(view.tree.cget("selectmode")) == "extended"
    assert "state_note" not in view.vars and not view.check_originals.get()
    assert all(not view.vars[key].get() for key in ("source_game", "target_game", "target_xaml"))
    view.select_visible()
    view.vars["fit"].set("contain")
    assert len(view.tree.selection()) == 2
    assert view.apply()
    settle(view)
    assert "2 Bilder" in view.status.get()
    output = scratch / "work" / "direct-output"
    report = core.verify_candidate(output)
    assert report["transferred_crops"] == 2
    assert all(path.read_bytes() == blob for path, blob in originals.items())
    assert (output / "index.json").read_bytes() == (target / "index.json").read_bytes()


def test_free_source_and_target_keys_are_native_combo_choices(view, projects):
    assert "Candle01" in view.source_picker.cget("values")
    assert "CrusaderOnly" in view.target_picker.cget("values")
    view.vars["source_key"].set("Candle01")
    view.vars["target_key"].set("CrusaderOnly")
    view.vars["fit"].set("stretch")
    assert view.add_mapping()
    settle(view)
    matching = [key for key in view.tree.get_children() if view._mapping[int(key)]["target_key"] == "CrusaderOnly"]
    assert len(matching) == 1
    view.tree.selection_set(matching)
    assert view.apply()
    settle(view)
    assert "1 Bilder" in view.status.get()
    output = projects[2] / "work" / "direct-output"
    assert core.verify_candidate(output)["transferred_crops"] == 1
    with Image.open(output / "UI-TrailAtlas" / "CrusaderOnly.png") as image:
        assert image.size == (4, 4)


def test_exact_size_mismatch_is_technical_and_publishes_no_output(view, projects):
    item = next(key for key in view.tree.get_children() if view._mapping[int(key)]["source_size"] != view._mapping[int(key)]["target_size"])
    view.tree.selection_set(item)
    view.vars["fit"].set("exact")
    assert view.apply()
    settle(view)
    assert "Größen" in view.status.get() or "Pixelmaße" in view.status.get()
    assert not (projects[2] / "work" / "direct-output").exists()


@pytest.mark.parametrize("scaling", [1.25, 1.5])
def test_small_scaled_window_reaches_last_field_action_and_long_status(view, scaling):
    old_scale = view.tk.call("tk", "scaling")
    view.tk.call("tk", "scaling", 96 / 72 * scaling)
    try:
        view.geometry("780x460+20+20")
        view.status.set("Long source diagnostic " * 100 + " FINAL_DETAIL")
        view.update()
        view.status_view.see("end-1c")
        view.update()
        assert view.status_view.dlineinfo("end-1c") is not None
        assert view.status_view.yview()[0] > 0
        assert view.area.canvas.winfo_height() > 150
        last = next(control for control in view._controls if getattr(control, "cget", None)
                    and control.winfo_class() == "TEntry" and str(control.cget("textvariable")) == str(view.vars["target_xaml"]))
        for control in (last, view.transfer_button):
            view.area.reveal(control)
            view.update()
            assert control.winfo_rooty() >= view.area.canvas.winfo_rooty()
            assert control.winfo_rooty() + control.winfo_height() <= view.area.canvas.winfo_rooty() + view.area.canvas.winfo_height()
    finally:
        view.tk.call("tk", "scaling", old_scale)
