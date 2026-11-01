"""Full-tree Origins/Noesis XAML authoring with editable, reproducible revisions.

No SHA lock on authored work: users may freely edit/reopen saved XAML. Baseline
hashes are provenance notes, not modification bans. Changes are published into
the existing asset-mod Patches/Assets/GUI/XAML/ directory, never game installs.

No claim of pixel-exact Noesis rendering or runtime command registration.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import copy
from io import BytesIO
import json
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

from hud_menu_workspace import WorkshopError, workspace, _relative
from se_asset_package import _check_xml
from suite_windows_paths import is_link_or_reparse

PRES="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
XNS="http://schemas.microsoft.com/winfx/2006/xaml"
ET.register_namespace("n",PRES)
ET.register_namespace("x",XNS)
_LIMIT=2*1024*1024
_ALLOWED_ROOTS={"UserControl","Window","Page","Grid","Canvas","ResourceDictionary"}
_SIMPLE_NAME=re.compile(r"[A-Za-z_][\w.-]*\Z",re.UNICODE)
_NUMBER=re.compile(r"^-?\d+(?:\.\d+)?$")
_HISTORY=60


def _sha(data:bytes)->str:
    return sha256(data).hexdigest()


def _local(qname:str)->str:
    return qname.rsplit("}",1)[-1]


def _element_children(node:ET.Element)->list[ET.Element]:
    return [child for child in node if isinstance(child.tag,str)]


def _parse(data:bytes)->ET.Element:
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise WorkshopError("External XML entities and DTDs are not supported")
    try:
        parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True,insert_pis=True))
        result=ET.fromstring(data,parser=parser)
    except ET.ParseError as exc:
        raise WorkshopError("XAML is not well-formed XML: "+str(exc)) from exc
    if _local(result.tag) not in _ALLOWED_ROOTS:
        raise WorkshopError("Select a Noesis view, page, grid or resource dictionary")
    return result


def _prefixes(data:bytes)->dict[str,str]:
    result={"n":PRES,"x":XNS,"":PRES}
    try:
        for _,namespace in ET.iterparse(BytesIO(data),events=("start-ns",)):
            key,uri=namespace
            result[key or ""]=uri
    except ET.ParseError:
        pass
    for prefix,uri in result.items():
        if prefix and prefix not in {"xml","xmlns"} and not prefix.startswith("ns"):
            try:ET.register_namespace(prefix,uri)
            except ValueError:pass
    return result


def _encode(root:ET.Element)->bytes:
    result=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    if len(result)>_LIMIT:
        raise WorkshopError("Edited view exceeds the 2 MiB patch output limit")
    _parse(result)
    return result


def _thickness(value:str)->list[float]:
    try:parts=[float(x.strip()) for x in value.split(",")]
    except (TypeError,ValueError):return [0.,0.,0.,0.]
    if len(parts)==1:return [parts[0]]*4
    if len(parts)==2:return [parts[0],parts[1],parts[0],parts[1]]
    if len(parts)==4:return parts
    return [0.,0.,0.,0.]


def _num(value:float)->str:
    from math import isfinite
    number=float(value)
    if not isfinite(number):
        raise WorkshopError("XAML layout coordinates must be finite")
    return str(int(number)) if number.is_integer() else ("%g" % number)


@dataclass(frozen=True)
class OutlineNode:
    path:tuple[int,...]
    depth:int
    tag:str
    label:str
    attrs:dict[str,str]
    text:str


class VisualXamlDocument:
    """Editable XML AST with complete tree, snapshots and no designer allowlist."""

    def __init__(self,source:Path,*,source_bytes:bytes|None=None):
        source=Path(source)
        if source_bytes is None:
            if (not source.is_file() or is_link_or_reparse(source)
                    or not 1<=source.stat().st_size<=_LIMIT):
                raise WorkshopError("Select a normal XAML source file below 2 MiB")
            source_bytes=source.read_bytes()
        self.source=source
        self.document_name=source.name
        self.source_bytes=source_bytes
        self.ns=_prefixes(source_bytes)
        self.root=_parse(source_bytes)
        self.undo:list[bytes]=[]
        self.redo:list[bytes]=[]
        self.unsupported_features:list[str]=[]

    def _tag(self,name:str,*,element:bool=False)->str:
        name=name.strip()
        if name.startswith("{"):
            if not re.fullmatch(r"\{[^{}]+\}[^\s{}]+",name):
                raise WorkshopError("Invalid namespace-qualified XAML name")
            return name
        if ":" in name:
            prefix,local=name.split(":",1)
            if prefix not in self.ns or not _SIMPLE_NAME.fullmatch(local):
                raise WorkshopError("Unknown XAML namespace or invalid attribute")
            return "{"+self.ns[prefix]+"}"+local
        if not _SIMPLE_NAME.fullmatch(name):
            raise WorkshopError("Invalid XAML element/attribute name")
        # In XAML, unprefixed ELEMENTS live in the document's default
        # presentation namespace. Attributes such as Margin/Canvas.Left do not.
        return ("{"+self.ns.get("",PRES)+"}"+name) if element else name

    def short_attribute(self,key:str)->str:
        if key.startswith("{") and "}" in key:
            uri,local=key[1:].split("}",1)
            prefix=next((p for p,u in self.ns.items() if p and u==uri),None)
            return (prefix+":" if prefix else "{"+uri+"}")+local
        return key

    def _target(self,path:tuple[int,...])->ET.Element:
        if not isinstance(path,tuple) or len(path)>64:
            raise WorkshopError("Invalid tree selection")
        result=self.root
        for part in path:
            children=_element_children(result)
            if type(part) is not int or part<0 or part>=len(children):
                raise WorkshopError("XAML tree selection no longer exists")
            result=children[part]
        return result

    def _parent(self,path:tuple[int,...])->tuple[ET.Element,ET.Element]:
        if not path:
            raise WorkshopError("The root element has no parent")
        return self._target(path[:-1]),self._target(path)

    def _commit(self,mutate)->None:
        old=_encode(self.root)
        before=copy.deepcopy(self.root)
        try:
            mutate()
            updated=_encode(self.root)
        except Exception:
            self.root=before
            raise
        if updated!=old:
            self.undo.append(old)
            if len(self.undo)>_HISTORY:self.undo.pop(0)
            self.redo.clear()

    def outline(self)->list[OutlineNode]:
        result=[]
        def walk(node:ET.Element,path:tuple[int,...]):
            text=(node.text or "").strip()[:160]
            label=(node.get("Name") or node.get("{"+XNS+"}Name") or
                   node.get("{"+XNS+"}Key") or node.get("Content") or
                   node.get("Text") or text or "")
            result.append(OutlineNode(
                path=path,depth=len(path),tag=_local(node.tag),label=label[:90],
                attrs={self.short_attribute(k):v for k,v in node.attrib.items()},
                text=node.text or ""))
            for index,child in enumerate(_element_children(node)):
                walk(child,(*path,index))
        walk(self.root,())
        return result

    def attributes(self,path:tuple[int,...])->dict[str,str]:
        return {self.short_attribute(k):v for k,v in self._target(path).attrib.items()}

    def edit(self,path:tuple[int,...],name:str,value:str|None)->None:
        """Set OR remove any attribute, including command/style and XAML xmlns attrs."""
        if value is not None and not isinstance(value,str):
            raise WorkshopError("XAML attribute values must be text")
        qname=self._tag(name)
        def action():
            element=self._target(path)
            if value is None:element.attrib.pop(qname,None)
            else:element.set(qname,value)
        self._commit(action)

    def edit_text(self,path:tuple[int,...],value:str)->None:
        if not isinstance(value,str):
            raise WorkshopError("XAML text content must be text")
        self._commit(lambda:setattr(self._target(path),"text",value))

    def insert(self,parent:tuple[int,...],tag:str,attrs:dict[str,str]|None=None,
               index:int|None=None)->tuple[int,...]:
        qname=self._tag(tag,element=True)
        attributes={self._tag(k):v for k,v in (attrs or {}).items()}
        newpath=None
        def action():
            nonlocal newpath
            node=self._target(parent)
            child=ET.Element(qname,attributes)
            children=_element_children(node)
            at=len(children) if index is None else max(0,min(index,len(children)))
            if at==len(children):node.append(child)
            else:node.insert(list(node).index(children[at]),child)
            newpath=(*parent,at)
        self._commit(action)
        return newpath

    def duplicate(self,path:tuple[int,...])->tuple[int,...]:
        parent,node=self._parent(path)
        newpath=(*path[:-1],path[-1]+1)
        def action():
            siblings=_element_children(parent)
            cloned=copy.deepcopy(node)
            existing={n.get("Name") or n.get("{"+XNS+"}Name") for n in self.root.iter()
                      if isinstance(n.tag,str)}
            for descendant in cloned.iter():
                if not isinstance(descendant.tag,str):continue
                for key in ("Name","{"+XNS+"}Name"):
                    name=descendant.get(key)
                    if not name:continue
                    suffix=1
                    proposal=name+"_Copy"
                    while proposal in existing:
                        suffix+=1
                        proposal=name+"_Copy"+str(suffix)
                    descendant.set(key,proposal)
                    existing.add(proposal)
            idx=list(parent).index(node)+1
            parent.insert(idx,cloned)
        self._commit(action)
        return newpath

    def remove(self,path:tuple[int,...])->None:
        def action():
            parent,node=self._parent(path)
            parent.remove(node)
        self._commit(action)

    def reorder(self,path:tuple[int,...],direction:int)->tuple[int,...]:
        if direction not in (-1,1):
            raise WorkshopError("Reorder direction must be -1 or +1")
        target_index=path[-1]+direction if path else -1
        def action():
            parent,node=self._parent(path)
            kids=_element_children(parent)
            if target_index<0 or target_index>=len(kids):
                raise WorkshopError("Cannot reorder past first/last sibling")
            other=kids[target_index]
            current_pos=list(parent).index(node)
            other_pos=list(parent).index(other)
            parent.remove(node)
            parent.insert(other_pos,node)
        self._commit(action)
        return (*path[:-1],target_index)

    def move(self,path:tuple[int,...],dx:float,dy:float)->None:
        """Drag in original XAML layout units; preserve alignment and margins."""
        if not (-100000<dx<100000 and -100000<dy<100000):
            raise WorkshopError("Invalid drag displacement")
        def action():
            element=self._target(path)
            parent=self._target(path[:-1]) if path else None
            if parent is not None and _local(parent.tag)=="Canvas":
                for attr,diff in (("Canvas.Left",dx),("Canvas.Top",dy)):
                    number=element.get(attr,"0")
                    try:current=float(number)
                    except ValueError:current=0.
                    element.set(attr,_num(current+diff))
            else:
                values=_thickness(element.get("Margin","0"))
                values[0]+=dx;values[1]+=dy
                element.set("Margin",",".join(_num(n) for n in values))
        self._commit(action)

    def resize(self,path:tuple[int,...],width:float,height:float)->None:
        if not 0<width<=16384 or not 0<height<=16384:
            raise WorkshopError("Invalid new layout dimensions")
        def action():
            node=self._target(path)
            node.set("Width",_num(width))
            node.set("Height",_num(height))
        self._commit(action)

    def rotate(self,path:tuple[int,...],angle:float)->None:
        if not -36000<=angle<=36000:
            raise WorkshopError("Invalid rotation angle")
        def action():
            node=self._target(path)
            name=_local(node.tag)+".RenderTransform"
            holder=next((c for c in _element_children(node)
                         if _local(c.tag)==name),None)
            if holder is None:
                holder=ET.SubElement(node,"{"+PRES+"}"+name)
            old=_element_children(holder)
            if len(old)==1 and _local(old[0].tag)=="RotateTransform":
                old[0].set("Angle",_num(angle))
            else:
                group=next((n for n in old if _local(n.tag)=="TransformGroup"),None)
                if group is None:
                    group=ET.Element("{"+PRES+"}TransformGroup")
                    for n in old:
                        holder.remove(n);group.append(n)
                    holder.append(group)
                rotation=next((n for n in group if _local(n.tag)=="RotateTransform"),None)
                if rotation is None:
                    rotation=ET.SubElement(group,"{"+PRES+"}RotateTransform")
                rotation.set("Angle",_num(angle))
            if node.get("RenderTransformOrigin") is None:
                node.set("RenderTransformOrigin","0.5,0.5")
        self._commit(action)

    def undo_edit(self)->bool:
        if not self.undo:return False
        self.redo.append(_encode(self.root))
        self.root=_parse(self.undo.pop())
        return True

    def redo_edit(self)->bool:
        if not self.redo:return False
        self.undo.append(_encode(self.root))
        self.root=_parse(self.redo.pop())
        return True

    def replace_xml(self,content:str)->None:
        """Advanced manual XAML source mode; edited markup is always permitted."""
        if not isinstance(content,str):
            raise WorkshopError("Edited XAML must be text")
        candidate=_parse(content.encode("utf-8"))
        if candidate.tag!=self.root.tag:
            raise WorkshopError("Keep the original Noesis view root type")
        self.ns.update(_prefixes(content.encode("utf-8")))
        self._commit(lambda:setattr(self,"root",candidate))

    def edited_bytes(self)->bytes:
        return _encode(self.root)

    def _xpath(self,parent:ET.Element,child:ET.Element,root:ET.Element)->str|None:
        tag=_local(child.tag)
        # Confirm matches globally for Name/x:Name (nested anim transforms too).
        for att,lookup in (("Name","Name"),("{"+XNS+"}Name","x:Name")):
            name=child.get(att)
            if (name and "'" not in name and '"' not in name
                    and len([n for n in root.iter()
                             if isinstance(n.tag,str) and _local(n.tag)==tag
                             and n.get(att)==name])==1):
                return f"//n:{tag}[@{lookup}='{name}']"
        # Anonymous direct child: only if it is the unique tag beneath root.
        same=[c for c in _element_children(parent) if c.tag==child.tag]
        if len(same)==1:
            return "/n:"+_local(root.tag)+"/n:"+tag
        return None

    def patch_bytes(self)->tuple[bytes,dict]:
        """Patch entire edited top-level regions, preserving all nested controls.

        Replacing a direct root Grid covers free edits, control creation,
        deletion, reordering, complex styles, arbitrary bindings, transforms,
        etc. Root attributes require SetAttribute or an explicit root Replace.
        """
        original=_parse(self.source_bytes)
        if original.tag!=self.root.tag:
            raise WorkshopError("Root Noesis type cannot be changed in this patch mode")
        if _encode(original)==_encode(self.root):
            raise WorkshopError("No changes to export")
        basechildren=_element_children(original)
        altered=_element_children(self.root)
        operations=[]
        notes=[]
        if len(basechildren)==len(altered) and all(a.tag==b.tag
            for a,b in zip(basechildren,altered)):
            for old,new in zip(basechildren,altered):
                if ET.tostring(old)==ET.tostring(new):
                    continue
                path=self._xpath(original,old,original)
                if path is None:
                    operations=[]
                    notes.append("Anonyme mehrfach vorhandene Wurzelknoten: Root-Replace")
                    break
                operations.append(("Replace",path,copy.deepcopy(new),None,None))
        else:
            notes.append("Wurzelstruktur verändert: Root-Replace")
        # Fully preserve root attribute modifications (including removals).
        changed_attrs=[(key,val) for key,val in self.root.attrib.items()
                       if original.get(key)!=val]
        removed_attrs=set(original.attrib)-set(self.root.attrib)
        if not operations and _encode(original)!=_encode(self.root):
            operations=[("Replace","/n:"+_local(original.tag),
                         copy.deepcopy(self.root),None,None)]
            notes.append("Root-Replacement muss in der Zielversion ingame geprüft werden")
        elif changed_attrs or removed_attrs or (original.text!=self.root.text):
            # Namespaced root attrs/removals cannot safely use SetAttribute.
            if removed_attrs or any("}" in k for k,_ in changed_attrs) or (
                    original.text!=self.root.text):
                operations=[("Replace","/n:"+_local(original.tag),
                             copy.deepcopy(self.root),None,None)]
                notes.append("Root-Replace für komplexe Wurzeleigenschaften")
            else:
                for key,val in changed_attrs:
                    operations.append(("SetAttribute","/n:"+_local(original.tag),
                                      None,key,val))
        if not operations:
            raise WorkshopError("Changed nodes have no supported Noesis patch target")
        patch=ET.Element("Patch")
        for kind,xpath,node,attr,value in operations:
            attrs={"Type":kind,"XPath":xpath}
            if kind=="SetAttribute":
                attrs.update(AttributeName=attr,Value=value)
            op=ET.SubElement(patch,"Operation",attrs)
            if kind=="Replace":
                ET.SubElement(op,"Content").append(node)
        result=ET.tostring(patch,encoding="utf-8",xml_declaration=True)
        if len(result)>_LIMIT:
            raise WorkshopError("Generated patch exceeds the 2 MiB size limit")
        # Real parse/operation validation; never interpreted as code.
        _parse(self.edited_bytes())
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/"menu-patch.xaml"
            target.write_bytes(result)
            _check_xml(target,patch=True)
        commands=set()
        for item in self.root.iter():
            if isinstance(item.tag,str) and item.get("CommandParameter"):
                commands.add(item.get("CommandParameter"))
        return result,{
            "schema":"sprite-suite.origins-visual-document.v1",
            "source_document":self.source.name,
            "source_sha256":_sha(self.source_bytes),
            "edited_sha256":_sha(self.edited_bytes()),
            "patch_sha256":_sha(result),
            "operations":len(operations),
            "custom_command_parameters":sorted(commands),
            "notes":notes,
            "native_action_handlers_attested":False,
            "in_game_qa_completed":False,
            "steam_installation_modified":False,
        }

    def save_revision(self,project:Path,*,publish:bool=True,
                      overwrite_existing:bool=False,
                      document_name:str|None=None)->dict:
        root=workspace(project,create=True)
        name=document_name or self.document_name
        relative="Patches/Assets/GUI/XAML/"+name
        _relative(relative,patch=True)
        patch,receipt=self.patch_bytes()
        # Keep editable history outside the packaged mod root: the asset
        # builder rightly accepts only Override/, Patches/ and Locales/.
        import hud_menu_workspace as work
        identity=_sha(root.relative_to(work.WORK.resolve()).as_posix().encode())[:16]
        base=work.WORK.resolve()/".origins-visual-revisions"/identity/name
        if is_link_or_reparse(base):
            raise WorkshopError("Linked revision history is not allowed")
        base.mkdir(parents=True,exist_ok=True)
        number=1
        while (base/("rev-%04d"%number)).exists():number+=1
        dest=base/("rev-%04d"%number)
        stage=Path(tempfile.mkdtemp(prefix=".menu-revision-",dir=base))
        try:
            (stage/"source.xaml").write_bytes(self.source_bytes)
            (stage/"edited.xaml").write_bytes(self.edited_bytes())
            (stage/"patch.xaml").write_bytes(patch)
            receipt.update(revision=number,
                           target_patch=relative,
                           published=False)
            (stage/"revision.json").write_text(json.dumps(
                receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
            os.rename(stage,dest)
        finally:
            if stage.exists() and not is_link_or_reparse(stage):
                shutil.rmtree(stage)
        active=root.joinpath(*relative.split("/"))
        if publish:
            if active.exists() and not overwrite_existing:
                receipt["notes"].append(
                    "Ein vorhandener Paketpatch wurde nicht überschrieben; "
                    "Revision liegt vollständig vor")
            else:
                if is_link_or_reparse(active) or any(
                    is_link_or_reparse(x) for x in active.parents if x!=root
                    and root in x.parents):
                    raise WorkshopError("Linked target path cannot be published")
                active.parent.mkdir(parents=True,exist_ok=True)
                if active.is_file():
                    (dest/"previous-package-patch.xaml").write_bytes(active.read_bytes())
                fd,staging=tempfile.mkstemp(prefix=".origins-patch-",
                                          suffix=".tmp",dir=active.parent)
                try:
                    with os.fdopen(fd,"wb") as stream:
                        stream.write(patch)
                        stream.flush();os.fsync(stream.fileno())
                    os.replace(staging,active)
                finally:
                    if os.path.exists(staging):os.unlink(staging)
                receipt["published"]=True
        (dest/"revision.json").write_text(json.dumps(
            receipt,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        return {"revision_dir":str(dest),
                "patch":str(active) if receipt["published"] else None,**receipt}

    @classmethod
    def reopen(cls,folder:Path)->"VisualXamlDocument":
        """Reload user-edited revision, even if manually altered after saving."""
        folder=Path(folder)
        if not folder.is_dir() or is_link_or_reparse(folder):
            raise WorkshopError("Revision folder missing or linked")
        source=folder/"source.xaml"
        edited=folder/"edited.xaml"
        if (not source.is_file() or not edited.is_file() or
                is_link_or_reparse(source) or is_link_or_reparse(edited)):
            raise WorkshopError("Revision requires its source and edited XAML")
        obj=cls(source)
        meta=folder/"revision.json"
        if meta.is_file():
            try:
                record=json.loads(meta.read_text("utf8"))
                obj.document_name=record.get("source_document",source.name)
            except (UnicodeError,ValueError):
                pass
        revised=edited.read_bytes()
        obj.root=_parse(revised)
        obj.ns.update(_prefixes(revised))
        return obj



def apply_existing_patch(document:VisualXamlDocument,patch_file:Path,
                         *,strict:bool=False)->dict:
    """Merge an existing Origins/Noesis XamlPatcher file into the editable view.

    This is an OFFLINE structural application, not the native XamlPatcher
    implementation. XPath misses may be skipped for an intentional custom
    source, reported to the user, and never silently called in-game parity.
    """
    if not isinstance(document,VisualXamlDocument):
        raise WorkshopError("Choose an original editable XAML document first")
    file=Path(patch_file)
    if (not file.is_file() or is_link_or_reparse(file) or
            not 1<=file.stat().st_size<=_LIMIT):
        raise WorkshopError("Choose a regular Noesis XAML patch under 2 MiB")
    raw=file.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise WorkshopError("DTD/ENTITY not allowed in imported patch")
    # Historical Origins patches may contain local:PropEx attributes without
    # declaring their prefix: native patcher loads these in the game's XAML
    # namespace context. Bind only namespaces known from THIS original view.
    match=re.search(rb"<(Patch|XamlPatch)(?=[\s>])",raw)
    if match is None:
        raise WorkshopError("Imported file needs a <Patch> root")
    head=raw[match.start():raw.find(b">",match.end())+1]
    declarations=[]
    for prefix,uri in sorted(document.ns.items()):
        if not prefix or prefix in {"xml","xmlns","n","ns0"}:
            continue
        if b"xmlns:"+prefix.encode("ascii")+b"=" in head:
            continue
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*",prefix):
            continue
        escaped=(uri.replace("&","&amp;").replace('"',"&quot;")
                 .replace("<","&lt;"))
        declarations.append((" xmlns:"+prefix+'="'+escaped+'"').encode("utf8"))
    if declarations:
        raw=raw[:match.end()]+b"".join(declarations)+raw[match.end():]
    try:
        parsed=ET.fromstring(raw,parser=ET.XMLParser(
            target=ET.TreeBuilder(insert_comments=True,insert_pis=True)))
    except ET.ParseError as exc:
        raise WorkshopError("Could not parse existing XAML patch: "+str(exc)) from exc
    if parsed.tag not in {"Patch","XamlPatch"}:
        raise WorkshopError("Existing patch root is not Patch/XamlPatch")
    entries=[x for x in parsed if isinstance(x.tag,str)]
    if len(entries)>2000:
        raise WorkshopError("Patch contains more than 2000 operations")
    if not entries:
        raise WorkshopError("Existing patch has no operations")
    applied=[]
    warnings=[]
    ns={"n":PRES,"x":XNS}
    ns.update({k:v for k,v in document.ns.items() if k})
    def match_xpath(expression:str)->list[ET.Element]:
        query=expression
        if query.startswith("//"):
            query="."+query
        elif query.startswith("/"):
            sections=query.strip("/").split("/")
            if not sections or _local(document.root.tag)!=sections[0].split(":")[-1]:
                return []
            query="." if len(sections)==1 else "./"+"/".join(sections[1:])
        try:
            if query==".":
                return [document.root]
            return document.root.findall(query,namespaces=ns)
        except (SyntaxError,KeyError,ValueError) as exc:
            raise WorkshopError("Unsupported existing XPath: "+expression) from exc

    def copy_content(op:ET.Element)->list[ET.Element]:
        children=[n for n in op if isinstance(n.tag,str) and n.tag=="Content"]
        if len(children)!=1:
            raise WorkshopError("Operation needs one Content container")
        result=[]
        for child in children[0]:
            if not isinstance(child.tag,str):continue
            clone=copy.deepcopy(child)
            for part in clone.iter():
                if isinstance(part.tag,str) and not part.tag.startswith("{"):
                    part.tag="{"+PRES+"}"+part.tag
            result.append(clone)
        if not result:
            raise WorkshopError("Operation Content has no actual Noesis element")
        return result

    def mutate():
        for op in entries:
            if op.tag!="Operation":
                raise WorkshopError("Unexpected XML node in XAML patch")
            kind=op.get("Type")
            xpath=op.get("XPath","")
            if kind not in {"SetAttribute","Replace","Add","InsertAfter",
                            "InsertBefore","Remove","AddNamespace"}:
                raise WorkshopError("Unknown XAML patch operation "+str(kind))
            if kind=="AddNamespace":
                warnings.append("AddNamespace verlangt Spiel-QA; Namespace-Deklaration "
                                "nicht als visuelles Element dargestellt")
                continue
            if not xpath:
                raise WorkshopError("XAML operation has no XPath")
            found=match_xpath(xpath)
            if len(found)!=1:
                diagnostic=f"{kind}: XPath trifft {len(found)} Elemente: {xpath}"
                if strict:raise WorkshopError(diagnostic)
                warnings.append(diagnostic)
                continue
            target=found[0]
            if kind=="SetAttribute":
                name=op.get("AttributeName")
                if not name:
                    raise WorkshopError("Missing SetAttribute name")
                attr=document._tag(name)
                target.set(attr,op.get("Value",""))
            elif kind=="Add":
                for node in copy_content(op):
                    target.append(node)
            else:
                parent=next((node for node in document.root.iter()
                             if target in node),None)
                if parent is None:
                    if kind=="Replace":
                        content=copy_content(op)
                        if len(content)!=1:
                            raise WorkshopError("Root Replace needs one node")
                        document.root=content[0]
                        applied.append((kind,xpath))
                        continue
                    if strict:raise WorkshopError("Cannot alter the root with "+kind)
                    warnings.append("Operation skipped on root: "+xpath)
                    continue
                if kind=="Remove":
                    parent.remove(target)
                else:
                    replacement=copy_content(op)
                    index=list(parent).index(target)
                    if kind=="Replace":
                        parent.remove(target)
                    elif kind=="InsertAfter":
                        index+=1
                    for n in replacement:
                        parent.insert(index,n)
                        index+=1
            applied.append((kind,xpath))

    document._commit(mutate)
    return {
        "patch_name":file.name,
        "operations_found":len(entries),
        "applied_operations":len(applied),
        "skipped_operations":len(entries)-len(applied),
        "warnings":warnings,
        "no_original_game_xaml_modified":True,
        "in_game_parity_verified":False,
    }
