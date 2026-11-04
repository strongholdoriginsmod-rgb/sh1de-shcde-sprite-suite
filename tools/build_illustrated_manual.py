"""Build SpriteSuite's illustrated German manual from real QA screenshots.

Dev-only dependency: ReportLab. This builder is NOT required to run the
bundled app and is not executed during regular SpriteSuite startup.
"""
from __future__ import annotations

from pathlib import Path
import math
import re
from PIL import Image as PILImage
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4,landscape
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

ROOT=Path(__file__).resolve().parents[1]
FIG=ROOT/"docs"/"handbuch_bilder"
OUT=ROOT/"docs"/"SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf"
FONT=Path("C:/Windows/Fonts/segoeui.ttf")
BOLD=Path("C:/Windows/Fonts/segoeuib.ttf")
if not FONT.is_file() or not BOLD.is_file():
    raise SystemExit("Windows Segoe UI TTF fonts are required for PDF authoring.")
pdfmetrics.registerFont(TTFont("Manual-Regular",str(FONT)))
pdfmetrics.registerFont(TTFont("Manual-Bold",str(BOLD)))
W,H=landscape(A4)
INK=HexColor("#223348")
DARK=HexColor("#162535")
BLUE=HexColor("#1b6480")
GOLD=HexColor("#d39c40")
SUB=HexColor("#536577")
LIGHT=HexColor("#edf3f7")
BORDER=HexColor("#d4e0e8")
WHITE=HexColor("#ffffff")
PAPER=HexColor("#f9fbfd")

def text(c,t,x,y,size=11,bold=False,color=INK):
    c.setFillColor(color)
    c.setFont("Manual-Bold" if bold else "Manual-Regular",size)
    c.drawString(x,y,str(t))


def _wrap(t,width,size,bold=False):
    font="Manual-Bold" if bold else "Manual-Regular"
    lines=[]
    for paragraph in str(t).split("\n"):
        if not paragraph.strip():
            lines.append("")
            continue
        words=paragraph.split()
        line=""
        for word in words:
            attempt=(line+" "+word).strip()
            if pdfmetrics.stringWidth(attempt,font,size)>width and line:
                lines.append(line)
                line=word
            else:
                line=attempt
            # Very long paths should never run into page borders.
            while pdfmetrics.stringWidth(line,font,size)>width and len(line)>1:
                cut=len(line)-1
                while cut>1 and pdfmetrics.stringWidth(line[:cut],font,size)>width:cut-=1
                lines.append(line[:cut])
                line=line[cut:]
        if line:lines.append(line)
    return lines


def para(c,s,x,top,width,size=10.5,leading=15,color=INK,bold=False,max_lines=None):
    lines=_wrap(s,width,size,bold)
    if max_lines is not None and len(lines)>max_lines:
        raise ValueError(f"Paragraph exceeds {max_lines} lines: {s[:100]}")
    for line in lines:
        if line:
            text(c,line,x,top-size,size,bold,color)
        top-=leading
    return top


def bullet(c,s,x,top,width,size=10.5,leading=16,color=INK):
    c.setFillColor(GOLD)
    c.circle(x+6,top-8,3,stroke=0,fill=1)
    return para(c,s,x+18,top,width-18,size,leading,color)-5


def card(c,x,top,w,h,title,body,accent=BLUE):
    c.setFillColor(LIGHT)
    c.roundRect(x,top-h,w,h,8,fill=1,stroke=0)
    c.setFillColor(accent)
    c.roundRect(x+12,top-35,4,22,2,fill=1,stroke=0)
    text(c,title,x+25,top-25,12,True)
    para(c,body,x+17,top-45,w-35,size=10,leading=14)


def figure(c,filename,x,top,maxwidth,maxheight,label=""):
    source=FIG/filename
    if not source.is_file():raise FileNotFoundError(source)
    with PILImage.open(source) as im:
        iw,ih=im.size
    scale=min(maxwidth/iw,maxheight/ih)
    w,h=iw*scale,ih*scale
    c.setFillColor(WHITE)
    c.setStrokeColor(BORDER)
    c.roundRect(x-5,top-h-5,w+10,h+10,6,fill=1,stroke=1)
    c.drawImage(ImageReader(str(source)),x,top-h,width=w,height=h,
                preserveAspectRatio=True,mask="auto")
    if label:
        text(c,label,x,top-h-20,9,color=SUB)
    return top-h


def header(c,page,section,title,subtitle):
    c.setFillColor(PAPER)
    c.rect(0,0,W,H,fill=1,stroke=0)
    c.setFillColor(DARK)
    c.rect(0,H-92,W,92,fill=1,stroke=0)
    text(c,"SPRITESUITE  /  HANDBUCH  /  2.0.0",35,H-23,10,True,HexColor("#b6d4e4"))
    text(c,title,35,H-52,22,True,WHITE)
    text(c,subtitle,35,H-77,10,color=HexColor("#d6e5ef"))
    c.setStrokeColor(BORDER)
    c.line(35,38,W-35,38)
    text(c,"Lokaler Windows-x64-Kandidat  |  Stand 04.11.2026",35,20,8.5,color=SUB)
    text(c,f"{page:02d}  /  {section}",W-169,20,8.5,color=SUB)


def next_page(c):
    c.showPage()


def image_page(c,number,section,title,subtitle,fn,legend,notes):
    header(c,number,section,title,subtitle)
    # Reserve separate areas for the figure caption and two bullet notes.
    # This avoids notes overlapping the caption at normal A4 zoom.
    with PILImage.open(FIG/fn) as im:
        iw,ih=im.size
    scale=min(755/iw,345/ih)
    screenshot_width=iw*scale
    image_bottom=figure(c,fn,(W-screenshot_width)/2,H-111,755,345,legend)
    if image_bottom<135:
        raise AssertionError((fn,image_bottom))
    top=100
    for line in notes:
        top=bullet(c,line,44,top,755,size=9.2,leading=12.2)
    next_page(c)


def section_title(c,s,x,y):
    text(c,s,x,y,13,True,BLUE)


def make():
    c=canvas.Canvas(str(OUT),pagesize=(W,H),pageCompression=1)
    c.setTitle("SpriteSuite 2.0.0 - Illustriertes Handbuch und geführte Anleitung")
    c.setAuthor("SpriteSuite")
    c.setSubject("Bebilderte Benutzeranleitung; Lernmodus; Demo und Windows-Kompatibilität")
    c.setKeywords("SpriteSuite; Anleitung; Demo; Noesis; Windows; Kompatibilität; PDF")

    # Page 01
    c.setFillColor(DARK);c.rect(0,0,W,H,stroke=0,fill=1)
    c.setFillColor(GOLD);c.roundRect(35,H-75,6,44,3,stroke=0,fill=1)
    text(c,"SpriteSuite 2.0.0",55,H-48,29,True,WHITE)
    text(c,"Bebildertes Handbuch & geführte Anleitung",55,H-74,16,color=HexColor("#e3edf5"))
    text(c,"Importieren - Bearbeiten - Prüfen - Sicher exportieren",55,H-100,11,color=HexColor("#b6d4e4"))
    figure(c,"01-projektwerkbank.png",55,H-121,730,386)
    text(c,"Reale Windows-Aufnahme aus einer isolierten SpriteSuite-Testumgebung.",55,65,9,color=HexColor("#c9d8e5"))
    text(c,"Stand: 04. November 2026  |  Ausgabe für Windows x64  |  keine native Ingame-Freigabe",55,40,9,color=HexColor("#d0dce7"))
    next_page(c)

    # Page 02
    image_page(c,2,"ÜBERBLICK","Ein Projekt. Ein sinnvoller Ablauf.",
               "Die zentrale Projekt-Werkbank ist der sichere Ausgangspunkt.",
               "01-projektwerkbank.png","Bild 1 - Hauptfenster mit Werkbank und Navigationsleiste.",
               ["Links liegen Dateien und Import; rechts erscheinen die Vorschau und Editoren.",
                "Prüfung und statischer Mod-ZIP-Export bleiben unten erreichbar."])

    # Page 03
    header(c,3,"ANLEITUNG","Geführter Anleitungsmodus",
           "Ohne Eingriffe in deine Bilddateien oder Spielinstallationen.")
    figure(c,"02-gefuhrte-anleitung.png",43,H-113,300,410,
           "Bild 2 - Der schrittweise Assistent.")
    section_title(c,"So funktioniert er",390,H-126)
    y=H-145
    for phrase in [
        "Über »Anleitung (Strg+F1)« links jederzeit öffnen.",
        "Lernpfad wählen: Projekt bis Mod-ZIP, Pixel/Ebenen, Spielvorschau, Demo oder Kompatibilität.",
        "Mit »Bedienelement zeigen« zum echten Werkzeug springen; das Ziel wird hervorgehoben.",
        "»Weiter« und »Zurück« steuern ausschließlich die Anleitung. Speichern, Bauen und Installieren werden nicht automatisch ausgeführt.",
        "Der Fortschritt bleibt nutzerlokal gespeichert; Schließen unterbricht keinen Bearbeitungsvorgang.",
    ]:y=bullet(c,phrase,389,y,401,size=11,leading=16.1)
    next_page(c)

    # Page 04
    header(c,4,"LERNPFADE","Fünf Wege durch SpriteSuite",
           "Starte bei deiner Aufgabe - nicht in einem unübersichtlichen Funktionskatalog.")
    sections=[
        ("01   Projekt bis Mod-ZIP","Import  →  Vorschau  →  Bearbeiten  →  Prüfen  →  Export  →  Projektsicherung"),
        ("02   Pixel und Ebenen","HUD-Pixel bearbeiten, Layout-Designer öffnen, Ebenen verschieben und Komposition prüfen"),
        ("03   Spielvorschau","Karte öffnen, Testfeld nutzen und fehlende Spielkonfiguration nachvollziehen"),
        ("04   Demo-Module","26 echte Demo-Module bewusst starten, Ergebnisse und SHA-256-Belege prüfen"),
        ("05   Kompatibilität und Sicherheit","Windows-/Python-/Tcl-/Qt-Status und Spielgrenzen lesend diagnostizieren"),
    ]
    y=H-116
    for i,(title,desc) in enumerate(sections):
        card(c,43+(i%2)*386,y-(i//2)*125,366,110,title,desc,
             GOLD if i==4 else BLUE)
    # last card occupies left; explanatory callout right
    card(c,429,H-116-2*125,366,110,"MERKE",
        "Eine geführte Ansicht ist keine Freigabe der Game-ABI. Die echte Spielprüfung bleibt separat.",
        GOLD)
    next_page(c)

    # Page 05
    image_page(c,5,"WORKFLOW","Dateien und Grafiken verwalten",
               "Eine private Projektkopie schützt deine Originaldaten.",
               "01-projektwerkbank.png","Bild 3 - Import, Vorschau, Bildbearbeitung und Export auf einer Seite.",
               ["»Dateien hinzufügen« kopiert Quellbilder in das aktuelle Projekt.",
                "Die Kategorie bleibt intern unverändert; Übersetzungen betreffen nur die Anzeige."])

    # Page 06
    image_page(c,6,"LAYOUT","Layout-Designer und Ebenen",
               "Bildflächen frei arrangieren, positionieren und reproduzierbar ausgeben.",
               "05-layout-designer.png","Bild 4 - Editor an seiner geprüften Mindestfenstergröße.",
               ["Mit Strg+S das editierbare Szenenlayout sichern, bevor ein PNG ausgegeben wird.",
                "Die Ebenenliste und exakten Positionseigenschaften sind unabhängig von der Vorschau."])

    # Page 07
    image_page(c,7,"DEMO","Interaktive Demos mit echten Dateien",
               "Ein durchlaufener Schritt erzeugt überprüfbare Ausgaben statt bloßer Animation.",
               "04-demo-modus.png","Bild 5 - Modulwahl, echte Schritte und nachvollziehbare Artefakte.",
               ["»Neuen Demolauf starten« legt einen separaten Demo-Arbeitsbereich an.",
                "Manche Module brauchen Originaldateien oder ein SDK; ohne Voraussetzung wird kein Erfolg vorgetäuscht."])

    # Page 08
    image_page(c,8,"SPIELVORSCHAU","Echte Spielvorschau - Grenzen kennen",
               "Eine leere Karte ist kein Renderfehler und kein Ingame-Beleg.",
               "06-spielvorschau.png","Bild 6 - Eingebettete Qt-Spielvorschau ohne zugeordnete Originalkarte.",
               ["»Karte öffnen« lädt eine konfigurierte Karte; ansonsten hilft »Spielordner einrichten«.",
                "Ein aktueller Steam-Build bestätigt noch keine native Noesis-/Script-Extender-Kompatibilität."])

    # Page 09
    header(c,9,"KOMPATIBILITÄT","Kompatibilität sicher prüfen",
           "Nur lesende Diagnose; keine Treiber-, SDK- oder Spielinstallation.")
    figure(c,"07-kompatibilitaetsdiagnose.png",39,H-115,453,378,
           "Bild 7 - Lokale Diagnose des Windows-Portable-Pakets.")
    section_title(c,"Was geprüft wird",524,H-126)
    y=H-144
    for s in [
       "Windows x64 und unterstützte CPython-Laufzeit (3.13 oder 3.14).",
       "Vorhandene Tcl/Tk-Skripte und Qt-Sandbox.",
       "Exakte Versionen aus der passenden Abhängigkeits-Lockdatei.",
       "Optionales .NET SDK: relevant für C#-Entwicklung, nicht für den normalen GUI-Start.",
       "Steam-Libraries auf Wunsch nur lesend.",
       "Native ABI bleibt ausdrücklich »Nicht bestätigt«.",
    ]:y=bullet(c,s,518,y,283,size=10.3,leading=14.4)
    next_page(c)

    # Page 10
    header(c,10,"EXPORT","Zwei ZIP-Dateien - zwei Zwecke",
           "Projekt sichern ist etwas anderes als ein statisches Mod-ZIP bauen.")
    card(c,42,H-117,365,226,"Bearbeitbares Projekt-ZIP",
         "Schaltfläche: »Projekt sichern (ZIP)«. Enthält Projektstruktur, editierbare PNG-/XAML-Revisionen und Arbeitsdaten. Zum Weiterbearbeiten über »Projekt-ZIP öffnen« wiederherstellen. KEIN installierbares Modpaket.")
    card(c,428,H-117,365,226,"Geprüftes statisches Mod-ZIP",
         "Schaltfläche: »Geprüftes Mod-ZIP bauen«. Enthält geprüfte exportierte Assets, dokumentierte Ressourcen und SHA-256-Belege. Baut KEINE eigene native DLL ein und installiert nichts automatisch.",GOLD)
    section_title(c,"Empfohlener sicherer Ablauf",44,H-380)
    y=H-398
    for item in [
        "Quellbilder importieren und bearbeiten, Zwischenschritte speichern.",
        "Projekt-ZIP erstellen, bevor Dateien umstrukturiert oder ersetzt werden.",
        "»Änderungen prüfen« ausführen und eventuelle Warnungen auswerten.",
        "Statisches Mod-ZIP bauen; ZIP-Inhalt und Prüfsumme kontrollieren.",
        "Einen echten Spieltest ausschließlich in einer autorisierten QA-Spielkopie durchführen.",
    ]:y=bullet(c,item,43,y,753,size=10.4,leading=14)
    next_page(c)

    # Page 11
    image_page(c,11,"SPRACHE","Deutsch und Englisch",
               "Die Oberfläche wechselt ohne Veränderung deiner Projektdateien.",
               "08-englische-oberflaeche.png","Bild 8 - Englische UI bei 1020 × 680 Pixeln.",
               ["Sprachauswahl links unten: DE / EN. Dateinamen und gespeicherte Exportpfade bleiben unverändert.",
                "Kompaktfenster: links Navigation, rechts Vorschau, unten Prüfen und Export."])

    # Page 12
    header(c,12,"BEDIENUNG","Fenstergrößen und Tastatur",
           "Für kleine Fenster, hohe DPI-Skalierung und reine Tastaturbedienung.")
    figure(c,"05-layout-designer.png",42,H-115,420,324,
           "Bild 9 - Kompaktlayout des Ebenen-Designers.")
    section_title(c,"Nützliche Steuerungen",493,H-122)
    y=H-141
    for s in [
      "Strg+F1 öffnet die neue geführte Anleitung.",
      "Strg+K findet weitere Arbeitsbereiche.",
      "Alt+Links / Alt+Rechts blättert durch Lernschritte.",
      "Strg+S sichert im Layout-Designer.",
      "Mausrad zoomt in der Spiele-/Bildvorschau abhängig vom Werkzeug.",
      "Weitere Fachfunktionen bleiben über »Werkzeuge« und die Abschnittsauswahl erreichbar.",
    ]:y=bullet(c,s,489,y,316,size=10.2,leading=14.3)
    para(c,"Hinweis: Die lokale Skalierungsprüfung ersetzt keinen unabhängigen Screenreader- oder Hardware-DPI-Test.",
         45,115,749,size=10,leading=14,color=SUB)
    next_page(c)

    # Page 13
    header(c,13,"FAQ","Häufige Fragen und typische Probleme",
           "Fehlermeldungen ernst nehmen: kein grünes Erfolgssignal ohne Beleg.")
    faq=[
      ("Kein Python installiert?", "Die Portable-Ausgabe enthält Python 3.13. Das ZIP vollständig in einen kurzen Ordner wie C:/SpriteSuite oder E:/SS entpacken: Sehr tiefe Pfade können die Windows-260-Zeichen-Grenze überschreiten. Dann »Suite starten.cmd« öffnen."),
      ("Fenster bleibt leer?", "Prüfe im Kompatibilitätsfenster Tcl/Tk und Qt. Eine fehlende Spielkarte ist zunächst ein Einrichtungsproblem, nicht automatisch ein Absturz."),
      ("Warum fehlt .NET?", "Das SDK wird nur für bestimmte native C#-Entwicklungsschritte benötigt. Der normale Grafik- und Projektworkflow bleibt verfügbar."),
      ("Warum ist mein neuer Steam-Build nicht freigegeben?", "Versionserkennung ist nur lesend. Unity-/Noesis-ABI und private Sprite-Mappings benötigen reale Ingame- und Rückbautests."),
      ("Wo sind die 26 Demos?", "»Werkzeuge« öffnen und »Interaktiver Demo-Modus« wählen, oder den Lernpfad »Demo-Module« starten."),
    ]
    y=H-122
    for i,(q,a) in enumerate(faq):
        section_title(c,q,45,y)
        y=para(c,a,47,y-8,740,size=10.8,leading=16)-18
    next_page(c)

    # Page 14
    header(c,14,"FREIGABE","Was die Tests belegen - und was nicht",
           "Nachvollziehbare Veröffentlichung statt voreiliger Kompatibilitätsbehauptungen.")
    card(c,40,H-120,363,228,"Lokal automatisiert überprüft",
         "Echte Tk-Hauptoberfläche und bedienbare Lernschritte; Portable-Start unter Windows x64; ZIP-Integrität; PNG-/XAML-Sicherung und synthetischer Export; Sprachen und Abhängigkeitsversionen.")
    card(c,423,H-120,373,228,"Vor Stable noch offen",
         "Unabhängiger Windows-Zweitgerätetest; echte Noesis-/Unity-/C#-ABI-Prüfung; autorisierte Ingame-Modinstallation samt Atlas-Rollback; manuelle Tastatur-, Screenreader- und Nutzungsabnahme.",GOLD)
    section_title(c,"Kurze Checkliste vor jedem echten Spieltest",44,H-386)
    y=H-400
    for s in [
       "Originalinstallation nicht automatisch überschreiben.",
       "Projekt und Quellgrafiken vor dem Export sichern.",
       "Alle kritischen Warnungen, CRC-/SHA-256-Belege und Spielversion dokumentieren.",
       "Nur in einer autorisierten QA-Spielkopie testen und Rollback nachvollziehen.",
    ]:y=bullet(c,s,45,y,750,size=10.5,leading=14.5)
    next_page(c)

    c.save()
    print("PDF_CREATED",OUT,"BYTES",OUT.stat().st_size,flush=True)


if __name__=="__main__":
    make()
