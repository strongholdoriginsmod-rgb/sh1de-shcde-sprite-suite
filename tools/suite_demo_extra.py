"""Additional self-contained demonstrations of real SpriteSuite specialty APIs.

All outputs use the same DemoSession / actual-file-receipt engine. Each
specialist's production method is invoked; no fake imported game source.
"""
from __future__ import annotations
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import shutil

from PIL import Image,ImageDraw

import hud_menu_workspace as work


def _source(session,name,image):
    file=session.samples/name
    file.parent.mkdir(parents=True,exist_ok=True)
    image.save(file,format="PNG")
    return file


def _input(session,name,image):
    src=_source(session,name,image)
    file=work.import_image(src,project=session.project,name=Path(name).stem)
    session.data["extra_asset"]=file.relative_to(session.project).as_posix()
    return src,file


def _save_image(session,image):
    relative=session.data["extra_asset"]
    dst=session.project/relative
    old=sha256(dst.read_bytes()).hexdigest()
    stream=BytesIO();image.convert("RGBA").save(stream,format="PNG")
    work.write_png(relative,stream.getvalue(),project=session.project,
                   expected_sha256=old)
    return dst


def _asset_package(session,slug,relative=None):
    resource=relative or session.data["extra_asset"]
    result=session._asset_mod(slug,resource)
    return str(result["zip"])


# -- Stone visual material ----------------------------------------------


def _do_stone_0(self):
    im=Image.new("RGBA",(112,96),(180,110,70,255))
    d=ImageDraw.Draw(im)
    for y in range(9,90,15):
        d.line((0,y,110,y),fill=(111,69,38,255),width=3)
    d.rectangle((3,3,23,25),fill=(60,60,65,255))
    original,dst=_input(self,"SandstoneOriginal.png",im)
    return {"outputs":[str(original),str(dst)],"preview":str(original),
            "message":"Originaltypisches warmes Steinmaterial in die echte Sprite-Werkstatt importiert"}


def _do_stone_1(self):
    from stone_recolour import recolour_image
    image=Image.open(self.project/self.data["extra_asset"]).convert("RGBA")
    output=recolour_image(image)
    dst=_save_image(self,output)
    if output.getpixel((50,50))==image.getpixel((50,50)):
        raise RuntimeError("Sandstein-Neufärbung wurde nicht angewendet")
    if output.getpixel((8,8))[3]!=image.getpixel((8,8))[3]:
        raise RuntimeError("Stein-Transparenz wurde verändert")
    return {"outputs":[str(dst)],"preview":str(dst),
            "message":"Echte HSV-Sandsteinumfärbung ausgeführt, Material-Alpha erhalten"}


def _do_stone_2(self):
    return {"outputs":[_asset_package(self,"stone")],
            "message":"Tatsächlich umgefärbtes Steinmaterial als Sprite-Mod exportiert"}


# -- Animal sprites: hyena -> boar palette -------------------------------


def _do_boar_0(self):
    im=Image.new("RGBA",(92,66),(0,0,0,0))
    draw=ImageDraw.Draw(im)
    draw.ellipse((10,8,80,51),fill=(131,92,44,255))
    draw.ellipse((3,42,86,63),fill=(31,27,24,165))
    src,dst=_input(self,"OriginalAnimal.png",im)
    return {"outputs":[str(src),str(dst)],"preview":str(src),
            "message":"Kleines Tier-Sprite mit Alpha und Bodenschatten vorbereitet"}


def _do_boar_1(self):
    from boar_recolour import faerbe_bild
    before=Image.open(self.project/self.data["extra_asset"]).convert("RGBA")
    converted,count=faerbe_bild(self.project/self.data["extra_asset"])
    if count<=0 or converted.tobytes()==before.tobytes():
        raise RuntimeError("Keilerpalette hat keine sichtbaren Pixel geändert")
    if converted.getchannel("A").tobytes()!=before.getchannel("A").tobytes():
        raise RuntimeError("Keilerumfärbung hat Alpha unerlaubt geändert")
    dst=_save_image(self,converted)
    return {"outputs":[str(dst)],"preview":str(dst),
            "message":f"{count} Tierpixel über echten boar_recolour-Algorithmus umgefärbt"}


def _do_boar_2(self):
    return {"outputs":[_asset_package(self,"boar")],
            "message":"Umgefärbtes Tier-Sprite mit unverändertem Alpha paketiert"}


# -- Actual historical Origins blue/silver palette ----------------------


def _do_historic_palette_0(self):
    im=Image.new("RGBA",(126,72),(0,0,0,0))
    d=ImageDraw.Draw(im)
    d.rectangle((4,6,39,66),fill=(205,20,23,255))
    d.rectangle((44,6,81,66),fill=(223,168,38,255))
    d.rectangle((86,6,121,66),fill=(30,80,211,255))
    src,dst=_input(self,"OriginalButtons.png",im)
    return {"outputs":[str(src),str(dst)],"preview":str(src),
            "message":"Historisches rot-gold-blaues Buttonsprite als Arbeitskopie angelegt"}


def _do_historic_palette_1(self):
    from suite_sh1_origins_palette import recolour
    original=Image.open(self.project/self.data["extra_asset"]).convert("RGBA")
    altered,count=recolour(original,themed=True,dark_blue=True)
    if count<100 or altered.tobytes()==original.tobytes():
        raise RuntimeError("Origins-Farbtransformation hat nicht gegriffen")
    dst=_save_image(self,altered)
    self.data["changed_palette_pixels"]=count
    return {"outputs":[str(dst)],"preview":str(dst),
            "message":f"Historische Origins-Blau/Silberformeln auf {count} Pixel angewendet"}


def _do_historic_palette_2(self):
    return {"outputs":[_asset_package(self,"palettes")],
            "message":"Tatsächlich konvertiertes blau-silbernes Original-UI paketiert"}


# -- Masked team-colour shader preview ----------------------------------


def _do_team_mask_0(self):
    im=Image.new("RGBA",(100,76),(145,123,96,255))
    d=ImageDraw.Draw(im)
    d.ellipse((15,11,82,66),fill=(190,174,144,255))
    mask=Image.new("RGBA",im.size,(0,0,0,255))
    md=ImageDraw.Draw(mask)
    md.ellipse((22,17,75,57),fill=(255,0,0,255))
    src,dst=_input(self,"OriginalUnit.png",im)
    source_mask=_source(self,"OriginalTeamMask.png",mask)
    self.data["team_mask"]=str(source_mask)
    return {"outputs":[str(src),str(dst),str(source_mask)],
            "preview":str(source_mask),
            "message":"Original-Teammasken-Äquivalent erzeugt und Sprite importiert"}


def _do_team_mask_1(self):
    from sandkasten import tint,TEAM_COLOURS
    before=Image.open(self.project/self.data["extra_asset"]).convert("RGBA")
    mask=Image.open(self.data["team_mask"]).convert("RGBA")
    result=tint(before,mask,TEAM_COLOURS["blau"])
    if result.tobytes()==before.tobytes():
        raise RuntimeError("Teammasken-Färbung hat keinen Pixel geändert")
    dst=_save_image(self,result)
    return {"outputs":[str(dst)],"preview":str(dst),
            "message":"Echte Sandbox-Teamfarbmischung anhand des roten Maskenkanals ausgeführt"}


def _do_team_mask_2(self):
    return {"outputs":[_asset_package(self,"team")],
            "message":"Über Masken tatsächlich umgefärbtes Unit-Asset paketiert"}


# -- Sandbox scene with actual projection and generated sprite source ----


class _ExampleFrameSource:
    """Own images, used by the *real* sandkasten rendering pipeline."""
    def __init__(self):
        from sandkasten import Frame
        ground=Image.new("RGBA",(64,32),(0,0,0,0))
        ImageDraw.Draw(ground).polygon(
            [(32,0),(63,16),(32,31),(0,16)],fill=(56,116,64,255))
        actor=Image.new("RGBA",(32,52),(0,0,0,0))
        d=ImageDraw.Draw(actor)
        d.ellipse((9,2,22,16),fill=(221,190,138,255))
        d.rectangle((7,15,25,39),fill=(146,116,71,255))
        d.polygon([(8,41),(12,51),(18,51),(23,41)],fill=(105,90,65,255))
        self.ground=Frame(ground,None,(32.,16.),"demo-image")
        self.actor=Frame(actor,None,(16.,50.),"demo-image")
    def frame(self,group,name):
        return self.actor if group.startswith("body_") else self.ground


def _do_sandbox_scene_0(self):
    scene={"schema":"stronghold-europe.sandkasten.v1","name":"Demo-Fenster",
           "karte":[8,8],
           "boden":{"gruppe":"tile_land8","frames":[1,2,3],"saat":7},
           "objekte":[{"art":"sprite","gruppe":"body_archer","frame":0,
                       "x":4,"y":4,"team":"rot","titel":"Beispielsprite"}],
           "hud":{"sichtbar":False}}
    file=self.samples/"sandbox-scene.json"
    file.write_text(json.dumps(scene,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    self.data["sandbox_scene"]=scene
    return {"outputs":[str(file)],"preview":str(file),
            "message":"Echte Sandkasten-Szene mit 64 Bodenkacheln und Beispiel-Figur vorbereitet"}


def _do_sandbox_scene_1(self):
    import sandkasten
    picture,items,missing=sandkasten.render(
        self.data["sandbox_scene"],_ExampleFrameSource(),
        tick=0.0,grid=True,pivots=True)
    if missing or len(items)<60:
        raise RuntimeError("Sandkasten hat fehlende oder unvollständige Frames")
    src=_source(self,"SandboxFrame0.png",picture)
    self.data["sandbox_frame0"]=str(src)
    return {"outputs":[str(src)],"preview":str(src),
            "message":f"Originale isometrische Sandkasten-Renderfunktion mit {len(items)} Elementen ausgeführt"}


def _do_sandbox_scene_2(self):
    import sandkasten
    scene=self.data["sandbox_scene"]
    scene["objekte"][0]["x"]=6
    image,items,missing=sandkasten.render(
        scene,_ExampleFrameSource(),tick=0.35,grid=True,pivots=True)
    src=_source(self,"SandboxFrame1.png",image)
    if src.read_bytes()==Path(self.data["sandbox_frame0"]).read_bytes():
        raise RuntimeError("Animierte/geänderte Szene lieferte denselben Frame")
    original,final=_input(self,"SandboxImage.png",image)
    return {"outputs":[str(src),str(final)],"preview":str(src),
            "message":"Figur neu positioniert, Szene neu gerendert und modifizierten Frame importiert"}


def _do_sandbox_scene_3(self):
    return {"outputs":[_asset_package(self,"sandbox")],
            "message":"Echte Sandkasten-Renderausgabe als Sprite-/UI-Modpaket exportiert"}


# -- Motif catalogue feature extraction ---------------------------------


def _button_image(fill,shape):
    image=Image.new("RGBA",(96,96),fill)
    draw=ImageDraw.Draw(image)
    if shape=="shield":
        draw.polygon([(48,13),(81,26),(75,69),(48,87),(21,69),(15,26)],
                     fill=(225,220,184,255))
    else:
        draw.ellipse((18,15,77,80),fill=(225,220,184,255))
    return image


def _do_button_motif_0(self):
    inputs=[("MotivGold.png",(175,125,40,255),"shield"),
            ("MotivRot.png",(180,40,51,255),"shield"),
            ("MotivAnders.png",(175,125,40,255),"ellipse")]
    paths=[]
    for name,colour,shape in inputs:
        paths.append(str(_source(self,name,_button_image(colour,shape))))
    self.data["motif_files"]=paths
    return {"outputs":paths,"preview":paths[0],
            "message":"Drei echte Icon-Bitmaps für Originalkatalog-Motiverkennung vorbereitet"}


def _do_button_motif_1(self):
    from ui_button_catalogue import signature,dist
    sources=[Image.open(p) for p in self.data["motif_files"]]
    signatures=[signature(img) for img in sources]
    similar=float(dist(signatures[0],signatures[1]))
    different=float(dist(signatures[0],signatures[2]))
    report={"schema":"spritesuite.demo-motif.v1",
            "distance_same_shape":similar,"distance_different_shape":different,
            "algorithm":"ui_button_catalogue.signature + dist",
            "real_image_files":self.data["motif_files"]}
    output=self.samples/"Motiv-Analyse.json"
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    if similar<0 or different<0:
        raise RuntimeError("Katalogdistanz ungültig")
    return {"outputs":[str(output)],"preview":str(output),
            "message":"Motivgradienten aus echten Bildpixeln gemessen und verglichen"}


def _do_button_motif_2(self):
    images=[Image.open(f).convert("RGBA") for f in self.data["motif_files"]]
    preview=Image.new("RGBA",(96*3,96),(0,0,0,0))
    for i,img in enumerate(images):preview.alpha_composite(img,(i*96,0))
    src,dst=_input(self,"MotivKontaktbogen.png",preview)
    result=_asset_package(self,"motifs")
    return {"outputs":[str(dst),result],"preview":str(dst),
            "message":"Echter Motivvergleich als Kontaktbogen generiert und paketiert"}


# -- Native tile material mapping (provisional in production) ------------


def _do_native_tiles_0(self):
    codes=[[8 if x<8 else 0 if x<16 else 130 if x<24 else 7
            for x in range(32)] for _ in range(16)]
    file=self.samples/"NativeTileCodes.json"
    file.write_text(json.dumps({"codes":codes,"map_in_game_loaded":False},
                               indent=2)+"\n",encoding="utf8")
    self.data["native_codes"]=codes
    return {"outputs":[str(file)],"preview":str(file),
            "message":"Echte Originaltyp-Tilecodes in eine private Testkarte geschrieben"}


def _do_native_tiles_1(self):
    from sandbox_native_canvas import native_tile_material
    colours={"grass":(63,136,67,255),"water":(45,96,164,255),
             "rock":(138,137,126,255),"shore":(208,182,118,255)}
    rows=self.data["native_codes"]
    counts={key:0 for key in colours}
    image=Image.new("RGBA",(len(rows[0])*12,len(rows)*12))
    draw=ImageDraw.Draw(image)
    for y,row in enumerate(rows):
        for x,code in enumerate(row):
            category=native_tile_material(code)
            counts[category]+=1
            draw.rectangle((x*12,y*12,x*12+11,y*12+11),
                           fill=colours[category])
    file=_source(self,"TileMaterialPreview.png",image)
    summary=self.samples/"TileMaterialMapping.json"
    summary.write_text(json.dumps({
        "schema":"sprite-suite.provisional-native-tiles.v1",
        "classification":counts,"mapping":"sandbox_native_canvas.native_tile_material",
        "in_game_mapping_attested":False},indent=2)+"\n",encoding="utf8")
    return {"outputs":[str(file),str(summary)],"preview":str(file),
            "message":"Original-Sandbox-Klassifizierung für 512 Kartenwerte wirklich ausgeführt (provisorisch)"}


def _do_native_tiles_2(self):
    path=Path(self.samples/"TileMaterialPreview.png")
    src,dst=_input(self,"TileExport.png",Image.open(path).convert("RGBA"))
    return {"outputs":[str(dst),_asset_package(self,"tiles")],
            "preview":str(dst),"message":"Kartenvorschau gespeichert und als Sprite-Overlay paketiert"}


# -- Texture codec regression ----------------------------


def _do_bc7_0(self):
    image=Image.new("RGBA",(64,64))
    pixels=image.load()
    for y in range(64):
        for x in range(64):
            pixels[x,y]=((x*17+y*13)%256,(x*31+y*7)%256,
                         (x*3+y*29)%256,255)
    source=_source(self,"OriginalTexture.png",image)
    self.data["bc7_source"]=str(source)
    return {"outputs":[str(source)],"preview":str(source),
            "message":"64×64 Originaltextur mit realen, reproduzierbaren Pixeln erzeugt"}


def _do_bc7_1(self):
    import sandkasten
    from PIL import ImageChops
    original=Image.open(self.data["bc7_source"]).convert("RGBA")
    import etcpak,texture2ddecoder
    result=sandkasten.bc7_roundtrip(original)
    if result.size!=original.size:
        raise RuntimeError("BC7-Roundtrip hat Bildabmessungen geändert")
    # Do not claim that a codec ran just because the helper returned an image:
    # verify actual encoder/decoder bytes with independently invoked libs.
    binary=etcpak.compress_bc7(original.tobytes(),64,64)
    decoded=texture2ddecoder.decode_bc7(binary,64,64)
    if len(decoded)!=64*64*4:
        raise RuntimeError("BC7-Decoder lieferte keine tatsächlichen Bildbytes")
    file=_source(self,"BC7Roundtrip.png",result)
    pack=self.samples/"BC7Data.bin";pack.write_bytes(binary)
    return {"outputs":[str(file),str(pack)],"preview":str(file),
            "message":f"Echten BC7-Encoder und Decoder mit {len(binary)} komprimierten Bytes ausgeführt"}


def _do_bc7_2(self):
    image=Image.open(self.samples/"BC7Roundtrip.png").convert("RGBA")
    src,dst=_input(self,"DecodedBC7.png",image)
    return {"outputs":[str(dst),_asset_package(self,"bc7")],
            "preview":str(dst),"message":"BC7-dekodierte echte Pixel als Sprite-Mod exportiert (keine Engine-Zusage)"}


# -- Exact native capture comparison ----------------------------


def _do_capture_diff_0(self):
    reference=self.samples/"Original-Screenshot.png"
    if self.source is None:
        picture=Image.new("RGBA",(640,360),(26,40,57,255))
        d=ImageDraw.Draw(picture)
        d.rectangle((160,100,480,255),fill=(58,89,130,255),
                    outline=(235,205,130,255),width=4)
        d.text((212,156),"ORIGINAL",fill=(246,246,231,255))
        _source(self,reference.name,picture)
    else:
        from origins_noesis_pixel_compare import _read_image
        image=_read_image(Path(self.source))
        image.save(reference,format="PNG")
    self.data["capture_before"]=str(reference)
    return {"outputs":[str(reference)],"preview":str(reference),
            "source":str(self.source) if self.source else None,
            "message":"Ausgangs-PNG privat kopiert; native Renderquelle nicht automatisch attestiert"}


def _do_capture_diff_1(self):
    image=Image.open(self.data["capture_before"]).convert("RGBA")
    rectangle=(image.width//3,image.height//3,
               image.width*2//3,image.height*2//3)
    ImageDraw.Draw(image).rectangle(rectangle,fill=(238,82,62,255))
    edited=_source(self,"Nachher-Screenshot.png",image)
    self.data["capture_after"]=str(edited)
    return {"outputs":[str(edited)],"preview":str(edited),
            "message":"Wirklich veränderte Pixel in einem zweiten PNG-Rahmen gespeichert"}


def _do_capture_diff_2(self):
    from origins_noesis_pixel_compare import compare_captured_frames
    path=self.root/"pixel-exact-diff"
    proof=compare_captured_frames(
        Path(self.data["capture_before"]),
        Path(self.data["capture_after"]),path,
        source_kind="original-or-user-supplied-reference-plus-demo-edit")
    if proof["changed_pixels"]<=0 or proof["pixel_identical"]:
        raise RuntimeError("Fehlerhafter Noesis-Pixeldifferenzbericht")
    return {"outputs":[proof["heatmap"],proof["overlay"],proof["report"]],
            "preview":proof["heatmap"],
            "message":f"{proof['changed_pixels']} echte unterschiedliche Pixel ermittelt, unveränderte Originalquelle"}


def _do_capture_diff_3(self):
    from origins_noesis_pixel_compare import compare_captured_frames
    image=Path(self.data["capture_after"])
    proof=compare_captured_frames(image,image,self.root/"identical-reference-check",
             source_kind="same-bitmap-selftest")
    if not proof["pixel_identical"] or proof["changed_pixels"]:
        raise RuntimeError("Identische Pixel wurden fälschlich als Unterschied gewertet")
    return {"outputs":[proof["report"]],
            "message":"Null-Differenzkontrolle bestanden; Pixelvergleich erfindet keine Abweichungen"}


# -- Extra UI Atlas production pipeline ---------------------------------


def _do_extra_atlas_0(self):
    from ui_extra_atlas import ROOT as GAME_ROOT
    src=self.root/"work"/"ExtraAtlasDemoImages"
    src.mkdir(parents=True)
    for number in range(4):
        image=Image.new("RGBA",(64+number*12,56+number*6),
                        (35+number*40,75+number*12,142,255))
        ImageDraw.Draw(image).rectangle((8,8,image.width-9,image.height-9),
                    outline=(243,222,162,255),width=3)
        _source(self,"AtlasSource"+str(number)+".png",image)
        shutil.copyfile(self.samples/("AtlasSource"+str(number)+".png"),
                        src/("Icon"+str(number)+".png"))
    gui=self.samples/"Original-GUI-Referenz"
    sprites=gui/"Sprites";sprites.mkdir(parents=True)
    xaml_resources=gui/"XAMLResources";xaml_resources.mkdir()
    pres="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
    xns="http://schemas.microsoft.com/winfx/2006/xaml"
    names=("UI-MasterAtlas","UI-TrailAtlas","UI-Colour1Atlas","UI-Colour2Atlas")
    for name in names:
        (sprites/(name+".xaml")).write_text(
            f'<ResourceDictionary xmlns="{pres}" xmlns:x="{xns}">'
            f'<BitmapImage x:Key="{name}" UriSource="{name}.png"/>'
            '</ResourceDictionary>',encoding="utf8")
    links="".join(f'<ResourceDictionary Source="../Sprites/{name}.xaml" />'
                  for name in names)
    (xaml_resources/"ApplicationResources.xaml").write_text(
        f'<ResourceDictionary xmlns="{pres}" xmlns:x="{xns}">'
        '<ResourceDictionary.MergedDictionaries>'+links+
        '</ResourceDictionary.MergedDictionaries></ResourceDictionary>',
        encoding="utf8")
    self.data["atlas_src"]=str(src)
    self.data["atlas_gui"]=str(gui)
    return {"outputs":[str(src/f"Icon{i}.png") for i in range(4)]+
            [str(xaml_resources/"ApplicationResources.xaml")],
            "preview":str(src/"Icon0.png"),
            "message":"Originaltypische 4 Atlas-ResourceDictionaries und 4 echte PNG-Quellen vorbereitet"}


def _do_extra_atlas_1(self):
    import ui_extra_atlas as tool
    previous=tool.ROOT
    tool.ROOT=self.root
    target=self.root/"dist"/"ExtraAtlasQA"
    try:
        result=tool.build(self.data["atlas_src"],self.data["atlas_gui"],target,
                          stem="DemoAtlas",prefix="Demonstration",size=256,gutter=2)
    finally:
        tool.ROOT=previous
    self.data["atlas_output"]=str(target)
    first=target/"Override/Assets/GUI/Sprites/DemoAtlas-001.png"
    if not first.is_file():
        raise RuntimeError("Atlas-Builder hat keine echte PNG-Seite geschrieben")
    return {"outputs":[str(first),str(target/"extra-ui-atlas-manifest.json")],
            "preview":str(first),
            "message":f"Originalen Noesis-Atlas-Builder ausgeführt, {len(result['pages'])} Seiten erzeugt"}


def _do_extra_atlas_2(self):
    import ui_extra_atlas as tool
    previous=tool.ROOT;tool.ROOT=self.root
    folder=Path(self.data["atlas_output"])
    try:
        checked=tool.verify(folder)
    finally:
        tool.ROOT=previous
    paths=[]
    # Only actual override assets, no QA manifest or Markdown are packageable.
    for file in sorted((folder/"Override").rglob("*")):
        if not file.is_file():continue
        relative=file.relative_to(folder)
        target=self.project/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(file,target)
        paths.append(str(target))
    if len(paths)<3:
        raise RuntimeError("Original-Atlas-Builder hat keine XAML/PNG-Ausgaben erzeugt")
    self.data["atlas_assets"]=paths
    return {"outputs":paths,
            "message":f"{len(paths)} tatsächliche Atlas-Override-Dateien geprüft und paketfähig übernommen"}


def _do_extra_atlas_3(self):
    package=_asset_package(self,"atlas",
                           "Override/Assets/GUI/Sprites/DemoAtlas-001.png")
    return {"outputs":[package],
            "message":"Neue echte UI-Atlas-Seite und XAMLResource-Dictionaries als Mod-ZIP paketiert"}


# -- Read-only native game ABI and private BepInEx menu candidate ----------


def _do_native_menu_0(self):
    from origins_native_abi_probe import _source,_digest
    from pathlib import Path
    game=Path(self.source)
    refs={
        "game":_source(game,"Stronghold Crusader Definitive Edition_Data/Managed/Assembly-CSharp.dll"),
        "noesis":_source(game,"Stronghold Crusader Definitive Edition_Data/Managed/Noesis.NoesisGUI.dll"),
        "bepinex":_source(game,"BepInEx/core/BepInEx.dll"),
        "harmony":_source(game,"BepInEx/core/0Harmony.dll"),
    }
    fingerprints={key:_digest(file) for key,file in refs.items()}
    report=self.samples/"Original-ABI-Referenzen.json"
    report.write_text(json.dumps({"schema":"sprite-suite.demo-game-metadata.v1",
         "game_root":str(game),"references_sha256":fingerprints,
         "source_game_dll_executed":False,
         "game_installation_modified":False},indent=2)+"\n",encoding="utf8")
    self.data["game_reference_hashes"]=fingerprints
    return {"outputs":[str(report)],"preview":str(report),
            "message":"Vier echte installierte Managed-DLLs nur lesend gehasht, kein Spielprozess gestartet"}


def _do_native_menu_1(self):
    from origins_runtime_authoring import write_campaign_draft
    plan={"name":"demo-native-menu","title":"Originalspiel-Menü QA",
          "missions":[{"number":1,"title":"Native Menü-Demomission",
                       "map":"Demo 1.map","act":"QA"}]}
    output=write_campaign_draft(self.project,plan)
    self.data["campaign"]=plan
    self.data["campaign_dir"]=output["output"]
    base=Path(output["output"])
    return {"outputs":[str(base/"OriginsCampaignData.g.cs"),
                       str(base/"FrontendMenus.draft.xaml")],
            "preview":str(base/"FrontendMenus.draft.xaml"),
            "message":"Echte BepInEx-bindungsfähige Menüquellen, Missionslabel und C#-Daten erzeugt"}


def _do_native_menu_2(self):
    from origins_native_abi_probe import probe_installed_game
    output=self.root/"metadata-only-installation"
    report=probe_installed_game(Path(self.source),output)
    if not all(report["structural_signatures"].values()):
        raise RuntimeError("Echte Spiel-API-Signatur fehlt: "+str(report["missing_signatures"]))
    return {"outputs":[report["report"],report["log"]],
            "preview":report["report"],
            "message":"7 Noesis-/Frontend-/BepInEx-Signaturen ohne Game-DLL-Ausführung geprüft"}


def _do_native_menu_3(self):
    from origins_native_menu_compiler import compile_menu_candidate
    report=compile_menu_candidate(self.project,"demo-native-menu",
                                   Path(self.source))
    if not report["compiled_candidate_metadata_attested"]:
        raise RuntimeError("Eigene Menübridge-ABI nicht nachgewiesen")
    if report["native_game_hook_registered"]:
        raise RuntimeError("Offline-Probelauf meldet unerlaubt Ingame-Hook")
    return {"outputs":[report["dll"],report["report"]],
            "preview":report["report"],
            "message":"Native BepInEx-Menü-DLL mit 5 Cecil-Metadatenprüfungen erstellt, NICHT installiert"}


def register(cls,original_modules):
    from suite_demo_engine import DemoModule,DemoStep
    specs=(
        ("stone","Steinfarben / Material","Echte gemessene Sandstein-Umfärbung",[
            ("Originalmaterial","Warmton-Sprite mit Schatten vorbereiten","stone_recolour"),
            ("HSV-Farbe ändern","Gemessene Steinpalette auf PNG-Pixel anwenden","stone_recolour.recolour_image"),
            ("Material ausliefern","Umgefärbte PNG als Mod-ZIP ausgeben","se_asset_package.build")]),
        ("boar","Tier-Sprites / Keilerpalette","Echter Hyänen-zu-Keiler-Fell-Farbalgorithmus",[
            ("Tieroriginal","Sprite mit Bodenschatten und Alpha vorbereiten","Pillow"),
            ("Originalpixel umfärben","RGB ohne Veränderung der Alpha-Kanäle umrechnen","boar_recolour.faerbe_bild"),
            ("Tier-Grafik paketieren","Geändertes Bild als Asset-Mod-ZIP exportieren","se_asset_package.build")]),
        ("historic_palette","Original-Origins Blau/Silber","Historische UI-Farbtransformation auf echten Pixeln",[
            ("Button-Grundfarben","Rot/Gold/Blau Bild vorbereiten","import_image"),
            ("Blau und Silber erzeugen","HSV-/Luminanzformeln der Originalpalette anwenden","suite_sh1_origins_palette.recolour"),
            ("UI exportieren","Veränderte echte PNG paketieren","se_asset_package.build")]),
        ("team_mask","Teamfarben / Shader-Masken","Bildmaske und Teamfarbe getrennt bearbeiten",[
            ("Original & Maske","Teammaskenbild und Pixeloriginal schreiben","Pillow"),
            ("Teamfarbe anwenden","Die echten roten Maskenkanal-Gewichte anwenden","sandkasten.tint"),
            ("Sprite exportieren","Echte umgefärbte Grafik paketieren","se_asset_package.build")]),
        ("sandbox_scene","Sandkasten / Spielvorschau","Isometrische Szene mit echtem Rendering, eigenen Sprite-Daten",[
            ("Szene vorbereiten","Objekte, Kacheln und Frames definieren","sandkasten.scene_items"),
            ("Szene zeichnen","Originalen isometrischen Pixelrenderer ausführen","sandkasten.render"),
            ("Position verändern","Objekt bewegen und erneut vollständig rendern","sandkasten.render"),
            ("Vorschau ausgeben","Gerenderte PNG als Asset exportieren","se_asset_package.build")]),
        ("button_motif","UI-Button-Motivkatalog","Originalalgorithmus für Motivsignaturen und Icon-Ähnlichkeit",[
            ("Drei Icon-Motive","Originaltypische Formfamilien vorbereiten","Pillow"),
            ("Motivdaten messen","Gradientensignaturen berechnen und Distanzen vergleichen","ui_button_catalogue.signature / dist"),
            ("Kontaktbogen erstellen","Gemessene Motive ausgeben","se_asset_package.build")]),
        ("native_tiles","Originalkarten / Kachelmaterial","Provisorische native Tile-Klassifizierung visualisieren",[
            ("Native Codes","512 native Kachelwerte vorbereiten","sandbox_native_canvas"),
            ("Materialdarstellung","Spielkachel-Klassifizierungsfunktion wirklich ausführen","native_tile_material"),
            ("Karte exportieren","Kachel-PNG als Asset-Mod paketieren","se_asset_package.build")]),
        ("bc7","BC7-Texturen / Decoder","Echte BC7-Kompression und Dekodierung ausführen",[
            ("Quelltextur","Reproduzierbare RGBA-Textur generieren","Pillow"),
            ("BC7 komprimieren","Native etcpak/texture2ddecoder-Bibliotheken ausführen","sandkasten.bc7_roundtrip"),
            ("Dekodierte Quelle exportieren","PNG und Mod-ZIP mit dekodierten Pixeln erstellen","se_asset_package.build")]),
        ("capture_diff","Noesis Pixelvergleich / Aufnahmen","Exakte Bildabweichungen messen, kein eigener Noesis-Renderer",[
            ("Ausgangsaufnahme","Echte lokale PNG oder Demo-Aufnahme einlesen","PIL.Image"),
            ("Zweite Ansicht ändern","Pixelsichtbar andere Screenshot-Version erzeugen","ImageDraw"),
            ("Pixelgenau vergleichen","Differenzbild, Überlagerung und exakte Zahlen erstellen","origins_noesis_pixel_compare"),
            ("Nullabweichung prüfen","Identische Bilder als gleich erkennen","origins_noesis_pixel_compare")]),
        ("extra_atlas","Noesis Zusatzatlas / UI-Texturen","Echten Sprite-Atlas-Builder und ResourceDictionary-Generator ausführen",[
            ("Sprites & Ressourcen","Vier UI-PNG und vier Noesis-Referenzdictionaries erstellen","ApplicationResources.xaml"),
            ("Atlanten generieren","Echten Crop-/Page-Packer und XAML-Generator ausführen","ui_extra_atlas.build"),
            ("Atlasquellen prüfen","Manifest/Bitmap-Dictionaries verifizieren","ui_extra_atlas.verify"),
            ("Atlas-Mod exportieren","Neue PNG-Blätter und Resource-XAML paketieren","se_asset_package.build")]),
        ("native_menu","Spiel-Menübridge / native ABI (nur offline)",
         "Echte installierte Spiel-DLLs lesend prüfen und privaten C#-Menükandidaten bauen",[
            ("Spiel-DLL-Referenzen prüfen","Originale verwaltete DLLs der Installation nur lesend erfassen",
             "origins_native_abi_probe._source"),
            ("C#-Menüdaten erstellen","Echte editierbare Missionen, XAML und C# erzeugen",
             "origins_runtime_authoring.write_campaign_draft"),
            ("Spiel-API-Struktur untersuchen","Noesis-, Menü- und Harmony-Signaturen in Original-DLLs ohne Ausführung prüfen",
             "origins_native_abi_probe.probe_installed_game"),
            ("Menübridge offline kompilieren","C#-BepInEx-Kandidat gegen echte Spiel-Referenzen kompilieren und Metadaten prüfen",
             "origins_native_menu_compiler.compile_menu_candidate")]),
    )
    extras=[]
    for key,title,summary,rows in specs:
        steps=tuple(DemoStep(n,d,f) for n,d,f in rows)
        extras.append(DemoModule(key,title,summary,steps,
                    input_type=("png" if key=="capture_diff" else
                                "game_dir" if key=="native_menu" else "")))
        for index in range(len(steps)):
            name=f"_do_{key}_{index}"
            fn=globals().get(name)
            if fn is None:raise RuntimeError("Demo step lacks implementation: "+name)
            setattr(cls,name,fn)
    return tuple(original_modules)+tuple(extras)
