# Sprite Suite – Fachabgleich ALLER erreichbaren Originalwerkzeuge

**Stand:** 22.10.2026 · **Arbeitsprojekt:** `E:\SpriteSuite` · **Vergleichsbestand:** `E:\SU\projekt` · **Git-HEAD:** `00276ec`  
**Status:** technisch belegte Teilparität mit klaren P0-Lücken. **KEINE Gesamtabnahme, kein Release, kein Installationsversuch.**

## 1. Verbindliche Quellen und Grenzen

Der ehemalige Quellbestand `E:\SU\projekt` liegt bei
Git `414d341` vom **01.09.2026**, nicht bei einer nachgewiesenen
originalen Juni-Baseline. Die Vergleiche beziehen sich deshalb
ausschließlich auf diesen historischen **September**-Stand und
die im Originalspiel versionierten SH1DE/SHCDE-Eingaben.
Für die tatsächliche Herstellung identischer Juni-Builds fehlen
vollständige Pins, Ausgabemanifeste, Quellzustand und Ingame-Referenzen.

**Keine** nachfolgende Prüfung hat einen Build, eine Installation, einen
modifizierten Spieleingriff, eine Datenkonvertierung oder eine
Originaldatei-Schreibaktion ausgeführt. Neue QA-Berichte und Tests
liegen ausschließlich unter `E:\SpriteSuite`, vor allem `work/`.
Alle vorhandenen fremden Git-Änderungen bleiben erhalten.

## 2. Werkzeuge: welche fachlichen Verträge stimmen?

SHA-Vergleich von Original und aktuellem `tools/` (Python, PowerShell,
Shell und Windows-Startskripte):

| Ergebnis | Dateien | Bedeutung |
| --- | ---: | --- |
| **Bit-/byteidentisch** | 74 | Exakt gleiche Werkzeugimplementierung, aber andere Spieldaten/Umgebung möglich |
| **Geändert** | 6 | `suite.pyw`, `suite_bridge.py`, `suite_center.pyw`, `suite_start.py`, `suite_universal.pyw`, `suite_workflow.py` |
| **Nur historisch vorhanden** | 28 | Mehrere ältere Full152-, Cold-Start-, RAM-, Build-, Installations- und Sonderprüfer |
| **Nur im neuen `tools/` vorhanden** | 42 | u.a. integrierte Karten-/Qt-Werkzeuge, neue BC7/Pivot- und QA-Läufe |

`work/reports/ui-audit/original-tools-contract-inventory-20261022.json`
enthält für jeden Dateieintrag seinen alten und aktuellen SHA-256-Wert
sowie bei geänderten Python-Dateien API-Namen und CLI-Literale.
Die 28 abwesenden Dateien dürfen **nicht** pauschal als
«gleichwertig ersetzt» gelten. Ihre früheren Referenz-Build-Pins
sind nicht automatisch für SHCDE 2.80 zulässig, einige greifen
auf Installationen zu und dürfen nicht blind aktiviert werden.

### Tatsächlich geprüfte Funktionsergebnisse

| Werkzeugfamilie | Vergleich | Stand |
| --- | --- | --- |
| Sprite-`sprites.py`, Atlas-`ui_atlas.py`, Tile-`tile_objects.py`, Editor-`editor_bruecke.py`, Katalog-`asset_katalog.py`, SE-`se_atlas.py`, Pin-`pin_digests.py`, alte Sandbox-`sandkasten.py` | Original-/aktuelle SHA-256 **identisch** | **Quellgleichheit** |
| CLI-Argumentoberfläche | **13 von 13** tatsächlich ausgeführte ungefährliche `--help`-Aufrufe: Optionen/Exitcodes gleich | **Funktional Teilbeweis**, keine Import-/Bauausgabe |
| Pixelplatzierung und Originalfußpunkt, Spiegelung, Resampling, Clipping, Frame-Namen, HTML-Brücke, UI-PNG-Digest/-Pfadsperre, ORA-Gruppenfreigabe | **216** echte synthetische Eingaben, Original- und aktiver Funktionscode unabhängig ausgeführt, Ausgabepixel/Metadaten verglichen | **Identisch für getestete Fälle** |
| Kanonische Tabellen/Profile | `asset-kategorien`, `kachelobjekt-raster`, `tile-object-presets`, `ui-textures-bc7-v1`, `vertical-slice`, `sprite-suite-world-bc7-v2` | **6 von 6 byteidentisch** |
| Alte `sandkasten.py`-Renderfunktion | Zwei echte historische V1-Dateien bei `tick=0` und `1.37` mit deterministischen Testpixeln unabhängig gerendert | Bytegleiche Renderausgabe im **alten, erhaltenen** Werkzeug, nicht im neuen integrierten Editor |
| Neuer Qt-Editor | `SceneHistory`, Overlay, Pixeleditor, Animationspanel mit fokussierten Tests | Teilweise belegt; **V1-Szenen noch nicht kompatibel** |

Dateien:
`original-tools-cli-help-20261022.json`,
`original-tool-functional-parity-20261022.json`,
`original-sandbox-v1-scene-compatibility-20261022.json`
(jeweils unter `work/reports/ui-audit/`).
Zwei neue headless Regressionstestdateien:
`tests/sandbox/test_original_tool_contracts.py` und
`test_original_scene_compatibility.py` (**20 Tests bestanden**).
Diese wurden in die explizite Headless-System-Prüfliste aufgenommen.

### Historischer Workflow: Sicherheitsabweichung bewusst erhalten

`work/qa_original_suite_workflow_differential_20261022.py`
führte acht echte `main()`-/`run_steps()`-Szenarien
unter komplett abgefangenem `subprocess.run` aus.
Die Reihenfolge und CLI-Argumente von Prepare/Check/Build
stimmen nach Normalisierung des Projektpfads überein.
Eine Abweichung ist **erwünscht**:

**Beim originalen nicht-strengen `build` meldet ein fehlgeschlagener
abschließender `validate`-Schritt trotzdem Exitcode 0.**
Im aktuellen `suite_workflow.py` beendet derselbe Fall korrekt
mit dem Validator-Fehlercode **23**. Diese geschlossene
Release-Sperre darf **nicht** zugunsten vermeintlicher
Originalparität zurückgebaut werden.
Beleg: `original-suite-workflow-differential-20261022.json`.
Die realen Build-PNGs, BC7-Bundles, Ingame-Ausgaben
und Installer wurden hierfür **nicht** erzeugt.

## 3. 135.000 Spritezuordnungen: echte Feld- statt Dateivergleiche

Die komprimierten `work/mapping/proposals.json.gz`-Dateien sind
nicht byteidentisch. Die alte Ausgabe wurde für **SHCDE 2.7**,
die heutige für **SHCDE 2.80** erstellt. Der gemeinsame
SH1DE-Quellstand und die 135.352 gemeinsamen
`(group,name)`-Schlüssel bleiben erhalten.

| Vergleichsfeld, 135.352 gemeinsame Frames | Differenzen |
| --- | ---: |
| Quell-Sprite-Metadaten (`source`) | **0** |
| Umwandlungsregeln und Geometrie (`transform`) | **0** |
| Aktion (`KEEP_CRUSADER`, `REPLACE_EXACT`, `REPLACE_DERIVED`, `REVIEW_MANUAL`) | **0** |
| Ziel-Pivot `pivot_x/pivot_y` | **0** |
| Ziel-`path_id` | 100.112 |
| Ziel-`rect_x` | 2.434 |
| Ziel-`rect_y` | 2.428 |
| Hinzugekommene Frames in 2.80 | `anim_drawbridge-128`, `anim_drawbridge-129` |

Die **100.757** veränderten vollständigen Datensätze
haben ausnahmslos Unterschiede im `target`-Objekt,
**nicht** in Quelle, Aktion oder Transformationslogik.
Dies ist die erwartbare Art einer Build-Versionierung;
es beweist keine identischen Endpixel, bis der genaue
Zielversionseintrag geprüft ist.

### Gegenprüfung gegen wirkliche Spiel-Dateien

Es wurden aus **allen drei lokalen Installationseingaben**
je fünf kanonische Dateien **vollständig mit SHA-256 gehasht**:
`globalgamemanagers`, `resources.assets`,
`resources.assets.resS`, `sharedassets1.assets`,
`Managed/Assembly-CSharp.dll` (je Installation).
Jedes Quintett stimmt **exakt** mit dem dazugehörigen
`supported-builds.json`-Eintrag überein:

- SH1DE-Quelle: `local-sh1de-unity-2021.3.27f1-2025-01-20` – **5/5**.
- Historische E:-SHCDE-2.7-Installation – **5/5**.
- Aktuelle `E:\SSGameQA`-2.80-QA-Kopie – **5/5**.

Damit stimmen **beide vollständigen Mapping-Build-IDs** mit
echten überprüften lokalen Spielressourcen. Die abweichenden
Ziel-`path_id`-Werte dürfen gerade **nicht** blind als alte
2.7-Werte im neuen 2.80-Game ausgegeben werden.
Belege:
`original-tools-mapping-content-20261022.json`,
`original-tools-mapping-field-differential-20261022.json`,
`original-and-current-map-build-pins-20261022.json`.
Diese Prüfung war vollständig **read-only**.

## 4. Bestätigte funktionale Lücken – NICHT grün

### TOOL-CONFIG-01 / TARGET-01: fehlende aktive Ziel-/Installationsbindung (P0)

Im alten `E:\SU\projekt` sind die beiden Spielziele
`d-280` und `e-27` registriert; aktiv ist `e-27` (2.7).
Dagegen fehlen im aktuellen `E:\SpriteSuite\config`
**beide** `installations.local.toml` und `ziele.json`.
Der byteidentisch erhaltene Zielverwalter
`tools/ziel_se211.py` liefert deshalb aktuell
**keine registrierten Ziele**. Unbekannte Ziele werden
sicher abgewiesen, aber die Zielwechsel- und
Installationsoberfläche ist **inhaltlich nicht
fertig eingerichtet**. Dass die separat vorhandene
2.80-QA-Installation exakt zum Mapping passt, berechtigt
keineswegs zum stillen Eintragen eines Produktionsziels.

**Nicht die alte Konfiguration kopieren**:
sie würde das 2.7-Ziel aktivieren, während das aktuelle
Mapping zur 2.80-Referenz gehört. Der Benutzer muss die
gewünschte Produktionsinstallation im Setup verbindlich
auswählen, ehe ein realer Build/Installationsworkflow
abgenommen wird. Beleg:
`original-target-manager-compatibility-20261022.json`.
Keine Installations- oder Zielwechselaktion wurde ausgeführt.

### SBX-V1-01: Original-Szenen werden vom neuen Editor nicht verlustfrei geladen (P0)

Historisches `beispieldorf.json` / `katalog-vorschau.json`:
je 26×26, **507** sichtbare Bodenelemente,
**169** GM1-Komposit-Bauteile und **zwei** animierte
Spriteobjekte; im Originalrenderer insgesamt
**680/681** Bildreferenzen bei `tick=0`.
Die neue editierbare Szene speichert bisher nur
`group/frame/x/y/team`, nicht den alten Boden-Saatwert,
GM1-Baustrukturen, Bildfolgen und HUD-Szenenstatus.
Der echte neue `load_scene` verwirft daher beide
V1-Quellen. **Es gibt noch keine verlustfreie Migration
oder parallele Bearbeitung in der neuen Qt-Sandbox.**

Die bestehende Fehlerbehandlung wurde dahingehend
präzisiert, dass sie *explizit vor Verlust von Boden,
Mehrteilerobjekten und Animationszuständen warnt*,
statt nur «unbekanntes Szenenformat» zu melden.
Original-V1-Dateien bleiben byteidentisch und auch
bei versehentlichem Speichern einer V2-Datei an ihren
Pfad geschützt. Die Tests vergleichen zudem den
erhaltenen ursprünglichen Renderer unter echten
historischen V1-Szenen bei zwei Zeitpunkten mit dem
aktuell erhaltenen alten `sandkasten.py`: **identisch**.
Eine produktive Migration ist damit **nicht** erledigt.
Beleg: `original-sandbox-v1-scene-compatibility-20261022.json`.

### PIPE-01 / ORIGINAL-RELEASE: Original-Build und fehlende ältere Prüfer (P0)

Es fehlen gegenüber dem September-Referenzbestand
**28** Tooldateien im aktiven `tools/`, darunter
spezifische Full152-/BC7-/Cold-Start-Proben,
`runtime_install.py`, ältere SHCDE-Installationshelfer,
RAM-Messprogramme und `system_workflows.py`.
Ob die neue Suite jede ihrer relevanten **Wirkungen**
durch andere Module sicher ersetzt, ist **nicht**
für alle 28 belegt. Alte, versionsabhängige
Installationskommandos dürfen nicht ohne Prüfung
auf SHCDE 2.80 übertragen werden.

**Trotz mehrerer hundert grüner Tests** sind noch
die vollständige historische CLI-Ausgabeparität,
echte Build-Bundles und -Validierung, exakte Juni-
Werkzeugversionen, Installations-/Rollback-Folge und
Ingame-Ausgabehashes als durchgehende Aufgabe offen.

**MAP-01/HUD-01/UI-01:** Zeitgleiche Shader-/Wasser-/
Gameplay-Pixelparität, Berater-/Bink-Zustände,
echte Windows-DPI-/Screenreader- und mehrstündige
Nutzersitzung sind weiterhin **nicht abgenommen**.

## 5. Headless-Gesamttest und Freigabeentscheidung

Aktueller Teststarter:
`tools/qa_sandbox_headless_system.ps1`;
die ursprünglichen zwei expliziten
`qa_sandbox_headless*.ps1`-Modullisten wurden
um `test_original_tool_contracts.py` und
`test_original_scene_compatibility.py` ergänzt.
**61 Modell-/Qt-Offscreen-Testmodule**, ohne
Tk-Fenster, Installations- oder Unity-Aufrufe.
Die **20 neuen Fachabgleichstests bestanden**
isoliert. Der danach ausgeführte vollständige
Headless-Systemlauf meldete **623 bestanden,
0 fehlgeschlagen, 0 übersprungen**, Exitcode
**0**, **445,59 Sekunden**. Das Ergebnis wurde
unabhängig gegen sämtliche 623 Testfälle im
`sandbox-headless-combined-20261022.xml`
verifiziert. Die reproduzierbare Ausführung
steht in `tools/qa_sandbox_headless_system.ps1`,
das Rohprotokoll unter
`work/reports/ui-audit/sandbox-headless-original-tools-20261022.log`.
Der Umfang sind **61 explizit ausgewählte Headless-Testmodule**,
nicht alle beliebigen GUI-/Produktionsfälle.

Der letzte vollständige gemischte Teststand vom
21.10.2026 enthielt **743 bestanden / 2 Tcl-/Tk-Skips**;
dessen Desktop-Isolationsproblem, der gemessene
GDI-Ressourcenanstieg und echte Tk-Langzeitsitzungen
werden **nicht** durch Headless-Tests ersetzt.

**Gesamturteil: Sprite Suite/Sandbox WEITERHIN NICHT FREIGEGEBEN.**
Die zentralen übernommenen Einzelwerkzeuge sind
auf den geprüften Quell- und Funktionsebenen
weitgehend konsistent. Die vollständige
historische Sandbox-Bedien-/Szenenparität und
der produktive Originalworkflow sind jedoch
nachweislich **nicht** vollständig vorhanden.
