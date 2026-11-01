# SpriteSuite – geführter Demo-Modus mit realen Verarbeitungsschritten

**Entwicklungszweig:** feature/module-demo-mode-20261101
**Einstieg:** Hauptnavigation → Interaktiver Demo-Modus oder HUD & Menüs → Bearbeitungswerkzeuge → Demo-Modus.

## Grundprinzip

Die Vorführungen sind keine Animation, kein Video und keine gefälschten
Erfolgsanzeigen: Jeder Schritt ruft echte vorhandene SpriteSuite-Funktionen
auf. Der Assistent schreibt bearbeitete Dateien, lädt sie erneut, prüft
Ergebnisse und erstellt bei den entsprechenden Modulen ein echtes
BepInEx-/Script-Extender-Asset-Mod-ZIP. Er dokumentiert tatsächliche
Dateigrößen und SHA-256-Werte. Bei einem fehlgeschlagenen Schritt bleibt die
Anzeige offen und springt nicht automatisch weiter.

Die Demo bietet zehn einzeln auswählbare Arbeitsmodule. Die
Schrittbeschreibungen nennen die tatsächlich genutzte Funktion.
Die Code- und Dateiansicht liest erzeugte XAML-, C#-, JSON-,
Text- und PNG-Dateien direkt von Datenträger.

### Vorführungen

| Modul | Tatsächlich ausgeführte Funktionen | Echte Ausgabe |
| --- | --- | --- |
| Original-Menüseiten / Noesis | Original-XAML einlesen, Attributes/Commands ändern, Elemente einfügen, verschieben, drehen, Version 1/2 speichern | Editierbares XAML, Noesis-Patch und Mod-ZIP |
| XAML-Patch-Werkstatt | SetAttribute-Patch erzeugen, XPath anwenden, Control weiter bearbeiten | XAML-Revisionen und Mod-ZIP |
| Pixelgrafik / HUD-Editor | PNG importieren, Pixel zeichnen, schreiben, Pixel nachlesen | Geändertes PNG und Mod-ZIP |
| HUD-/Menü-Layout & Ebenen | Ebenen anlegen, verschieben, kopieren, drehen, speichern, rendern, prüfen | Layout-JSON, Composite-PNG und Mod-ZIP |
| Noesis-Themes | ResourceDictionary lesen, Color ersetzen, Brush-Bindings prüfen | Geändertes Theme-XAML und Mod-ZIP |
| Sprachdateien | crusader.txt erzeugen, Menütext ersetzen, importieren | Locale-Datei und Mod-ZIP |
| Origins-Kampagnen | 3 Missionen generieren, C#-/XAML-Quellen prüfen, C# kompilieren und ausführen | Missionsplan, C#-Quelle, Verhaltenstests |
| Atlas-/Saisonwerkstatt | PNG-Atlas/Frames rendern, GM-ID prüfen, C#-Routen erzeugen, MapLoad/MapUnload testen | Atlas, Saisonpaket und C#-Testbericht |
| Mod-Paketbuilder | PNG+XAML importieren, Grafik bearbeiten, Assets prüfen, ZIP CRC lesen | Script-Extender-Mod-ZIP |
| Menüvideo / WebM-Override | Echte Benutzer-WebM prüfen, Bytes übernehmen und im ZIP bestätigen | Echte WebM-Override-Ressource |

### Original-Codebestandteile und Beispielquellen

1. **Vorbereitete, eigenständige Beispielquellen:** Originaltypische
   Noesis-XAML mit echten Button-Bindings, Noesis-ResourceDictionary,
   crusader.txt mit Lokalisierungsmarkern, PNGs und C#-Kampagnenplan.
   Sie entstehen in der privaten Demo-Sitzung und werden wirklich geändert.
2. **Echte lokale Originalquelle des Anwenders:** Für Noesis und XAML-Patches
   kann eine aus dem installierten Spiel gelesene FrontendMenus.xaml
   ausgewählt werden. Die Quelle wird nur lesend kopiert; es wird niemals
   in die echte Installation geschrieben. Für Kampagnen zeigt die Demo
   einen Auszug des eigenen Laufzeit-C#-Kerns aus
   runtime/SpriteSuite.Origins.Authoring/OriginsRuntimeCore.cs.
   Anschließend werden generierte Quellen echt kompiliert und getestet.
   Für Menüvideo wird ein wirklich vorhandenes WebM benötigt.

Die portable Suite liefert weder vollständige proprietäre Spielgrafiken
noch Original-XAML des Spiels mit. Diese werden nur mit expliziter Auswahl
aus der eigenen Installation gelesen.

### Bedienung

1. Gewünschtes Modul in der linken Liste auswählen.
2. Optional Original-XAML wählen; für die WebM-Demo muss ein echtes Video
   ausgewählt werden.
3. „Neuen Demolauf starten“ wählen.
4. Den hervorgehobenen Schritt lesen und „Nächsten Schritt wirklich
   ausführen“ wählen, oder „Alle Schritte dieses Moduls ausführen“.
5. Dateien, Prüfsummen, PNG-Vorschau, Originalcode und bearbeitete XAML/
   C#-/JSON-Dateien kontrollieren.
6. „Gespeicherte Belege erneut prüfen“ kontrolliert echte Dateien.
   Absichtlich veränderte eigene Dateien werden dabei nur als Differenz
   angezeigt und nicht zurückgesetzt oder gesperrt.
7. Über „Ergebnisordner anzeigen“ die bearbeitbaren Dateien öffnen.
8. Über „Ergebnis im echten Editor öffnen“ direkt in die reguläre
   Noesis-, Pixel-, Layout-, Theme- oder Kampagnenwerkstatt wechseln.
   Die bearbeitbaren Demo-Dateien werden dort nicht durch eine Animation
   ersetzt; die spezialisierten Original-Werkzeuge laufen tatsächlich.

Jede Demo liegt separat unter:

    SpriteSuite/work/demo-sessions/<modul>-<zufalls-id>/

- original-beispiele/: Quelle, Codeausschnitte, Beispielgrafiken
- mod-projekt/: tatsächliche modifizierte Mod-Ressourcen
- .origins-runtime-candidates/: private C#-/Saisonentwürfe, sofern erzeug
- belege/schritt-XX/: frühere Dateiversionen bis 16 MiB
- demo-protokoll.json: tatsächliche Pfade, Bytes, Hashes, Schrittstatus

Der gleiche Backend-Demolauf ist auch ohne GUI ausführbar:

    python tools/suite_demo_cli.py --lis
    python tools/suite_demo_cli.py --module pixels
    python tools/suite_demo_cli.py --module noesis --source C:\\Pfad\\FrontendMenus.xaml
    python tools/suite_demo_cli.py --all

Bei --all wird das Video-Modul ohne ausgewählte echte WebM offen
als übersprungen gemeldet. Alle übrigen Module werden tatsächlich
nacheinander ausgeführt und geprüft.

Paket-ZIPs liegen im normalen Suite-Arbeitsordner work/se-asset-mods/.
Die vollständigen Pfade werden im Demo-Protokoll aufgezeichnet.

### Sicherheit, Freiheit und Versionsehrlichkei

Keine Steam-/Script-Extender-Installation wird verändert, kein nativer
Spielcode wird aufgerufen. Der User kann alle eigenen Dateien anschließend
weiterhin verändern. Frühere Versionen bleiben als Zwischenstände erhalten.
Die Demo unterscheidet beabsichtigte Änderungen späterer Schritte von
unerwarteten Nachbearbeitungen; eine Hashabweichung ist keine Schreibsperre.

Ein korrektes XAML-Patch ist nicht automatisch eine pixelgenaue Noesis-
Ingame-Vorschau oder ein funktionierender neuer C#-Handler. Bei
Kampagnen und Jahreszeiten laufen echte C#-Verhaltenstests, aber keine
nativen Spielaktionen. Origins 2.7.0 ist dadurch nicht automatisch für
Steam-Build 24816905 ABI-freigegeben. Die Video-Demo zeigt echtes
Asset-Replacement und keine Videobearbeitung oder Wiedergabe.

Andere Engine- und Spezialwerkzeuge außerhalb dieser zehn Kategorien
haben noch keine pauschale Demo-Abnahme. Ihre Funktionen werden nich
als fertig geprüft ausgegeben. Der Demo-Modulbaukasten ist erweiterbar.

### Tests

    python -m pytest -q tests/sandbox/test_suite_demo_engine.py
        tests/sandbox/test_suite_demo_mode_gui.py

Für die erweiterte Abnahme außerdem echte lokale Original-XAML
und echtes WebM verwenden, Quelle davor/danach bytegenau vergleichen,
Hauptnavigation testen, Portable-Selftest ausführen und die Demo
aus der gebündelten Portable-Laufzeit unter Windows öffnen.


### Nachprüfbarer QA-Stand am 1. November 2026

- Alle zehn Modul-Abläufe nacheinander über die echte Kommandozeile
  ausgeführt, einschließlich einer lokalen 3,8-MB-WebM-Datei:
  null fehlgeschlagen, null übersprungen; alle Mod-/ZIP-Belege geprüft.
- Echte installierte FrontendMenus.xaml separat als Noesis-Demo geladen,
  modifiziert und paketiert; vor/nach der Demo byteidentischer Original-Hash.
- 27 gezielte neue Demo-/Windows-GUI-Tests bestanden; zusätzliche echte
  Übergabe in die Pixel-, Noesis-, Layout-, Theme- und Kampagneneditoren.
- 144 produktive Nicht-GUI-Regressionstests aus den vorhandenen HUD-,
  Layout-, C#-, Assets- und Origins-Modulen bestanden.
- Isolierter Hauptnavigations-Test inklusive vollständigem Demo-Probelauf
  erfolgreich.
- Breiter, mehrfacher Tk-Testlauf: 138 andere Tests bestanden; ein Fehler
  und ein Setup-Fehler durch sporadisch fehlgeschlagene Tcl/Tk-Skript-Ladevorgänge
  nach wiederholtem Erzeugen neuer Tk-Interpreter. Diese Windows-Testumgebungs-
  Instabilität ist gesondert vermerkt, nicht als vollständig gelöst ausgegeben.
  Der echte Portable-Tk/Qt-Selbsttest gehört deshalb ausdrücklich zur Abnahme.
