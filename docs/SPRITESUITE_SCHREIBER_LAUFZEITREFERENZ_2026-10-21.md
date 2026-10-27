# Sprite Suite – Schreiber-Laufzeitbelege und manueller Originalframe-Betrachter

**Datum:** 21.10.2026 · **Projekt:** `E:\SpriteSuite` · **Branch:** `feature/sandbox-studio` · **Ausgangs-HEAD:** `00276ec`

**Status: prüfbarer Teilauftrag – KEINE Wiederherstellung der originalen Schreiber-Animation.**

## 1. Originalcode: was jetzt tatsächlich belegt ist

Aus der **nur gelesenen** installierten
`E:\SSGameQA\Stronghold Crusader Definitive Edition_Data\Managed\Assembly-CSharp.dll`
wurden `MainHUD`, `CrusaderDE.MainViewModel`, `CrusaderDE.HUD_Options`
und `SFXManager` zur Untersuchung lokal dekompiliert. Die
ausgelesenen Tatsachen sind in
`work/reports/ui-audit/scribe-original-runtime-evidence-20261021.json`
mit Assembly- und XAML-SHA-256 festgehalten:

- `HUD_Options.xaml` enthält `ScribeClassicButton` mit
  `CommandParameter=-15` und `ScribeModernButton` mit
  `CommandParameter=-17`. Der originale C#-Handler setzt
  damit `ConfigSettings.Settings_Scribe=0` beziehungsweise
  `=2`. Die Spieleinstellung `1` ist ebenfalls als Handler
  `-16` im Code vorhanden, ihre reale Bedienung im Spiel
  wurde **nicht** untersucht.
- Beim Übergang zur Hauptspielsituation setzt
  `MainViewModel` den Wert `ScribeHeadImage=GameSprites[24]`.
  Das ist eine initiale Bildbindung und **noch kein**
  Beleg dafür, welchen `UI-Scribe B/C`-Frame sie zeigt.
- Die originale `MainHUD`-Oberfläche besitzt das
  `MediaElement RadarME`; dessen
  `MediaEnded`-/Abbruchverhalten beachtet
  `SFXManager.requestBinkPlayState` und
  `binkWaitForSpeech`. `SFXManager.playBink(..., loop,
  waitForSpeech)` referenziert einen gesonderten
  `Assets/GUI/Video`-Pfad. Der vollständige Sprech-/Video-
  und Framezustandsautomat wird hier **nicht** simuliert.
- Die vorhandene XAML-Resource-Bank besitzt
  `UI-Scribe B001…B045` (45 Keys) und
  `UI-Scribe C001…C044` (44 Keys). Sie wurden bereits
  aus den richtigen Original-BC7-Quellpixeln mit SHA-256
  gesichert. **B045 ist 178×164** statt 374×414 Pixel.
  Das rechtfertigt ein Sonderformat, aber **kein**
  angenommenes Animationsende und keine erzwungene
  Wiedergabereihenfolge.

Die B/C-Bildfamilien und die Classic/Modern-Einstellungsbuttons
haben ähnlich benannte Ressourcen. Ein *direkter* Mechanismus
zwischen `Settings_Scribe`, Zeit, Stimme,
`UI-Scribe B/C` und dem Video wurde jedoch nicht vollständig
nachgewiesen. Diese Zuordnung bleibt im Datenvertrag offen.

## 2. Neue tatsächliche Sandbox-Funktion

`tools/sandbox_scribe_reference.py` ist eine strikt **manuelle**
Bildreferenzquelle. Sie akzeptiert nur den vorhandenen
`OriginalGameUICrops`-Provider mit SHA-geprüfter lokaler
Original-`globalgamemanagers.assets` und originalem XAML.
Vor Anzeige vergleicht sie *alle 89* Scribe-Quellrechtecke
erneut mit der installierten XAML-Datei. Sie verhindert
fehlende, doppelte oder außerhalb der Familien liegende Keys;
vorhandene PNG-Frames werden bei Auswahl per SHA verifiziert.
Die Quelle wird ausschließlich aus
`work/original-ui-native-crops-20261015/manifest.json`
benutzt; keine Unity-Extraktion oder Installation in der Qt-UI.

`tools/sandbox_gameplay_mode.py`: Ein separat beschrifteter
**„S“-Knopf** öffnet im rechten, mit der Originalkarte
verbundenen Spiel-HUD eine vierte Seite
`Schreiber-Referenz`. Der Benutzer kann **B oder C**
wählen und mit `‹`/`›` ein einzelnes Bild
vor- oder zurückstellen. Es gibt **keinen** Timer,
automatischen Durchlauf, Sprachwiedergabe,
Spielkommando, `Settings_Scribe`-Schreibvorgang
oder simuliertes Wirtschaftsevent. Bei fehlender
Originalquelle bleibt der „S“-Knopf gesperrt;
auf falsche europäische Packkoordinaten fällt er nicht zurück.

Beschriftung und Barrierefreiheit:
`B001/45`, `C001/44`, der genaue Quellen-Key und
Originalpixel-Hinweise als zugänglicher Name/Tooltip,
DE/EN-Sprachwechsel ohne Bildsprung. `B045` besitzt
einen sichtbaren Sonderformat-Hinweis im Tooltip und
keine über den letzten Frame hinaus laufende Automatik.
Der Knopf `M` führt unverändert zur echten
kameraabhängigen Minikarte zurück, der Editor behält
dieselbe Originalkarte und History.

## 3. Prüfbelege – nur nach tatsächlichem Test gültig

- Reiner Quell-/Grenzvertrag:
  `tests/sandbox/test_scribe_manual_reference.py`:
  **15 bestanden** mit synthetischem Hash-/XAML-Provider,
  B-/C-Seitenlängen, B045-Sonderfall, beschädigtem
  Quellbild, manipulierten XAML-Rechtecken und ungültigen
  Frame-Anforderungen.
- `tests/sandbox/test_gameplay_mode_workspace.py`
  ergänzt drei GUI-Aufgaben für manuelle Referenz,
  kleine Fenster, Sprachwechsel, fehlende Quelle,
  nie veränderte Originalkarte/Overlay-History.
  **3 gezielte Qt-Tests bestanden**.
- `work/qa_scribe_manual_reference_20261021.py`:
  auf `Antioch.map`, **SCRIBE_MANUAL_REALMAP_QA_PASS**.
  Zu B001, B002, C001, B045 sowie 784×342 wurden Screenshots
  erstellt. Die ursprüngliche Overlay-Serialisierung und die
  SHA-256-Originalkarte blieben identisch.
  Maschinenlesbarer Nachweis:
  `work/reports/ui-audit/scribe-manual-reference-proof-20261021.json`.
- Tatsächlich eingebettete Windows/Tk-/Qt-Ansicht:
  `tools/qa_suite_embedded.py` enthält einen zusätzlichen
  `NATIVE_MANUAL_SCRIBE_REFERENCE_PASS`-Prüfpfad.
  Screenshots werden nur in `work/reports/ui-audit`
  geschrieben:
  `suite-embedded-manual-scribe-1500x930.png` und
  `suite-embedded-manual-scribe-C-1500x930.png`.
  Der native Gesamtlauf ergab **QA_PASS** (Exit 0,
  125,37 Sekunden) und **NATIVE_MANUAL_SCRIBE_REFERENCE_PASS**.
  Der Test hat B001 → B002 → C001 sowie B045 im echten
  Windows/Tk-/Qt-Kindfenster ausgeführt und nach der manuellen
  Bildauswahl die originale Minikarte wieder eingeblendet.
  Die Bilder `suite-embedded-manual-scribe-1500x930.png`
  und `suite-embedded-manual-scribe-C-1500x930.png` wurden
  anschließend visuell geprüft.
- Abschließende kombinierte Regression über **11**
  gezielte Modell-, Originalpixel-, HUD-/Canvas-, Auswahl-,
  Kompositions- und native Engine-Testdateien:
  **114 bestanden** in 223,36 Sekunden, Exit 0.
  Diese Zahl bezeichnet ausdrücklich **nicht** die
  vollständige 609+-Suite oder eine Freigabe der
  historischen Produktions- und Spielabläufe.

## 4. Unveränderte Originale und offene Abnahmeaufträge

Keine `.map`, keine Unity-/XAML-Ressource, keine
ausgelieferte Atlasdatei, keine Game-Config, kein
Bilddatenpaket und keine Installation wurden geändert.
Schreiber-Framedateien bleiben ausschließlich in einer
lokalen privaten QA-Ablage. Git-HEAD `00276ec`
wurde nicht zurückgesetzt; keine vorgefundenen
unfertigen Änderungen wurden global eingecheckt.

**HUD-01 (P0): OFFEN** – die echte ereignisabhängige
Sprecher-/Porträt-/Bink-State-Machine,
Frame-Zeitfolgen, Auslöser, Beraterzustände,
Sprachwiedergabe und Zustandsinteraktion fehlen.

**MAP-01 (P0): OFFEN** – Shader, Wasser, Kamerapose
und zeitgleiche Original-Gameplay-Frames sind nicht
in Pixelparität abgenommen.

**PIPE-01 (P0): OFFEN** – ursprünglicher Juni-Werkzeugstand,
gesamte Arbeits- und Buildpipeline, Abhängigkeiten,
identische Ausgabedaten noch nicht belegt.

**UI-01 (P1): OFFEN** – reale Multimonitor-DPI-,
Screenreader-/Tastaturlangzeit- und Alltagstests.

**Fazit:** Das Spiel-HUD kann jetzt nachgewiesen echte
Schreiber-Grafikquellen als manuelle Referenz darstellen.
Das ist die belegbare Vorstufe zur späteren State-Machine,
nicht deren vermeintliche Fertigstellung.
