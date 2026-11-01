"""Visual Noesis menu *control* editing, based on actual, SHA-pinned XAML.

Unlike the bitmap layout designer, this modifies real XAML elements.  Reuses
only proven existing game commands and does not pretend to create a C# handler.
The renderer is an approximate authoring preview, never an in-game attestation.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import copy
import json
import re
import xml.etree.ElementTree as ET

from hud_menu_workspace import WorkshopError, import_patch, workspace
from se_asset_package import _check_xml

PRES="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
XNS="http://schemas.microsoft.com/winfx/2006/xaml"
ET.register_namespace("",PRES)
ET.register_namespace("x",XNS)
VISIBLE_TAGS=frozenset({"Button","Image","TextBlock","Grid","Border","Canvas","StackPanel"})
PROPERTIES=frozenset({
    "Margin","Width","Height","Opacity","Visibility","IsEnabled","Content",
    "HorizontalAlignment","VerticalAlignment","Source","CommandParameter",
    "Text","FontSize","Foreground","Background","Panel.ZIndex",
    "local:PropEx.TextCentre","local:PropEx.TextLeft","local:PropEx.TextRight",
    "local:PropEx.Sprite1","local:PropEx.Sprite2","local:PropEx.Sprite3",
    "local:PropEx.Sprite4",
})
BOUND_COMMAND=re.compile(r"\{Binding\s+[A-Za-z_][A-Za-z0-9_]*\s*\}\Z")
RECT=re.compile(r"(?:-?[0-9]+(?:\.[0-9]{1,2})?,){3}-?[0-9]+(?:\.[0-9]{1,2})?\Z")


def _sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def _safe_doc(path: Path) -> tuple[bytes,ET.Element]:
    file=Path(path)
    if (not file.is_file() or file.is_symlink() or
            not 1 <= file.stat().st_size <= 2*1024**2):
        raise WorkshopError("Choose a regular XAML document under 2 MiB")
    raw=file.read_bytes()
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise WorkshopError("External entities or DTDs are not allowed")
    try:
        root=ET.fromstring(raw)
    except ET.ParseError as exc:
        raise WorkshopError("Source XAML cannot be parsed") from exc
    if root.tag not in (f"{{{PRES}}}UserControl",f"{{{PRES}}}Grid"):
        raise WorkshopError("Only genuine Noesis view XAML can be edited")
    return raw,root


def _name_of(element:ET.Element)->tuple[str,str]|None:
    for attr,selector in ((f"{{{XNS}}}Name","x:Name"),("Name","Name")):
        value=element.get(attr)
        if value and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,100}",value):
            return selector,value
    return None


def _tag_of(element:ET.Element)->str:
    return element.tag.rsplit("}",1)[-1]


def _target_xpath(root:ET.Element,element:ET.Element)->str:
    pair=_name_of(element)
    if pair is None:
        raise WorkshopError("Cannot modify unnamed XAML node safely")
    key,name=pair
    tag=_tag_of(element)
    matches=[e for e in root.iter() if _tag_of(e)==tag and _name_of(e)==pair]
    if len(matches)!=1:
        raise WorkshopError("Target XAML name or node is not unique")
    return f"//n:{tag}[@{key}='{name}']"


@dataclass(frozen=True)
class Node:
    label:str
    xpath:str
    tag:str
    name:str
    properties:dict[str,str]
    bound_command:str|None
    command_parameter:str|None


def controls(source:Path)->list[Node]:
    _,root=_safe_doc(source)
    items=[]
    for e in root.iter():
        tag=_tag_of(e)
        if tag not in VISIBLE_TAGS or _name_of(e) is None:
            continue
        xpath=_target_xpath(root,e)
        label=_name_of(e)[1]
        attrs={}
        for k,v in e.attrib.items():
            normalized=k
            if k.startswith("{clr-namespace:CrusaderDE}"):
                normalized="local:"+k.split("}",1)[1]
            if normalized in PROPERTIES and len(v)<200:
                attrs[normalized]=v
        cmd=e.get("Command")
        items.append(Node(f"{tag} · {label}",xpath,tag,label,attrs,
                          cmd if cmd and BOUND_COMMAND.fullmatch(cmd) else None,
                          e.get("CommandParameter")))
    return items


def _one(root:ET.Element,xpath:str)->ET.Element:
    choices=controls_from_root(root)
    found=[el for query,el in choices if query==xpath]
    if len(found)!=1:
        raise WorkshopError("XAML target is missing or ambiguous")
    return found[0]


def controls_from_root(root:ET.Element)->list[tuple[str,ET.Element]]:
    all_nodes=[]
    for node in root.iter():
        if _tag_of(node) not in VISIBLE_TAGS or _name_of(node) is None:
            continue
        try:
            all_nodes.append((_target_xpath(root,node),node))
        except WorkshopError:
            pass
    return all_nodes


def _change(old:ET.Element,prop:str,value:str)->ET.Element:
    if prop not in PROPERTIES:
        raise WorkshopError("This property is not supported by the visual designer")
    if len(value)>250 or "\x00" in value or "\n" in value or "\r" in value:
        raise WorkshopError("Invalid XAML property value")
    if prop in {"Width","Height","Opacity","FontSize","Panel.ZIndex"}:
        try:
            number=float(value)
            if number<0 or number>16384:
                raise ValueError()
        except ValueError as exc:
            raise WorkshopError("Expected a bounded numeric XAML value") from exc
    if prop=="Margin" and not RECT.fullmatch(value):
        raise WorkshopError("Margin requires left,top,right,bottom numeric values")
    if prop=="Visibility" and value not in {"Visible","Collapsed","Hidden"}:
        raise WorkshopError("Visibility must be Visible, Collapsed or Hidden")
    if prop=="IsEnabled" and value not in {"True","False"}:
        raise WorkshopError("IsEnabled must be True or False")
    if prop=="CommandParameter":
        # An existing bound command accepts only its existing parameters
        # until the user supplies a separately verified runtime handler.
        if not value or len(value)>90 or not re.fullmatch(r"[\w.-]+",value):
            raise WorkshopError("Invalid command parameter")
    if prop in {"Source","Foreground","Background"} and (
        "<" in value or ">" in value or value.startswith(("file:","http:","https:"))
    ):
        raise WorkshopError("External resource URIs are not permitted")
    if prop.startswith("local:"):
        if prop.startswith("local:PropEx.Sprite") and (
            not re.fullmatch(r"\{StaticResource [A-Za-z0-9_ .-]+\}",value)
        ):
            raise WorkshopError("Sprite binding requires an existing StaticResource key")
        prop="{clr-namespace:CrusaderDE}"+prop.removeprefix("local:")
    new=copy.deepcopy(old)
    new.set(prop,value)
    return new


def create_patch(source:Path, *, xpath:str, operation:str,
                 property_name:str, value:str, runtime_parameters:dict|None=None
                 )->tuple[bytes,dict]:
    raw,root=_safe_doc(source)
    node=_one(root,xpath)
    if operation not in {"SetAttribute","Replace"}:
        raise WorkshopError("Use the structural editor for Add/Insert/Remove operations")
    if property_name=="CommandParameter":
        cmd=node.get("Command")
        available=set()
        if cmd:
            available={
                e.get("CommandParameter")
                for e in root.iter() if e.get("Command")==cmd and e.get("CommandParameter")
            }
        if value not in available:
            raise WorkshopError(
                "Unverified new command handler. Existing parameter required; "
                "create and verify runtime binding separately."
            )
    if operation=="SetAttribute" and property_name.startswith("local:"):
        raise WorkshopError("Namespaced PropEx attributes require Replace, not SetAttribute")
    if property_name.startswith("local:PropEx.Sprite"):
        # Do not invent a missing StaticResource; the new image must be added
        # separately through an explicit verified Noesis resource dictionary.
        if not any(value==existing for element in root.iter()
                   for existing in element.attrib.values()):
            raise WorkshopError("Selected Sprite StaticResource not present in source view")
    after=_change(node,property_name,value)
    patch=ET.Element("Patch")
    op=ET.SubElement(patch,"Operation",{
        "Type":operation,"XPath":xpath,
    })
    if operation=="SetAttribute":
        op.attrib.update({"AttributeName":property_name,"Value":value})
    else:
        content=ET.SubElement(op,"Content")
        content.append(after)
    original=copy.deepcopy(root)
    actual=_one(original,xpath)
    if operation=="SetAttribute":
        actual.set(property_name,value)
    else:
        parents=[p for p in original.iter() if actual in p]
        if len(parents)!=1:
            raise WorkshopError("No unambiguous parent for XAML replacement")
        parent=parents[0]
        index=list(parent).index(actual)
        parent.remove(actual)
        parent.insert(index,after)
    # Patch/Operation/Content are in the NOESIS patch namespace (empty).
    # A default presentation xmlns on <Patch> would silently make these
    # elements namespaced and unrecognizable by the XamlPatcher.
    ET.register_namespace("n",PRES)
    blob=ET.tostring(patch,encoding="utf-8",xml_declaration=True)
    return blob,{
        "schema":"sprite-suite.origins-xaml-control-edit.v1",
        "source_xaml_sha256":_sha(raw),
        "xpath":xpath,"operation":operation,
        "attribute":property_name,"new_value":value,
        "patch_sha256":_sha(blob),
        "selected_control":_name_of(node)[1],
        "bound_existing_command_only":True,
        "new_runtime_callback_created":False,
        "in_game_qa_completed":False,
    }


def save_patch(source:Path, *, xpath:str, operation:str,
               property_name:str,value:str,project:Path,
               target_document:str|None=None)->tuple[Path,dict]:
    project=workspace(project,create=True)
    source=Path(source)
    source_before=_sha(source.read_bytes())
    blob,receipt=create_patch(source,xpath=xpath,operation=operation,
                              property_name=property_name,value=value)
    if source_before!=_sha(source.read_bytes()):
        raise WorkshopError("Source XAML changed during patch creation")
    document=target_document or ("XAML/"+source.name)
    if document.count("/")>4:
        raise WorkshopError("XAML target path too deep")
    # Validate and stage without touching the original XAML.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="origins-xaml-",dir=project) as temp:
        file=Path(temp)/"source.xaml"
        file.write_bytes(blob)
        _check_xml(file,patch=True)
        saved=import_patch(file,project=project,target_document=document)
    receipt["relative_patch"]=saved.relative_to(project).as_posix()
    # A receipt stays outside Patches/ so no unsupported metadata is shipped.
    from hud_menu_workspace import _metadata_dir,_write_new
    record=_metadata_dir(project)/"origins-control-receipts"
    proof=record/(_sha(receipt["relative_patch"].encode())+".json")
    if proof.exists():
        raise WorkshopError("Control patch receipt already exists; refuse overwrite")
    _write_new(proof,(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n").encode("utf8"))
    return saved,receipt


def create_structural_patch(
    source:Path, *, xpath:str, operation:str, new_name:str="",
    command_parameter:str="", text:str="", image_source:str="",
)->tuple[bytes,dict]:
    """Add/InsertAfter/Remove actual XAML elements with strict identity checks.

    New native buttons inherit an *existing* command and may only reuse a
    command parameter demonstrably already bound in this version of the view.
    A new campaign handler cannot be invented by copying an image or XAML.
    """
    raw,root=_safe_doc(source)
    node=_one(root,xpath)
    if operation not in {"Add","InsertAfter","InsertBefore","Remove"}:
        raise WorkshopError("Unsupported structural patch")
    tag=_tag_of(node)
    if operation=="Add" and tag not in {"Grid","Canvas","StackPanel"}:
        raise WorkshopError("Add requires a real container")
    if operation in {"InsertAfter","InsertBefore"} and tag not in {
        "Button","Image","TextBlock"}:
        raise WorkshopError("Insertion requires a named visual element")
    if operation=="Remove" and _name_of(node) is None:
        raise WorkshopError("Remove requires a named element")
    names={p[1] for e in root.iter() if (p:=_name_of(e))}
    if operation!="Remove":
        if (not re.fullmatch(r"SpriteSuite_[A-Za-z0-9_]{1,75}",new_name)
                or new_name in names):
            raise WorkshopError("New element needs a unique SpriteSuite_ name")
    if len(text)>200 or any(x in text for x in ("\x00","\r","\n")):
        raise WorkshopError("Invalid visual label")
    patch=ET.Element("Patch")
    operation_node=ET.SubElement(
        patch,"Operation",{"Type":operation,"XPath":xpath}
    )
    command_reused=False
    if operation=="Remove":
        if any(_name_of(node)[1] == e.get("Storyboard.TargetName")
               or _name_of(node)[1] == e.get(f"{{{XNS}}}TargetName")
               for e in root.iter()):
            raise WorkshopError("Control is referenced by animation, cannot safely remove")
    else:
        visual=copy.deepcopy(node) if operation in {
            "InsertAfter","InsertBefore"} else ET.Element(
            f"{{{PRES}}}TextBlock"
        )
        if operation in {"InsertAfter","InsertBefore"}:
            old_pair=_name_of(visual)
            if old_pair is not None:
                attr=f"{{{XNS}}}Name" if old_pair[0]=="x:Name" else "Name"
                visual.set(attr,new_name)
            # Cloned storyboard targets and nested transform names cannot be
            # reused by an inserted control. Drop only nested x:Name values.
            for descendant in visual.iter():
                if descendant is visual: continue
                descendant.attrib.pop(f"{{{XNS}}}Name",None)
                descendant.attrib.pop("Name",None)
            if tag=="Button":
                command=visual.get("Command")
                existing_params={
                    e.get("CommandParameter")
                    for e in root.iter() if e.get("Command")==command
                    and e.get("CommandParameter")
                }
                requested=command_parameter or visual.get("CommandParameter")
                if not command or not BOUND_COMMAND.fullmatch(command):
                    raise WorkshopError("Source button has no proven existing command")
                if requested not in existing_params:
                    raise WorkshopError("New command handler is unverified, not allowed")
                visual.set("CommandParameter",requested)
                command_reused=True
                if text:
                    visual.set("Content",text)
            elif tag=="Image" and image_source:
                if (not image_source.startswith("../Images/") or
                        ".." in image_source.removeprefix("../Images/") or
                        any(x in image_source for x in ('"',"'",'<','>','\n','\x00'))):
                    raise WorkshopError("Image source must be a relative game image")
                visual.set("Source",image_source)
                visual.set("IsHitTestVisible","False")
            elif tag=="TextBlock" and text:
                visual.set("Text",text)
        else:
            visual.set("Name",new_name)
            visual.set("Text",text)
            visual.set("IsHitTestVisible","False")
            visual.set("FontSize","22")
        content=ET.SubElement(operation_node,"Content")
        content.append(visual)
    ET.register_namespace("n",PRES)
    payload=ET.tostring(patch,encoding="utf-8",xml_declaration=True)
    return payload,{
        "schema":"sprite-suite.origins-xaml-structural-patch.v1",
        "source_xaml_sha256":_sha(raw),
        "xpath":xpath,"operation":operation,
        "new_name":new_name if operation!="Remove" else None,
        "reuses_verified_existing_command":command_reused,
        "creates_new_runtime_handler":False,
        "in_game_qa_completed":False,
        "patch_sha256":_sha(payload),
    }


def save_structural_patch(source:Path, *,project:Path,
                          target_document:str|None=None,**options
                          )->tuple[Path,dict]:
    source=Path(source)
    project=workspace(project,create=True)
    original_hash=_sha(source.read_bytes())
    blob,proof=create_structural_patch(source,**options)
    if _sha(source.read_bytes())!=original_hash:
        raise WorkshopError("Game XAML changed during structural patch creation")
    target=target_document or "XAML/"+source.name
    from hud_menu_workspace import _metadata_dir
    receipt_dir=_metadata_dir(project)/"origins-control-receipts"
    key=_sha(("structural/"+target+"/"+options["xpath"]).encode("utf-8"))
    evidence=receipt_dir/(key+".json")
    if evidence.exists():
        raise WorkshopError("A structural patch receipt exists for this target")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="origins-struct-",dir=project) as tmp:
        staging=Path(tmp)/"patch.xaml"
        staging.write_bytes(blob)
        _check_xml(staging,patch=True)
        saved=import_patch(staging,project=project,target_document=target)
    proof["relative_patch"]=saved.relative_to(project).as_posix()
    from hud_menu_workspace import _write_new
    _write_new(evidence,(json.dumps(proof,ensure_ascii=False,indent=2)+"\n").encode("utf8"))
    return saved,proof


def combine_control_patches(source:Path,patches:list[tuple[bytes,dict]]
                            )->tuple[bytes,dict]:
    """Combine multiple actual XAML control edits for the SAME game document."""
    raw,_=_safe_doc(source)
    baseline=_sha(raw)
    if not 1<=len(patches)<=300:
        raise WorkshopError("Choose between 1 and 300 verified XAML changes")
    parent=ET.Element("Patch")
    keys=set()
    xpath_changes={}
    for blob,proof in patches:
        if proof.get("source_xaml_sha256")!=baseline or proof.get("patch_sha256")!=_sha(blob):
            raise WorkshopError("One selected edit belongs to a different XAML source")
        if proof.get("new_runtime_callback_created") is True or proof.get(
            "creates_new_runtime_handler") is True:
            raise WorkshopError("Unverified runtime callback in menu patch")
        try:parsed=ET.fromstring(blob)
        except ET.ParseError as exc:raise WorkshopError("Malformed pending patch") from exc
        ops=list(parsed)
        if parsed.tag!="Patch" or len(ops)!=1 or ops[0].tag!="Operation":
            raise WorkshopError("Pending patch is not a standalone Noesis operation")
        op=ops[0]
        kind=op.get("Type")
        xpath=op.get("XPath")
        if kind not in {"SetAttribute","Replace","Add","InsertAfter","InsertBefore","Remove"} or not xpath:
            raise WorkshopError("Unknown operation in pending patch")
        detail=op.get("AttributeName","") if kind=="SetAttribute" else ""
        uniq=(kind,xpath,detail)
        if uniq in keys:
            raise WorkshopError("The same XAML operation is queued twice")
        keys.add(uniq)
        previous=xpath_changes.get(xpath,set())
        if ("Replace" in previous or "Remove" in previous or
            (kind in {"Replace","Remove"} and previous)):
            raise WorkshopError("Conflicting structural edits on one XAML target")
        xpath_changes.setdefault(xpath,set()).add(kind)
        parent.append(copy.deepcopy(op))
    ET.register_namespace("n",PRES)
    merged=ET.tostring(parent,encoding="utf8",xml_declaration=True)
    return merged,{
        "schema":"sprite-suite.origins-manual-combined-xaml.v1",
        "source_xaml_sha256":baseline,
        "operations":len(patches),
        "patch_sha256":_sha(merged),
        "new_runtime_handlers_compiled":False,
        "requires_ingame_testing":True,
    }


def save_combined_patch(source:Path,*,project:Path,
                        patches:list[tuple[bytes,dict]],
                        target_document:str|None=None)->tuple[Path,dict]:
    project=workspace(project,create=True)
    source=Path(source)
    before=_sha(source.read_bytes())
    blob,receipt=combine_control_patches(source,patches)
    if _sha(source.read_bytes())!=before:
        raise WorkshopError("Game XAML changed while queued edits were built")
    doc=target_document or "XAML/"+source.name
    from hud_menu_workspace import _metadata_dir
    meta=_metadata_dir(project)
    proof=meta/("origins-"+_sha(doc.encode())+".json")
    if proof.exists():
        raise WorkshopError("This document already has a saved patch revision")
    from tempfile import TemporaryDirectory
    with TemporaryDirectory(prefix="origins-queued-",dir=project) as temp:
        staged=Path(temp)/"patch.xaml"
        staged.write_bytes(blob)
        from se_asset_package import _check_xml
        _check_xml(staged,patch=True)
        saved=import_patch(staged,project=project,target_document=doc)
    receipt["relative_patch"]=saved.relative_to(project).as_posix()
    from hud_menu_workspace import _write_new
    _write_new(proof,(json.dumps(receipt,ensure_ascii=False,indent=2)+"\n").encode())
    return saved,receipt
