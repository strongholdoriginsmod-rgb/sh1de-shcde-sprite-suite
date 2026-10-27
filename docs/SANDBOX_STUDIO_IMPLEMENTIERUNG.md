# Sandbox Studio – Implementierungsstand und Folgeaufgaben

## Aktueller Stand: Original-Engine-Grafikbefehle statt Terrain-Heuristik

Die auf diesem PC installierte `CrusaderDE.dll` kann jetzt in einem isolierten
Unterprozess eine **Kopie** der Originalkarte laden und einen pausierten
Grafikframe liefern. Der Spielkern bestimmt damit tatsächliche GM-Familien,
Tile-/Objekt-Bildindizes, Höhen und Lichtinformationen. Der neue Kartenmodus
zeichnet diese Entscheidungen mit Original- oder Arbeitsgrafiken.

**Nachgewiesene Referenzaufnahmen:** Antioch 44.104 sichtbare Tilebefehle /
1.040 weitere Zeichenbefehle; Crusader Demo 44.104 / 1.080; A Mighty Oasis
78.804 / 1.242. Die MAP-Quelldateien bleiben byteidentisch. Der bekannte
DLL-/Managed-Build ist gehasht; unbekannte Versionen werden nicht ausgeführt.

**Bedienung:** F4 → Sandbox-Spiel-HUD → `Engine + Arbeitsgrafiken` oder
`Engine + Originalgrafiken`. Eine Engine-Kachel anklicken und rechts
`Grafik dieser Engine-Kachel direkt bearbeiten` nutzen. Die native
Spritewahl, Original-Ressourcen, sichere temporäre Ausführung und
verbleibenden Unity-/HUD-Abweichungen sind dokumentiert unter
`docs/SANDBOX_NATIVE_ENGINE_INTEGRATION.md`.

Die nachfolgenden Meilensteine sind historische Arbeitsschritte. Ihre Aussagen,
dass die aktuelle Standard-Karte weiterhin nur zufällige oder manuell
zugeordnete Bodenframes benutzt, treffen auf den neuen **Engine-Modus**
nicht mehr zu. Er ist allerdings noch kein vollständig nachgebildeter
Unity-Shader oder eine laufende Spielsimulation.


## 10. Oktober 2026: Erster Meilenstein

Im Projekt auf E:\SpriteSuite ist die bisherige Tkinter-Vorschau in tools/sandkasten.py weiterhin vorhanden. Der neue eigenständige Qt-Kartenexplorer liegt in tools/sandbox_studio.py.

### Bereits umgesetzt

- Read-only-Importer für echte SHCDE-.map-Karten in src/stronghold_europe_de/sandbox/map_importer.py
- Formatprüfungen für Radarkompression und die bekannten Felder der Headerstruktur
- Map-Typ, Weltgröße, Spielerzahl, editierbar-Flag und Burgpositionen aus echten Kartenheadern
- Authentische 200x200-Radargrafik: 512-Byte-RGB555-Palette, 40.000 Indexpixel
- Mitgelieferter PKWare-DCL-Decoder von Travis Collins (MIT) in tools/vendor
- Qt-Hauptfenster mit Kartenauswahl, Suche, Scroll-/Zoom-Kamera, klickbarer Minikarte, Eigenschaften, PNG-Export
- Ein separater Startknopf in der Universal Suite; bisherige Grafikvorschau bleibt bedienbar
- Regressionstests für fehlerhafte Header und tatsächliche Map-Dateien

Mit E:\SSGameQA wurden 257 Originalkarten erkannt. Ancient River, Antioch und Crusader Demo konnten erfolgreich dekodiert werden.

### Wichtige Grenze

Die 200x200-Radarvorschau sind echte Daten aus der Karte, aber **noch kein vollständiges Spiel-Terrain**. In diesem Meilenstein gibt es noch keine extrahierten Tile-IDs, Höhenlayer, Gebäudeinstanzen oder editierbare Spielobjekte. Die Radaransicht darf nicht als vollständiger Terrain-Renderer bezeichnet werden.

### Abhängigkeiten

Optionales PySide6 wird separat über requirements-sandbox-studio.txt installiert.
Node.js >= 18 dekodiert den proprietären PKWare-DCL-Radardatenblock mit einem mitgelieferten MIT-lizenzierten JavaScript-Decoder. Die Software arbeitet auf den Originalkarten immer read-only.

Lokaler Start über Sandbox Studio starten.cmd, den Knopf im Reiter Sandkasten oder python tools/sandbox_studio.py --maps <Originalkartenverzeichnis>.

Die Standardeinstellung E:\SSGameQA gilt nur für diese Entwicklungsumgebung; ein alternativer Kartenordner ist direkt auswählbar.

## Zweiter Meilenstein: editierbares isometrisches Sprite-Testfeld

Zusätzlich zur unverändert aus Originaldateien stammenden 200×200-Radarkartenansicht
steht jetzt ein separater Reiter **Interaktives Sprite-Testfeld** zur Verfügung.

**Umgesetzt:**

- Isometrisches 64×32-Raster als rein lokale Testszene (standardmäßig 26×26; aktuell maximal 64×64, bis Chunk-Rendering verfügbar ist).
- Platzieren aus der Sprite-Gruppen-/Frame-Auswahl (Schaltfläche **Sprite platzieren**
  oder Taste **P**), Anklicken, Verschieben per Drag & Drop mit Raster-Snap,
  Löschen per Entf-Taste, Esc zum Beenden des Platziermodus.
- Objekt-Inspector mit X/Y, Frame und Teamfarbe; Änderung wird beim Übernehmen
  validiert und ist rückgängig zu machen.
- **Ctrl+Z / Ctrl+Y** für Undo/Redo, **Ctrl+S** für atomisches Speichern,
  Szenenöffnung und **Ctrl+N** für neue Testszene; Sicherheitsdialog bei
  ungespeicherten Änderungen.
- Die Szenen liegen im versionierten `stronghold-europe.sandbox.scene.v2`-Format:
  ausschließlich Referenzen auf Sprite-Gruppe/Frame und editorseitige Positionen,
  keinerlei kopierte Spieldatei-Inhalte.
- Ein-/ausschaltbare echte `tile_land8`-Bodensprites aus der vorhandenen
  lokalen Grafikpipeline als **Testboden**. Diese sind kein aus einer
  Original-Map extrahiertes Terrain.
- Anzeige der tatsächlich ausgelieferten Sprites aus dem Atlas, sofern
  vorliegend; korrektes Alpha, Pivot, näherungsweise Teamfarben.
- Seitenvergleich Referenz/Arbeitsansicht und periodische Dateiprüfung für
  geänderte Arbeitskopie-PNGs/Masken/Indizes. Sichtbare Objekte werden ohne
  Austausch der Szene neu geladen. Automatische Übernahme ist abhängig von
  einer vorhandenen bzw. vorbereiteten Arbeitskopie.
- Qt-Offscreen-Test der GUI und Interaktionen, lokal geprüfte Sprite-Extraktion
  aus dem bereits erzeugten `anim_armourer`-Atlas.

**Bedienung:**

1. `Sandbox Studio starten.cmd` starten, zum Testfeld mit **F2** wechseln.
2. Gruppe und Frame rechts im Grafikvorschau-Dock wählen, **Grafik laden**.
3. Mit **P** oder **Sprite platzieren** den Platziermodus einschalten und auf
   eine Kachel klicken. Mit **Esc** beenden.
4. Objekt anklicken, verschieben oder im **Objekt-Inspector** ändern.
5. Testszene mit **Ctrl+S** als JSON sichern. Lokale PNG-Änderungen werden im
   geöffneten Grafikvergleich bzw. an verwendeten Testobjekten erkannt.
6. Bei Bedarf **Bodensprites im Testfeld** einschalten. Es wird keine
   Original-Map-Datei verändert.

**Noch offen:** vollständiger SHCDE-Terrain-/Gebäudeparser, echtes Karten-HUD,
dynamische Animationen, Sprite-Drag-and-drop aus einem visuellen Asset-Browser,
Performanceoptimierung großer Karten, portable Auslieferung ohne separaten
Node-/Qt-Abhängigkeitsaufbau. Die Arbeitskopie muss außerhalb der Sandbox über
den bestehenden Katalog bzw. Malprogramme bearbeitet werden; die Live-Vorschau
ist bereits nutzbar, aber kein vollwertiger eingebetteter Sprite-Pixel-Editor.

## Dritter Meilenstein: originale SHCDE-Kartensektionen (read-only)

Für einen Teil der echten SHCDE-.map-Dateien ist jetzt zusätzlich zur
200×200-Radarvorschau ein **streng validierter Sektionsleser** implementiert.
Er erkennt ein 3036-Byte-Verzeichnis mit 150 Tabellenplätzen und ermittelt
daraus unabhängige Datenabschnitte; jeder geladene DCL-Block wird anhand
von Länge und CRC32 verifiziert. Der Code verwendet weiterhin den
mitgelieferten MIT-lizenzierten DCL-Decoder, ohne Spieldateien zu verändern.

**Direkt geprüft** wurden Antioch.map, A Mighty Oasis.map und
Crusader Demo.map: 145, 142 bzw. 136 abschnittsweise indexierte
Sektoren. Darunter befinden sich die IDs 3003, 3004, 3005, 3037 und 3043.
Die Sektion 3005 enthält nach Prüfung tatsächlich **320.800 einbyteige
Original-Kachelwerte** in einem isometrischen 800-Reihen-Diamantraster:
Reihenlängen 2, 4, ..., 800, 800, ..., 4, 2. Die vorherige Interpretation
als zwei 400×401-Kanäle war falsch und wurde korrigiert. Die Positionen der
unterschiedlichen Werte entsprechen sichtbaren Fluss- und Geländeformen in
den jeweiligen originalen Radarvorschaubildern. Die genauen Grafik- und
Materialcodes sind **noch nicht** endgültig verifiziert.

Im Reiter **Native Kacheldaten 3005 (Diagnose)** (F3) zeigt die Suite
diese realen Kacheldaten als 800×800-Diamant mit numerischen Fehlfarben,
präzisem Kachelindex unter dem Mauszeiger und Zoom-/Pan-Kamera.
Das ist ein Debugger für originale Kartenbytes, **keine optisch oder
semantisch vollständige Originalkarte**. Der Karten-Inspector kennzeichnet
den Unterstützungsgrad des jeweiligen Dateiformats.

Weitere geprüfte .map-Dateien (z. B. Ancient River.map) weisen abweichende
Containerdaten auf. Bei solchen Dateien meldet die Sandbox die bisher
fehlende Unterstützung klar und zeigt keine erfundenen Terrain-Daten.
Originalkarten bleiben stets read-only.

Tests prüfen den validierten Abschnittsimport aus drei Originalkarten,
künstliche fehlerhafte Tabellen und die Erkennung beschädigter
komprimierter Sektionen mit CRC32. Die Qt-GUI-Regression prüft den
F3-Kanaldatentab.

### Weiterhin P0 für eine richtige spielgetreue Karte

- Bedeutung und Koordinatenkonvention der Originalabschnitte
  herleiten und mit Referenzbildern aus dem Spiel beweisen.
- Import aller Kartenformatvarianten und echte Tiles/Höhen/Gebäude
  ohne Lücken dekodieren.
- Die bestätigten Terrain- und Objektlayer mit Sprite-Pivots
  und performantem Chunk-Renderer in den Kartenmodus integrieren.
- Danach HUD und vollständige interaktive Bearbeitung einer
  **importierten** Spielkarte statt nur des lokalen Testfelds.

## Vierter Meilenstein: Animations-Testleiste und Bedienoberfläche

Das Sandbox Studio besitzt eine **funktionale Frame-Testleiste** mit
Abspielen/Pause, Frame für Frame vor und zurück, frei wählbarem
Framebereich, 1–30 FPS und einem Scrubber. Eine gewählte Figur,
Pflanze oder Animation wird direkt als Sprite auf dem isometrischen
Testfeld aktualisiert. Dabei bleibt das gespeicherte Projekt
unverändert: Animationsframes werden nur für die Vorschau angezeigt.
**Originalframe** stellt das Ausgangsbild wieder her; Szene-Neuaufbau
und Löschen einer Auswahl beenden aktive Wiedergabe sicher.

Bei Auswahl eines Objekts werden außerdem Gruppe und Frame im
Grafikvergleich automatisch auf die Auswahl synchronisiert. Dadurch
kann man das Objekt gezielt bearbeiten bzw. nach einer PNG-Änderung
sofort im entsprechenden Kontext prüfen.

Die bisher überfüllte Werkzeugleiste wurde durch
**Datei / Ansicht / Bearbeiten** und eine kompakte
Schnellzugriffsleiste ersetzt. Original-Radar (F1),
Testfeld (F2), Rohdaten (F3), Live-Sprite-Vorschau,
Inspector und Animation bleiben aufrufbar. Keine
unbelegten oder dekorativen Interaktionsknöpfe werden als
voll funktionsfähige Spiel-HUD-Elemente ausgegeben.

Qt-Tests prüfen die Animation einschließlich Pause,
Löschen, Zurücksetzen und unveränderten Szenen-/Undo-Zustand.

## Fünfter Meilenstein: visuelle Sprite-Palette

Links ist zusätzlich zur Kartenliste eine **Sprite-Palette** verfügbar. Sie zeigt tatsächlich vorhandene Atlasframes in paginierten Gruppen mit Bildvorschau (32 pro Seite). Ein Klick synchronisiert Sprite-Gruppe und Frame mit dem Vorher-Nachher-Vergleich, ein Doppelklick schaltet das Platzierwerkzeug im isometrischen Testfeld für diesen Frame ein. Fehlende Frames werden nicht als vorhandene Grafiken ausgegeben. Diese Funktionen sind durch Qt-Offscreen-Tests abgesichert.

Die Palette ist die Asset-Auswahl; das separate neue Fenster **Sprite-Pixeleditor** bearbeitet inzwischen tatsächliche Bildpixel direkt. Vollständige Terrain-/Spielmechanik und das originale Unity-/Noesis-HUD sind weiterhin nicht nachgebildet.

## Sechster Meilenstein: integrierte echte Kartenwerkstatt und Pixelbearbeitung

**Start:** `Sandbox Studio starten.cmd` doppelklicken, alternativ im
Hauptprogramm im Reiter Sandkasten den Button `Sandbox Studio (Originalkarten)`.

Standardmäßig wird aus der lokal bekannten Spielinstallation eine unterstützte
Karte wie `Antioch.map` geöffnet. Mit **F4** zum neuen
`Spielkarte (Original-Tiles + Sprites)`-Reiter wechseln, mit
**F1** zu den echten 200×200-Radardaten, mit **F3** zum
untexturierten nativen Diamant-Rohkanal und mit **F2** zum
unabhängigen kleinen Sprite-Testfeld.

### Bereits ausführbar

- **Echte Karte:** Original-.map-Abschnitte 3003/3004/3005/3037/3043 werden
  per DCL dekodiert, CRC-überprüft und mit ihren exakten nativen Kachelindizes
  angeboten. Die Spielkarte ist 800 Diamantzeilen breit und umfasst 320.800
  gültige Originalkachelpositionen; kein künstliches 26×26-Testdorf.
- **Laufende Karte:** echte `tile_land8`, `tile_sea8`, `tile_rocks8` usw.
  aus den lokal installierten Sprite-Atlanten werden nur im sichtbaren
  Ausschnitt gezeichnet; ausgezoomt erscheint ein vollständiges native
  Originaldaten-Overview. Zoomen, Panning und Minikarten-Navigation.
  Wichtig: Die *Material-zu-Frame*-Zuordnung ist eine nachvollziehbar als
  **vorläufig** gekennzeichnete visuelle Näherung.
- **Originalgebäude:** Die tatsächlich im Abschnitt 1013 gespeicherten
  Gebäudedatensätze werden einschließlich Typ-ID, Besitzer, UID, Footprint
  und exakt belegter Kachelposition gelesen. Die Originalgebäude sind
  eigene auswählbare **read-only-Marker**, keine erfundenen Gebäude-Sprites.
  Das Ein-/Ausschalten ist im HUD möglich.
- **Eigene Objekte:** aus visueller Sprite-Palette oder dem Spiel-HUD
  auswählen; auf der **realen** Karte platzieren, verschieben, löschen,
  Eigenschaften/Pivot aus der vorhandenen Sprite-Pipeline anwenden,
  Teamfarbe testen. Undo/Redo gilt für diese Bearbeitungen.
- **Sichere Persistenz:** eigene Objekte werden als
  `stronghold-europe.sandbox.map-overlay.v1` in
  `sandbox/overlays/<kartenname>-<sha256-kurz>.overlay.json` gespeichert.
  Identität/Hash der zugehörigen Originalkarte werden geprüft. Originalkarten
  werden **niemals** verändert. Ctrl+S speichert im Kartenmodus ein Overlay,
  Ctrl+Shift+M ist ein expliziter Overlay-Speicherbefehl.
- **Echter Pixel-Editor:** Mit Ctrl+E oder `Sprite-Pixel bearbeiten`
  öffnen. Stift, Radierer, Pipette, Füllen, Farbauswahl, Pinselgröße,
  Pixelzoom, Undo/Redo. Beim Speichern wird nur
  `work/katalog/arbeit/<gruppe>/<frame>.png` geschrieben; eine Arbeitskopie
  wird bei Bedarf aus lokal vorhandenen Crusader-/Auslieferungs-Assets
  vorbereitet. Änderungen werden in Vergleich und Kartenansicht sofort
  übernommen; externe PNG-/Masken-Änderungen werden durch Dateisignaturen
  periodisch erkannt und gezielt neu geladen.
- **Funktionales HUD:** Kategorie/Gruppen-/Framewahl, Platzieren/Löschen,
  Rückgängig/Wiederholen, Overlay speichern, Original-Rohwerte anzeigen,
  Originalbauwerke ein-/ausblenden, Frame-Animation und Pixel-Editor öffnen.
  Es ist **kein** behaupteter 1:1-Nachbau des proprietären Spiel-HUDs.
- **Dokumentation und QA:** Ctrl+Shift+P exportiert die aktuelle Kartenansicht
  als PNG. Der Quelldatenvergleich, farbkanalbasierte Diagnostik und
  Qt-Offscreen-Tests bleiben verfügbar.

### Nüchterne Grenze der Engine-Parität

Der neue Kartenmodus ist jetzt eine echte, dynamisch texturierte Arbeitsfläche
über **realen Kartentiles und gespeicherten Originalbauwerkspositionen**.
Er ist trotzdem noch **kein pixelidentischer Stronghold-Crusader-DE-
Spiele-Renderer**. Die genaue Terrain-Frame-/Höhen-/Shader-Zuordnung,
die vollständige Darstellung bereits vorhandener Spiel-Einheiten,
Gebäudemodelle, Straßen und Vegetation, alle unterschiedlichen .map-Versionen,
Unity-Spezialeffekte und das exakte proprietäre Noesis-HUD benötigen
weiterführende Formatanalyse und Spielreferenz-Abgleiche. Die Sandbox
stellt solche fehlenden Funktionen nicht als fertig dar.

## Siebter Meilenstein: flüssigeres Kartenrendering und korrektes Pixelmalen

- Der native Kartenmodus rendert sichtbare Boden-Grafiken jetzt in
  **512×256-Chunkbilder** statt bei jedem Kamera- oder Fenstervorgang tausende
  Texteinzelteile neu zu zeichnen. Es gibt einen begrenzten **LRU-Cache mit
  maximal 72 Chunks** (rund 36 MiB für unverkleinerte RGBA-Bilder).
- Die Chunk-Bilder berücksichtigen **Sprite-Pivots und überragende Pixel** über
  die Chunkgrenzen hinweg. Automatisierte Pixeldifferenz-Tests vergleichen
  benachbarte Chunks mit einer direkt gerenderten Originaldatenfläche und
  sichern eine nahtlose Darstellung.
- Lokale Änderungen an Boden-PNG oder Sprite-Index invalidieren den Karten-
  Cache sofort bei der folgenden Live-Reload-Prüfung; geänderte Objektframes
  bleiben an ihren gespeicherten Koordinaten.
- Der integrierte Sprite-Pixeleditor behandelt zügige Mausbewegungen jetzt als
  **durchgehende Pixelstriche** (Bresenham-Interpolation). Auch gerade
  Pinselgrößen malen exakt ihre gewählte Breite. Einzelne Mausaktionen, etwa
  Füllen, erzeugen **genau einen** Undo-Eintrag statt mehrfacher Schritte.
- Der Schachbretthintergrund wird als Qt-Muster gezeichnet statt pro
  Frame zehntausende Bildschirmrechtecke zu erzeugen. Ein zusätzlicher
  Qt-Maustest überprüft genau diesen Mal-/Undo-/Redo-Ablauf.

Die Änderungen beschleunigen das lokale Editor-Rendering; eine vollständige
Benchmark- oder Spielclient-Framerate-Messung sind sie **nicht**. Die
Originalterrain-Texturzuordnung bleibt weiterhin als Näherung markiert.

**Fehlerresistenz bei beschädigten Overlay-Dateien:** Wenn eine gespeicherte
Kartenbearbeitung ungültig oder beschädigt ist, wird die originale Spielkarte
weiterhin geöffnet. Die beschädigte Overlay-Datei bleibt unverändert. Neue
Bearbeitungen werden unter einem getrennten Recovery-Namen gespeichert, und
bei einem späteren Kartenstart wieder geladen. Ein Qt-Integrationstest prüft
Erkennung, Warnmeldung, Recovery-Speicherung und unveränderte Ursprungsdatei.

## Achter Meilenstein: Originalvegetation, Objektgrafik-Zuordnung und Radar-Abgleich

### Verifizierte Kartenobjekte aus der Originaldatei

Die 156-Byte-Datensätze der SHCDE-Sektion **1014** sind jetzt im
read-only-Importer analysiert. Ihre nativen Koordinaten sind als uint16 an den
Offsets 98/100 dekodiert. Auf drei originalen Karten passen **alle**
nichtleeren Datensätze in das 320.800-Kachel-Diamantraster:

- Antioch.map: **1.139** Vegetationsobjekte
- Crusader Demo.map: **1.050** Vegetationsobjekte
- A Mighty Oasis.map: **1.242** Vegetationsobjekte

Der neue Reiter **Spielkarte** bietet zusätzlich zu den bereits bekannten
Originalgebäuden einen getrennt schaltbaren, anklickbaren Vegetations-Layer.
Baumobjekte behalten Originalposition, Datensatz-ID und Rohcodes aus der
Originalkarte. Sie sind nicht löschbar oder bewegbar; originale .map-Dateien
werden niemals zurückgeschrieben.

**Wichtig:** Die Rohgruppen 29,30,31,70,71,72,200 sind tatsächlich in diesen
Dateien enthalten, ihre genaue 1:1-Zuordnung zu Sprite/Animation ist aber
noch NICHT durch Screenshots/Engine-Code nachgewiesen. Daher wird standardmäßig
ein unterscheidbarer, echter Positionsmarker statt eines erfundenen Sprites
gezeichnet.

### Echte Spritegrafiken auf Originalobjekte legen und testen

Bei ausgewähltem Originalgebäude bzw. Vegetationsobjekt:

1. Gewünschte lokale Spritegruppe und Frame im rechten Grafikvergleich oder
   über die linke Sprite-Palette wählen.
2. Im Originalkarten-Inspector **Aktuelle Spritegrafik dem Originaltyp
   zuordnen** drücken (Tastenkürzel **Ctrl+Shift+G**).
3. Sofort wird bei allen Objekten desselben Rohcodes diese echte Atlasgrafik
   mit Original-Pivot gerendert. Die Quelle bleibt die unveränderte SHCDE-Karte.
4. Die getestete Kombination unter
   `sandbox/mappings/native-original-visuals.json` wird atomisch gespeichert.
   Das versionsgebundene Format enthält ausschließlich Grafikreferenzen.
5. **Grafik-Zuordnung für diesen Typ aufheben** bzw. **Ctrl+Alt+G**
   setzt diesen Rohcode auf den verifizierten Datenmarker zurück.
6. Änderungen an den verwendeten Arbeitskopie-Sprites werden über das
   bestehende Live-Reload an den Originalobjekten aktualisiert, ohne die
   Kamera oder Szene neu zu laden.

Die UI bezeichnet diese Zuordnung ausdrücklich als **benutzerdefinierten
Grafiktest**, nicht als automatisch erkanntes Engine-Mapping. Auch eine
unvollständig oder beschädigt gespeicherte Mapping-JSON verändert keine
Spiel- oder Originalkartendatei.

### Echte Minikarte statt synthetischer Diagnoseraster

Die Minikarte im Kartenwerkzeug verwendet jetzt die tatsächlich aus der
jeweiligen `.map` gelesene **200×200-Radargrafik**. Ein projizierter
Kamera-Ausschnitt zeichnet die aktuelle Kartenposition ein, Links-Klick
versetzt die Kartenkamera. Die Umrechnung zwischen 800-Diamantraster und
dem quadratischen Radar wurde mit Rückrechnungs-/GUI-Tests abgesichert.

Bei abweichenden Kartenvarianten ist die mathematische Projektion noch
an realen Spielszenen zu kalibrieren, daher wird kein durchgehend
pixelgenaues Kamera-Overlay versprochen.

### Referenzbilder wirklich vergleichen

Über **Datei → Pixelabgleich mit originalem Spielbild**
(Tastenkürzel **Ctrl+Shift+C**) öffnet sich ein eigener Screenshot-Abgleich.

- PNG/JPG-Screenshot aus dem echten Spiel laden, Kartenausschnitt direkt
  aus der laufenden Sandbox aufnehmen.
- X-/Y-Ausschnitt im Spielbild exakt wählen, **kein** stilles Resampling.
- Abweichungen über mittleren absoluten RGB-Pixelfehler (MAE) und Anteil
  abweichender Pixel mit einstellbarer Toleranz messen.
- Absolutes RGB-Differenzbild als PNG exportieren.
- Synthetische Bilder prüfen bereits exakte Übereinstimmung,
  Offset-Korrektheit, Abweichungsprozente und Toleranzgrenzen.

Diese Werkzeuge sind die Grundlage für einen beweisbaren optischen Abgleich,
nicht bereits der Nachweis einer 1:1-Spielengine.

### Offen bleibende technische Arbeiten

- Semantik von Abschnitt 3005/3004 und 3003 gegen die originalen Terrain-
  Shader, Wasser-, Küsten-, Höhen- und Wege-Renderer nachweisen.
- Die Grafik-IDs aller Gebäude-/Vegetationsgruppen mit Engine-Ressourcen
  und Referenzszenen verbinden; 1015 enthält in den getesteten Karten
  keine Einheiteninstanzen, andere Versionen müssen getrennt analysiert werden.
- Original-UI-Atlanten, XAML-Bindings, Panels und Interaktionen des
  proprietären **Stronghold-HUDs** pixelgenau rekonstruieren. Das funktionale
  aktuelle **Sandbox-HUD** ist ausdrücklich kein fertiger 1:1-Nachbau.

## Neunter Meilenstein: XAML-Bau-HUD mit echten lokalen Atlasgrafiken

Das Spiel-HUD hat jetzt zusätzlich zum generischen, weiter nutzbaren Editor-HUD
einen opt-in/reproduzierbaren **Original-XAML-Grafikmodus**. Dieser Modus ist
im Kartenstudio als unterer Reiter **Original-XAML-Grafiken / HUD-Test**
erreichbar und wird im F4-Kartenmodus bevorzugt sichtbar.

- Die lokale Datei `config/sandbox-hud-original-art-v1.json` dokumentiert
  die analysierten XAML-Befehle und Ressourcenausschnitte mitsamt SHA-256
  ihrer Quellen. Aktueller Prüfstand: **141 original-XAML-Schaltflächen**,
  **134 verschiedene Spiel-Befehlstoken**, **14 Bauseiten** sowie **265
  gegengeprüfte PNG-Ausschnitte**.
- Die PNG-Ausschnitte stammen aus dem lokal abgeleiteten Europa-Override
  `assets/ui/derived/ui-europa-geprueft/`. Sie sind ausdrücklich **keine
  unveränderten proprietären Originalspiel-Atlanten**. Die Benutzung erfolgt
  nur lokal; Spielassets werden nicht ins Repository kopiert.
- Schaltflächen sind als echte QGraphicsItems anklickbar; Hoverbilder und
  Seitenwahl werden geladen. Ein tatsächlicher Qt-Mausklick auf einen
  Bergfried-Bauknopf löst den bestätigten XAML-Befehl aus.
- Weil der im XAML enthaltene Bau-Befehl **keine nachgewiesene Zuordnung zu
  einem konkreten Sprite-Katalogframe** belegt, kann der Nutzer beim
  ausgewählten Bauknopf die gewünschte Sprite-Gruppe/Framenummer im
  Grafikvergleich wählen und über **Ausgewählten Originalbefehl mit
  Palette-Sprite verbinden** verknüpfen. Weitere Klicks aktivieren damit
  die Platzierung auf der echten Karte. **Verknüpfung aufheben** setzt die
  Zuordnung zurück.
- Die benutzerdefinierten Verknüpfungen werden atomisch als
  `sandbox/mappings/hud-original-commands.json` gespeichert. Ausschließlich
  im XAML gefundene Befehlstoken sind erlaubt, falsche/fehlende Formate
  werden abgewiesen. Das .map-Original bleibt unverändert.
- Die Qt-Regression prüft alle 14 Bauseiten, sämtliche sichtbaren
  lokalen PNG-Ausschnitte, XAML-Befehlselektion, echte Mausereignisse,
  Persistenz und die Übergabe der Bauplatzierung an die Kartenwerkstatt.
- Die Anzeige ist bewusst als **Teilrekonstruktion** gekennzeichnet:
  vollständige Windows-/Noesis-HUD-Geometrie, Zustandsbindungen, alternative
  Mauszustände, Spielökonomie und pixelgenaue Renderingparität bleiben offen.
  Im frisch ausgecheckten Repository ohne private lokale UI-Crops bleibt
  der zusätzliche Reiter optional statt die Kartenwerkstatt zu blockieren.

## Zehnter Meilenstein: Original-Terrain-Bytewerte direkt mit Spritegrafiken testen

Bisher ordnete der Kartenrenderer Rohwerte aus SHCDE-Abschnitt 3005
durch eine vorläufige Heuristik den Materialien Gras/Fels/Wasser zu und
wechselte Katalogframes nach einem deterministischen Muster. Das war eine
sichtbare Näherung, kein nachgewiesenes Original-Terrain.

**Neu: überprüfbare manuelle Frame-Zuordnungen pro Rohwert und Karte.**

1. Sandbox Studio starten, `Antioch.map` bzw. eine andere unterstützte
   Originalkarte öffnen (F4).
2. Eine Kachel anklicken. Rechts im Inspector erscheinen ihre
   Originalkanäle und der **Bytewert 3005** sowie die Anzahl aller
   Originalkacheln mit genau diesem Bytewert.
3. In der **Grafikvorschau** die gewünschte Spritegruppe und Framenummer
   auswählen.
4. **Palette-Sprite als Terrain-Test für Rohwert 3005** anklicken.
   Für jede Kachel mit diesem Wert wird sofort die gewählte echte
   lokale Spritegrafik verwendet. Neue Terrain-Chunks werden mit dem
   gewählten Frame zusammengesetzt.
5. Weitere Bytewerte nacheinander konfigurieren. Die restlichen Werte
   behalten den ausdrücklich vorläufigen Heuristik-Fallback.
6. **Terrain-Test für diesen Rohwert zurücksetzen** verwirft die
   Frame-Zuordnung und stellt den bisherigen Fallback wieder her.

- Dateiformat: `stronghold-europe.sandbox.native-terrain-test.v1`.
- Speicherort: `sandbox/terrain-mappings/<kartenname>-<sha-kurz>.terrain.json`.
- Original-Kartendaten und Kanalwerte werden nur gelesen. Die Zuordnung
  wird anhand der vollständigen SHA-256-Prüfsumme an **genau die
  Originalkartenversion** gebunden, nicht still auf andere Karten übertragen.
- Speichern erfolgt atomisch, korruptes JSON bleibt erhalten und
  neue Änderungen landen getrennt in einer Recovery-Datei.
- Die Arbeitskopie-Sprite-Pixelbearbeitung und das Asset-Live-Reload
  invalidieren auch **benutzerdefinierte** Terrain-Grafiken.
- Die Regression testet Schema, ungültige Codes und Pfade, Persistenz,
  Kartenversionen, Dateischutz, Kachel-Inspektor, Bildzuordnung,
  Chunk-Invalidierung, Rücksetzen und Recovery mit realer Karte.

**Wichtige Grenze:** Ein Code aus 3005 wird nur als numerischer
**Original-Rohwert** interpretiert. Es ist noch nicht bewiesen, dass er
alleine das Spielterrain oder die tatsächliche Texturidentität angibt.
Die zugeordneten Frames sind durch den Nutzer festgelegte visuelle Tests,
keine automatisch dekodierten, pixelidentischen Engine-Materialien.

## Elfter Meilenstein: Original-3003-Randmasken und echte 3004-Kachelbelegung

Die bisherige Karte hatte einen grundlegenden Fehler: Alle 320.800
Originalkachel-Slots der Datei wurden als potenzielle Spielfläche behandelt.
Die tatsächliche abgesicherte SHCDE-Analyse belegt für **drei** Originalkarten:

| Karte | 3003=16 | 3003=32 | Nicht als Rand markiert | 3004-Belegungen |
| --- | ---: | ---: | ---: | ---: |
| Antioch | 274.500 | 2.179 | **44.121** | **2.503** |
| Crusader Demo | 274.500 | 2.152 | **44.148** | **2.407** |
| A Mighty Oasis | 239.600 | 2.392 | **78.808** | **1.541** |

Für alle drei Karten sind die beiden 3003-Marken **nicht mit belegten
3004-Kacheln überlagert**. Die nun standardmäßig verwendete
read-only-`NativeLayerGeometry`-Ansicht unterscheidet damit ausdrücklich
Randdaten von tatsächlichen Datenpositionen. Sie ist keine Spekulation,
dass 3005-Bytewerte automatisch Gräser, Wasser oder Felsen bedeuten.

- Original-Rand `3003 in {16, 32}` wird nicht mit erfundenen
  Terrain-Sprites gefüllt, auch nicht auf gezoomten Kartenabschnitten.
  Die native Übersicht verwendet denselben tatsächlichen Maskenlayer.
- Kamera/Fit-in-View nutzen den aus dem Original ermittelten inneren
  Daten-Ausschnitt statt der gesamten technisch serialisierten 800×800-Hülle.
- Kartenklick, Objektsprite-Platzierung, Drag-and-drop, Minikarten-Kamera
  und Inspector verbieten das Bearbeiten markierter Randkacheln. Gespeicherte
  Overlay-Grafikobjekte aus älteren Editorversionen werden nicht still
  aus der Datei gelöscht.
- **Objektbelegung 3004** im Sandbox-HUD ist ein zuschaltbarer
  Diagnose-Layer aus realen Rohdaten. Im Inspector zeigt ein Klick
  die tatsächliche ID, Anzahl der belegten Kacheln und native
  Bounding-Box. Verifiziert wurden IDs, die je nach Karte eine
  2×2-, 3×3- oder 4×4-Rechteckbelegung besitzen.
- Abschnitt 3004 ist damit als tatsächlicher Occupancy-Rohdatenlayer
  **geometrisch** nutzbar. Eine automatische Zuweisung von 3004-IDs zu
  gerenderten Gebäude-Frames ist noch nicht bestätigt.

Tests prüfen CRC-basierte Abschnittsimporte, reale Zählwerte,
Footprint-Formen, Kachelmasken, saubere Fallbacks ohne Abschnitt 3003,
kein Overdraw auf Originalrand, Qt-Toggling und blockierte Editoraktionen.

**Restgrenze:** Die vollständige Spieloberfläche, Wasser-/Terrainmaterialien,
Shader, Höhen, Gebäudeframes und Spiel-HUD-Logik bleiben Teil der
offenen 1:1-Abnahmekriterien. Ein visuell gefälliges Zufalls-Terrain
ist ausdrücklich kein akzeptiertes Ende dieser Arbeit.

Der phasenweise verbindliche Gesamtplan steht in
`docs/SANDBOX_STUDIO_1ZU1_IMPLEMENTIERUNGSPLAN.md`.

## Nächste Aufgaben (autonome Priorisierung)

### P0: vollständige Karteninhalte

1. Kartencontainer nach SHCDE-Version und nicht nach alten SHC-Layoutannahmen analysieren.
2. Abschnittsverzeichnis und DCL-komprimierte Terraindaten mit Prüfsummen lesen.
3. Tile-Raster, Höhen, Terrain, Wasser, Straßen, Vegetation, Gebäude und Einheiten aus drei unterschiedlichen Originalkarten verifizieren.
4. Read-only-Kartenmodell mit separat gespeicherter Overlay-Szene einführen.
5. Isometrisches Terrain mit der vorhandenen 64x32-Projektion und Asset-Daten der Suite darstellen.
6. Screenshot-Abgleich und klare Abweichungsdiagnostik als Abnahme.

### P0: Live-Grafiktest

1. Arbeitskopie, installiertes Bundle und Crusader-Original als Quellen in einer gemeinsamen Frame-Registry.
2. Dateisystem- und Katalog-Änderungssignale für Sprite, Maske, Pivot und UI einführen.
3. Nur betroffene Frames und sichtbare Kartenobjekte aktualisieren.
4. Direkten Vorher-Nachher-Vergleich und BC7-Simulationsstufe bereitstellen.
5. Asset-Status und Fehler statt stiller Fallbacks anzeigen.

### P1: Funktionsfähiger Karteneditor

1. Objekt-Auswahl, Drag & Drop, Inspector, Paint-Werkzeuge, Undo/Redo.
2. Echtes HUD aus UI-Atlaszuordnungen mit funktionalen Eingaben statt Screenshot-Overlay.
3. Zeitleiste für Animation und deterministische Zustandstests.
4. Chunk-Rendering und Leistungsbudget bei großen Karten.
5. Portables Qt-Paket, native Konfigurationspfade und Qt-Offscreen-/GUI-Tests.

## Regression

PowerShell:

    $env:PYTHONPATH="E:\SpriteSuite\src"
    E:\SpriteSuite\.venv\Scripts\python.exe -m pytest -q E:\SpriteSuite\tests\sandbox

Keine der originalen .map-Dateien, keine daraus generierten Bilder und keine Spielgrafiken werden in Git eingecheckt.


## Zwölfter Meilenstein: mit Originalkarten empirisch kalibrierte Minikarte

**Umgesetzt, aber noch keine 1:1-Terrain-Engine:** Native 3003-Randmasken
liefern jetzt die echten logischen Min-/Max-Bereiche der spielbaren Welt:
`u=(x+y-399)/2`, `v=(y-x+399)/2`. Die Originalkarten `Antioch`,
`Crusader Demo` und `A Mighty Oasis` belegen übereinstimmend die
Radarorientierung **Radar-X = umgekehrtes v**, **Radar-Y = u**.
Das echte 200×200-Spielradar wird nicht mehr durch die technische
800er-Datenhülle skaliert, sondern durch die jeweils originale
kartenspezifische Spielfläche.

Die automatisierte Wasserindikator-Gegenprobe `3003 & 0x100000 != 0`
liegt in diesen drei Referenzkarten bei **81 %, 78 % und 85 %**
blauen Radarpixeln; exemplarisch gewählte `3003=0x8000`-Kacheln
bleiben bei weniger als 16 % blau. Dieser Befund unterstützt
den Flag-Wasserhinweis in der **vorläufigen** Sprite-Ansicht,
belegt jedoch nicht die tatsächlichen Wasser-Shader oder Frame-IDs.
Manuelle Sprite-Testzuordnungen haben weiterhin Vorrang.

Die Kamera springt beim Klick ins tatsächliche Spielfeld, nicht in
die äußere .map-Datenhülle. Die gelbe Kamera-Markierung ist auf
das Radargrafik-Rechteck begrenzt. Qt-Integrationstests prüfen
Navigation und Kameramarkierung bei "Karte einpassen".
Quell-`.map`-Dateien und lokale Sprite-PNGs bleiben unverändert.

**Messmethode, Zahlen, Umrechnungen und Einschränkungen:**
`docs/SANDBOX_RADAR_KALIBRIERUNG.md`.

**Noch offen:** der tatsächlich pixelidentische Boden-,
Höhen- und Wasser-Renderer, das vollständig dekodierte
Originalsprite-Mapping und die vollständigen Zustände des Spiel-HUDs.


## Dreizehnter Meilenstein: getrenntes Terrain aus Höhe 3005 und Bodenklasse 3037

Die vorherige Vorschau verwendete **3005** als vermeintlichen Materialindex.
Dies war ein grundlegender Datenmodellfehler. Der dokumentierte ältere
Stronghold-Kartenstandard verwendet **1005 als Höhe** und **1037 als
Boden-/Texturkanal**. Die entsprechend strukturierten SHCDE-Abschnitte
**3005** und **3037** wurden mit `Antioch.map`, `Crusader Demo.map`
und `A Mighty Oasis.map` direkt statistisch gegen das echte Radar geprüft.

**Jetzt direkt implementiert:**

- Im detaillierten Kartenrenderer bestimmt **3037** die vorläufige
  Boden-Spritefamilie; **3005** wird nicht mehr automatisch als Gras-,
  Wasser- oder Felskennzahl missverstanden. Der per Spiel-Radar geprüfte
  `3003 & 0x100000`-Wasserhinweis bleibt als gesonderter Layer erhalten.
- Die Gesamtansicht wird aus denselben Originaldaten als abgestufte,
  ausdrücklich **diagnostische** Bodengrafik erstellt:
  Bodenfläche/-Farbe nach 3037, vorsichtige Helligkeitsvariation nach
  3005-Höhe, echter Wasser- und Nichtspielfeld-Hinweis nach 3003.
  Die diagnostischen RGB-Farben sind **keine** originalen Unity-Shader.
- Der Inspector zeigt **Bodenart 3037** und **Höhenwert 3005** getrennt.
  **„Palette-Sprite für Bodenart 3037 testen“** weist einer bekannten
  Originalbodenklasse eine benutzerdefinierte Spritegruppe/Frame-ID zu.
  Alle Kacheln der Karte mit diesem Rohwert aktualisieren sich gemeinsam.
  **„Bodenart-3037-Test zurücksetzen“** stellt die neue Näherung wieder her.
- Die neuen Zuordnungen werden versions- und kartenprüfsummengebunden
  als `stronghold-europe.sandbox.native-surface-3037.v1`
  unter `sandbox/surface-mappings/` atomisch gespeichert.
  Defektes JSON wird **nicht** überschrieben, sondern über
  eine separate Recovery-Datei umgangen.
- Die bestehenden älteren `sandbox/terrain-mappings/*`-Dateien für
  den Wert **3005** bleiben **vollständig erhalten** und behalten
  aus Kompatibilitätsgründen Vorrang bei manuellen Sprite-Tests.
  Ist eine alte 3005-Zuordnung aktiv, muss sie entfernt werden,
  damit der neue 3037-Test für diese Höhenwerte sichtbar wird.
- Das Sprite-Pixel-Live-Reload berücksichtigt nun auch manuell zugeordnete
  3037-Spritegruppen; Renderchunks werden gezielt neu zusammengesetzt.
- Die visuellen, integrierten und Datenformat-Tests prüfen drei
  Originalkarten, die Trennung der beiden Datenkanäle, altes und
  neues Mapping, persistente Bedienung, Recovery, fehlerhafte Codes
  sowie die Original-.map-Unveränderlichkeit.

**Quellbelege, Messwerte und technischer Reststand:**
`docs/SANDBOX_TERRAIN_HOEHE_BODEN_3037.md`.

**Weiterhin offen:** Die Original-Unity-Spriteframe-IDs samt tatsächlicher
Küsten-, Stufen-, Klippen-, Wasser- und Übergangs-Shaderlogik sind
mit diesem Datenmodell noch nicht vollständig rekonstruiert.

## Vierzehnter Meilenstein: Pixelgenauere Engine-Grafikauswahl und originale Kachelfarben

Die echte Engine-Ansicht lässt sich nun **direkt über die sichtbaren Pixel**
bedienen. Ein Klick auf ein Gebäude, eine erhöhte Klippengrafik, einen Baum
oder eine Einheit prüft die zuletzt aufgemalten Original-Kommandos in
umgekehrter Z-Reihenfolge und berücksichtigt Transparenz. Dadurch kann
auch eine lange Baumgrafik über fremden Boden hinweg korrekt ausgewählt
werden. Der Inspector zeigt nun das an der angeklickten Stelle tatsächlich
sichtbare `Sprite-Gruppe/Frame`-Paar, inklusive ursprünglicher GM-ID,
Bildnummer und Deckkraft.

- Die ausgewählte Originalgrafik erscheint direkt im sichtbaren
  **Originalkarten-Werkzeugstatus** und wird mit dem
  Arbeits-/Referenz-Spritevergleich synchronisiert.
- **Ctrl+E** beziehungsweise **„Grafik dieser Engine-Kachel direkt
  bearbeiten“** öffnet den eingebauten Pixel-Editor auf der tatsächlichen
  Sprite-ID. Speichern verändert ausschließlich die Arbeitskopie.
- Der Hit-Test nutzt echte Alpha-Pixel, nicht nur die Bounding-Box.
  Ein transparenter Baum gibt das darunterliegende Gelände frei.
- Die Engine-Originalfarben wurden erweitert: originale
  `gameTile`-Schattenstufen (1–7, 11–17, 50–55) und
  `TilemapManager`-Floatfarben (55–63), mit RGB-komponentenweiser
  Einfärbung, getrennten Cache-Einträgen und unverändertem Alpha.
  **In den drei geprüften Karten ist Floatfarbe 0**, daher sind
  Sonderfarben nur auf synthetischen Fixtures getestet.
- Die Klicksuche wurde mit einem begrenzten nativen Suchbereich und
  günstigem Anker-/Größenfilter deutlich beschleunigt: nach
  vorbereiteter Bildquelle fünf zusätzliche Echtkarten-Klicks
  überwiegend 0,06–0,30 Sekunden, erster Klick mit Originalressourcen
  ca. 0,5 Sekunden. Nicht als allgemeine Reaktionszeitgarantie.
- Ein echter Qt-Mausklick auf eine Vegetationsgrafik in `Antioch.map`
  öffnete im Pixel-Editor den spezifischen Frame
  `tree_pine/20` mit Canvas `163×309` Pixel. Die originale
  .map-SHA-256-Prüfsumme blieb vor und nach dem Dialog identisch.

**Regression:** 200 bestandene Sandbox-Tests, davon 38 zusätzlich zur
vorherigen Engine-Einführung, plus separat geprüfter realer
Engine-/GUI-/Bildschirm-Smoke-Test.

Details und Grenzen:
`docs/SANDBOX_NATIVE_ENGINE_INTEGRATION.md`.
Es fehlen weiterhin vollständige dynamische Unity-Shader- und
Gameplay-HUD-Zustände; die Standbild-Engine ist noch keine
spielbare Stronghold-Simulation.

## Integration in die Universal-Suite – Standard-Sandbox statt Zweitfenster

Die Hauptanwendung `tools/suite_universal.pyw` verwendet nun ihren schon
vorhandenen ttk-Reiter **Sandkasten** als Host des vollständigen
`SandboxStudio`-Qt-Editors. Das moderne Kartenstudio wird beim ersten
Aufruf im **selben Windows-Prozess** mit `SetParent` in den Tab eingebettet;
anders als bisher wird **kein zweiter Sandbox-Hauptprozess** gestartet.

- **`Suite starten.cmd` → `Sandkasten`** zeigt den vollständigen
  Originalkarteneditor unmittelbar an der Stelle des alten Reiters.
  Die Spielkarte, Sprite-Palette, Inspector, HUD-Seiten und Pixeleditor
  bleiben erreichbar. Das Suite-Protokoll kehrt beim nächsten Reiter zurück.
- **Asset-Katalog → Im Sandkasten zeigen** wählt genau den geöffneten Frame
  im eingebetteten Qt-Editor aus und aktiviert die Platzierung auf der
  Originalkarte. **Sandbox → Originalgrafik im Katalog** führt zum passenden
  Asset zurück, ohne die Sandbox-Instanz zu verlieren.
- Die breiten HUDs werden innerhalb der Sandkasten-Oberfläche als
  **scrollbare rechte Werkzeug-Reiter** angezeigt. Kompakte Fenster
  erzwingen keinen separaten Qt-Dialog und schneiden die Karte nicht ab.
- Das Studio bleibt bis zum Suite-Schließen aktiv; Speichern-/Abbrechen-
  Dialoge für ungesicherte Szenen und Overlays werden beachtet.
- Für die frische Installation enthält `requirements-py313-win_amd64.lock`
  PySide6 6.10.2 mit den SHA-256-geprüften Windows-Wheels.

Geprüft auf dem autorisierten Windows-Rechner mit einer tatsächlich
geöffneten **`Antioch.map`**: Native Qt-HWND-Elternschaft ist der Tk-Frame,
Qt- und Tk-Frame-Abmessungen stimmen überein, Spiel-HUDs sind im Qt-Dock
sichtbar, Katalog→Sandkasten→Katalog funktioniert ohne Zweitfenster.
Ein separates Fake-Bridge-Tk-Regressionstestmodul prüft zusätzlich
Reiterwechsel, Bestätigungsabbruch und fehlende Original-HUD-Crops.

Einrichtung, technische Grenzen und Screenshot-Abnahme:
`docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`.

## Fünfzehnter Meilenstein: Bedien- und Integritätstest in der Hauptanwendung

Die tatsächlich integrierte Sandbox wurde nochmals als **Teil der
Universal-Suite** geprüft und verbessert: Animation war bislang durch
das Dock-Umsortieren unsichtbar, ein früherer Engine-Frame konnte
die aktuelle Katalogauswahl verfälschen und Qt-Alt+F4 konnte einen
leeren Sandkasten-Reiter zurücklassen. Diese drei konkreten Fehler
sind korrigiert; neue **Animation / Frames**- und
**Spiel-HUD**-Schaltflächen machen die Werkzeuge direkt erreichbar.

Der Projektstart verwendet künftig den tatsächlich konfigurierten
SHCDE-Zielspielordner statt eines lokalen Entwickler-QA-Pfads.
Fehlt eine gültige Konfiguration, lässt sich im Sandkasten mit
**Kartenordner wählen** die Originalkarten-Installation bestimmen,
ohne auf andere Festplatten zu raten.

Integrationstest, Sicherheitsgrenzen und Windows-QA:
`docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`.

## Sechzehnter Meilenstein: read-only Startburgenprüfung aus Origins-Vermessungen

Aus dem autorisierten `E:\GS\StrongholdOrigins-Projekt\tools\check-start-keeps.py`
wurden **nur die nachgewiesenen Originaldatenfelder und die Prüflogik**
für die aktuelle Sandbox übernommen, nicht dessen historischen Kartenpacker
oder DLL-/Script-Extender-Annahmen.

Beim Öffnen einer SHCDE-Originalkarte zeigt der bestehende Qt-Karteninspektor
jetzt **Original-Startburgen** und – sofern vorhanden – die Eigentümer- und
Koordinatenliste aus dem nativen Gebäudeabschnitt 1013. Der Bauwerktyp **41**
ist für die untersuchten Skirmish-Karten der echte Startburgtyp; andere
Gebäude werden ausdrücklich **nicht** als Startburg gezählt.

Auf den drei lokal installierten Referenzkarten lautet die sichere Diagnose:

- `Antioch.map`: 3 Skirmish-Spielerslots, Typ-41-Burgstarts für 1–3 → **Passend**.
- `Crusader Demo.map`: 5 Slots, Typ-41-Burgstarts für 1–5 → **Passend**.
- `A Mighty Oasis.map`: kein Skirmish-Kartentyp, 0 Startburgen →
  **Nicht Skirmish**, keine irreführende Startburg-Warnung.

Bei falscher Anzahl oder mehrfach besetzten Slots erscheint **WARNUNG**,
aber keine automatische Reparatur. Kartenvarianten mit nicht decodierbarer
Bauwerksektion werden **Unverifiziert** genannt – niemals als fehlerfrei
ausgegeben. Keine Original-.map wird beschrieben oder verändert.

Implementierung: `src/stronghold_europe_de/sandbox/start_keep_audit.py`;
GUI: `tools/sandbox_studio.py`; Regression:
`tests/sandbox/test_start_keep_audit.py`.

**Offen:** Weitere Kartenformate, andere Spielversionen und
kampagnenspezifische Startpositionen benötigen eigene Nachweise.
Eine Skirmish-Startburgprüfung allein garantiert keine vollständige
Startbarkeit oder Kampagnenverträglichkeit.
