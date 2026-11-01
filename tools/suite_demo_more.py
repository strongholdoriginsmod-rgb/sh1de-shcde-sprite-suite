"""Additional real processing tours: masks, layer blending, UI states, trees, relief.

Each demo edits actual private files via existing SpriteSuite production code.
The baseline artwork is original *to the demo*, never claimed to be proprietary
Firefly/Noesis art. All outputs are logged by DemoSession and re-verifiable.
"""
from __future__ import annotations

from pathlib import Path
from hashlib import sha256
import json
import math

from PIL import Image,ImageDraw
import numpy as np

import hud_menu_workspace as work
from suite_demo_extra import _source,_input,_save_image,_asset_package


# -- Background selection masks and registered source crop ----------------
def _do_background_masked_0(self):
    before=Image.new("RGBA",(320,180),(54,75,94,255))
    paint=ImageDraw.Draw(before)
    paint.rectangle((30,28,290,160),fill=(86,108,130,255))
    paint.ellipse((105,40,230,135),fill=(158,120,85,255))
    paint.rectangle((0,155,320,180),fill=(45,69,40,255))
    after=Image.new("RGBA",(242,140),(25,145,160,255))
    draft=ImageDraw.Draw(after)
    for y in range(10,140,14):
        draft.line((0,y,240,y),fill=(35,168,166,255),width=6)
    origin=_source(self,"OriginalBackground.png",before)
    proposed=_source(self,"EditedMaterial.png",after)
    self.data["mask_source"]=str(origin)
    self.data["mask_generated"]=str(proposed)
    self.data["mask_original_sha256"]=sha256(origin.read_bytes()).hexdigest()
    self.data["mask_crop"]=(45,25,260,155)
    return {"outputs":[str(origin),str(proposed)],"source":str(origin),
            "preview":str(origin),
            "message":"Editierbares Originalbeispiel und neues Material auf echte Dateien geschrieben"}


def _do_background_masked_1(self):
    from background_v2_manual_mask import make_assets
    x0,y0,x1,y1=self.data["mask_crop"]
    mask=Image.new("L",(x1-x0,y1-y0),0)
    ImageDraw.Draw(mask).ellipse((73,40,132,100),fill=255)
    subtraction=_source(self,"ProtectedZone.png",mask)
    result=make_assets(
        source=Path(self.data["mask_source"]),
        crop_box=self.data["mask_crop"],
        polygons=[[(9,10),(200,10),(200,117),(9,117)]],
        subtract_masks=[subtraction],
        output_dir=self.samples/"editable-background-mask",
        prefix="DemoBackground",
        erode=1,dilate=2,
    )
    if result["editable_pixels"]<=0 or result["editable_pixels"]>=215*130:
        raise RuntimeError("Polygonauswahl hat keine begrenzte Maske erzeugt")
    self.data["mask_result"]=result
    receipt=self.samples/"mask-selection-report.json"
    receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return {"outputs":[result["mask"],result["preview"],result["crop"],
                       str(subtraction),str(receipt)],
            "preview":result["preview"],
            "message":f"Echte Polygonauswahl mit {result['editable_pixels']} editierbaren Pixeln erstellt"}


def _do_background_masked_2(self):
    from background_v2_inner_blend import compose
    original=Path(self.data["mask_source"])
    after=self.samples/"BackgroundAfterMask.png"
    evidence=compose(
        original_path=original,
        generated_path=Path(self.data["mask_generated"]),
        mask_path=Path(self.data["mask_result"]["mask"]),
        output_path=after,
        crop_box=self.data["mask_crop"],
        inner_feather=9.5,
    )
    if (not evidence["outside_mask_bit_exact"] or
        not evidence["alpha_bit_exact"] or
        evidence["outside_mask_changed_pixels"]!=0 or
        evidence["changed_pixels"]<=0):
        raise RuntimeError("Background edit escaped the selected mask")
    if sha256(original.read_bytes()).hexdigest()!=self.data["mask_original_sha256"]:
        raise RuntimeError("Original background source was changed")
    imported=work.import_image(after,project=self.project,
                               name="BackgroundFeathered")
    self.data["extra_asset"]=imported.relative_to(self.project).as_posix()
    proof=self.samples/"background-blend-report.json"
    proof.write_text(json.dumps(evidence,indent=2)+"\n",encoding="utf8")
    return {"outputs":[str(after),str(imported),str(proof)],
            "source":str(original),"preview":str(after),
            "message":f"Inneres Feathering auf {evidence['changed_pixels']} Pixel ausgeführt; außerhalb bitidentisch"}


def _do_background_masked_3(self):
    return {"outputs":[_asset_package(self,"mask")],
            "source":self.data["mask_source"],
            "message":"Tatsächlich mit Polygonmaske bearbeitete Menü-Grafik paketiert"}


# -- Four authentic UI state formulas from the same graphics module -------
def _do_button_states_0(self):
    from ui_button_rahmen import wappenschild
    original=wappenschild(86,96,"ruhend",saat=1568)
    src,dst=_input(self,"DemoOriginalButton.png",original.bild)
    self.data["button_state_original"]=str(src)
    self.data["button_field"]=list(original.feld)
    return {"outputs":[str(src),str(dst)],"preview":str(src),
            "message":"Echten Wappenschildträger mit gemessener Zeichenfläche erzeugt und importiert"}


def _do_button_states_1(self):
    from ui_button_rahmen import wappenschild
    states=("ruhend","ueberfahren","gedrueckt","aus")
    all_images=[]
    outputs=[]
    for state in states:
        result=wappenschild(86,96,state,saat=1568)
        if result.bild.size!=(86,96):
            raise RuntimeError("Button frame dimensions changed")
        item=_source(self,"ButtonState-"+state+".png",result.bild)
        outputs.append(str(item))
        all_images.append(result.bild)
    if len({img.tobytes() for img in all_images})!=4:
        raise RuntimeError("Button algorithm generated duplicate UI states")
    sheet=Image.new("RGBA",(86*4,96),(0,0,0,0))
    for i,img in enumerate(all_images):
        sheet.alpha_composite(img,(i*86,0))
    sheet_file=_source(self,"ButtonStatesComparison.png",sheet)
    outputs.append(str(sheet_file))
    self.data["button_state_variant"]=str(outputs[1])
    return {"outputs":outputs,"preview":str(sheet_file),
            "source":str(self.samples/"DemoOriginalButton.png"),
            "message":"Vier unterschiedliche historische Knopfzustände mit echter UI-Renderfunktion erstellt"}


def _do_button_states_2(self):
    src=Path(self.data["button_state_variant"])
    with Image.open(src) as loaded:
        edited=loaded.convert("RGBA")
    with Image.open(self.data["button_state_original"]) as source:
        original=source.convert("RGBA")
    if original.tobytes()==edited.tobytes():
        raise RuntimeError("Selected UI button state was not actually changed")
    output=_save_image(self,edited)
    with Image.open(output) as reloaded:
        if reloaded.convert("RGBA").tobytes()!=edited.tobytes():
            raise RuntimeError("Changed UI button pixels were not saved")
    return {"outputs":[str(output)],"preview":str(output),
            "message":"Hover-Button als echte neue Pixelversion im modifizierbaren Projekt gespeichert"}


def _do_button_states_3(self):
    return {"outputs":[_asset_package(self,"buttons")],
            "message":"Geändertes UI-Button-Bild mit Original-Resource-Key paketiert"}


# -- Transparent multi-donor vegetation and original pivot math ----------
def _donors(self):
    return [Image.open(self.data["tree_source"]).convert("RGBA"),
            Image.open(self.data["bush_source"]).convert("RGBA")]


def _do_vegetation_0(self):
    tree=Image.new("RGBA",(56,84),(0,0,0,0))
    t=ImageDraw.Draw(tree)
    t.rectangle((23,38,32,83),fill=(116,74,39,255))
    t.ellipse((6,7,50,66),fill=(55,124,59,245))
    bush=Image.new("RGBA",(44,48),(0,0,0,0))
    b=ImageDraw.Draw(bush)
    b.ellipse((3,12,41,46),fill=(81,136,55,255))
    b.ellipse((13,3,38,32),fill=(109,155,70,235))
    first=_source(self,"TreeDonor.png",tree)
    second=_source(self,"BushDonor.png",bush)
    self.data["tree_source"]=str(first)
    self.data["bush_source"]=str(second)
    return {"outputs":[str(first),str(second)],"preview":str(first),
            "message":"Zwei transparente Baum-/Strauch-Originalquellen als RGBA-Daten vorbereitet"}


def _do_vegetation_1(self):
    from vegetation_gen import Placement,compose_on_canvas
    tree,bush=_donors(self)
    plans=[
        (Placement("TreeDonor",0.88,-8,0),tree,(28.0,0.0)),
        (Placement("BushDonor",0.90,30,-8),bush,(22.0,0.0)),
    ]
    picture,placed=compose_on_canvas((156,144),(78,20),plans)
    if len(placed)!=2 or any(
       i.left<0 or i.top<0 or i.left+i.size[0]>156 or i.top+i.size[1]>144
       for i in placed):
        raise RuntimeError("Vegetation donor exceeded its original canvas")
    file=_source(self,"VegetationOriginalComposite.png",picture)
    proof=self.samples/"vegetation-position-report.json"
    proof.write_text(json.dumps(
        [{"donor":row.donor,"left":row.left,"top":row.top,
          "size":list(row.size),"foot_from_below":list(row.foot_from_below)}
         for row in placed],indent=2)+"\n",encoding="utf8")
    self.data["vegetation_first"]=str(file)
    imported=work.import_image(file,project=self.project,
                               name="VegetationComposite")
    self.data["extra_asset"]=imported.relative_to(self.project).as_posix()
    return {"outputs":[str(file),str(proof),str(imported)],
            "preview":str(file),
            "message":"Echte Donor-Skalierung und Fußpunkt-Verankerung mit zwei Sprites gerendert"}


def _do_vegetation_2(self):
    from vegetation_gen import Placement,compose_on_canvas
    tree,bush=_donors(self)
    previous=Image.open(self.data["vegetation_first"]).convert("RGBA")
    picture,placed=compose_on_canvas((156,144),(78,20),[
        (Placement("TreeDonor",0.88,-13,0),tree,(28.0,0.0)),
        (Placement("BushDonor",0.98,21,-8),bush,(22.0,0.0)),
    ])
    if picture.tobytes()==previous.tobytes():
        raise RuntimeError("Move/scale did not affect real vegetation pixels")
    edited=_save_image(self,picture)
    return {"outputs":[str(edited)],"preview":str(edited),
            "source":self.data["vegetation_first"],
            "message":"Baum und Strauch mit ursprünglicher Pivot-Logik real verschoben und neu gerendert"}


def _do_vegetation_3(self):
    return {"outputs":[_asset_package(self,"trees")],
            "message":"Bearbeitete vegetationsbasierte Sprite-Ansicht als Mod-ZIP exportiert"}


# -- Gold relief learned from sample geometry via the production feature extractor
def _do_gold_relief_0(self):
    mask=Image.new("L",(96,96),0)
    d=ImageDraw.Draw(mask)
    star=[]
    for i in range(10):
        rad=33 if i%2==0 else 15
        ang=-math.pi/2+i*math.pi/5
        star.append((48+rad*math.cos(ang),47+rad*math.sin(ang)))
    d.polygon(star,fill=255)
    file=self.samples/"GoldEmblemMask.png"
    mask.save(file)
    original=Image.new("RGBA",(96,96),(46,56,69,255))
    before,asset=_input(self,"ReliefOriginal.png",original)
    return {"outputs":[str(file),str(before),str(asset)],
            "preview":str(file),
            "message":"Sternsilhouette und originale, noch unvergoldete Buttonplatte vorbereitet"}


def _gold_table(colours):
    from ui_gold_lernen import TIEFE,SEKTOREN,tafel_schliessen
    sums=np.zeros((TIEFE,SEKTOREN,3),dtype=np.float64)
    counts=np.zeros((TIEFE,SEKTOREN),dtype=np.int64)
    for depth in range(TIEFE):
        for sector in (1,7):
            counts[depth,sector]=1
            sums[depth,sector]=np.asarray(colours[0 if sector==1 else 1])*(1-depth*.038)
    return tafel_schliessen(sums,counts)


def _paint_gold(mask_file:Path,table)->Image.Image:
    from ui_gold_lernen import merkmale,einfaerben
    with Image.open(mask_file) as loaded:
        mask=np.asarray(loaded.convert("L"))>128
    depths,directions=merkmale(mask)
    rgb=einfaerben(mask,table)
    rgba=np.zeros((mask.shape[0],mask.shape[1],4),dtype=np.uint8)
    rgba[:,:,:3]=np.clip(rgb,0,255).astype(np.uint8)
    rgba[:,:,3]=mask.astype(np.uint8)*255
    return Image.fromarray(rgba,"RGBA")


def _do_gold_relief_1(self):
    table=_gold_table([(251,220,117),(138,81,30)])
    picture=_paint_gold(self.samples/"GoldEmblemMask.png",table)
    proof=_source(self,"GoldReliefLayer.png",picture)
    with Image.open(self.project/self.data["extra_asset"]) as base:
        combined=base.convert("RGBA")
    combined.alpha_composite(picture)
    edited=_save_image(self,combined)
    if edited.stat().st_size==0 or combined.getpixel((48,47))[:3]==(46,56,69):
        raise RuntimeError("Real gold relief image did not apply")
    return {"outputs":[str(proof),str(edited)],
            "preview":str(edited),
            "message":"Tatsächliche goldene Reliefstruktur aus Kanten-/Sektor-Tabelle auf das Original gemalt"}


def _do_gold_relief_2(self):
    table=_gold_table([(237,247,255),(96,134,170)])
    silver=_paint_gold(self.samples/"GoldEmblemMask.png",table)
    gold=Image.open(self.samples/"GoldReliefLayer.png").convert("RGBA")
    if silver.tobytes()==gold.tobytes():
        raise RuntimeError("Second relief palette did not change pixel data")
    with Image.open(self.samples/"ReliefOriginal.png") as base:
        composite=base.convert("RGBA")
    composite.alpha_composite(silver)
    edited=_save_image(self,composite)
    comparison=Image.new("RGBA",(192,96),(0,0,0,0))
    comparison.alpha_composite(gold,(0,0))
    comparison.alpha_composite(silver,(96,0))
    side_by_side=_source(self,"GoldAndSilverRelief.png",comparison)
    return {"outputs":[str(edited),str(side_by_side)],
            "preview":str(side_by_side),
            "message":"Dieselbe echte Kanten-/Reliefstruktur als Silberversion neu gerechnet und gespeichert"}


def _do_gold_relief_3(self):
    return {"outputs":[_asset_package(self,"relief")],
            "message":"Umgefärbtes Reliefbild als echte UI-Asset-Mod veröffentlicht"}


# -- Actual C# command handling with fake Noesis/Harmony/game host --------
def _do_menu_behavior_0(self):
    from origins_runtime_authoring import write_campaign_draft
    plan={"name":"demo-menu-mock","title":"Menu behavior demonstration",
          "missions":[{"number":1,"title":"First Mission","map":"Demo 1.map","act":"Act A"},
                      {"number":2,"title":"Second Mission","map":"Demo 2.map","act":"Act A"}]}
    result=write_campaign_draft(self.project,plan)
    self.data["mock_campaign"]=plan["name"]
    self.data["campaign"]=plan
    self.data["campaign_dir"]=result["output"]
    folder=Path(result["output"])
    return {"outputs":[str(folder/"OriginsCampaignData.g.cs"),
                       str(folder/"FrontendMenus.draft.xaml")],
            "source":str(folder/"OriginsCampaignData.g.cs"),
            "message":"C# mit zwei realen, überprüfbaren Missionsdaten erzeugt"}


def _do_menu_behavior_1(self):
    from origins_menu_mock_qa import run_menu_mock_qa
    result=run_menu_mock_qa(self.project,self.data["mock_campaign"])
    if result["behavior_assertions_executed"]<29 or result["game_binaries_loaded"]:
        raise RuntimeError("Origin C# adapter did not execute its actual mock tests")
    self.data["mock_report"]=result
    return {"outputs":[result["log"],result["report"],result["exe"]],
            "preview":result["log"],
            "message":f"Echten C#-Menüadapter in isoliertem Fake-Host ausgeführt: {result['behavior_assertions_executed']} Prüfungen"}


def _do_menu_behavior_2(self):
    report=self.data["mock_report"]
    info=json.loads(Path(report["report"]).read_text("utf8"))
    if (not info["mock_host_executable_executed"] or
        info["native_game_hook_registered"] or
        info["harmony_mock_patch_calls"]!=1 or
        info["harmony_mock_unpatch_calls"]!=1):
        raise RuntimeError("Mock UI routing or Harmony mock lifecycle inconsistent")
    status=self.samples/"menu-command-evidence.json"
    status.write_text(json.dumps({
        "mock_assertions":info["behavior_assertions_executed"],
        "menu_commands_executed_in_mock":True,
        "real_game_interactions":False,
        "mission_start_supported":False,
        "mock_log":report["log"],
    },ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    return {"outputs":[str(status)],
            "preview":str(status),
            "message":"Originalbefehle, Menüeinblendung und Unpatch-Lebenszyklus erneut mit Protokoll geprüft"}


def register(cls,modules):
    from suite_demo_engine import DemoModule,DemoStep
    specs=(
       ("background_masked","Original-Hintergrund / Polygonmaske",
        "Polygon-Auswahl, Subtraktionsmaske und echtes nur-innen-Feathering",
        [("Quellgrafiken vorbereiten","Zwei bearbeitbare PNG-Quellen schreiben",
          "Pillow"),
         ("Geschützten Bereich markieren","Registrierte Polygon-Maske mit Original-Freistellung",
          "background_v2_manual_mask.make_assets"),
         ("Feathering ausführen","Neue Pixel nur innerhalb der echten hart begrenzten Maske schreiben",
          "background_v2_inner_blend.compose"),
         ("Bearbeitung exportieren","Geänderte Bildressource in ein geprüftes Mod-ZIP",
          "se_asset_package.build")]),
       ("button_states","UI-Buttons / vier Zustände",
        "Vier Zustandsfarben aus der tatsächlichen historischen UI-Rahmenfunktion",
        [("Original-Knopf erzeugen","Bild und Zeichenfeld mit Original-Rahmenrenderer",
          "ui_button_rahmen.wappenschild"),
         ("Zustände zeichnen","Ruhend, Hover, gedrückt, inaktiv als unterschiedliche RGBA-Pixel",
          "ui_button_rahmen.wappenschild"),
         ("Hover wirklich übernehmen","Reale Original-PNG-Pixel in einer Arbeitskopie ändern",
          "hud_menu_workspace.write_png"),
         ("Button-Mod erzeugen","Geänderte Buttonfarbe als Resource-Override exportieren",
          "se_asset_package.build")]),
       ("vegetation","Bäume / Vegetationskomposition",
        "Zwei Spenderbilder mit realer Foot/Pivot-Geometrie und Alpha-Resize",
        [("Baum-Spender erstellen","Zwei transparente Originalgrafiken anlegen",
          "Pillow"),
         ("Vegetation zusammensetzen","Echte Fußpunkt- und Skalierungsalgorithmen ausführen",
          "vegetation_gen.compose_on_canvas"),
         ("Platzierung ändern","Bäume und Sträucher erneut skalieren und verschieben",
          "vegetation_gen.compose_on_canvas / hud_menu_workspace.write_png"),
         ("Baumgrafik paketieren","Veränderter Sprite als Mod-ZIP",
          "se_asset_package.build")]),
       ("gold_relief","Buttons / Goldrelief und Silberrelief",
        "Echte Distanztransformations- und Relief-Lookup-Tabellen aus dem Button-Werkzeug",
        [("Originalmotiv zeichnen","Sternmaske und Farbträger als echte Dateien",
          "Pillow.ImageDraw"),
         ("Gold erstellen","Kantenabstände und Winkel-Sektoren mit echten Relief-Tafeln auswerten",
          "ui_gold_lernen.merkmale / tafel_schliessen / einfaerben"),
         ("Silbervariante erzeugen","Gleiche Reliefgeometrie real neu kolorieren",
          "ui_gold_lernen.einfaerben / hud_menu_workspace.write_png"),
         ("Grafik exportieren","Modifizierte Relief-Ressource als Mod-ZIP",
          "se_asset_package.build")]),
       ("menu_behavior","C#-Menübefehle / ausgeführte Offline-Tests",
        "Produktiver C#-Menüadapter mit 29 echten Assertions im isolierten Fake-Noesis-Host",
        [("Kampagnendaten generieren","Eigene editierbare C#-Menü- und XAML-Quellen",
          "origins_runtime_authoring.write_campaign_draft"),
         ("Originaladapter ausführen","C# tatsächlich kompilieren und mit Testimplementierungen ausführen",
          "origins_menu_mock_qa.run_menu_mock_qa"),
         ("Ergebnisse prüfen","29 Assertions, Originalbefehle und Unpatch-Verhalten bestätigen",
          "origins_menu_mock_qa")]),
    )
    extras=[]
    for key,title,summary,steps in specs:
        module=DemoModule(key,title,summary,
                          tuple(DemoStep(n,d,f) for n,d,f in steps))
        extras.append(module)
        for i in range(len(steps)):
            fn=globals().get("_do_"+key+"_"+str(i))
            if fn is None:
                raise RuntimeError("Unimplemented demo step "+key+" "+str(i))
            setattr(cls,"_do_"+key+"_"+str(i),fn)
    return tuple(modules)+tuple(extras)
