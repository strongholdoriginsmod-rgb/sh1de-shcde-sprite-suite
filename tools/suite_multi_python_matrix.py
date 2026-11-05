"""Read-only multi-Python 3.13/3.14/3.15 compatibility and ABI matrix.

Each interpreter runs an isolated subprocess; no package installation, no
PATH edits and no global Python modifications. A missing dependency is
reported as missing, never claimed compatible.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

PROBE=r"""
import importlib.metadata as md
import importlib.util
import json
import platform
import struct
import sys
rows={"python":sys.version.split()[0],"implementation":platform.python_implementation(),
      "architecture":platform.machine(),"bits":8*struct.calcsize("P"),
      "tcl_tk":None,"packages":{}}
try:
 import tkinter
 rows["tcl_tk"]={"tcl":str(tkinter.TclVersion),"tk":str(tkinter.TkVersion)}
except (ImportError,RuntimeError,OSError) as exc:
 rows["tcl_tk"]={"error":type(exc).__name__+": "+str(exc)[:140]}
for name in ("PySide6","Pillow","UnityPy","numpy","scipy","pytest"):
 try:rows["packages"][name]={"installed":True,"version":md.version(name)}
 except md.PackageNotFoundError:
  rows["packages"][name]={"installed":False}
try:
 import importlib.util
 rows["tkinter_importable"]=bool(importlib.util.find_spec("tkinter"))
except (ImportError,ValueError):
 rows["tkinter_importable"]=False
print(json.dumps(rows))
"""

QT_PROBE=("import os;os.environ['QT_QPA_PLATFORM']='offscreen';"
          "from PySide6.QtWidgets import QApplication;"
          "app=QApplication([]);print('QT_PROBE_OK',app.platformName());app.quit()")


def inspect(executable:Path,*,timeout:float=30.0)->dict[str,Any]:
    path=Path(executable)
    if not path.is_file() or path.is_symlink():
        return {"executable":str(path),"status":"missing"}
    try:
        probe=subprocess.run([str(path),"-c",PROBE],check=False,
               capture_output=True,text=True,encoding="utf-8",errors="replace",
               stdin=subprocess.DEVNULL,timeout=timeout,
               env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1"))
    except (OSError,subprocess.TimeoutExpired) as error:
        return {"executable":str(path),"status":"unavailable","error":str(error)}
    if probe.returncode or not probe.stdout.strip():
        return {"executable":str(path),"status":"failed_to_probe",
                "rc":probe.returncode,"stderr":probe.stderr[-700:]}
    try:
        data=json.loads(probe.stdout.strip().splitlines()[-1])
    except (ValueError,IndexError) as exc:
        return {"executable":str(path),"status":"invalid_probe_output",
                "error":str(exc),"stdout":probe.stdout[-700:]}
    data["executable"]=str(path)
    major_minor=tuple(int(part) for part in data["python"].split(".")[:2])
    valid=(major_minor in ((3,13),(3,14),(3,15))
           and data["implementation"]=="CPython" and data["bits"]==64)
    data["source_version_supported"]=valid
    packages=data["packages"]
    data["qt_widget_probe"]=None
    if packages["PySide6"]["installed"]:
        try:
            qt=subprocess.run([str(path),"-c",QT_PROBE],check=False,
                   capture_output=True,text=True,encoding="utf-8",errors="replace",
                   stdin=subprocess.DEVNULL,timeout=timeout,
                   env=dict(os.environ,QT_QPA_PLATFORM="offscreen",
                            PYTHONDONTWRITEBYTECODE="1"))
            data["qt_widget_probe"]={
                "success":qt.returncode==0 and "QT_PROBE_OK" in qt.stdout,
                "stdout":qt.stdout[-200:],"stderr":qt.stderr[-200:],
                "rc":qt.returncode}
        except (OSError,subprocess.TimeoutExpired) as error:
            data["qt_widget_probe"]={"success":False,"error":str(error)}
    all_packages=all(packages[p]["installed"]
       for p in ("PySide6","Pillow","UnityPy","numpy","scipy"))
    data["full_gui_dependency_set_present"]=all_packages
    data["full_gui_runtime_verified"]=bool(
        valid and all_packages and data["qt_widget_probe"]
        and data["qt_widget_probe"].get("success")
        and data["tcl_tk"] and "error" not in data["tcl_tk"])
    data["status"]=("gui_runtime_probe_ready" if data["full_gui_runtime_verified"]
                else "source_only" if valid else "unsupported")
    return data


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python",action="append",required=True,type=Path,
                        help="Windows CPython executable (repeatable)")
    parser.add_argument("--json-out",type=Path)
    opts=parser.parse_args(argv)
    report={"schema":"sprite-suite.multi-python-compatibility.v1",
            "tests":[inspect(path) for path in opts.python],
            "no_packages_installed":True,"no_game_files_modified":True}
    if opts.json_out:
        if opts.json_out.exists() or opts.json_out.is_symlink():
            parser.error("Output already exists; refuse overwrite")
        opts.json_out.parent.mkdir(parents=True,exist_ok=True)
        opts.json_out.write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",
                                encoding="utf-8")
    print(json.dumps(report,indent=2,ensure_ascii=False))
    return 0 if all(t.get("source_version_supported",False)
                    for t in report["tests"]) else 2


if __name__=="__main__":
    raise SystemExit(main())
