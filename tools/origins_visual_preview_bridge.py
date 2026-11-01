"""Project editable Noesis source layout on the Tk authoring stage.

Purely visual preview adapter. Original XML controls/bindings are not replaced
by rectangles; editing, roundtrip and patch export use VisualXamlDocument.
"""
from __future__ import annotations
from pathlib import Path
from math import cos, sin, radians, isfinite
from PIL import Image, ImageTk
from origins_visual_geometry import projected_geometry, screen_size

DRAW_LABELS={"Button","TextBlock","Label","TextBox","CheckBox","RadioButton",
             "ComboBox","TabItem","Slider","ProgressBar"}


def _rotate_preview(element,x,y,w,h):
    """Approximate XAML RotateTransform; preserve the actual XML untouched."""
    from origins_visual_document import _local
    property_node=next((c for c in element if isinstance(c.tag,str)
         and _local(c.tag).endswith(".RenderTransform")),None)
    if property_node is None:return None
    rot=next((c for c in property_node.iter() if isinstance(c.tag,str)
              and _local(c.tag)=="RotateTransform"),None)
    if rot is None:return None
    try:
        angle=float(rot.get("Angle","0"))
        if not isfinite(angle):return None
    except ValueError:return None
    if abs(angle)%360<0.01:return None
    center_x=x+w*.5;center_y=y+h*.5
    try:
        pivot=[float(v) for v in element.get("RenderTransformOrigin","0.5,0.5").split(",")]
        if len(pivot)==2:
            center_x=x+w*pivot[0];center_y=y+h*pivot[1]
    except ValueError:pass
    a=radians(angle);ca=cos(a);sa=sin(a)
    points=[]
    for sx,sy in ((x,y),(x+w,y),(x+w,y+h),(x,y+h)):
        dx=sx-center_x;dy=sy-center_y
        points.extend([center_x+dx*ca-dy*sa,center_y+dx*sa+dy*ca])
    return points


def draw_original_layout(view):
    doc=view.doc
    canvas=view.canvas
    canvas.delete("all")
    view._boxes={}
    view._image_refs=[]
    if doc is None:return
    vw,vh,scale=view._preview_scale()
    view._world_scale=scale
    offset=13.
    canvas.create_rectangle(offset,offset,offset+vw*scale,offset+vh*scale,
                            fill="#182437",outline="#6d879e",width=2)
    reference=getattr(view,"reference_image_path",None)
    if reference is not None:
        try:
            with Image.open(reference) as picture:
                if picture.width*picture.height<=30_000_000:
                    scaled=picture.convert("RGB").resize((max(1,int(vw*scale)),
                        max(1,int(vh*scale))),Image.Resampling.LANCZOS)
                    image=ImageTk.PhotoImage(scaled,master=view)
                    view._image_refs.append(image)
                    canvas.create_image(offset,offset,image=image,anchor="nw")
        except (OSError,ValueError):pass
    geometry=projected_geometry(doc,width=vw,height=vh,include_hidden=True)
    by_path={g.path:g for g in geometry}
    scope=view._selected_scope()
    focused=by_path.get(scope) if scope else None
    if focused:
        geometry=[g for g in geometry if g.path[:len(scope)]==scope]
        origin_x=focused.x;origin_y=focused.y
    else:origin_x=0.;origin_y=0.
    # The scope viewport is still mapped into the user-selected screen size.
    canvas.configure(scrollregion=(0,0,vw*scale+45,vh*scale+45))
    for g in geometry:
        if g.path==():continue
        x=offset+(g.x-origin_x)*scale
        y=offset+(g.y-origin_y)*scale
        w=max(2.,g.w*scale);h=max(2.,g.h*scale)
        if x+w<-200 or y+h<-200 or x>vw*scale+300 or y>vh*scale+300:
            continue
        element=doc._target(g.path)
        view._boxes[g.path]=(x,y,w,h)
        hidden=g.hidden
        stroke="#4f5c73" if hidden else ("#6b84a2" if g.container else "#8da9c3")
        color=view._resolve_image(element.get("Source","")) if g.tag=="Image" else None
        if color is not None and len(view._image_refs)<100:
            try:
                if color.stat().st_size>96*1024**2:raise ValueError()
                with Image.open(color) as source:
                    if source.width*source.height>32_000_000:raise ValueError()
                    image=source.convert("RGBA")
                    image.thumbnail((max(1,min(2048,int(w))),
                                     max(1,min(2048,int(h)))),
                                    Image.Resampling.LANCZOS)
                photo=ImageTk.PhotoImage(image,master=view)
                view._image_refs.append(photo)
                canvas.create_image(x,y,image=photo,anchor="nw",
                                    tags=(view._path_id(g.path) if hasattr(view,"_path_id") else
                                          ("root" if not g.path else "p"+"_".join(map(str,g.path))),))
            except (OSError,ValueError):
                pass
        if g.tag=="Ellipse":
            canvas.create_oval(x,y,x+w,y+h,outline=stroke,
                fill=view._color(element.get("Background",""),"#304157")
                if hasattr(view,"_color") else "",width=1)
        else:
            from suite_origins_visual_editor import _color,_path_id
            fill=_color(element.get("Background",""),
                        "#304258" if g.tag in {"Button","Border","TextBox"} else
                        "" if g.container else "#24364b")
            polygon=_rotate_preview(element,x,y,w,h)
            if polygon is not None:
                canvas.create_polygon(*polygon,outline=stroke,
                    fill=fill if g.tag not in {"Image","TextBlock"} else "",
                    width=1,tags=(_path_id(g.path),))
            else:
                canvas.create_rectangle(x,y,x+w,y+h,outline=stroke,
                    fill=fill if g.tag not in {"Image","TextBlock"} else "",
                    width=1,dash=(4,4) if hidden else (),tags=(_path_id(g.path),))
        label=(element.get("Content") or element.get("Text") or
               element.get("{clr-namespace:CrusaderDE}PropEx.TextCentre") or
               element.get("Name") or g.name)
        if (g.tag in DRAW_LABELS and isinstance(label,str) and label and
                w>27 and h>16):
            from suite_origins_visual_editor import _path_id
            canvas.create_text(x+w/2,y+h/2,anchor="center",text=label[:110],
                width=max(10,int(w-8)),fill="#e8eff9",
                font=("Segoe UI",max(7,min(18,int(scale*30)))),
                tags=(_path_id(g.path),))
    if view.selected in view._boxes:
        x,y,w,h=view._boxes[view.selected]
        canvas.create_rectangle(x,y,x+w,y+h,outline="#ffcc66",width=3,
                                dash=(5,3))
        canvas.create_rectangle(x+w-6,y+h-6,x+w+6,y+h+6,
                                fill="#ffec9c",outline="#182437",tags=("handle",))
    canvas.create_text(19,19,anchor="nw",
        text="Original-XAML – Layoutprojektion, Styles/Animationen nur angenähert",
        font=("Segoe UI",9),fill="#b0c8de")
