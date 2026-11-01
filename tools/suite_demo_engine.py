"""Executable, step-by-step SpriteSuite demos using production processing APIs.

Each module gets its own private work/demo-sessions/ project, genuine source,
modification, verification and export. Only explicit user-supplied originals
are copied into that private workspace; no game or installed mod is written.
Demo records report observed bytes/paths, never simulated successes.
"""
from __future__ import annotations

from dataclasses import dataclass,field
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from secrets import token_hex
import json
import os
import re
import shutil
from zipfile import ZipFile

from PIL import Image,ImageDraw

import hud_menu_workspace as work
import hud_menu_layout as layout
import origins_visual_document as visual
import origins_runtime_authoring as author
import origins_runtime_offline_qa as runtime_qa
import se_asset_package as asset_mod
from suite_origins_theme_editor import read_palette,save_palette
from suite_windows_paths import is_link_or_reparse

PRES="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
XNS="http://schemas.microsoft.com/winfx/2006/xaml"
DEFAULT_XAML=(f'''<?xml version="1.0" encoding="utf-8"?>
<UserControl xmlns="{PRES}" xmlns:x="{XNS}" xmlns:local="clr-namespace:CrusaderDE">
  <Grid Name="MainMenu" Width="960" Height="540" Background="#FF263D5D">
    <Image Name="MenuBackground" Source="../Images/DemoMenu.png"
       HorizontalAlignment="Stretch" VerticalAlignment="Stretch" />
    <StackPanel Name="MainActions" HorizontalAlignment="Center"
       VerticalAlignment="Center" Width="340">
      <TextBlock Name="MenuHeadline" Text="Original-Menü" FontSize="32"
         Foreground="#FFF6EACB" />
      <Button Name="StartButton" Content="Original: Start" Width="300" Height="66"
         Margin="0,15,0,0" Command="{{Binding ButtonMainMenuCommand}}"
         CommandParameter="Multiplayer" />
      <Button Name="SettingsButton" Content="Einstellungen"
         Command="{{Binding ButtonMainMenuCommand}}" CommandParameter="Roadmap" />
    </StackPanel>
  </Grid>
</UserControl>
''').encode("utf8")
DEFAULT_THEME=(f'''<ResourceDictionary xmlns="{PRES}" xmlns:x="{XNS}">
  <Color x:Key="Color.Accent">#FF224466</Color>
  <Color x:Key="Color.Text">#FFF3F0D6</Color>
  <SolidColorBrush x:Key="Brush.Accent" Color="{{StaticResource Color.Accent}}"/>
</ResourceDictionary>
''').encode("utf8")
DEFAULT_LOCALE=("deDE\n>>TEXTSTART\n>>6-----\nOriginaler Menütext\n").encode("utf8")


@dataclass(frozen=True)
class DemoStep:
    title:str
    explain:str
    function:str


@dataclass(frozen=True)
class DemoModule:
    key:str
    title:str
    summary:str
    steps:tuple[DemoStep,...]
    input_type:str=""


MODULES=(
 DemoModule("noesis","Original-Menüseiten / Noesis",
    "Originale XAML-Bäume laden, Controls frei ändern, Revisionen und echte Mod-Patches erzeugen.",
    (DemoStep("Originalansicht vorbereiten","Lädt echte gewählte Spiel-XAML oder eine mitgelieferte eigenständige XAML-Beispielseite in eine private Kopie.","VisualXamlDocument"),
     DemoStep("Controls wirklich bearbeiten","Ändert Text, Position, Drehung und einen CommandParameter; fügt ein Control in die echte XML-Hierarchie ein.","VisualXamlDocument.edit / move / rotate / insert / save_revision"),
     DemoStep("Gespeicherte Revision erneut öffnen","Lädt das editierbare Ergebnis, ändert es weiter und speichert Version 2 samt Patchhistorie.","VisualXamlDocument.reopen / save_revision"),
     DemoStep("Noesis-Mod-ZIP bauen und prüfen","Packt den tatsächlich erzeugten Patch ein, prüft den ZIP-Inhalt und die unveränderte Quelle.","se_asset_package.build")), "xaml"),
 DemoModule("patch","XAML-Patch-Werkstatt",
    "Historische Patchoperationen wirklich anwenden und als bearbeitbare XAML-Seite weiterführen.",
    (DemoStep("Noesis-Quelle und Patch vorbereiten","Erzeugt aus einem benannten Original-Control eine echte SetAttribute-Patchoperation.","origins_xaml_designer.create_patch"),
     DemoStep("Patch auf XAML anwenden","Führt die Operation auf dem XML-Objektbaum aus und erstellt einen reproduzierbaren Zwischenstand.","apply_existing_patch / save_revision"),
     DemoStep("Eigene Patchfassung exportieren","Ändert den übernommenen Control erneut, speichert Revision 2 und baut ein geprüftes Mod-ZIP.","VisualXamlDocument / se_asset_package.build")),"xaml"),
 DemoModule("pixels","Pixelgrafik / HUD-Editor",
    "PNG importieren, echte Bildpunkte verändern, den Unterschied prüfen und ein Mod-Paket erstellen.",
    (DemoStep("Originalbild anlegen und importieren","Erzeugt eine Beispiel-Grafik und importiert sie über die bestehende HUD-Werkstatt inklusive Baseline.","hud_menu_workspace.import_image"),
     DemoStep("Pixel tatsächlich umzeichnen","Öffnet die importierte PNG, zeichnet Farben und Formen und speichert über die produktive Pixel-Schreibroutine.","hud_menu_workspace.write_png"),
     DemoStep("Vorher/Nachher und Export kontrollieren","Vergleicht tatsächliche Pixel, prüft den Assetstatus 'Bearbeitet' und paketiert die PNG.","hud_menu_workspace.list_assets / se_asset_package.build"))),
 DemoModule("layout","HUD-/Menü-Layout & Ebenen",
    "Ebenen aus echten PNGs verschieben, drehen, speichern, rendern und paketieren.",
    (DemoStep("Ebene aus einem Original-PNG anlegen","Importiert ein echtes PNG in den Projektbaum und legt eine Layout-Szene an.","hud_menu_layout.add_layer"),
     DemoStep("Verschieben, Duplizieren und Drehen","Führt transformierende Modell-Operationen aus und speichert alle Ebenen.","move_layer / duplicate_layer / set_geometry / save_scene"),
     DemoStep("Komposition wirklich rendern","Erstellt eine neue gerenderte PNG aus den Ebenen, lädt sie erneut und prüft die Export-Manifeste.","export_composition / audit_export"),
     DemoStep("Sauberes Layout-Paket erstellen","Baut eine isolierte Quelle aus der tatsächlichen Komposition und daraus ein Mod-ZIP.","prepare_package_source / se_asset_package.build"))),
 DemoModule("theme","Noesis-Themes & Farbpaletten",
    "Echte ResourceDictionary-Farben ändern, Brush-Bindings erhalten, eigenes Theme paketieren.",
    (DemoStep("Original-Theme laden","Lädt ein Noesis ResourceDictionary mit realen Color- und Brush-Einträgen.","read_palette"),
     DemoStep("Farben wirklich bearbeiten","Ändert den Accent-Farbwert über die produktive Theme-Werkstatt.","save_palette"),
     DemoStep("Bindings und Mod-ZIP überprüfen","Liest Theme erneut, vergleicht Farben und packt das Ergebnis als Resource-Override.","read_palette / se_asset_package.build"))),
 DemoModule("locale","Sprachdateien / Menütexte",
    "Eine echte crusader.txt ändern, importieren und im Mod-Paket verifizieren.",
    (DemoStep("Sprachdatei vorbereiten","Erzeugt eine gültige deutsche Sprachressource mit den originaltypischen Markern.","Locales/de-DE/crusader.txt"),
     DemoStep("Menütext bearbeiten und importieren","Schreibt einen neuen Text und übernimmt ihn über die produktive Ressourcenwerkstatt.","hud_menu_workspace.import_media"),
     DemoStep("Sprachressource paketieren","Prüft, dass der geänderte Text wirklich im generierten ZIP enthalten ist.","se_asset_package.build"))),
 DemoModule("campaign","Origins-Kampagnen & C#-Runtime",
    "Missionsseiten und echten C#-Quellcode erzeugen, offline kompilieren und ausführen.",
    (DemoStep("Original-C#-Kern und Missionen vorbereiten","Zeigt einen Auszug des vorhandenen SpriteSuite-Origins-C#-Kerns und einen Kampagnenplan.","OriginsRuntimeCore.cs / validate_campaign"),
     DemoStep("Kampagne wirklich generieren","Erzeugt echte Missions-XAML, C#-Daten und Fortschrittsstrukturen in einem Kandidaten.","write_campaign_draft"),
     DemoStep("Quelldaten und Zuordnungen prüfen","Liest den generierten Kandidaten erneut, validiert 3 Missionskarten und die Buttons.","verify_campaign"),
     DemoStep("C# tatsächlich kompilieren und ausführen","Kompiliert den generierten Code mit dem vorhandenen .NET-Compiler und führt echte Verhaltenstests aus.","run_offline_qa"))),
 DemoModule("season","Atlas-/Saisonwerkstatt",
    "Echte PNG-Atlanten und Kartenrouten erzeugen; C#-Saisonlogik kompilieren und testen.",
    (DemoStep("Saison-Atlas erzeugen","Rendert einen bearbeitbaren PNG-Atlas plus JSON-Frames und prüft eine historische GM-Gruppe.","Pillow / GM_IDS"),
     DemoStep("Saison-Paket generieren","Verarbeitet Atlas-Bytes und Map-Routen zu einem privaten Saisonpaket mit C#-Quelle.","write_season_draft"),
     DemoStep("Kampagnendaten als Testpartner erzeugen","Erzeugt eine separat editierbare Kampagne für den gemeinsamen Runtime-Test.","write_campaign_draft"),
     DemoStep("Kartenwechsel wirklich in C# testen","Kompiliert Kampagnen- und Saisonrouten gemeinsam; prüft MapLoad und MapUnload offline.","run_offline_qa"))),
 DemoModule("package","Mod-Paketbuilder / Ressourcen",
    "Echte Override- und Patch-Dateien vorbereiten, prüfen und als BepInEx-Mod-ZIP ausgeben.",
    (DemoStep("Quellressourcen für einen Mod vorbereiten","Importiert Bild und ein gültiges XML-Patchfragment in den richtigen Ressourcenpfad.","import_image / import_patch"),
     DemoStep("Quellressourcen tatsächlich bearbeiten","Bearbeitet die PNG und kontrolliert alle vorhandenen Paketressourcen.","write_png / audit_assets"),
     DemoStep("Mod-ZIP erzeugen und auslesen","Baut den vorhandenen Paketbuilder und prüft CRC, Manifest und veränderte Bildbytes.","se_asset_package.build / zipfile"))),
 DemoModule("video","Menüvideo / WebM-Override",
    "Ein vom Anwender ausgewähltes echtes WebM lesen, ins Projekt übernehmen und paketieren (kein Videoencoder).",
    (DemoStep("Echtes WebM prüfen","Öffnet das ausgewählte Originalvideo lesend und prüft EBML/WebM-Header und Dateigröße.","se_asset_package._validate_webm"),
     DemoStep("WebM als Mod-Override importieren","Kopiert die echten unveränderten Videobytes über den offiziellen Importpfad.","hud_menu_workspace.import_media"),
     DemoStep("Video-Paket verifizieren","Packt den Video-Override und vergleicht die tatsächlich ausgelieferten Bytes.","se_asset_package.build")),"video"),
)
MODULE_BY_KEY={module.key:module for module in MODULES}


def _sha(path:Path)->str:
    digest=sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition:bool,message:str)->None:
    if not condition:raise RuntimeError(message)


def _picture(path:Path,*,width=224,height=112,label="ORIGINAL")->None:
    img=Image.new("RGBA",(width,height),(34,61,93,255))
    draw=ImageDraw.Draw(img)
    draw.rectangle((8,8,width-9,height-9),outline=(240,205,128,255),width=3)
    draw.rectangle((26,28,width-26,height-29),fill=(65,121,166,255))
    draw.text((34,37),label,fill=(250,250,231,255))
    img.save(path)


def _make_source(session:"DemoSession",data:bytes,name:str)->Path:
    file=session.samples/name
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_bytes(data)
    return file


def _zip_contains(result:dict,expected:str,needle:bytes|None=None)->Path:
    zip_path=Path(result["zip"])
    _require(zip_path.is_file(),"Der Paketbuilder hat kein ZIP erzeugt")
    with ZipFile(zip_path) as archive:
        _require(archive.testzip() is None,"Mod-ZIP CRC-Fehler")
        content=archive.read(f"BepInEx/plugins/{result['guid']}/{expected}")
        if needle is not None:_require(needle in content,"Export enthält die Veränderung nicht")
    _require(result["runtime_dll"] is False,"Ungeprüfte Runtime-DLL im Mod-Paket")
    return zip_path


@dataclass
class DemoSession:
    module:DemoModule
    root:Path
    project:Path
    samples:Path
    source:Path|None=None
    initial_source_hash:str|None=None
    next_step:int=0
    data:dict=field(default_factory=dict)
    receipts:list[dict]=field(default_factory=list)

    @classmethod
    def start(cls,module_key:str,*,source:Path|str|None=None)->"DemoSession":
        module=MODULE_BY_KEY.get(module_key)
        if module is None:raise ValueError("Unbekanntes Demo-Modul")
        if module.input_type=="video" and source is None:
            raise ValueError("Diese Demo benötigt ein echtes eigenes .webm-Video")
        if module.input_type=="game_dir" and source is None:
            raise ValueError("Für Native-ABI-Demo echtes Spielverzeichnis nur lesend wählen")
        external=Path(source) if source is not None else None
        if external is not None:
            if module.input_type=="game_dir":
                if not external.is_dir() or is_link_or_reparse(external):
                    raise ValueError("Installiertes Spielverzeichnis nicht verfügbar")
            elif (not external.is_file() or is_link_or_reparse(external) or
                    external.stat().st_size>256*1024**2):
                raise ValueError("Die ausgewählte Originaldatei ist nicht lesbar oder zu groß")
            if module.input_type=="xaml" and external.suffix.lower()!=".xaml":
                raise ValueError("Bitte eine originale Noesis-XAML auswählen")
            if module.input_type=="video" and external.suffix.lower()!=".webm":
                raise ValueError("Bitte eine echte WebM-Datei auswählen")
            if module.input_type=="png" and external.suffix.lower()!=".png":
                raise ValueError("Bitte ein echtes PNG-Spielbild auswählen")
            if not module.input_type:
                raise ValueError("Dieses Modul benötigt keine externe Quelldatei")
        base=work.WORK.resolve()
        parent=base/"demo-sessions"
        if is_link_or_reparse(parent):raise ValueError("Verknüpftes Demo-Ziel nicht erlaubt")
        parent.mkdir(parents=True,exist_ok=True)
        name=module.key+"-"+token_hex(7)
        root=parent/name
        root.mkdir() # Newly created: never reuse an existing session
        samples=root/"original-beispiele";samples.mkdir()
        project=root/"mod-projekt";project.mkdir()
        return cls(module=module,root=root,project=project,samples=samples,
                   source=external,
                   initial_source_hash=_sha(external) if external and external.is_file() else None)

    @property
    def complete(self):
        return self.next_step==len(self.module.steps)

    def _original(self,name="FrontendMenus.xaml")->Path:
        if self.source is not None and self.module.input_type=="xaml":
            return _make_source(self,self.source.read_bytes(),"XAML/"+name)
        # A self-authored UI asset really exists at the Noesis relative URI.
        png=self.samples/"Images"/"DemoMenu.png"
        png.parent.mkdir(parents=True,exist_ok=True)
        if not png.exists():
            _picture(png,width=480,height=270,label="DEMO MENU")
        return _make_source(self,DEFAULT_XAML,"XAML/"+name)

    def _asset_mod(self,slug:str,relative:str,marker:bytes|None=None)->dict:
        guid="demo"+self.root.name.split("-")[-1]+slug
        result=asset_mod.build(self.project,guid,name="SpriteSuite Demo "+self.module.title,
                               author="SpriteSuite Demo")
        zip_path=_zip_contains(result,relative,marker)
        return {"zip":str(zip_path),"asset_mod_folder":result["asset_mod_folder"],
                "guid":guid,"source_files":result["source_files"]}

    def _unchanged_external_source(self):
        if self.source is not None:
            if self.module.input_type=="game_dir":
                _require(self.source.is_dir() and not is_link_or_reparse(self.source),
                         "Das ausgewählte Spielverzeichnis ist nicht mehr gültig")
            else:
                _require(self.source.is_file() and _sha(self.source)==self.initial_source_hash,
                         "Die externe Originaldatei wurde unerwartet verändert")

    def execute_next(self)->dict:
        if self.complete:raise ValueError("Alle Schritte dieses Moduls sind abgeschlossen")
        index=self.next_step
        method=getattr(self,"_do_"+self.module.key+"_"+str(index),None)
        if method is None:raise RuntimeError("Demo-Schritt ohne Implementierung: "+self.module.key)
        self._unchanged_external_source()
        record=method()
        self._unchanged_external_source()
        _require(isinstance(record,dict) and record.get("outputs"),
                 "Demo hat keinen echten überprüfbaren Ausgabestand erzeugt")
        for output in record["outputs"]:
            _require(Path(output).is_file(),"Demo-Ausgabe fehlt: "+output)
        # Preserve the exact bytes of each small step output. Later steps can
        # deliberately overwrite the current mod-patch or image: that is not
        # corruption. Original step snapshots remain independently inspectable.
        snapshots=self.root/"belege"/("schritt-%02d"%(index+1))
        snapshots.mkdir(parents=True,exist_ok=True)
        outputs=[]
        for i,p in enumerate(record["outputs"]):
            file=Path(p)
            digest=_sha(file)
            entry={"path":str(file),"bytes":file.stat().st_size,"sha256":digest}
            if file.stat().st_size<=16*1024**2:
                saved=snapshots/(str(i)+"-"+file.name)
                shutil.copyfile(file,saved)
                _require(_sha(saved)==digest,"Der Schritt-Snapshot stimmt nicht")
                entry["snapshot"]=str(saved)
            outputs.append(entry)
        report={
            "index":index,"title":self.module.steps[index].title,
            "function":self.module.steps[index].function,
            "outputs":outputs,
            "message":record.get("message","Schritt tatsächlich ausgeführt"),
            "preview":record.get("preview",str(record["outputs"][0])),
            "source":record.get("source"),
            "script":record.get("script"),
            "game_original_modified":False,
            "native_game_calls":False,
        }
        self.receipts.append(report)
        self.next_step+=1
        manifest={
            "schema":"spritesuite.demo-execution.v1",
            "module":self.module.key,"module_title":self.module.title,
            "completed":self.complete,"next_step":self.next_step,
            "steps":self.receipts,"project":str(self.project),
            "requires_in_game_validation":self.module.key in {"noesis","patch","campaign","season","video","native_menu"},
            "installation_modified":False,
        }
        proof=self.root/"demo-protokoll.json"
        staging=self.root/".demo-protokoll.tmp"
        staging.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
        os.replace(staging,proof)
        return report

    def verify_receipts(self)->dict:
        """Check all step snapshots and only the LATEST bytes of mutable paths.

        User edits are reported as a difference, never forbidden or silently
        reverted. Intermediate outputs intentionally superseded by later steps
        are validated using their immutable per-step snapshots.
        """
        latest={}
        for entry in self.receipts:
            for item in entry["outputs"]:
                latest[item["path"]]=item["sha256"]
        problems=[]
        snapshots=0
        for entry in self.receipts:
            for item in entry["outputs"]:
                saved=item.get("snapshot")
                if saved:
                    snapshots+=1
                    candidate=Path(saved)
                    if (not candidate.is_file() or is_link_or_reparse(candidate)
                        or _sha(candidate)!=item["sha256"]):
                        problems.append("Historischer Snapshot geändert: "+str(candidate))
        for path,digest in latest.items():
            file=Path(path)
            if (not file.is_file() or is_link_or_reparse(file) or
                _sha(file)!=digest):
                problems.append("Aktueller Stand wurde extern verändert: "+path)
        return {"valid":not problems,"problems":problems,
                "current_files":len(latest),"historical_snapshots":snapshots,
                "module":self.module.key,"completed":self.complete}

    def _do_pixels_0(self):
        original=self.samples/"OriginalHUD.png"
        _picture(original,label="ORIGINAL HUD")
        imported=work.import_image(original,project=self.project,folder="HUD / UI-Sprites",
                                  name="DemoHUD")
        self.data["relative"]=imported.relative_to(self.project).as_posix()
        self.data["initial"]= _sha(imported)
        return {"outputs":[str(original),str(imported)],"source":str(original),
                "preview":str(imported),
                "message":"Eigenes Original-PNG erzeugt und mit echten Import-Baseline-Daten kopiert"}
    def _do_pixels_1(self):
        relative=self.data["relative"]
        file=self.project/relative
        old=file.read_bytes()
        with Image.open(file) as img:converted=img.convert("RGBA")
        paint=ImageDraw.Draw(converted)
        paint.rectangle((75,19,157,84),fill=(233,67,88,255))
        paint.line((16,100,200,14),fill=(251,240,171,255),width=5)
        out=BytesIO();converted.save(out,format="PNG")
        work.write_png(relative,out.getvalue(),project=self.project,
                       expected_sha256=sha256(old).hexdigest())
        with Image.open(file) as after:
            _require(after.convert("RGBA").getpixel((80,35))==(233,67,88,255),
                     "Pinseländerung nicht wirklich auf Datenträger")
        return {"outputs":[str(file)],"source":str(self.samples/"OriginalHUD.png"),
                "preview":str(file),"message":"Pixel auf Datenträger neu gezeichnet und erneut gelesen"}
    def _do_pixels_2(self):
        from hud_menu_workspace import list_assets
        items=list_assets(self.project)
        _require(any(x.relative_path==self.data["relative"] and x.status=="Bearbeitet"
                     for x in items),"HUD-Änderungsstatus nicht erkannt")
        result=self._asset_mod("pixel",self.data["relative"])
        return {"outputs":[result["zip"]],"source":str(self.project/self.data["relative"]),
                "message":"Veränderte Grafik nach Baseline-Vergleich im CRC-geprüften Mod-ZIP"}

    def _do_layout_0(self):
        original=self.samples/"OriginalEbene.png"
        _picture(original,width=195,height=120,label="LAYER 1")
        dst=work.import_image(original,project=self.project,name="OriginalEbene")
        self.data["relative"]=dst.relative_to(self.project).as_posix()
        scene=layout.Scene(name="demo-ebenen",width=640,height=360,
          target_resource="Override/Assets/GUI/Images/DemoComposite.png")
        layer=layout.add_layer(scene,self.project,self.data["relative"],x=46,y=34)
        self.data["scene"]=scene
        self.data["layer_id"]=layer.id
        return {"outputs":[str(dst)],"preview":str(dst),
                "source":str(original),"message":"Eine echte importierte PNG-Ebene im Layoutmodell angelegt"}
    def _do_layout_1(self):
        scene=self.data["scene"]
        layout.move_layer(scene,self.data["layer_id"],87,49)
        other=layout.duplicate_layer(scene,self.data["layer_id"],dx=55,dy=76)
        layout.set_geometry(scene,other.id,rotation=26.,opacity=190,width=240,height=150)
        file,digest=layout.save_scene(scene,self.project)
        self.data["scene_hash"]=digest
        _require(len(layout.load_scene(self.project,scene.name)[0].layers)==2,
                 "Layout wurde nicht mit beiden Ebenen geladen")
        return {"outputs":[str(file)],"preview":str(file),
                "message":"Verschieben, Kopieren, Rotieren, Transparenz und Speichern ausgeführt"}
    def _do_layout_2(self):
        scene=self.data["scene"]
        out=layout.export_composition(scene,self.project,resource_name="DemoComposite",
                                      scene_sha256=self.data["scene_hash"])
        layout.audit_export(scene,self.project,scene_sha256=self.data["scene_hash"])
        with Image.open(out["png"]) as image:
            _require(image.size==(640,360),"Gerenderte Bildgröße stimmt nicht")
        self.data["composite"]=out["png"]
        return {"outputs":[out["png"],out["manifest"]],"preview":out["png"],
                "message":"Echte 640×360-Pixelkomposition neu gerendert und geprüft"}
    def _do_layout_3(self):
        folder=layout.prepare_package_source(self.data["scene"],self.project,
                              scene_sha256=self.data["scene_hash"])
        guid="demo"+self.root.name.split("-")[-1]+"layout"
        result=asset_mod.build(folder,guid,name="Demo Ebenen",author="SpriteSuite")
        zip_path=_zip_contains(result,"Override/Assets/GUI/Images/DemoComposite.png")
        return {"outputs":[str(zip_path)],"source":self.data["composite"],
                "message":"Nur die tatsächlich gebackene Komposition im Mod-ZIP"}

    def _do_noesis_0(self):
        file=self._original()
        doc=visual.VisualXamlDocument(file)
        self.data["xaml_source"]=str(file)
        self.data["original_count"]=len(doc.outline())
        image=self.samples/"Images"/"DemoMenu.png"
        outputs=[str(file)]+([str(image)] if image.is_file() else [])
        return {"outputs":outputs,"source":str(file),
                "preview":str(image if image.is_file() else file),
                "message":f"{len(doc.outline())} originale XML-Knoten eingelesen; "
                          "eigene Demo-Grafik bei Bedarf daneben angezeigt"}
    def _do_noesis_1(self):
        source=Path(self.data["xaml_source"])
        doc=visual.VisualXamlDocument(source)
        nodes=doc.outline()
        button=next((x for x in nodes if x.tag=="Button" and x.attrs.get("Name")),None)
        grid=next((x for x in nodes if x.tag=="Grid"),None)
        _require(button is not None and grid is not None,
                 "Original-XAML hat keinen editierbaren benannten Button und Grid")
        doc.edit(button.path,"Content","SpriteSuite: Demo-Start")
        doc.edit(button.path,"CommandParameter","SpriteSuiteDemoAction")
        doc.move(button.path,35,21)
        doc.rotate(button.path,8)
        doc.insert(grid.path,"TextBlock",{"Name":"SpriteSuite_DemoHeadline",
                    "Text":"Ein eigener Menütext","FontSize":"36"})
        saved=doc.save_revision(self.project,overwrite_existing=True)
        self.data["revision"]=saved["revision_dir"]
        self.data["patch"]=saved["patch"]
        return {"outputs":[saved["patch"],str(Path(saved["revision_dir"])/"edited.xaml")],
                "source":str(source),"preview":str(Path(saved["revision_dir"])/"edited.xaml"),
                "message":"Original-Controls bearbeitet; neue Seite im echten XAML-Baum; Patchrevision 1"}
    def _do_noesis_2(self):
        doc=visual.VisualXamlDocument.reopen(Path(self.data["revision"]))
        target=next(x for x in doc.outline() if x.attrs.get("Name")=="SpriteSuite_DemoHeadline")
        doc.edit(target.path,"Text","Nach Speichern weiterbearbeitet")
        saved=doc.save_revision(self.project,overwrite_existing=True)
        self.data["revision"]=saved["revision_dir"]
        self.data["patch"]=saved["patch"]
        _require((Path(saved["revision_dir"])/"previous-package-patch.xaml").is_file(),
                "Vorheriger Patch nicht historisiert")
        _require(b"Nach Speichern weiterbearbeitet" in Path(saved["patch"]).read_bytes(),
                 "Neue Änderung nicht im Mod-Patch")
        return {"outputs":[saved["patch"],str(Path(saved["revision_dir"])/"edited.xaml")],
                "preview":saved["patch"],"message":"Revision 2 erneut geladen, editiert und alten Patch gesichert"}
    def _do_noesis_3(self):
        result=self._asset_mod("noesis","Patches/Assets/GUI/XAML/FrontendMenus.xaml",
                               b"Nach Speichern weiterbearbeitet")
        return {"outputs":[result["zip"]],"source":self.data["patch"],
                "message":"Aktueller frei bearbeiteter Noesis-Patch im realen BepInEx-Mod-ZIP"}

    def _do_patch_0(self):
        source=self._original()
        from origins_xaml_designer import controls,create_patch
        targets=[x for x in controls(source) if x.tag=="Button"]
        _require(targets,"Noesis-Original bietet keine benannten editierbaren Buttons")
        node=targets[0]
        blob,record=create_patch(source,xpath=node.xpath,operation="SetAttribute",
                              property_name="Margin",value="22,80,0,0")
        path=_make_source(self,blob,"Original-Patch.xaml")
        self.data["patch_source"]=str(path)
        self.data["xaml_source"]=str(source)
        self.data["target_name"]=node.name
        return {"outputs":[str(source),str(path)],"source":str(source),
                "preview":str(path),"message":"Originalcode in einen echten SetAttribute-XAML-Patch übertragen"}
    def _do_patch_1(self):
        doc=visual.VisualXamlDocument(Path(self.data["xaml_source"]))
        report=visual.apply_existing_patch(doc,Path(self.data["patch_source"]),strict=True)
        _require(report["applied_operations"]==1 and report["skipped_operations"]==0,
                 "Bestehender Patch nicht eindeutig angewendet")
        saved=doc.save_revision(self.project,overwrite_existing=True)
        self.data["revision"]=saved["revision_dir"]
        return {"outputs":[saved["patch"]],"source":self.data["patch_source"],
                "message":"SetAttribute auf echter XML-Hierarchie angewendet und gespeichert"}
    def _do_patch_2(self):
        doc=visual.VisualXamlDocument.reopen(Path(self.data["revision"]))
        item=next(x for x in doc.outline() if x.attrs.get("Name")==self.data["target_name"])
        doc.edit(item.path,"Content","Aus Original-Patch weiterbearbeitet")
        saved=doc.save_revision(self.project,overwrite_existing=True)
        result=self._asset_mod("patch","Patches/Assets/GUI/XAML/FrontendMenus.xaml",
                         b"Aus Original-Patch weiterbearbeitet")
        return {"outputs":[saved["patch"],result["zip"]],"source":self.data["patch_source"],
                "message":"Übernommene Original-Patchoperation manuell erweitert und paketiert"}

    def _do_theme_0(self):
        src=_make_source(self,DEFAULT_THEME,"Theme.Brushes.DarkRed.xaml")
        self.data["theme_source"]=str(src)
        before,root,colors=read_palette(src)
        _require("Color.Accent" in colors,"Farbpaletten-Resource-Key fehlt")
        return {"outputs":[str(src)],"preview":str(src),
                "message":"Color und SolidColorBrush aus echtem Noesis ResourceDictionary gelesen"}
    def _do_theme_1(self):
        source=Path(self.data["theme_source"])
        output,record=save_palette(source,self.project,{"Color.Accent":"#FF36A7D9"})
        self.data["theme_output"]=str(output)
        _require(b"#FF36A7D9" in output.read_bytes(),"Theme-Farbwert wurde nicht ersetzt")
        return {"outputs":[str(output)],"source":str(source),
                "message":"Original-Farbwert durch neue Farbe im tatsächlichen Override geändert"}
    def _do_theme_2(self):
        original=Path(self.data["theme_source"])
        target=Path(self.data["theme_output"])
        _,_,colors=read_palette(target)
        _require(colors["Color.Accent"]=="#FF36A7D9","Gespeichertes Theme inkonsistent")
        _require(b"StaticResource Color.Accent" in target.read_bytes(),
                 "Originale Brush-Bindings gingen verloren")
        result=self._asset_mod("theme","Override/Assets/GUI/XAMLResources/Theme.Brushes.DarkRed.xaml",
                                b"#FF36A7D9")
        return {"outputs":[result["zip"]],"source":str(original),
                "message":"Theme und bestehende Brush-Bindings ausgelesen und paketiert"}

    def _do_locale_0(self):
        source=_make_source(self,DEFAULT_LOCALE,"crusader-original.txt")
        self.data["locale_original"]=str(source)
        return {"outputs":[str(source)],"preview":str(source),
                "message":"Gültigen alten Locales-Markup- und Textblock erzeugt"}
    def _do_locale_1(self):
        source=Path(self.data["locale_original"])
        modified=_make_source(self,source.read_bytes().replace(
            b"Originaler Men\xc3\xbctext","Neuer Demo-Menütext".encode("utf8")),"crusader-neu.txt")
        _require(modified.read_bytes()!=source.read_bytes(),
                 "Menütext blieb trotz Bearbeitung unverändert")
        dest=work.import_media(modified,resource="Locales/de-DE/crusader.txt",
                               project=self.project)
        self.data["locale_output"]=str(dest)
        return {"outputs":[str(modified),str(dest)],"source":str(source),
                "message":"Neuen Text geschrieben und als Locales/de-DE/crusader.txt importiert"}
    def _do_locale_2(self):
        marker="Neuer Demo-Menütext".encode("utf8")
        result=self._asset_mod("locale","Locales/de-DE/crusader.txt",marker)
        return {"outputs":[result["zip"]],"source":self.data["locale_original"],
                "message":"Der neue Menütext steht tatsächlich im Mod-ZIP"}

    def _do_campaign_0(self):
        core=Path(__file__).resolve().parents[1]/"runtime"/"SpriteSuite.Origins.Authoring"/"OriginsRuntimeCore.cs"
        _require(core.is_file(),"Mitgelieferter Originals-Origins-C#-Laufzeitkern fehlt")
        source=_make_source(self,"\n".join(core.read_text("utf8").splitlines()[:105]).encode("utf8"),
                            "OriginsRuntimeCore-Ausschnitt.cs")
        plan={"name":"demo-kampagne","title":"SpriteSuite Demo-Kampagne",
              "missions":[{"number":i,"title":f"Mission {i}: Originalstil",
                           "map":f"Demo {i}.map","act":"Akt I"}
                          for i in range(1,4)]}
        checked=author.validate_campaign(plan)
        doc=_make_source(self,json.dumps(plan,ensure_ascii=False,indent=2).encode("utf8"),
                         "Kampagne.original.json")
        self.data["campaign"]=plan
        return {"outputs":[str(source),str(doc)],"preview":str(doc),
                "source":str(source),"message":"Echte OriginsRuntimeCore.cs und 3 sichere Missionsrouten vorbereitet"}
    def _do_campaign_1(self):
        proof=author.write_campaign_draft(self.project,self.data["campaign"])
        output=Path(proof["output"])
        self.data["campaign_dir"]=str(output)
        files=[output/"OriginsCampaignData.g.cs",output/"FrontendMenus.draft.xaml",
               output/"campaign-plan.json"]
        _require(all(x.is_file() for x in files),"Kampagnengenerator hat Dateien ausgelassen")
        return {"outputs":[str(x) for x in files],
                "source":str(self.samples/"OriginsRuntimeCore-Ausschnitt.cs"),
                "preview":str(files[0]),"message":"3 Missionen und tatsächliche C#/XAML-Dateien generiert"}
    def _do_campaign_2(self):
        plan,code=runtime_qa.verify_campaign(self.project,"demo-kampagne")
        _require(len(plan["missions"])==3 and b"new Mission" in code,
                 "C#-Quelldaten oder Missionsanzahl fehlerhaft")
        path=Path(self.data["campaign_dir"])/"qa-status.json"
        return {"outputs":[str(path)],"preview":str(path),
                "message":"Generierte Quelldateien und referenzierte Missionskarten erneut geprüft"}
    def _do_campaign_3(self):
        report=runtime_qa.run_offline_qa(self.project,"demo-kampagne")
        _require(report["offline_behavior_tests_passed"] is True,
                 "C#-Verhaltenstest nicht ausgeführt")
        _require(report["steam_build_abi_attested"] is False,
                 "Ungeprüfte native Freigabe im Report")
        path=Path(report["output"])/"behavior.log"
        _require("ORIGINS_AUTHORED_QA_ASSERTIONS=" in path.read_text("utf8"),
                 "Keine echten C#-Testassertionen aufgezeichnet")
        return {"outputs":[str(path),str(Path(report["output"])/"qa-report.json")],
                "source":str(Path(self.data["campaign_dir"])/"OriginsCampaignData.g.cs"),
                "message":"C# real kompiliert und Tests ausgeführt; keine nativen Steam-Aufrufe"}

    def _do_season_0(self):
        folder=self.samples/"tree_pine";folder.mkdir()
        image=folder/"atlas.png"
        _picture(image,width=128,height=128,label="WINTER")
        metadata=folder/"atlas.json"
        metadata.write_text(json.dumps({"schema":1,"frames":[
            {"name":"tree_1","x":0,"y":0,"w":64,"h":64},
            {"name":"tree_2","x":64,"y":0,"w":64,"h":64}]},
             ensure_ascii=False,indent=2),encoding="utf8")
        self.data["season_folder"]=str(folder)
        return {"outputs":[str(image),str(metadata)],"preview":str(image),
                "message":"Echten 128×128-Pixel-Atlas samt veränderbaren JSON-Frames erstellt"}
    def _do_season_1(self):
        proof=author.write_season_draft(self.project,pack_id="demo-winter",
                   groups={"tree_pine":Path(self.data["season_folder"])},
                   map_routes=["Demo 1.map"])
        directory=Path(proof["output"])
        self.data["season_dir"]=str(directory)
        _,source=runtime_qa.verify_season(self.project,"demo-winter")
        return {"outputs":[str(directory/"pack.json"),
                           str(directory/"OriginsSeasonData.g.cs")],
                "source":str(self.samples/"tree_pine"/"atlas.json"),
                "message":"Atlas-Pixel und MapRoute verarbeitet, C#-Saisondaten wirklich generiert"}
    def _do_season_2(self):
        plan={"name":"demo-winter-kampagne","title":"Jahreszeiten-Demo",
              "missions":[{"number":1,"title":"Winter-Mission",
                           "map":"Demo 1.map","act":"Demo"}]}
        proof=author.write_campaign_draft(self.project,plan)
        target=Path(proof["output"])/"OriginsCampaignData.g.cs"
        return {"outputs":[str(target)],"preview":str(target),
                "message":"Abhängige Testkampagne für gemeinsame C#-Abnahme generiert"}
    def _do_season_3(self):
        report=runtime_qa.run_offline_qa(self.project,"demo-winter-kampagne",
                                          "demo-winter")
        _require(report["offline_behavior_tests_passed"] is True and
                 report["season_pack_id"]=="demo-winter",
                 "Saison- und Kampagnenfunktionen nicht zusammen ausgeführt")
        output=Path(report["output"])/"behavior.log"
        _require("ORIGINS_AUTHORED_QA_ASSERTIONS=" in output.read_text("utf8"),
                 "C#-Runtime hat keine Saisonassertionen ausgeführt")
        return {"outputs":[str(output),str(Path(report["output"])/"qa-report.json")],
                "source":str(Path(self.data["season_dir"])/"OriginsSeasonData.g.cs"),
                "message":"C# MapLoad/MapUnload erfolgreich real getestet; native Engine bleibt frei"}

    def _do_package_0(self):
        original=self.samples/"PluginGrafik.png"
        _picture(original,width=90,height=60,label="MOD")
        dst=work.import_image(original,project=self.project,name="DemoPlugin")
        patch=self.samples/"FrontendMenus.patch.xaml"
        patch.write_text('<Patch><Operation Type="SetAttribute" '
                         "XPath=\"//n:Grid[@Name='MainMenu']\" "
                         'AttributeName="Opacity" Value="0.94"/></Patch>',encoding="utf8")
        copied=work.import_patch(patch,project=self.project,
                                 target_document="XAML/FrontendMenus.xaml")
        self.data["plugin_image"]=str(dst)
        return {"outputs":[str(dst),str(copied)],"source":str(patch),
                "preview":str(patch),"message":"PNG und echter XAML-Patch im Script-Extender-Quelllayout"}
    def _do_package_1(self):
        path=Path(self.data["plugin_image"])
        before=path.read_bytes()
        with Image.open(path) as image:pic=image.convert("RGBA")
        ImageDraw.Draw(pic).rectangle((22,15,63,47),fill=(202,57,116,255))
        stream=BytesIO();pic.save(stream,format="PNG")
        work.write_png(path.relative_to(self.project).as_posix(),stream.getvalue(),
                       project=self.project,expected_sha256=sha256(before).hexdigest())
        audit=work.audit_assets(self.project)
        _require(audit["assets"]==2,"Asset-Audit zählt nicht beide echten Ressourcen")
        report=_make_source(self,json.dumps(audit,indent=2).encode(),"asset-audit.json")
        return {"outputs":[str(path),str(report)],"preview":str(path),
                "message":"Tatsächliche Grafik bearbeitet, PNG+XAML mit Paketvalidator geprüft"}
    def _do_package_2(self):
        result=self._asset_mod("package","Override/Assets/GUI/Images/DemoPlugin.png")
        with ZipFile(result["zip"]) as z:
            _require(any(x.endswith("Patches/Assets/GUI/XAML/FrontendMenus.xaml")
                         for x in z.namelist()),"Menüpatch fehlt im ZIP")
        return {"outputs":[result["zip"]],"source":self.data["plugin_image"],
                "message":"BepInEx/Mod-ZIP mit beiden bearbeiteten Ressourcen und CRC-Abnahme"}

    def _do_video_0(self):
        _require(self.source is not None,"Es wurde kein echtes WebM gewählt")
        asset_mod._validate_webm(self.source,
                       "Override/Assets/GUI/Video/demo-background.webm")
        staged=self.samples/"OriginalMenuVideo.webm"
        shutil.copyfile(self.source,staged)
        _require(_sha(staged)==self.initial_source_hash,"Video-Kopie nicht identisch")
        self.data["video"]=str(staged)
        return {"outputs":[str(staged)],"message":"Echtes WebM geprüft, kopiert und SHA-verglichen"}
    def _do_video_1(self):
        dst=work.import_media(Path(self.data["video"]),
              resource="Override/Assets/GUI/Video/demo-background.webm",
              project=self.project)
        _require(_sha(dst)==_sha(Path(self.data["video"])),
                 "WebM-Import hat echte Videobytes nicht übernommen")
        self.data["video_dst"]=str(dst)
        return {"outputs":[str(dst)],"message":"Videodaten als reales Menüvideo-Override importiert"}
    def _do_video_2(self):
        result=self._asset_mod("video",
                "Override/Assets/GUI/Video/demo-background.webm")
        with ZipFile(result["zip"]) as z:
            bytes_out=z.read(f"BepInEx/plugins/{result['guid']}/"
                             "Override/Assets/GUI/Video/demo-background.webm")
        _require(sha256(bytes_out).hexdigest()==self.initial_source_hash,
                 "Video im ZIP ist nicht mit der echten Vorlage identisch")
        return {"outputs":[result["zip"]],"source":str(self.source),
                "message":"Echtes WebM als Mod-Replacement paketiert (kein Video-Neuencoding)"}


# Specialty modules use the same observed-file execution and receipt contract.
# Register after DemoSession is defined to avoid dependency cycles.
from suite_demo_extra import register as _register_specialty_demos
MODULES=_register_specialty_demos(DemoSession,MODULES)
from suite_demo_more import register as _register_more_demos
MODULES=_register_more_demos(DemoSession,MODULES)
MODULE_BY_KEY={item.key:item for item in MODULES}
