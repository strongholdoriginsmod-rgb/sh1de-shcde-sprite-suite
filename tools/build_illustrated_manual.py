"""Rebuild SpriteSuite's bilingual screenshot handbook (authoring tool only).

Requires ReportLab on the authorized *packaging* workstation.
The shipped application only reads the finished PDF and does not require
ReportLab or an installed system Python. Never includes original game assets.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
from pathlib import Path
import os
from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.lib.utils import ImageReader

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "docs" / "guide-screens"
OUTPUT = ROOT / "docs" / "SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
W, H = landscape(A4)
INK = colors.HexColor("#15202a")
PANEL = colors.HexColor("#1d2934")
PANEL2 = colors.HexColor("#253541")
TXT = colors.HexColor("#f2f5f7")
MUTED = colors.HexColor("#b5c5d0")
GOLD = colors.HexColor("#edbb66")
CYAN = colors.HexColor("#77cbd2")
BORDER = colors.HexColor("#40505e")
WARN = colors.HexColor("#f5d399")


def register_fonts() -> None:
    """Use locally available fonts for generating PDF, never bundle TTFs."""
    options = [
        (Path("C:/Windows/Fonts/segoeui.ttf"), Path("C:/Windows/Fonts/segoeuib.ttf")),
        (Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")),
        (Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
         Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")),
    ]
    for normal, bold in options:
        if normal.is_file() and bold.is_file():
            pdfmetrics.registerFont(TTFont("SS", str(normal)))
            pdfmetrics.registerFont(TTFont("SS-Bold", str(bold)))
            pdfmetrics.registerFontFamily("SS", normal="SS", bold="SS-Bold")
            return
    raise RuntimeError("A Unicode TTF font is required to build the illustrated manual")


def text(c: Canvas, x: float, y: float, content: str, *, size: float = 11,
         bold: bool = False, color=TXT) -> None:
    c.setFont("SS-Bold" if bold else "SS", size)
    c.setFillColor(color)
    c.drawString(x, y, content)


def paragraph(c: Canvas, x: float, y: float, width: float, body: str, *,
              size: float = 10.6, leading: float = 15, color=MUTED,
              bottom: float = 65) -> float:
    """Draw a wrapped paragraph, fail rather than clipping below footer."""
    from reportlab.platypus import Paragraph
    style = ParagraphStyle(
        "body", fontName="SS", fontSize=size, leading=leading,
        textColor=color, alignment=TA_LEFT,
    )
    item = Paragraph(escape(body).replace("\n", "<br/>"), style)
    _, height = item.wrap(width, 1000)
    dest = y - height
    if dest < bottom:
        raise ValueError(f"Paragraph would clip page: {body[:45]!r} at {dest}")
    item.drawOn(c, x, dest)
    return dest - 11


def base(c: Canvas, page: int, chapter: str, title: str, subtitle: str) -> None:
    c.setFillColor(INK)
    c.rect(0, 0, W, H, fill=1, stroke=0)
    c.setFillColor(GOLD)
    c.roundRect(34, H - 56, 26, 26, 8, fill=1, stroke=0)
    c.setFillColor(INK)
    c.setFont("SS-Bold", 17)
    c.drawCentredString(47, H - 48, "S")
    text(c, 72, H - 46, "SPRITESUITE", size=13, bold=True)
    text(c, 197, H - 45.5, chapter.upper(), size=9, color=CYAN)
    text(c, W - 208, H - 45.5, "WINDOWS · VERSION 2.0.0", size=8.8, color=MUTED)
    text(c, 35, H - 97, title, size=24, bold=True)
    text(c, 36, H - 120, subtitle, size=10.8, color=MUTED)
    c.setStrokeColor(BORDER)
    c.line(34, 51, W - 34, 51)
    text(c, 36, 32, "Lokaler Integrationskandidat / Local integration candidate — keine Ingame-Freigabe", size=8.2, color=MUTED)
    text(c, W - 86, 32, f"{page:02d} / 09", size=8.5, color=GOLD)


def finish(c: Canvas) -> None:
    c.showPage()


def image_box(c: Canvas, filename: str, x: float, y: float, w: float, h: float, *,
              label: str = "", pad: float = 7) -> None:
    source = SCREEN / filename
    if not source.is_file():
        raise FileNotFoundError(source)
    c.setFillColor(PANEL)
    c.setStrokeColor(BORDER)
    c.roundRect(x, y, w, h, 12, fill=1, stroke=1)
    picture = ImageReader(str(source))
    iw, ih = picture.getSize()
    scale = min((w - 2 * pad) / iw, (h - (25 if label else 0) - 2 * pad) / ih)
    outw, outh = iw * scale, ih * scale
    px = x + (w - outw) / 2
    py = y + (h - (25 if label else 0) - outh) / 2 + (20 if label else 0)
    c.drawImage(picture, px, py, outw, outh)
    if label:
        text(c, x + 13, y + 10, label, size=8.8, color=CYAN)


def box(c: Canvas, x: float, y: float, w: float, h: float, title: str,
        body: str, *, gold: bool = False):
    c.setFillColor(PANEL2)
    c.roundRect(x, y, w, h, 9, fill=1, stroke=0)
    text(c, x + 12, y + h - 25, title, size=11, bold=True, color=GOLD if gold else TXT)
    paragraph(c, x + 12, y + h - 40, w - 24, body, size=9.4, leading=13.4,
              bottom=y + 9)


def points(c: Canvas, x: float, y: float, width: float,
           rows: list[tuple[str, str]], *, gap: float = 19) -> float:
    for index, (title, detail) in enumerate(rows, start=1):
        c.setFillColor(GOLD)
        c.circle(x + 13, y - 2, 12, fill=1, stroke=0)
        c.setFont("SS-Bold", 10)
        c.setFillColor(INK)
        c.drawCentredString(x + 13, y - 5.5, str(index))
        text(c, x + 35, y + 2, title, size=11, bold=True)
        y = paragraph(c, x + 35, y - 8, width - 36, detail,
                      size=9.7, leading=13.8, bottom=60) - gap
    return y


def build(output: Path) -> int:
    register_fonts()
    rl_config.invariant = 1
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise RuntimeError("Refusing symlinked output")
    # Deterministic object IDs and timestamps aid artifact integrity checks.
    c = Canvas(str(output), pagesize=(W, H), pageCompression=1, invariant=1)
    c.setTitle("SpriteSuite - Illustriertes Handbuch / Illustrated user guide")
    c.setAuthor("SpriteSuite development")
    c.setSubject("Windows x64, project workflow, compatibility, 2026-11-04")

    # Cover -----------------------------------------------------------------
    base(c, 1, "Benutzerhandbuch / user guide",
         "Deine Grafikwerkstatt. Ein Projekt.",
         "SpriteSuite 2.0.0 · Deutsch und English · Stand: 04.11.2026")
    text(c, 48, 422, "ILLUSTRIERTES HANDBUCH", size=17, bold=True, color=GOLD)
    y = paragraph(c, 48, 399, 320,
                  "Vom eigenen Bild bis zum überprüften statischen Mod-ZIP. "
                  "Projekt, Pixel, Layout, Noesis-XAML, Demo und Diagnose "
                  "bleiben in derselben Anwendung.", size=13.0, leading=20, color=TXT)
    y = paragraph(c, 48, y - 6, 320,
                  "From first image to a verified static mod ZIP. Work with "
                  "your files safely, with bilingual contextual guidance.",
                  size=11.2, leading=17)
    box(c, 48, 118, 300, 92, "WICHTIG / IMPORTANT",
        "Ein grüner Dateitest ist keine native Unity-, Noesis- oder "
        "Script-Extender-Freigabe.", gold=True)
    image_box(c, "ux-workflow-current.png", 385, 113, 421, 357,
              label="Echte Programmoberfläche / Real application view")
    finish(c)

    # Main application ------------------------------------------------------
    base(c, 2, "01 · Die Hauptoberfläche",
         "Ein gemeinsamer Arbeitsbereich",
         "Start mit 'Mein Mod-Projekt' · Hauptwege in der linken Seitenleiste")
    image_box(c, "ux-workflow-current.png", 34, 118, 768, 352,
              label="Arbeitsoberfläche: Projektdateien, Vorschau, Prüfung und Export")
    text(c, 49, 93,
         "Projekt & Dateien → Pixel & Layout → Spielvorschau → Prüfung & Fehler → Zielspiel & Mods",
         size=10.5, bold=True, color=GOLD)
    finish(c)

    # Import & edit ---------------------------------------------------------
    base(c, 3, "02 · Projekt-Workflow",
         "Importieren, bearbeiten, sichern",
         "Achte auf die Trennung von bearbeitbarem Projekt-ZIP und installierbarem Mod-ZIP")
    points(c, 42, 448, 375, [
        ("Projekt anlegen oder öffnen",
         "Wähle Neues Projekt oder Projekt-ZIP öffnen. Ein ZIP zur Projektsicherung ist keine Modinstallation."),
        ("Eigene Quellen importieren",
         "Wähle Dateien hinzufügen: PNG/JPG/WebP oder eine Noesis-XAML-Originalseite. SpriteSuite arbeitet mit Projektkopien."),
        ("Vorschau und Editoren",
         "Nach der Auswahl: Datei bearbeiten, Layout gestalten oder Noesis-XAML bearbeiten. Speichere offene Änderungen."),
        ("Dateien statisch prüfen",
         "Änderungen prüfen meldet Dateiintegrität und syntaktische Probleme, nicht erfolgreiche Unity-Laufzeitintegration."),
    ])
    image_box(c, "ux-workflow-current.png", 432, 140, 367, 300,
              label="Keine Originalspiel-Dateien zum Üben nötig")
    finish(c)

    # Tutorial --------------------------------------------------------------
    base(c, 4, "03 · Geführte Anleitung",
         "Hilfestellung ohne versteckte Aktionen",
         "Strg+F1 · Schritt für Schritt · markiert echte Bedienelemente")
    image_box(c, "ux-tutorial-quickstart-DE.png", 42, 117, 306, 352,
              label="Lernpfad: Projekt bis Mod-ZIP")
    y = 448
    for heading, desc in [
        ("Lernpfad auswählen", "Projekt bis Mod-ZIP, Pixel und Ebenen, Spielvorschau, Demo-Module oder Kompatibilität."),
        ("Weiter / Zurück", "Der Lernpfad markiert echte Schaltflächen. Er importiert, installiert oder exportiert NICHT automatisch."),
        ("Bedienelement zeigen", "Bringt dich zur richtigen Ansicht. Erst dein bewusster Klick startet eine Verarbeitung."),
        ("Fortschritt speichern", "Lokal pro Benutzer. Der Status ist keine technische oder Ingame-Abnahme."),
    ]:
        text(c, 377, y, heading, size=12, color=GOLD, bold=True)
        y = paragraph(c, 377, y - 10, 402, desc, size=10.4, leading=15) - 12
    finish(c)

    # Layout DE/EN ----------------------------------------------------------
    base(c, 5, "04 · Pixel und Ebenen",
         "Layout bearbeiten / Edit your layout",
         "Dieselben Schritte in Deutsch und Englisch · echte Tutorial-Fenster")
    image_box(c, "ux-tutorial-layout-DE.png", 42, 128, 300, 342,
              label="DE: Pixel und Ebenen")
    image_box(c, "ux-tutorial-layout-EN.png", 359, 128, 300, 342,
              label="EN: Pixels and layers")
    box(c, 673, 242, 134, 182, "Ablauf / Steps",
        "1. Bild importieren.\n2. Layout gestalten.\n3. Ebenen sichern.\n4. PNG und Positionen prüfen.", gold=True)
    text(c, 675, 190, "Die Spielansicht ist", size=9.5, color=TXT)
    text(c, 675, 176, "separat zu prüfen.", size=9.5, color=MUTED)
    finish(c)

    # Demos -----------------------------------------------------------------
    base(c, 6, "05 · Interaktive Demos",
         "Funktionen kennenlernen – ohne Installation",
         "26 Demo-Module mit Beispieldaten; die Werkzeugaktion bleibt bewusst getrennt")
    image_box(c, "ux-demo-26-modules.png", 41, 119, 765, 350,
              label="Interaktiver Modul-Demo-Modus · Screenshot aus der laufenden Suite")
    text(c, 47, 93,
         "Ein Demo-Beleg ist kein Ingame-Nachweis. Originalressourcen nur autorisiert und optional verwenden.",
         size=10.0, color=GOLD)
    finish(c)

    # Compatibility ---------------------------------------------------------
    base(c, 7, "06 · Kompatibilität",
         "Lesende Diagnose statt blinder Freigabe",
         "Python, Tcl/Tk, Qt und optionale Werkzeuge prüfen · lokale Steam-Installation getrennt behandeln")
    image_box(c, "ux-compatibility-readonly.png", 39, 119, 476, 347,
              label="Tatsächlicher Windows-Kompatibilitätsbericht")
    y = 441
    for heading, body in [
        ("Bereit / Ready", "Die Voraussetzung wurde lokal geprüft. Das gilt nur für die angegebene Komponente."),
        ("Eingeschränkt / Limited", "Etwa ein fehlendes .NET-SDK: normale Bildbearbeitung kann dennoch funktionieren."),
        ("Nicht bestätigt / Unverified", "Die native Spiel-ABI und echte Noesis-Ereignisse brauchen gesonderte Ingame-Prüfung."),
        ("Steam lesen", "Die Steam-Version wird lesend erkannt. Ein BuildID bestätigt weder Mapping noch native Binärkompatibilität."),
    ]:
        text(c, 543, y, heading, size=11, bold=True, color=GOLD)
        y = paragraph(c, 543, y - 11, 258, body, size=9.8, leading=14) - 8
    finish(c)

    # Export workflow -------------------------------------------------------
    base(c, 8, "07 · Sicherer Export",
         "Zwei ZIPs. Zwei unterschiedliche Zwecke.",
         "Prüfsumme und Projekt-Backup erhalten · keine automatische Installation in Spielordner")
    box(c, 45, 298, 361, 151, "BEARBEITBARES PROJEKT-ZIP",
        "Projekt sichern (ZIP) bewahrt importierte Quellen, Layout, "
        "Metadaten und private Noesis-Revisionsdateien. "
        "Projekt-ZIP öffnen erstellt eine geprüfte neue Arbeitskopie.",
        gold=True)
    box(c, 434, 298, 361, 151, "STATISCHES MOD-ZIP",
        "Geprüftes Mod-ZIP bauen erstellt nach der Dateiprüfung eine "
        "SHA-256-gebundene Paketdatei. Sie kann immer noch nicht als "
        "native Spiel-/Plugin-Freigabe gelten.",
        gold=False)
    box(c, 45, 122, 361, 155, "Bei einem Fehler",
        "Vorherige ZIP-Dateien nicht überschreiben. Prüfe den Exportbeleg, "
        "den Status 'aktuell' und die Projekt-Hashes. "
        "Sichere zuerst deine editierbaren Quellen.")
    box(c, 434, 122, 361, 155, "Before distributing",
        "Use the fully extracted Windows x64 package with its bundled "
        "Python runtime. Verify ZIP SHA-256, open the project again, "
        "and test the GUI on an independent Windows computer.")
    finish(c)

    # Last page -------------------------------------------------------------
    base(c, 9, "08 · Hinweise / release gates",
         "Was tatsächlich bestätigt ist",
         "Complete application does not mean automatic game compatibility")
    box(c, 44, 287, 363, 171, "LOKAL TESTBAR / LOCAL CHECKS",
        "Python-, Tcl/Tk- und Qt-Start\nBilder, XAML, Projekt-ZIP und statisches Mod-ZIP\nDemo-Schritte und SHA-Nachweise\nLesende Steam-/Kompatibilitätsdiagnose",
        gold=True)
    box(c, 429, 287, 365, 171, "OFFEN / STILL REQUIRES QA",
        "Echte Native-Noesis-/Unity-Ausgabe und Script Extender ABI\n"
        "Rückkehr zur Originalgrafik / Rollback\n"
        "DPI, Bedienbarkeit, Screenreader und Belastung\n"
        "Unabhängiger zweiter Windows-PC\n"
        "GitHub-CI sowie menschliche Merge-/Releasefreigabe",
        gold=False)
    text(c, 48, 243, "Start / Launch", size=12, bold=True, color=GOLD)
    paragraph(c, 48, 233, 755,
              "ZIP vollständig entpacken → SpriteSuite/Suite starten.cmd. "
              "Diagnose: Suite starten.cmd --self-test. "
              "Das Handbuch installiert nichts und erfordert keine eigenen Spielressourcen.",
              size=11.1, leading=18, color=TXT)
    text(c, 48, 140, "Sicherheit / Safety", size=12, bold=True, color=CYAN)
    paragraph(c, 48, 130, 755,
              "Kein automatisches Überschreiben fremder Mods, keine native "
              "Versionsfreigabe aus einer Steam-Buildnummer, keine Aussage "
              "über echte Ingame-Funktion ohne unabhängigen Nachweis. "
              "No installation, merge or public release is implied by this PDF.",
              size=10.7, leading=17, color=MUTED)
    finish(c)
    c.save()
    return 9


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    opts = parser.parse_args()
    pages = build(opts.output)
    print(f"HANDBOOK_CREATED={opts.output}")
    print(f"HANDBOOK_PAGES={pages}")
    print(f"HANDBOOK_BYTES={opts.output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
