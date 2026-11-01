# SpriteSuite – ausführbarer Demo-Modus mit echten Arbeitsschritten

**Entwicklungszweig:** feature/demo-coverage-noesis-tcl-runtime-20261101
**Einstieg:** Hauptnavigation → **Interaktiver Demo-Modus**; alternativ HUD & Menüs → Bearbeitungswerkzeuge → Interaktiver Modul-Demo-Modus.

## Grundsatz

Dieser Demo-Modus ist keine Animation und keine Nachstellung von Dateiausgaben.
Jeder ausgeführte Schritt ruft die tatsächlich im Programm vorhandene
Grafik-, XAML-, C#-, Layout- oder Mod-Verarbeitung auf. Jede Ausgabe wird
erneut gelesen und ihre Größe sowie ihr SHA-256-Wert dokumentiert. Bei
einem fehlgeschlagenen Schritt wird kein Erfolg behauptet und der Assistent
springt nicht weiter. Frühere Zwischenstände bleiben als eigene
Dateisnapshots erhalten, damit das spätere Bearbeiten einer Datei
nicht rückwirkend einen früheren Demo-Schritt verfälscht.

**Insgesamt 26 einzeln auswählbare Module** sind implementiert.

## Die verfügbaren Module

| Nr. | Modul | Echte Bearbeitung und Ergebnis |
| --- | --- | --- |
| 1 | Original-Menüseiten / Noesis | Echte oder eigenständige XAML öffnen, Befehle/Controls frei ändern, Revisionen erneut laden, Patch und Mod-ZIP bauen |
| 2 | XAML-Patch-Werkstatt | Original-Control anhand XPath mit SetAttribute bearbeiten, Änderung übernehmen und Patch weitereditieren |
| 3 | Pixelgrafik / HUD | PNG importieren, Pinseländerung speichern, Pixel und Assetstatus nachlesen, ZIP erzeugen |
| 4 | HUD-/Menü-Layout | PNG-Ebenen verschieben, duplizieren und rotieren, Komposition rendern, Export prüfen |
| 5 | Noesis-Themes | Color-Resource im XAML-ResourceDictionary ändern, Brush-Verknüpfung erhalten |
| 6 | Sprachdateien | Echten Menütext in crusader.txt ersetzen, importieren, im Mod-ZIP verifizieren |
| 7 | Origins-Kampagnen | Drei Missionsdatensätze, XAML und C# generieren, C# offline kompilieren und ausführen |
| 8 | Atlas-/Saisonwerkstatt | PNG-Atlas, JSON-Frames, GM-Gruppe und Kartenrouten real verarbeiten, C#-Saisonlogik testen |
| 9 | Mod-Paketbuilder | PNG und Menüpatch importieren, PNG ändern, Ressourcen prüfen und BepInEx-ZIP bauen |
| 10 | Menüvideo / WebM | **Echte ausgewählte WebM** prüfen, bytesicher importieren und als Override paketieren |
| 11 | Steinfarben | Gemessene Sandstein-HSV-Transformation auf echte Bildpixel anwenden und paketieren |
| 12 | Tier-Sprites | Keiler-Fell-Umfärbung aus dem Originalalgorithmus durchführen und Alpha erhalten |
| 13 | Origins Blau/Silber | Historische Rot-/Gold-/Blau-Umfärbungen auf UI-Pixeln ausführen |
| 14 | Teamfarben / Masken | Teamfarbmaske erzeugen und den echten Sandkasten-Farbmischer auf RGB anwenden |
| 15 | Sandkasten / Spielvorschau | Isometrische Szene mit eigenen Sprite-Frames rendern, Objekt neu positionieren |
| 16 | UI-Button-Motivkatalog | Gradienten-Signaturen aus Bildpixeln berechnen, ähnliche und andere Motive vergleichen |
| 17 | Native Kacheltypen | 512 Kartenwerte mit der vorhandenen, **provisorischen** Tile-Klassifizierung zeichnen |
| 18 | BC7-Texturen | Echten etcpak-BC7-Encoder und Decoder ausführen, Pixelergebnis exportieren |
| 19 | Noesis-Pixelvergleich | Exakte PNG-Abweichungsmaske und numerischen Bericht erzeugen; kein eigener Noesis-Renderer |
| 20 | Noesis-Zusatzatlas | Vier PNGs mit dem produktiven Atlas-Builder zu CroppedBitmaps/XAML/PNG-Blatt verarbeiten |
| 21 | Native Menübridge / ABI | **Echte gewählte Spielinstallation nur lesend** auswerten, BepInEx-C#-Kandidat offline kompilieren und mit Mono.Cecil prüfen |
| 22 | Hintergrund / Polygonmaske | Originalgrafik polygonal auswählen, Teilmaske abziehen, tatsächliches inneres Feathering durchführen |
| 23 | UI-Buttonzustände | Ruhend/Hover/Gedrückt/Aus aus der Original-Rahmenfunktion rendern, echten Hover-Pixelstand speichern |
| 24 | Vegetationskomposition | Transparente Baumspender mit Original-Pivotlogik skalieren, zusammensetzen und verschieben |
| 25 | Gold-/Silberrelief | Distanz-/Kantensektor-Algorithmus und Lookup-Tafel real berechnen und Reliefgrafik zweimal bearbeiten |
| 26 | C#-Menübefehle | Unveränderten C#-Menüadapter gegen isolierte Fake-Noesis-/Harmony-/BepInEx-Klassen kompilieren, **29 Assertions wirklich ausführen** |

Bei den Grafik-Modulen werden eigenständig erzeugte, editierbare
Beispielgrafiken verwendet. Die synthetischen Beispielbilder werden **nicht**
als proprietäre Originalspiel-Grafiken ausgegeben. Die tatsächlich
demonstrierten Funktionen sind hingegen die regulären SpriteSuite-
Produktionsalgorithmen, keine separaten Demonstrations-Simulationen.

Für Noesis/Patch kann der Benutzer zusätzlich eine originale lokale
FrontendMenus.xaml auswählen; für die Video-Demo ein originales WebM
und für die Native-ABI-Demo einen installierten SHCDE-Spielordner.
Es werden keine Originaldateien aus dem Spiel überschrieben.

## Schritt-für-Schritt-Bedienung

1. In der linken Suche ein Spezialwerkzeug finden oder die Modulliste
   durchsuchen und ein Modul auswählen.
2. Bei Bedarf Original-XAML, PNG-Screenshot, WebM oder lokalen Spielordner
   nur lesend auswählen.
3. „Neuen Demolauf starten“ wählen.
4. Für jeden Schritt die Erklärung und die genannte Programmfunktion
   lesen; über „Nächsten Schritt wirklich ausführen“ die Operation
   ausführen, oder alle Schritte nacheinander abarbeiten.
5. Tatsächliche Ausgabedateien, Pixelbild, Quellcode, Dateigrößen
   und SHA-256-Prüfsummen prüfen. Vorherige Schritte können angewählt
   werden; ihre Original-Snapshots bleiben erhalten.
6. Über „Ergebnis im echten Editor öffnen“ die bearbeitbaren
   Ergebnisgrafiken und Kampagnendaten in den regulären Werkzeugen
   selbst weiterbearbeiten.
7. „Gespeicherte Belege erneut prüfen“ kontrolliert aktuelle und
   frühere Dateistände. Absichtlich geänderte eigene Dateien werden
   als Differenz gemeldet, nicht stillschweigend zurückgesetzt.

Je Modul entsteht ein neues privates Projekt unter:

    SpriteSuite/work/demo-sessions/<modul>-<zufalls-id>/

Typischer Inhalt:

- original-beispiele/ – vorbereitete, eigenständig erstellte Originalgrafik,
  XAML-Vorlage, Quellcode und ggf. Bildmasken
- mod-projekt/ – tatsächlich veränderte Ressourcen und Override-/Patch-Pfade
- belege/schritt-XX/ – unveränderliche Dateisnapshots bis 16 MiB
- demo-protokoll.json – echte Dateipfade, Hashes und abgeschlossene Schritte

Die Script-Extender-Mod-ZIPs liegen unter work/se-asset-mods/.
Native C#-Kandidaten liegen stattdessen in einem separaten **nicht
installierten** privaten QA-Verzeichnis. Der Mock-Menütest enthält ein
ausgeführtes Testprogramm und ein detailliertes Verhaltenstestprotokoll.

## Dieselben Abläufe ohne GUI ausführen

Die CLI benutzt exakt dieselben Demo-Backendfunktionen:

    python tools/suite_demo_cli.py --list
    python tools/suite_demo_cli.py --module pixels
    python tools/suite_demo_cli.py --module background_masked
    python tools/suite_demo_cli.py --module menu_behavior
    python tools/suite_demo_cli.py --module noesis --source "D:\MeineQuellen\FrontendMenus.xaml"
    python tools/suite_demo_cli.py --module capture_diff --capture "D:\Bilder\Originalaufnahme.png"
    python tools/suite_demo_cli.py --module native_menu --game "D:\Games\Stronghold Crusader Definitive Edition"
    python tools/suite_demo_cli.py --all --game "D:\Games\Stronghold Crusader Definitive Edition" --video "D:\Private\menue.webm"

Wenn für die Video- oder Native-ABI-Demo bei --all die Originalquelle
fehlt, wird die Kategorie **ausdrücklich als übersprungen** gemeldet.
Bei angegebenen gültigen Quellen wird sie tatsächlich ausgeführt.

## Native Noesis- und Spielgrenzen

Ein geometrisches XAML-Canvas oder zwei verglichene Spiel-Screenshots
sind kein pixelgenauer Live-Renderer. Die native Noesis-GUI müsste mit
allen Spielstyles, DataBindings, Ressourcen, Unity-Texturen und den
richtigen Grafikschnittstellen tatsächlich initialisiert und im
Originalspiel bzw. einer isolierten Engine-Umgebung geprüft werden.

Auch die tatsächlich ausgeführte C#-Menübefehl-Demo ist ein
**Fake-Host-Verhaltenstest**: Die produktive Menübridge wird kompiliert
und aufgerufen; Noesis-, BepInEx- und Harmony-Typen werden dabei für die
Offline-Testumgebung nachgebildet. Die Prüfung bestätigt echtes Verhalten
der unveränderten C#-Quellen, ersetzt aber nicht die Registrierung
eines Plugins im Spiel. Aktuell ist der echte Kartenstart aus
LegacyStart **nicht** implementiert; ebenso fehlen native
Saison-Atlaswechsel, Save/Load-Anbindung und deren Ingame-Abnahme.

Das Ziel bleibt eine möglichst freie Bearbeitung der eigenen
Arbeitskopien. Sicherheitsprüfungen auf gültige Dateiformate, exakte
Spielreferenzen oder ein reproduzierbares QA-Protokoll sollen bewusst
geänderte eigene Befehle und Assets nicht pauschal verbieten.

## Prüflauf

    python -m pytest -q -p no:cacheprovider tests/sandbox/test_suite_demo_engine.py tests/sandbox/test_suite_demo_specialists.py tests/sandbox/test_suite_demo_more.py tests/sandbox/test_suite_demo_mode_gui.py tests/sandbox/test_origins_menu_mock_qa.py

Eine Windows-Portable-Abnahme umfasst zusätzlich den Launcher-Selbsttest,
ZIP-CRC, originale Spiel-XAML-Dateihashes und einen vollständigen
Demo-Lauf mit echtem WebM und ausgewähltem Spielordner.

### Erweiterter Abnahmestand

Seit dem C#-Menübefehltest überprüft die native Offline-Compilerfunktion
nicht mehr nur die DLL-Metadaten, sondern führt zusätzlich 29 echte
Verhaltensprüfungen der unveränderten C#-Menübridge gegen einen isolierten
Fake-Noesis-/Harmony-/BepInEx-Host aus. Unter anderem bleiben ursprüngliche
Spielbefehle unverändert und der Patch wird beim Test-Beenden deregistriert.
Dies ist kein live installierter Spielhook.

Ein von Windows .NET Framework csc.exe verursachter Fehler bei langen,
tief verschachtelten Arbeitsordnern wurde behoben: Die tatsächliche
Kompilierung und Ausführung finden jetzt in einem eindeutigen, kurzen
Benutzerprofil-Scratch-Verzeichnis statt. Nur die geprüften Ausgabedateien
und Logs werden anschließend in den privaten Demo-Arbeitsordner kopiert.
Die temporären Compiler-Dateien werden nach jedem Lauf gelöscht.

26/26 Demoabläufe wurden mit originaler, nur lesend geöffneter Spiel-XAML,
echtem WebM und den realen installierten Spiel-DLLs erfolgreich ausgeführt.
Keine Quelle wurde dadurch verändert; es wurde kein nativer Spielhook aktiviert.

Weitere technische Nachweise und offen gebliebene Engine-Beschränkungen:
SPRITESUITE_ORIGINS_TCL_NATIVE_MENU_ABNAHME_2026-11-01.md.
