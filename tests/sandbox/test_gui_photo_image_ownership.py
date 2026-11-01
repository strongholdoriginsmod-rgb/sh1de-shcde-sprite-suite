"""Tk PhotoImage creation must always use a live, explicit owner widget.

A single TestSuite process creates and destroys many Tk roots. Relying on
Tkinter's process-global default root can silently associate image handles
with an already closed interpreter, causing the entire GUI to fail late.
"""
from __future__ import annotations

import ast
from pathlib import Path
import pytest

ROOT=Path(__file__).resolve().parents[2]
MODULES=(
    "tools/suite_universal.pyw",
    "tools/suite.pyw",
    "tools/suite_hud_menu_editor.py",
    "tools/suite_hud_menu_layout_editor.py",
    "tools/sandkasten.py",
    "tools/pivot_review_gui.py",
    "tools/suite_sh1_hud_editor.py",
    "tools/ui_sh1_to_shcde_gui.py",
)


@pytest.mark.parametrize("relative",MODULES)
def test_every_image_tk_photo_image_uses_explicit_widget_owner(relative):
    filename=ROOT/relative
    syntax=ast.parse(filename.read_text(encoding="utf8"),filename=str(filename))
    found=[]
    unowned=[]
    for node in ast.walk(syntax):
        if not isinstance(node,ast.Call):
            continue
        if (not isinstance(node.func,ast.Attribute)
                or node.func.attr!="PhotoImage"
                or not isinstance(node.func.value,ast.Name)
                or node.func.value.id!="ImageTk"):
            continue
        found.append(node.lineno)
        if not any(k.arg=="master" for k in node.keywords):
            unowned.append(node.lineno)
    assert found, f"No ImageTk.PhotoImage calls detected in {relative}"
    assert unowned==[], f"Missing master in {relative}: {unowned}"


def test_window_image_owner_remains_valid_after_fake_default_root_is_destroyed(
    tmp_path,
):
    """A fake dead default root must not be needed by the explicit canvas."""
    import tkinter as tk
    from PIL import Image,ImageTk
    app=tk.Tk()
    app.withdraw()
    old_default=tk._default_root
    try:
        canvas=tk.Canvas(app)
        canvas.pack()
        tk._default_root=object()  # Represents stale global default root.
        image=Image.new("RGBA",(24,24),(240,90,100,255))
        photo=ImageTk.PhotoImage(image,master=canvas)
        canvas.create_image(0,0,image=photo,anchor="nw")
        assert photo.width()==24 and photo.height()==24
        assert canvas.tk is app.tk
    finally:
        tk._default_root=old_default
        app.destroy()
