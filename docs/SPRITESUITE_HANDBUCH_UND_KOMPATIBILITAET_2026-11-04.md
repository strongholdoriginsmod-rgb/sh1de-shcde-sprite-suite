# SpriteSuite – illustrierte Anleitung und fehlersichere Kompatibilitätsprüfung

**Stand:** 4. November 2026 · **Quelle:** isolierter Integrationszweig
`feature/illustrated-handbook-20261104` auf Basis von `2284a86`.

## Enthaltene Komponenten

- `docs/SPRITESUITE_ILLUSTRIERTES_HANDBUCH.pdf`: illustriertes, zweisprachiges
  Handbuch mit neun echten, überprüften PDF-Seiten.
- `docs/guide-screens/`: sechs Screenshots aus einer lokalen QA-Installation
  von SpriteSuite, ohne private Originalgrafiken oder Spielinstallationsdaten.
- `tools/build_illustrated_manual.py`: reproduzierbarer, optionaler
  Dokumentations-Builder für Entwicklungsumgebungen mit ReportLab.
- `tools/verify_illustrated_manual.py`: optionaler Render-/Text-/Bild-Check
  für eine Entwicklungsumgebung mit PyMuPDF.
- Neue geführte Tutorial- und Kompatibilitätsfenster aus dem separaten
  UI-Entwicklungszweig als lokal gesicherter Snapshot – **keine Änderungen**
  an der dortigen Arbeitskopie.

Die normale Portable-Anwendung benötigt für das **Öffnen** des fertigen
PDFs weder ReportLab noch PyMuPDF.

## Handbuch erneut erstellen

Auf einer autorisierten Entwicklungsmaschine mit ReportLab:

```powershell
python tools/build_illustrated_manual.py
```

Die generierte PDF-Datei kann in einem PDF-Betrachter gelesen werden.
Der Build verwendet lokale Schriftarten, die **nicht** in den Quellstand
übernommen werden. Die interne PDF-Metadatenzeit ist stabil, damit sich
dieselben Quellen bytegenau reproduzieren lassen.

Die mit PyMuPDF gerenderten neun Seiten wurden visuell geprüft; 8
Bildverwendungen, 833 extrahierbare Textwörter, 0 Wörter außerhalb
der Seitenfläche. Ein unabhängiger zweiter Build stimmte
SHA-256-identisch mit dem ersten überein.

## Behobene Kompatibilitätsrisiken

1. **Diagnosebericht:** Die Exportfunktion legt ihre lokale JSON-Datei
   nur noch neu an. Bereits vorhandene Dateien werden auch dann nicht
   überschrieben, wenn der Dateidialog denselben Namen zurückgibt.
   Symbolische Links als direkte Ziele oder direkte Eltern werden
   zurückgewiesen. Eine bewusste Änderung vorhandener Berichte ist
   in dieser Funktion nicht vorgesehen.
2. **Tcl/Tk 8.6:** Zwei vorhandene Skripte reichen nicht für den Status
   `ready`. Der Prüfer nutzt nun den vierteiligen Startvertrag der
   tatsächlichen Anwendung (Tcl-Init, Tk-Init, ttk, PanedWindow).
   Ein unvollständig entpacktes Paket meldet `limited` und nennt
   die defekte Laufzeit, statt vorschnell Erfolg auszugeben.
3. **Native Freigabe:** Eine aktuelle Steam-Buildnummer oder
   ein grüner Hostbericht bedeutet weiterhin ausdrücklich **keine**
   verifizierte Unity-/Noesis-/Script-Extender-ABI, Modinstallation oder
   Hardware-/Ingame-Abnahme.

## Offene Freigabe

Vor einer späteren öffentlichen Version weiterhin notwendig:

- Unabhängiger GitHub-Windows-CI-Test auf Python 3.13 und 3.14
- C#-/Plugin-Build und echte ABI-Prüfung mit korrekt gepinnten Binärdateien
- Ingame-Noesis-Interaktion, Rollback und echte Originalgrafik-Golden-Tests
- Barrierefreiheit/DPI/Screenreader sowie unabhängiger zweiter Windows-PC
- Ein bestätigter Review der Änderungen aus weiteren Entwicklerzweigen

**Kein Spiel wurde verändert, kein Merge/Push/Release ausgeführt.**

## Windows-Tcl-Bootstrap bei sporadischem Datei-Lesezugriff

Die vorhandene, maximal fünffache Tk-Initialisierungswiederholung wurde
auf zwei weitere konkret beobachtete native Bibliothekspfade ausgedehnt:
`tcl8.6/auto.tcl` und `tk8.6/ttk/panedwindow.tcl`. Wiederholt wird
ausschließlich ein Tcl-Lesefehler dieser bekannten Laufzeitdateien,
**nicht** ein gewöhnlicher fehlgeschlagener Editor-/Benutzerskriptaufruf.

Wirklich fehlende oder beschädigte Dateien werden durch wiederholte
Versuche nicht als gültig ausgegeben. Der private Tcl-Cache wird weder
gelöscht noch überschrieben. Die Regression prüft beide Wiederholungen
sowie, dass Fehler eines fremden Skripts unverändert durchgereicht werden.
