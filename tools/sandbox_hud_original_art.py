"""Interactable building-command HUD using original XAML geometry and atlas crops.

The source is the locally available European override atlas plus the exact
CroppedBitmap rectangles and command IDs extracted from SHCDE HUD_Main.xaml.
It intentionally does NOT claim 1:1 runtime HUD composition or engine bindings.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from dataclasses import dataclass
from PIL import Image
from PySide6.QtCore import Qt, Signal, QTimer, QRectF
from PySide6.QtGui import QImage, QPixmap, QColor, QPen, QPainter, QBrush
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QPushButton, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem, QGraphicsSimpleTextItem,
)

from stronghold_europe_de.sandbox.hud_composition import HudComposition

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_FILE = ROOT / "config" / "sandbox-hud-original-art-v1.json"
MANIFEST_SCHEMA = "stronghold-europe.sandbox.hud-original-art.v1"
GROUPS = {
    "A":"Navigation","B":"Bergfriede","C":"Befestigungen",
    "D":"Rohstoffe","E":"Nahrung","F":"Stadt",
    "G":"Produktion","H":"Waffen","I":"Kirche",
    "J":"Vergnügen","K":"Zusatzbau","L":"Verteidigung",
    "M":"Militär","N":"Weitere Bauten"
}
COMMAND_KEY = re.compile(r"^[A-Z][A-Z0-9_]{1,120}$")
RESOURCE_KEY = re.compile(r"^UI-(?:Buildings|HUD) [A-Za-z0-9 ]{3,40}$")


class HudContractError(ValueError):
    pass


def load_hud_contract(path=CONTRACT_FILE):
    data=json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") != MANIFEST_SCHEMA:
        raise HudContractError("Unbekannter XAML-HUD-Vertrag")
    rects=data["rectangles"]
    commands=data["commands"]
    if not 1 <= len(commands) <= 300:
        raise HudContractError("Ungültige Anzahl an HUD-Schaltflächen")
    if not isinstance(rects, dict) or len(rects)>1000:
        raise HudContractError("Ungültiges HUD-Ressourcenverzeichnis")
    for key, xywh in rects.items():
        if not RESOURCE_KEY.fullmatch(key) or len(xywh)!=4:
            raise HudContractError(f"Unbekannte HUD-Ressource {key}")
        x,y,w,h=xywh
        if not all(type(n) is int for n in xywh) or x<0 or y<0 or w<1 or h<1 or x+w>8192 or y+h>8192:
            raise HudContractError(f"Unzulässiger Atlas-Ausschnitt {key}")
    HudComposition.from_contract(data)
    for item in commands:
        if item["image"] not in rects or item["page"] not in GROUPS:
            raise HudContractError("HUD-Element verweist auf fehlende Grafik/Seite")
        if item["hover_image"] and item["hover_image"] not in rects:
            raise HudContractError("Hoverbild nicht im Atlas")
        if not isinstance(item["command"], str):
            raise HudContractError("Ungültiger HUD-Spielbefehl")
        if item["command"] and not COMMAND_KEY.fullmatch(item["command"]):
            raise HudContractError("Ungültiger HUD-Spielbefehl")
    return data


def atlas_path(contract):
    relative=Path(contract["source"]["atlas_relative"])
    if relative.is_absolute() or ".." in relative.parts or relative.suffix.lower()!=".png":
        raise HudContractError("HUD-Atlas muss aus lokalen Projektassets stammen")
    path=(ROOT/relative).resolve()
    if not path.is_relative_to(ROOT):
        raise HudContractError("HUD-Atlas liegt außerhalb des Projekts")
    return path


class OriginalHudArt:
    """Load verified *small* crops, never a 268-MB full atlas in every window."""
    def __init__(self, contract):
        self.contract=contract
        directory=Path(contract["source"].get("crop_dir_relative",""))
        if (directory.is_absolute() or ".." in directory.parts or
                str(directory)=="." or len(contract.get("cropped_assets",{}))!=len(contract["rectangles"])):
            raise HudContractError("Verifizierte lokale HUD-Ausschnitte fehlen")
        self.folder=(ROOT/directory).resolve()
        if not self.folder.is_relative_to(ROOT):
            raise HudContractError("HUD-Crops außerhalb des Projekts")
        self._cache={}

    def crop(self,key):
        if key not in self._cache:
            meta=self.contract["cropped_assets"][key]
            name=meta["name"]
            if not re.fullmatch(r"[0-9a-f]{24}\.png",name):
                raise HudContractError("Unsicherer HUD-Crop-Dateiname")
            path=self.folder/name
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=meta["sha256"]:
                raise HudContractError("HUD-Crop fehlt oder besitzt falsche Prüfsumme")
            pix=QPixmap(str(path))
            x,y,w,h=self.contract["rectangles"][key]
            if pix.isNull() or pix.width()!=w or pix.height()!=h:
                raise HudContractError("HUD-Grafikausschnitt und XAML-Rechteck widersprechen sich")
            self._cache[key]=pix
        return self._cache[key]


class HudIcon(QGraphicsPixmapItem):
    def __init__(self, owner, spec, normal, hovered, parent=None):
        super().__init__(normal,parent)
        self.owner=owner
        self.spec=spec
        self.normal=normal
        self.hovered=hovered or normal
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setToolTip(f"{spec['name']} | {spec['command']} | {spec['image']}")

    def hoverEnterEvent(self, event):
        self.setPixmap(self.hovered)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self,event):
        self.setPixmap(self.normal)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton:
            self.owner._activate(self.spec)
            event.accept()
        else:
            super().mousePressEvent(event)


class HudGraphicsView(QGraphicsView):
    """Fit after this viewport (not its still-being-laid-out parent) resizes."""
    def fit_original_art(self):
        if (self.scene() is not None and self.viewport().width() > 5
                and self.viewport().height() > 5 and
                getattr(self,"_xaml_mode",False)):
            self.fitInView(self.scene().sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.fit_original_art)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self.fit_original_art)


class OriginalHudArtPanel(QWidget):
    """Real resource-pixel/XAML icon browser with functional command selection."""
    command_selected=Signal(str)
    bind_requested=Signal(str)
    clear_requested=Signal(str)

    def __init__(self,parent=None,contract=None,art=None):
        super().__init__(parent)
        self.contract=contract or load_hud_contract()
        self.art=art or OriginalHudArt(self.contract)
        self.geometry=HudComposition.from_contract(self.contract)
        self.active_command=None
        self.active_name=None
        self.icons=[]
        self._page_specs=[]
        self._compact=False
        outer=QVBoxLayout(self)
        header=QHBoxLayout()
        self._header=header
        title=QLabel("Original-XAML-Bauicons · lokale Europagrafiken · Teilrekonstruktion")
        self._title=title
        header.addWidget(title,1)
        self.page=QComboBox()
        self.page.setObjectName("sandbox_hud_original_page")
        for code, title in GROUPS.items():
            self.page.addItem(f"{code} – {title}", code)
        header.addWidget(self.page)
        self.display_mode=QComboBox()
        self.display_mode.setObjectName("sandbox_hud_display_mode")
        self.display_mode.addItem("Bauicons: vollständig & anklickbar", "gallery")
        self.display_mode.addItem("Original-XAML: Positionen & Clipping", "xaml")
        self.display_mode.setToolTip(
            "Bauicons: alle Kommandos lesbar und einzeln anklickbar. "
            "XAML: verifiziertes Teil-HUD mit echten Clip-/Transformregeln. "
            "Das originale vollständige Spiel-HUD ist noch nicht nachgebaut."
        )
        header.addWidget(self.display_mode)
        self.command_choice=QComboBox()
        self.command_choice.setObjectName("sandbox_hud_original_command_choice")
        self.command_choice.setMinimumWidth(175)
        self.command_choice.setToolTip(
            "Originalbefehl wählen; hier sind auch die im Spiel bedingt "
            "sichtbaren, überlagerten XAML-Varianten erreichbar."
        )
        self.command_choice.setAccessibleName("Original-HUD-Befehl auswählen")
        header.addWidget(self.command_choice)
        outer.addLayout(header)
        self.scene=QGraphicsScene(self)
        self.view=HudGraphicsView(self.scene)
        self.view.setMinimumHeight(150)
        self.view.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(self.view,1)
        self.message=QLabel("Schaltfläche anklicken: Original-Befehl auswählen; Grafik zuweisen, um Platzieren zu aktivieren.")
        self.message.setWordWrap(True)
        outer.addWidget(self.message)
        commands=QHBoxLayout()
        self._button_row=commands
        self.bind_button=QPushButton("Ausgewählten Originalbefehl mit Palette-Sprite verbinden")
        self.bind_button.clicked.connect(
            lambda: self.bind_requested.emit(self.active_command)
            if self.active_command else None
        )
        self.clear_button=QPushButton("Verknüpfung aufheben")
        self.clear_button.clicked.connect(
            lambda: self.clear_requested.emit(self.active_command)
            if self.active_command else None
        )
        commands.addWidget(self.bind_button)
        commands.addWidget(self.clear_button)
        outer.addLayout(commands)
        self.page.currentIndexChanged.connect(self._page_changed)
        self.command_choice.currentIndexChanged.connect(self._choice_selected)
        self.display_mode.currentIndexChanged.connect(self.redraw)
        self._page_changed()

    def configure_compact(self):
        """Make the real-art HUD usable in a 275px embedded inspector.

        The full gallery remains 8 columns in the standalone Studio;
        only the embedded Suite displays 2 columns with vertically stacked
        selectors. Never hide 21 conditional ruins variants again.
        """
        if self._compact:
            return
        self._compact=True
        layout=self.layout()
        header_item=layout.takeAt(0)
        header=header_item.layout()
        for widget in (self._title,self.page,self.display_mode,self.command_choice):
            header.removeWidget(widget)
            widget.setParent(None)
        header.deleteLater()
        self._title.setText("Original-Bauicons (Werkstatt)")
        self._title.setToolTip(
            "XAML-Bauicons aus lokalen Europagrafiken; keine "
            "vollständige Original-HUD-Simulation."
        )
        self._title.setWordWrap(True)
        self.command_choice.setMinimumWidth(0)
        self.command_choice.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.command_choice.setMinimumContentsLength(10)
        self.display_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.display_mode.setMinimumContentsLength(10)
        header=QVBoxLayout()
        header.setSpacing(3)
        for widget in (self._title,self.page,self.display_mode,self.command_choice):
            header.addWidget(widget)
        layout.insertLayout(0,header)

        # The old 500px-wide "Palette-Sprite verbinden" button forced the
        # entire HUD inside a horizontally scrolling QScrollArea. A 275px
        # editor would show only the leftmost label and none of the action.
        self.bind_button.setToolTip(self.bind_button.text())
        self.bind_button.setText("Sprite verbinden")
        self.clear_button.setToolTip(self.clear_button.text())
        self.clear_button.setText("Verknüpfung löschen")
        command_item=layout.takeAt(layout.count()-1)
        old_row=command_item.layout()
        old_row.removeWidget(self.bind_button)
        old_row.removeWidget(self.clear_button)
        self.bind_button.setParent(None)
        self.clear_button.setParent(None)
        old_row.deleteLater()
        buttons=QVBoxLayout()
        buttons.setSpacing(3)
        buttons.addWidget(self.bind_button)
        buttons.addWidget(self.clear_button)
        layout.addLayout(buttons)
        self.view.setMinimumHeight(170)
        self.view.setMinimumWidth(0)
        layout.setContentsMargins(4,4,4,4)
        self.redraw()

    @staticmethod
    def slot(spec):
        # Several XAML buttons occupy precisely the same location and are
        # runtime-conditional variants (e.g. twenty-one ruins on page N).
        # Painting every variant at once was visually nonsensical and made
        # only the topmost random command clickable.
        return (round(float(spec["x"]), 3),round(float(spec["y"]), 3))

    def _page_changed(self):
        self.active_command=None
        self.active_name=None
        page=self.page.currentData() or self.page.currentText()[:1]
        self._page_specs=[
            spec for spec in self.contract["commands"] if spec["page"]==page
        ]
        self.command_choice.blockSignals(True)
        self.command_choice.clear()
        self.command_choice.addItem("Befehl auswählen …",None)
        for spec in self._page_specs:
            self.command_choice.addItem(
                f'{spec["name"]} ({spec["command"]})',spec["name"]
            )
        self.command_choice.blockSignals(False)
        self.redraw()

    def _choice_selected(self):
        name=self.command_choice.currentData()
        if not name:
            return
        spec=next((c for c in self._page_specs if c["name"]==name),None)
        if spec:
            self._activate(spec)

    def redraw(self):
        if self.display_mode.currentData()=="gallery":
            self._redraw_gallery()
            return
        self._redraw_xaml()

    def _redraw_gallery(self):
        """All native art, every alternative individually accessible.

        A real game may show just one of several Ruins/Keep variants; placing
        all at identical XAML margins made the buttons unreadable and
        unclickable. This is an explicitly labelled *authoring* arrangement.
        """
        self.scene.clear()
        self.icons.clear()
        columns=2 if self._compact else 8
        cell_w,cell_h=(105,118) if self._compact else (120,130)
        rows=max(1,(len(self._page_specs)+columns-1)//columns)
        self.scene.setSceneRect(0,0,columns*cell_w,rows*cell_h)
        self.scene.setBackgroundBrush(QColor("#202829"))
        for number,spec in enumerate(self._page_specs):
            x=(number%columns)*cell_w
            y=(number//columns)*cell_h
            tile=self.scene.addRect(
                QRectF(x+3,y+3,cell_w-7,cell_h-8),
                QPen(QColor("#59675d"),1.0),QBrush(QColor("#303a38"))
            )
            tile.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            normal=self.art.crop(spec["image"])
            hover=(self.art.crop(spec["hover_image"])
                   if spec["hover_image"] else normal)
            icon=HudIcon(self,spec,normal,hover)
            image_w=85 if self._compact else 94
            image_h=80 if self._compact else 94
            icon.setScale(min(1.0,image_w/normal.width(),
                              image_h/normal.height()))
            visual_w=normal.width()*icon.scale()
            visual_h=normal.height()*icon.scale()
            icon.setPos(x+(cell_w-visual_w)/2,y+5+(image_h-visual_h)/2)
            self.scene.addItem(icon)
            label=self.scene.addSimpleText(
                spec["name"].removeprefix("ButtonBuild")[
                    :13 if self._compact else 17
                ]
            )
            label.setBrush(QBrush(QColor("#efe7cf")))
            label.setScale(.85)
            label.setPos(x+4,y+cell_h-23)
            label.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
            label.setToolTip(f'{spec["name"]} | {spec["command"]}')
            self.icons.append(icon)
        self.view._xaml_mode=False
        self.view.resetTransform()
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.view.horizontalScrollBar().setValue(0)
        self.view.verticalScrollBar().setValue(0)
        self.message.setText(
            f'{len(self._page_specs)} echte XAML-Bauicons, einzeln anwählbar. '
            "Werkstattansicht: keine behauptete 1:1-Spiel-HUD-Geometrie."
        )

    def _redraw_xaml(self):
        self.scene.clear()
        self.icons.clear()
        geom=self.geometry
        # The original HUD_Main.xaml has TWO independently clipped visual
        # layers. Older code placed the full 1752x206 atlas crop at (0,0),
        # then moved icons by an invented +16/+17 offset; it was not the XAML
        # composition and displayed a jumble of superimposed backgrounds.
        self.scene.setSceneRect(
            QRectF(0,0,geom.scene_width,geom.scene_height)
        )
        self.scene.setBackgroundBrush(QColor("#202525"))

        sx,sy,sw,sh=geom.scroll_clip
        scroll=self.scene.addRect(
            QRectF(sx,sy,sw,sh),
            QPen(Qt.PenStyle.NoPen),QBrush(Qt.BrushStyle.NoBrush)
        )
        scroll.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        scroll.setFlag(scroll.GraphicsItemFlag.ItemClipsChildrenToShape)
        scroll.setPos(*geom.scroll_parent)
        scroll.setZValue(-10)
        background=QGraphicsPixmapItem(
            self.art.crop(self.contract["layout"]["art_resource"]),scroll
        )
        background.setScale(geom.pixel_scale)
        background.setPos(*geom.scroll_offset)

        mx,my,mw,mh=geom.menu_clip
        menu=self.scene.addRect(
            QRectF(mx,my,mw,mh),
            QPen(Qt.PenStyle.NoPen),QBrush(Qt.BrushStyle.NoBrush)
        )
        menu.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        menu.setFlag(menu.GraphicsItemFlag.ItemClipsChildrenToShape)
        menu.setPos(*geom.menu_parent)
        menu.setZValue(10)

        # A conditional XAML alternative must replace, never cover,
        # another command sharing the very same (margin x,y).
        selected={}
        for spec in self._page_specs:
            key=self.slot(spec)
            if key not in selected or spec["name"]==self.active_name:
                selected[key]=spec

        hidden=len(self._page_specs)-len(selected)
        for spec in selected.values():
            normal=self.art.crop(spec["image"])
            hover=(self.art.crop(spec["hover_image"])
                   if spec["hover_image"] else normal)
            item=HudIcon(self,spec,normal,hover,menu)
            item.setScale(geom.button_scale(
                spec,normal.width(),normal.height()
            ))
            item.setPos(
                geom.menu_offset[0]+float(spec["x"]),
                geom.menu_offset[1]+float(spec["y"])
            )
            item.setZValue(1)
            self.icons.append(item)

        self.view._xaml_mode=True
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.fit_original_art()
        self.message.setText(
            f"{len(self.icons)} im XAML-Untermenü sichtbar, "
            f"{hidden} bedingte Alternativen über die Befehlsauswahl. "
            "Ausschnitt mit geclippten originalen Eltern-Transformationen."
        )
        self.view.setToolTip(
            f'{len(self.icons)} sichtbare Bauicons, '
            f'{hidden} bedingte Varianten im Befehlsfeld auswählbar. '
            "Original-XAML-Untermenü, keine vollständige Spiel-HUD-Simulation."
        )

    def resizeEvent(self,event):
        super().resizeEvent(event)
        if hasattr(self, "view"):
            QTimer.singleShot(0,self.view.fit_original_art)

    def _activate(self,spec):
        changed=self.active_name!=spec["name"]
        self.active_name=spec["name"]
        self.active_command=spec["command"]
        index=self.command_choice.findData(spec["name"])
        if index>=0:
            self.command_choice.blockSignals(True)
            self.command_choice.setCurrentIndex(index)
            self.command_choice.blockSignals(False)
        if changed and self.display_mode.currentData()=="xaml":
            # Defer deleting a clicked GraphicsItem until its event returns.
            QTimer.singleShot(0,self.redraw)
        self.message.setText(
            f"{spec['name']} · {self.active_command or 'kein CommandParameter'} · "
            f"Sprite-Ressource {spec['image']} aus originalem XAML"
        )
        self.command_selected.emit(self.active_command)

    def select_command(self, token):
        for index,label in enumerate(GROUPS):
            candidates=[spec for spec in self.contract["commands"]
                        if spec["page"]==label and spec["command"]==token]
            if candidates:
                self.page.setCurrentIndex(index)
                self._activate(candidates[0])
                return True
        return False
