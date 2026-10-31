"""Synthetic performance budgets and repeatability; no real games involved."""
from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path
import tkinter as tk

import pytest
from PIL import Image

from suite_benchmarks import measure, main

ROOT=Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("side",[16,256,1024,2048,4096])
def test_synthetic_preview_never_exceeds_memory_budget(side):
    report=measure(side=side,repeats=1)
    assert report["source_pixels"]==side*side
    assert report["display_pixels"]<=4_004_096
    assert report["render_milliseconds"][0]>=0


def test_benchmark_does_not_overwrite_a_user_report(tmp_path):
    out=tmp_path/"report.json"
    assert main(["--sides","64","--repeats","2","--output",str(out)])==0
    before=out.read_bytes()
    with pytest.raises(FileExistsError):
        main(["--sides","64","--repeats","2","--output",str(out)])
    assert out.read_bytes()==before


def test_tk_preview_survives_repeated_open_zoom_clear_close(tmp_path):
    loader=importlib.machinery.SourceFileLoader("suite_preview_stress",str(ROOT/"tools"/"suite.pyw"))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    source=tmp_path/"thumbnail.png"
    Image.new("RGBA",(96,96),(70,90,130,110)).save(source)
    root=tk.Tk()
    root.withdraw()
    try:
        for _ in range(20):
            preview=module.ImagePreview(root)
            preview.pack()
            preview.show(source)
            preview.zoom.set("400 %")
            preview.redraw(force=True)
            assert len(preview.canvas.find_all())==1
            preview.clear()
            preview.destroy()
        root.update_idletasks()
    finally:
        root.destroy()
