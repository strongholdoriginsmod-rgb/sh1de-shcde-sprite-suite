"""Best-effort geometric preview of a REAL, editable Noesis XAML document.

The proprietary game renderer is not used: Styles, animations, bindings and
responsive layout cannot be shown pixel-exactly. The XML edit itself is exact.
"""
from __future__ import annotations
from dataclasses import dataclass
import math

from origins_visual_document import VisualXamlDocument, _element_children, _local, _thickness, XNS

VISIBLE={"Grid","Canvas","Border","DockPanel","StackPanel","WrapPanel",
 "Viewbox","Image","Button","TextBlock","TextBox","CheckBox","RadioButton",
 "Label","Rectangle","Ellipse","ContentControl","UserControl","Page","Window",
 "ScrollViewer","ListBox","ListView","UniformGrid","ProgressBar"}
CONTAINERS={"Grid","Canvas","Border","DockPanel","StackPanel","WrapPanel",
 "Viewbox","ContentControl","ScrollViewer","UserControl","Window","Page","UniformGrid"}
HINTS={"Button":(250,70),"TextBlock":(300,44),"Label":(240,44),
 "CheckBox":(250,38),"RadioButton":(250,38),"Image":(300,160),
 "Rectangle":(200,100),"Ellipse":(100,100),"TextBox":(300,42),
 "ListBox":(280,240),"ProgressBar":(300,36)}

@dataclass(frozen=True)
class Geometry:
    path:tuple[int,...]
    tag:str
    name:str
    x:float
    y:float
    w:float
    h:float
    depth:int
    hidden:bool
    z:int
    container:bool

def _float(value,default=0.):
    try:
        v=float(str(value))
        return v if math.isfinite(v) and -1e6<v<1e6 else default
    except (TypeError,ValueError):
        return default

def _size(node,name,default):
    value=node.get(name)
    return max(1.,_float(value,default)) if value not in (None,"Auto","NaN") else default

def _grid_segments(node,axis,available):
    group="Grid."+axis+"Definitions"
    child="RowDefinition" if axis=="Row" else "ColumnDefinition"
    field="Height" if axis=="Row" else "Width"
    entries=next(([c.get(field,"*") for c in _element_children(n)
                   if _local(c.tag)==child] for n in _element_children(node)
                   if _local(n.tag)==group),[])
    if not entries:return [available]
    fixed=0.;weighted=0.; measures=[]
    for val in entries:
        if val=="Auto":measures.append(("fixed",70.));fixed+=70.
        elif val.endswith("*"):
            weight=max(.01,_float(val[:-1],1.) if val[:-1] else 1.)
            weighted+=weight;measures.append(("star",weight))
        else:
            number=max(0.,_float(val))
            fixed+=number;measures.append(("fixed",number))
    return [(max(0.,available-fixed)*v/weighted if k=="star" else v)
            for k,v in measures]

def screen_size(doc:VisualXamlDocument)->tuple[float,float]:
    for n in [doc.root,*_element_children(doc.root)[:3]]:
        w=_float(n.get("Width"));h=_float(n.get("Height"))
        if 300<=w<=8192 and 200<=h<=8192:return (w,h)
    return (1920.,1080.)

def projected_geometry(doc:VisualXamlDocument,*,width=None,height=None,
                       include_hidden=True,max_items=3000)->list[Geometry]:
    if width is None or height is None:width,height=screen_size(doc)
    if not 10<float(width)<16385 or not 10<float(height)<16385:
        raise ValueError("Invalid preview dimensions")
    out=[]
    def visit(n,path,box,flow=None,hidden=False,depth=0):
        if depth>64 or len(out)>=max_items:return
        tag=_local(n.tag)
        if tag not in VISIBLE:return
        bx,by,bw,bh=box
        left,top,right,bottom=_thickness(n.get("Margin","0"))
        if flow and flow["type"]=="grid":
            rows,cols=flow["rows"],flow["cols"]
            ri=max(0,min(len(rows)-1,int(_float(n.get("Grid.Row")))))
            ci=max(0,min(len(cols)-1,int(_float(n.get("Grid.Column")))))
            rs=max(1,int(_float(n.get("Grid.RowSpan"),1)))
            cs=max(1,int(_float(n.get("Grid.ColumnSpan"),1)))
            bx+=sum(cols[:ci]);by+=sum(rows[:ri])
            bw=sum(cols[ci:ci+cs]);bh=sum(rows[ri:ri+rs])
        elif flow and flow["type"]=="stack":
            if flow["horizontal"]:bx+=flow["offset"]
            else:by+=flow["offset"]
        hint=(bw,bh) if tag in CONTAINERS else HINTS.get(tag,(200.,90.))
        w=_size(n,"Width",hint[0]);h=_size(n,"Height",hint[1])
        horizontal=n.get("HorizontalAlignment","Stretch" if tag in CONTAINERS else "Left")
        vertical=n.get("VerticalAlignment","Stretch" if tag in CONTAINERS else "Top")
        if horizontal=="Stretch" and n.get("Width") is None:w=max(1.,bw-left-right)
        if vertical=="Stretch" and n.get("Height") is None:h=max(1.,bh-top-bottom)
        x=bx+left;y=by+top
        if horizontal=="Center":x=bx+(bw-w)/2+left-right
        if horizontal=="Right":x=bx+bw-w-right
        if vertical=="Center":y=by+(bh-h)/2+top-bottom
        if vertical=="Bottom":y=by+bh-h-bottom
        if flow and flow["type"]=="canvas":
            x=bx+_float(n.get("Canvas.Left"),left)
            y=by+_float(n.get("Canvas.Top"),top)
            if n.get("Canvas.Right") is not None:x=bx+bw-w-_float(n.get("Canvas.Right"))
            if n.get("Canvas.Bottom") is not None:y=by+bh-h-_float(n.get("Canvas.Bottom"))
        hidden=hidden or n.get("Visibility") in ("Hidden","Collapsed")
        if include_hidden or not hidden:
            name=(n.get("Name") or n.get("{"+XNS+"}Name") or n.get("Content")
                  or n.get("Text") or tag)[:120]
            out.append(Geometry(path,tag,name,x,y,w,h,depth,hidden,
                      int(_float(n.get("Panel.ZIndex"))),tag in CONTAINERS))
        if tag=="Grid":
            flow_next={"type":"grid",
                       "rows":_grid_segments(n,"Row",h),
                       "cols":_grid_segments(n,"Column",w)}
        elif tag=="Canvas":flow_next={"type":"canvas"}
        elif tag in ("StackPanel","WrapPanel"):
            flow_next={"type":"stack","offset":0.,
                       "horizontal":n.get("Orientation")=="Horizontal"}
        else:flow_next=None
        children=[(i,c) for i,c in enumerate(_element_children(n))
                  if _local(c.tag) in VISIBLE]
        children.sort(key=lambda x:_float(x[1].get("Panel.ZIndex")))
        for idx,child in children:
            previous=len(out)
            visit(child,(*path,idx),(x,y,w,h),flow_next,hidden,depth+1)
            if flow_next and flow_next["type"]=="stack":
                found=next((g for g in out[previous:] if g.path==(*path,idx)),None)
                if found:
                    flow_next["offset"]+=found.w if flow_next["horizontal"] else found.h
    visit(doc.root,(),(0.,0.,float(width),float(height)))
    return out
