"""Geometry and scoped input regression for overflowing existing workspaces."""
import tkinter as tk
from tkinter import ttk

from suite_workarea import ScrollableWorkarea
from suite_tcl_runtime import create_tk_root


def test_workarea_focus_and_shift_wheel_reach_overflow_without_global_bindings():
    root = create_tk_root()
    try:
        root.geometry("500x300+20+20")
        before = root.bind_all("<MouseWheel>")
        area = ScrollableWorkarea(root, min_width=1000, min_height=900)
        area.pack(fill="both",expand=True)
        last = ttk.Entry(area.body)
        last.place(x=790,y=780,width=150,height=30)
        root.update()
        area.reveal(last)
        root.update()
        assert area.canvas.xview()[0] > 0
        assert area.canvas.yview()[0] > 0
        assert last.winfo_rootx() >= area.canvas.winfo_rootx()
        assert last.winfo_rooty() + last.winfo_height() <= area.canvas.winfo_rooty() + area.canvas.winfo_height() + 1
        area.canvas.xview_moveto(0)
        area.canvas.event_generate("<Shift-MouseWheel>",delta=-120)
        root.update()
        assert area.canvas.xview()[0] > 0
        assert root.bind_all("<MouseWheel>") == before
    finally:
        root.destroy()


def test_notebook_is_constructed_inside_canvas_for_native_clipping():
    root = create_tk_root()
    try:
        root.geometry("500x300+20+20")
        area = ScrollableWorkarea(root)
        area.pack(fill="both", expand=True)
        notebook = ttk.Notebook(area.canvas)
        area.set_content(notebook)
        page = ttk.Frame(notebook, width=900, height=900)
        notebook.add(page, text="Tall page")
        root.update()
        assert notebook.master is area.canvas
        assert notebook.winfo_ismapped()
        assert area.canvas.yview()[1] < 1
        notebook.select(page)
        area.canvas.yview_moveto(1)
        root.update()
        assert area.canvas.yview()[0] > 0
    finally:
        root.destroy()


def test_toplevel_wheel_routes_to_pointer_workarea_and_cleans_its_bindings():
    root = create_tk_root()
    try:
        root.geometry("500x300+20+20")
        original = root.bind("<MouseWheel>")
        global_original = root.bind_all("<MouseWheel>")
        area = ScrollableWorkarea(root,min_width=1000,min_height=900)
        area.pack(fill="both",expand=True)
        label = ttk.Label(area.body,text="Pointer destination")
        label.pack(anchor="nw")
        root.update()
        area.ybar.focus_set()
        x,y = label.winfo_rootx()+5,label.winfo_rooty()+5
        root.event_generate("<MouseWheel>",delta=-120,rootx=x,rooty=y)
        root.update()
        assert area.canvas.yview()[0] > 0
        root.event_generate("<Shift-MouseWheel>",delta=-120,
            rootx=area.canvas.winfo_rootx()+10,rooty=area.canvas.winfo_rooty()+30)
        root.update()
        assert area.canvas.xview()[0] > 0
        assert root.bind_all("<MouseWheel>") == global_original
        area.destroy()
        assert root.bind("<MouseWheel>") == original
    finally:
        root.destroy()


def test_toplevel_wheel_gives_native_text_scrolling_priority():
    root = create_tk_root()
    try:
        root.geometry("500x300+20+20")
        area = ScrollableWorkarea(root,min_height=900)
        area.pack(fill="both",expand=True)
        text = tk.Text(area.body,height=3)
        text.pack()
        text.insert("1.0","many lines\n"*50)
        root.update()
        root.event_generate("<MouseWheel>",delta=-120,
            rootx=text.winfo_rootx()+10,rooty=text.winfo_rooty()+10)
        root.update()
        assert text.yview()[0] > 0
        assert area.canvas.yview()[0] == 0
    finally:
        root.destroy()
