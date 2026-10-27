"""Actual editable Qt controls for historic Sandkasten v1 records.

No source migration. The model serializes the SAME v1 shape, including
random seed, exact GM1 rectangles/layout, per-sprite time sequences and HUD.
All changes enter ordinary SceneHistory, so Ctrl+Z and Ctrl+Y work.
"""
from __future__ import annotations
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QDialog,QVBoxLayout,QFormLayout,QHBoxLayout,QGroupBox,
    QLineEdit,QSpinBox,QDoubleSpinBox,QCheckBox,QComboBox,
    QPushButton,QLabel,QMessageBox,QScrollArea,QWidget,
)
from stronghold_europe_de.sandbox.scene_model import SceneError


class LegacyV1SceneDialog(QDialog):
    def __init__(self,board,parent=None):
        super().__init__(parent)
        self.board=board
        self.setWindowTitle("Historische V1-Szene verlustfrei bearbeiten")
        self.resize(600,740)
        layout=QVBoxLayout(self)
        self.help=QLabel(
            "Original-Sandkasten v1 · Boden-Saat, GM1-Komposite, Animation und "
            "HUD-Daten bleiben im V1-Dateiformat. Anwenden ist rückgängig machbar. "
            "Speichern erfolgt ausschließlich über die Testszene als Arbeitskopie."
        )
        self.help.setWordWrap(True)
        layout.addWidget(self.help)
        scroll=QScrollArea(self)
        scroll.setWidgetResizable(True)
        body=QWidget()
        controls=QVBoxLayout(body)
        general=QGroupBox("Szene, prozeduraler Boden und HUD")
        fields=QFormLayout(general)
        self.name=QLineEdit()
        self.ground_group=QLineEdit()
        self.frames=QLineEdit()
        self.frames.setToolTip("Exakte, sortierungstreue kommaseparierte V1-Bodenframefolge")
        self.seed=QSpinBox()
        self.seed.setRange(-2147483648,2147483647)
        self.hud=QCheckBox("Historisches HUD sichtbar")
        fields.addRow("Szenenname",self.name)
        fields.addRow("Bodengruppe",self.ground_group)
        fields.addRow("Bodenframes (CSV)",self.frames)
        fields.addRow("Boden-Saatwert",self.seed)
        fields.addRow(self.hud)
        self.apply_general=QPushButton("Boden / Szene / HUD übernehmen (Undo)")
        self.apply_general.clicked.connect(self.save_general)
        fields.addRow(self.apply_general)
        controls.addWidget(general)

        details=QGroupBox("Ausgewähltes V1-Objekt")
        selected=QFormLayout(details)
        self.ident=QLabel("Kein Objekt ausgewählt")
        self.title=QLineEdit()
        self.start=QSpinBox()
        self.start.setRange(0,999999)
        self.columns=QSpinBox();self.columns.setRange(1,64)
        self.rows=QSpinBox();self.rows.setRange(1,64)
        self.layout_kind=QComboBox()
        self.layout_kind.setEditable(True)
        self.layout_kind.addItems((
            "gm1","row-major","column-major","row-major-flip-x",
            "row-major-flip-y","row-major-rotate-180",
            "column-major-flip-x","column-major-flip-y",
        ))
        self.animate=QCheckBox("Zeitabhängige Sprite-Animation verwenden")
        self.anim_start=QSpinBox();self.anim_start.setRange(0,999999)
        self.anim_end=QSpinBox();self.anim_end.setRange(0,999999)
        self.fps=QDoubleSpinBox()
        self.fps.setRange(0.01,120.0)
        self.fps.setDecimals(3)
        self.fps.setValue(10)
        self.alt=QCheckBox("Alternatives Sprite-Namensschema (alt)")
        for label,widget in (
            ("Auswahl",self.ident),("Titel",self.title),
            ("Startframe (sprite/frame bzw. GM1/von)",self.start),
            ("GM1-Spalten",self.columns),("GM1-Zeilen",self.rows),
            ("GM1-Layout",self.layout_kind),
        ):
            selected.addRow(label,widget)
        selected.addRow(self.animate)
        selected.addRow("Animation von",self.anim_start)
        selected.addRow("Animation bis",self.anim_end)
        selected.addRow("Animation FPS",self.fps)
        selected.addRow(self.alt)
        self.apply_object=QPushButton("Gewähltes Objekt verlustfrei ändern (Undo)")
        self.apply_object.clicked.connect(self.save_object)
        selected.addRow(self.apply_object)
        controls.addWidget(details)

        playback=QGroupBox("V1-Zeitvorschau · ohne Szenendatenänderung")
        clock=QFormLayout(playback)
        self.tick=QDoubleSpinBox()
        self.tick.setRange(0,3600)
        self.tick.setDecimals(2)
        self.tick.setSingleStep(.1)
        self.tick.valueChanged.connect(self.board.set_legacy_tick)
        clock.addRow("Renderer-Zeit (Sekunden)",self.tick)
        row=QHBoxLayout()
        self.play=QPushButton("Abspielen")
        self.play.clicked.connect(self.toggle_play)
        row.addWidget(self.play)
        self.stop=QPushButton("Reset auf 0")
        self.stop.clicked.connect(lambda:self.tick.setValue(0))
        row.addWidget(self.stop)
        clock.addRow(row)
        controls.addWidget(playback)
        self._clock=QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(
            lambda:self.tick.setValue(0 if self.tick.value()+.5>3600
                                      else self.tick.value()+.5))
        controls.addStretch(1)
        scroll.setWidget(body)
        layout.addWidget(scroll)
        close=QPushButton("Schließen")
        close.clicked.connect(self.close)
        layout.addWidget(close)
        self.board.scene_changed.connect(self.sync_scene_if_needed)
        self.board.selected_id_changed.connect(self.sync_object)
        self.sync_general()
        self.sync_object(self.board.selected_id() or "")

    def _record(self):
        obj=next((o for o in self.board.history.scene.objects
                  if o.id==self.board.selected_id()),None)
        if obj is None:return None,None
        return obj,self.board.history.scene.legacy_entries[obj.id]

    def sync_general(self):
        scene=self.board.history.scene
        if not scene.is_legacy_v1:return
        raw=scene.serialize()
        self.name.setText(scene.name)
        ground=raw.get("boden") or {"gruppe":"tile_land8","frames":[1],"saat":1}
        self.ground_group.setText(ground["gruppe"])
        self.frames.setText(",".join(map(str,ground["frames"])))
        self.seed.setValue(ground.get("saat",1))
        self.hud.setChecked((raw.get("hud") or {}).get("sichtbar",True))

    def sync_scene_if_needed(self):
        if not self.board.history.scene.is_legacy_v1:
            self.close()
        # Selected object may have been deleted/undone in the main inspector.
        else:
            self.sync_object(self.board.selected_id() or "")

    def sync_object(self,ident):
        obj,raw=self._record()
        enabled=obj is not None
        self.apply_object.setEnabled(enabled)
        if not enabled:
            self.ident.setText("Klicken Sie ein historisches Sprite/GM1-Objekt an.")
            return
        self.ident.setText(f"{raw['art']}: {obj.group} · ({obj.x},{obj.y})")
        self.title.setText(raw.get("titel",""))
        self.start.setValue(obj.frame)
        composite=raw["art"]=="kachelobjekt"
        self.columns.setEnabled(composite)
        self.rows.setEnabled(composite)
        self.layout_kind.setEnabled(composite)
        self.animate.setEnabled(not composite)
        self.anim_start.setEnabled(not composite)
        self.anim_end.setEnabled(not composite)
        self.fps.setEnabled(not composite)
        self.alt.setEnabled(not composite)
        self.columns.setValue(raw.get("spalten",1))
        self.rows.setValue(raw.get("zeilen",1))
        self.layout_kind.setCurrentText(raw.get("layout","gm1"))
        sequence=raw.get("animation")
        self.animate.setChecked(sequence is not None)
        self.anim_start.setValue(sequence["von"] if sequence else obj.frame)
        self.anim_end.setValue(sequence["bis"] if sequence else obj.frame)
        self.fps.setValue(sequence.get("fps",10) if sequence else 10)
        self.alt.setChecked(bool(raw.get("alt",False)))

    def save_general(self):
        try:
            parts=self.frames.text().split(",")
            frames=[int(item.strip()) for item in parts]
            self.board.history.legacy_set_scene_details(
                name=self.name.text(),ground_group=self.ground_group.text().strip(),
                ground_frames=frames,ground_seed=self.seed.value(),
                hud_visible=self.hud.isChecked())
            focus=self.board.selected_id()
            self.board.rebuild(focus_id=focus)
        except (SceneError,ValueError) as exc:
            QMessageBox.warning(self,"Historische V1-Szene",str(exc))

    def save_object(self):
        obj,raw=self._record()
        if obj is None:return
        try:
            if raw["art"]=="kachelobjekt":
                self.board.history.legacy_update_object_details(
                    obj.id,title=self.title.text(),frame=self.start.value(),
                    columns=self.columns.value(),
                    rows=self.rows.value(),layout=self.layout_kind.currentText())
            else:
                animation=dict(von=self.anim_start.value(),
                    bis=self.anim_end.value(),fps=self.fps.value()) if self.animate.isChecked() else None
                self.board.history.legacy_update_object_details(
                    obj.id,title=self.title.text(),frame=self.start.value(),
                    animation=animation,
                    remove_animation=not self.animate.isChecked(),
                    alternate=self.alt.isChecked())
            self.board.rebuild(focus_id=obj.id)
        except (SceneError,ValueError) as exc:
            QMessageBox.warning(self,"Historisches Objekt",str(exc))

    def toggle_play(self):
        if self._clock.isActive():
            self._clock.stop()
            self.play.setText("Abspielen")
        else:
            self._clock.start()
            self.play.setText("Pause")

    def closeEvent(self,event):
        self._clock.stop()
        self.board.scene_changed.disconnect(self.sync_scene_if_needed)
        self.board.selected_id_changed.disconnect(self.sync_object)
        super().closeEvent(event)
