# Sprite Suite – Gesamtabnahme der integrierten Sandbox (NICHT FREIGEGEBEN)

**Beginn:** 21.10.2026  
**Projekt/Branch:** `E:\SpriteSuite` · `feature/sandbox-studio` · letzter geprüfter HEAD `00276ec`  
**Abnahmeobjekt:** **Die vollständige** Sandbox im Tk-Hauptfenster, einschließlich
Qt-Spielmodus, Qt-Editor, Karten-/Testfeldansichten, Frame-/Pixelwerkzeuge,
Assets, Animation, Speicherung, Katalogverbindung und Original-Spielreferenzen.

## Verbindliches Qualitätsprinzip

Eine grüner HUD-Test **ist keine Sandbox-Abnahme**. Ein bestandenes
Unit-Testmodul **ist kein menschlicher Bedienbarkeitstest**, ein identischer
SHA-256 einer Python-Datei **kein gleichwertiger historischer Workflow**,
ein gerenderter Screenshot **kein Nachweis von Original-Spielsimulation**.
Ein Test kann nur genau die nachgewiesenen Voraussetzungen belegen.

**Freigaberegel:** Solange ein P0/P1-Fehler offen, der vollständige
Sandbox-Regressionstest nicht abgeschlossen, eine essentielle
Benutzeraufgabe ungeprüft oder die Original-Spielnähe nicht
nachvollziehbar belegt ist, bleibt die **GESAMTE SANDBOX: NICHT FREIGEGEBEN**.

### Akzeptanzmatrix (nicht als bestanden vorwegnehmen)

| ID | End-to-End-Ziel / Fehlerweg | Nachweis für erfolgreiche Abnahme | Stand |
|---|---|---|---|
| SBX-01 | Start ohne installiertes Spiel, leere/kaputte Kartenquelle | Tk/Qt startet, verständliche Warnung, keine falschen Aktionen, kein erzwungener Download | OFFEN |
| SBX-02 | Start mit Originalkarte | korrekte Quelle, Zoom/Kamera/Layer, Spielmodus als **ein** Qt-Kindfenster; Originaldatei-Hash unverändert | TEILWEISE |
| SBX-03 | Karte wechseln und Ladefehler | Antioch → zweite echte Map → Antioch, keine alten Auswahl-/Undo-/Speicherzustände | TEILWEISE |
| SBX-04 | Spielansicht↔Editor inkl. F1–F4, Tk-Werkzeugnavigation | Keine versteckte Spielleiste über einem Editor-Testfeld; keine verlorene Auswahl oder Szene | **TEILWEISE**, P1-Fehler bestätigt/korrigiert, Qt+native QA |
| SBX-05 | Katalog→Sandbox→zurück→Katalog | dieselbe Gruppe, derselbe Frame; bestehender **Spielmodus nicht unerwartet verlassen** | **TEILWEISE**, P1-Fehler bestätigt/korrigiert, Qt+native QA |
| SBX-06 | Karte: Klick, Sprites, Editor-Overlay | erlaubte Kachel, Objekt-Selektion, Drag, Undo/Redo, Abbruch, Save nur in Arbeitsdatei | TEILWEISE |
| SBX-07 | Separates isometrisches Sprite-Testfeld | Assetwahl, Platzierung, Team, Verschieben, Löschen, Undo/Redo, Neu/Laden/Speichern/Neuladen | **TEILWEISE** – E2E Inspector, Undo/Redo, Szenenspeicherung bestanden; weitere Bedienfälle offen |
| SBX-08 | Sprite-Palette, Framevorschau, Live-Reload | Quelle/Frame in Qt und Tk identisch; Änderungen erkennbar; fehlende Frames ohne Fantasiegrafik | TEILWEISE |
| SBX-09 | Animations-/Frame-Test | Framebereich, Scrub, Play/Pause, Geschwindigkeit, Fokuswechsel, Undo, gewählter Frame konsistent | **TEILWEISE** – Frame-Schritt/Reset im E2E; FPS/Play-Langlauf offen |
| SBX-10 | Pixeleditor | Originalschutz, Bearbeitung einer Arbeitskopie, Stroke, Undo/Redo, Speicherabbruch, Reload | OFFEN: komplette UI-Aufgabe |
| SBX-11 | Originalkarten-Radar, Höhen-/Terrain- und Rohkanäle | korrekte Datenquelle, Reihen, Grenzen, Tooltip; Originaldaten bleiben lesend | TEILWEISE |
| SBX-12 | Original-Objekte/Grafikzuordnung | 1013/1014 Rohdatensatz, Zuordnung, Rücknahme, Quelle sichtbar, kein unbewiesener Typname | TEILWEISE |
| SBX-13 | HUD-Bauicon/Kategorien/bedingte Varianten | Original-PNG-Hash+XAML-Rechteck, sichtbarer Klick, Bindungsvertrag, Kategorie-Wiederherstellung | TEILWEISE |
| SBX-14 | HUD-Auswahl, Radar, Grafiken, manueller Schreiber | Auswahl-Clear/Map-Wechsel, echte Frames, keine animierte Fake-Wirtschaft | TEILWEISE |
| SBX-15 | Original-Spieltreue: Karte/Shader/Gameplay-HUD | identische Kamera/Zoom/Zeit gegen 4 Originalbilder; Wasser/Wind/Animation/Portraits | **P0 UNBEWIESEN** |
| SBX-16 | Exporte/Originalvergleich/Arbeitsablage | Quelle/Ziel/Sicherungsstatus transparent, validierte PNGs/Scene/Overlays; Fehler werden nicht verschwiegen | OFFEN |
| SBX-17 | Übergabe an Pivot/Maske/BC7/Build/Install | identische Frame-IDs und Hashes, Versionen; Build/Installation bei Fehler gesperrt | **P0 UNBEWIESEN** |
| SBX-18 | Größe, DE/EN, Fokus, Tastatur, DPI, Dauerbetrieb | 1020×680, 1320×800, 1500×930, System-DPI, Screenreader, lange Wiederholung ohne Leck/Freeze | **TEILWEISE** – drei native Größen bestanden; echte DPI/Screenreader/Langlauf offen |

### Reproduzierte und korrigierte übergreifende Fehler

**SBX-ROUTE-01:** Vom integrierten Spielmodus aus
`Studio.show_test_field()` / F2 aufzurufen zeigte den
Editor-Testfeldinhalt, ließ aber `CompactSandboxLayout.game_mode=True`,
`tabs.tabBar` verborgen und das Spiel-HUD über dem fremden Tab.
Mit `tests/sandbox/test_cross_workspace_navigation.py` wurde
dieser Fehler **vor der Korrektur reproduziert**. Neue zentrale
`QTabWidget.currentChanged`-Überwachung im Embedded-Workspace
stellt den Editor bei jeder anderen Seite wieder her.
`Studio.open_map` vermeidet beim erfolgreichen Game-zu-Game-
Kartenwechsel eine solche Zwischen-Radarumschaltung; bei
fehlgeschlagener nativer Dekodierung wird bewusst der echte
Editor-Radar sichtbar. Der QT-Test und native Tk-/Qt-Test
`NATIVE_CROSS_VIEW_GAME_EDITOR_ROUTING_PASS` sind danach bestanden.

**SBX-ROUTE-02:** `EmbeddedSandboxStudio.select_sprite()`
verließ beim Übergang Katalog→Sandbox **ungefragt** den laufenden
Spielmodus, weil der Karten-Inspector erzwingend geöffnet wurde.
Nach separater Reproduktion mit einer echten nur lesend geladenen
Originalkarte wahrt die Übergabe nun den jeweils aktuellen
Game-/Expertenmodus und die Sprite-ID. Der Qt-Test sowie
`NATIVE_CATALOGUE_PRESERVES_GAME_VIEW_PASS` sind bestanden.

**LANG-SETUP-01:** Der vollständige Testlauf fand ein uneinheitliches
DE/EN-Bereitschaftsfenster: der zu Recht übersetzte Button
`Go to setup` widersprach der deutschen Testannahme. Die Fixture
übernahm irrtümlich die Sprache aus der persönlichen
Suite-Konfiguration; sie ist nun isoliert deutsch.
`suite_center.pyw` zeigt nun den Titel, statische Begründung,
Buttonaktionen und Zähler tatsächlich passend zur gewählten
deutschen oder englischen Sprache. Ein neuer expliziter
EN-Dialogtest verhindert den gemischten Zustand. Alle
**13 Tests** in `test_suite_build_readiness_gui.py` bestanden.

**Zusammenhängende Benutzeraufgabe:**
`work/qa_full_sandbox_user_journey_20261021.py` verlief
mit **11 erfolgreich geprüften Aufgaben-/Statusschritten** über
Katalog, echte Karte, Spriteklick, temporäre Overlay-Datei,
Undo/Redo, unabhängiges Testfeld, Inspector, Animation,
temporäre Szenenspeicherung/Laden, Radar, Rohkacheln,
DE/EN, Game-/Editor-Umschaltung und echten Map-A/B/A-Wechsel.
Nachweis `work/reports/ui-audit/sandbox-cross-workflow-journey-20261021.json`;
die Hashes beider Originalkarten blieben identisch.
Die Beweise gelten für genau diese Aufgaben, nicht für
alle möglichen Spritekombinationen und täglichen Sessions.

**Native Windows-QA:** `tools/qa_suite_embedded.py` meldete
`QA_PASS` mit drei Hauptfenstergrößen 1020×680,
1320×800 und 1500×930. Die Game-/Editor-Route und der
Katalog-Rückweg wurden im echten Tk-/Qt-Kindfenster geprüft.
Bei 1020×680 bleibt die Karte im kleinen Arbeitsraum sehr
knapp: dies ist weiterhin ein **offener Usability-Abnahmeblocker**,
auch wenn die Schaltflächen technisch erreicht wurden.

### Testreichweite (nur tatsächliche Evidenz)

`pytest tests/sandbox --collect-only -q` sammelte zu Beginn
**732 Tests**. Die früher berichteten 114 gezielten Fälle deckten
nur eine Teilmenge ab. Der erste breite Lauf mit `-x` wurde
**NICHT bestanden und nicht vollständig**:
**591 bestanden, 1 fehlgeschlagen, Stop nach 756,92 Sekunden**.
Der Fehlertest
`test_suite_build_readiness_gui.py::test_report_dialog_has_actionable_setup_and_close_buttons`
enthielt eine deutschsprachige Erwartung bei tatsächlich englischem,
aber unvollständig übersetztem Bereitschaftsdialog. Quellen:
`work/reports/ui-audit/sandbox-full-regression-20261021.log`
und `sandbox-full-regression-20261021.xml`.

Nach Korrekturen wurden die beiden neuen Cross-Workspace-Tests
zusammen mit bestehenden 29 Qt-Game-Tests (**31 bestanden**) sowie
alle 13 Bereitschaftsdialog-GUI-Tests erfolgreich ausgeführt.
Neue Benutzeraufgaben- und Testfälle erhöhen die gesammelte
Testanzahl gegenüber der ursprünglichen Zahl 732.

Der **vollständige erneute Run ohne `-x`** wurde gestartet.
Die Dateien
`work/reports/ui-audit/sandbox-full-after-fixes-20261021.log`
und `sandbox-full-after-fixes-20261021.xml` werden nur
nach bestätigtem vollständigem Prozessende als Endergebnis bewertet.
Ein Abbruch/FREEZE oder weiterer Fehler führt ausdrücklich zu
**NICHT BESTANDEN / NICHT VOLLSTÄNDIG**, niemals „grün“.

Der vorhandene native Windows-Skriptlauf `tools/qa_suite_embedded.py`
bestätigte einzelne Tk-/Qt-Kindfenster- und Werkzeugpfade,
aber nicht sämtliche obigen Benutzeraufgaben.

### Reproduzierbare visuelle Referenzen

- Historische Sandbox: `E:\SU_merge\gui_sandkasten.png`.
- Originalspiel-HUD: `E:\SU\projekt\sandbox\hud\hud.png` und
  `hud.json`; vier zugehörige Originalbilder (September 2026).
- Native Qt-Screenshots:
  `E:\SpriteSuite\work\reports\ui-audit\sprite-gameplay-1168x542.png`,
  `suite-embedded-original-ui-crops-1500x930.png`,
  `suite-embedded-manual-scribe-1500x930.png`.
- Neue Originallokale Pixelcrops sind nur **private QA-Quellreferenzen**.
  Eine Quell-CRC/Hash-Übereinstimmung ersetzt keine Original-Skin-/Engine-State-Machine.

### Sofortige Korrekturreihenfolge

1. Tatsächliche **seitenübergreifende Modusnavigation** und
   **Katalog→Spielkarte-Rückweg** instrumentieren, Fehler beheben und
   mit echten Nutzeraufgaben (inklusive Tastatur/Undo) prüfen.
2. Alle 4 zentralen Arbeitsflächen gemeinsam testen: Spielkarte,
   Testfeld, Radar, Roh-/Höhendaten; Speicherung und Editor-History
   getrennt, kein versteckter Modus.
3. Dateiöffnen/-schließen, negative Asset-/Karten-/Exportpfade,
   Abbuch/Abbrechen und Desktop-Fokus-/DPI-Verhalten testen.
4. Kern-Testdateien und alle realen Qt-Bedienpfade reproduzierbar
   auswerten, Screenshots und Quellhashes beilegen.
5. Nachweis der originalen Karte/Simulation und historischer
   Pipeline-Versionen **separat** vor einer Freigabe.

### Schutz

Original-`.map`, `globalgamemanagers.assets`, XAML, alte
Arbeitsgrafiken und fremde Git-Hunks werden nicht überschrieben.
Tests schreiben nur in `work/` oder isolierte temporäre Dateien.
Ohne unabhängige Freigabe werden keine Release-Pakete
oder Spielinstallationen geschrieben.

**Gesamtstatus: NICHT FREIGEGEBEN.**


### Weitere nachgewiesene Fehler der GESAMTEN Sandbox (21.10.2026, Folgeprüfung)

**SBX-SAVE-01 – stillschweigende falsche Datei beim Speichern:**
`SandboxStudio.save_active()` behandelte bislang **alle**
Ansichten außer der nativen Spielkarte als Sprite-Testszene.
Damit löste Strg+S aus dem lesenden Radar (F1) oder
der Kachel-Rohdatenansicht (F3) einen Speichervorgang der **nicht sichtbaren
Testszene** aus. Der Fehler wurde im Quellpfad reproduzierbar
nachvollzogen. Jetzt wird nur auf aktiver Spielkarte (Index 3)
das *Arbeits-Overlay* und nur im Testfeld (Index 1) die
*Testszene* gespeichert. Radar/Rohdaten verweigern das
Speichern mit einer expliziten Meldung. Neuer Qt-Test:
`test_ctrl_s_saves_only_the_current_editable_workspace`:
**BESTANDEN** (keine verdeckten Speichercallbacks).

**SBX-LEGACY-01 – zweites altes Sandboxfenster aus der Suite:**
Die historische Methode `Universal.open_sandbox(scene_path)`
erzeugte weiterhin einen separaten `sandkasten.SandboxWindow`,
obwohl die aktuelle Suite verbindlich einen einzigen
eingebetteten Tk-/Qt-Arbeitsplatz verlangt. Der
Kompatibilitätseinstieg routet jetzt ausschließlich über
`sandbox_tab.ensure_studio()`. Ein übergebener Testszene-Pfad
durchläuft `Studio.load_test_scene()` mit dessen vorhandenem
Ungespeichert-/Validierungsdialog. Fehlendes Embedded-Studio
wird nicht als Erfolg gemeldet. Neuer Regressionstest:
`test_legacy_sandbox_compatibility_cannot_launch_second_window`:
**BESTANDEN**. Der eigenständig aufrufbare historische
`tools/sandkasten.py`-Entwicklertest wird nicht als
Suite-Komponente freigegeben.

**SBX-ARM-01 – versteckte Aktionen nach Ansichtswechsel:**
Beim Verlassen des isometrischen Testfelds blieb
`board._placing` vormerkbar; ein späterer Klick konnte
ungewollt einen Sprite-Eintrag erzeugen. Ebenso konnte der
`SpriteAnimationPanel`-Timer im Hintergrund weiterlaufen.
Diesen Fehler reproduzierte der neue Test **vor der Korrektur**.
`SandboxStudio._tab_changed` stoppt jetzt bei Wechsel zu einer
anderen Arbeitsfläche die Testfeld-Platzierung und die visuelle
Frame-Animation. Beim Verlassen der nativen Karte wird dessen
Platzierungsmodus beendet. Der reine Wechsel zwischen
Spiel- und Expertenmodus *innerhalb derselben nativen Karte*
bewahrt einen bewusst vorgemerkten Spriteauftrag.
Beide zusätzlichen Tests nach Korrektur: **BESTANDEN**.

**SBX-INSPECT-01 – falscher Inspector neben dem Testfeld:**
Im tatsächlichen Windows-Hauptfenster bei 1020×680 und
1500×930 erschien nach der Auswahl von `Testfeld`
rechts weiterhin der `Karten-Inspector` der anderen
Originalkartenarbeitsfläche. Vorherbild:
`work/reports/ui-audit/sandbox-all-surfaces-testfeld-1020x680.png`
aus dem ersten Vier-Ansichten-Bildtest; der neue Qt-Test
reproduzierte die falsche `_selected_right`-Identität.
Die Modussteuerung schaltet nun auf `Objekt-Inspector`
für die isometrische Szene und auf `Karten-Inspector`
für Radar, Raw-Daten und native Karte. Bewusst
gewählte Spezialwerkzeuge (z. B. Animation im Testfeld)
bleiben innerhalb ihres Bereichs bestehen.
Der Qt-Test und 11 vorhandene kompakte Layouttests:
**12 BESTANDEN**. Die erneute native Bildprüfung bei
1020×680 zeigte den korrekten `Objekt`-Inspector.

**SBX-STATUS-01 – unzutreffende Statuszeile bei Radar:**
Das native Vorherbild
`sandbox-all-surfaces-radar-1020x680.png`
zeigte die echte Radaransicht, aber weiterhin die alte
Statusmeldung `Isometrisches Testfeld...`. Der Fall
`index=0` fehlte in `_tab_changed` vollständig.
Die Statuszeile zeigt nun die tatsächliche Radarquelle,
Bildgröße und den nur lesenden Charakter bzw. den Zustand
`Keine Karte geladen`. Deutsch/Englisch wird ohne
Kartendatenänderung neu berechnet. Zwei gezielte Tests
für leere bzw. echte Originalkarte: **BESTANDEN**.

**Neue native Vier-Arbeitsflächen-Prüfung:**
`tools/qa_suite_embedded.py` wechselt an drei
Hauptfenstergrößen (1020×680, 1320×800, 1500×930)
zwischen `Testfeld`, `Radar`, `Kacheldaten`
und `Spielkarte`. Geprüft werden reale Tk/Win32-Elternschaft,
sichtbare und sinnvolle Widgetgeometrie, passende
aktuelle Werkzeug-Identität, gemeinsame Karten-/Szenen-History
und kein überlagerndes Spiel-HUD im Editor.
12 QA-Screenshots stehen unter
`work/reports/ui-audit/sandbox-all-surfaces-*-<breite>x<hoehe>.png`.
`NATIVE_FOUR_WORKSPACES_PASS` wurde für alle drei Größen
nach der Werkzeugkorrektur erneut bestätigt. **Diese
Tests beweisen geometrische und funktionale Teilaufgaben,
nicht eine perfekte Pixel-/Spieltreue.**

Der anfängliche JUnit-Lauf `sandbox-full-after-fixes-20261021.xml`
wurde unabhängig ausgewertet: **735 Tests, 0 Fehler,
0 Ausnahmen, 0 Übersprungene** in 1186,732 Sekunden.
Diese Zahl war der vollständige Stand **vor den fünf
zusätzlichen Sicherheits-/Usability-Korrekturen**.
Nach ihnen läuft der gesonderte Endlauf
`sandbox-full-system-regression-20261021.xml` samt Log.
Die Testergebnisse dürfen erst nach dessen Abschluss auf
den neuen Codezustand übertragen werden.

**Noch ausdrücklich offen:** Die historische Engine-
und Shaderparität, Original-Bink-/Beraterzustände,
die vollständige Juni-Pipeline, echte Langzeit-DPI-
und Screenreader-Prüfung, vollständige Pixeleditor-/
Export-/Installations-Realeingaben und
unabhängige Freigabe des Gesamtsystems.


### Zusatzprüfung nach dem zweiten Gesamtlauf – 21.10.2026

**Neue Auswertung mit tatsächlichen JUnit-Testidentitäten:**
Der vollständig abgeschlossene Lauf
`work/reports/ui-audit/sandbox-full-system-regression-20261021.xml`
enthielt **742 Tests, 739 bestanden, 3 fehlgeschlagen**. Die drei
Failures waren die beiden alten Inspector-Erwartungen
`test_editor_tab_navigation_cannot_leave_hidden_tab_bar_and_map_hud`
und `test_editor_dock_focus_and_selection_restore_without_cloning_scene`
sowie die Radar-Status-Testannahme
`test_status_bar_and_compact_tab_labels_are_truly_bilingual`.
**Alle zehn Tests `test_radar_diamond_roundtrip` waren laut JUnit
bestanden.** Eine frühere Zuordnung des Fortschrittszeichens „F“
zum Radar war falsch und ist hiermit ausdrücklich korrigiert.

Die Tests sichern nach den bestätigten Bedienkorrekturen
`Objekt-Inspector` im Testfeld statt des historischen Fehlers
`Karten-Inspector` ab. Der DE/EN-Sprachwechsel des Radars
erhält vorhandene, beliebig gesetzte Statuszeilen, während
die neue originale Radarstatuszeile dynamisch übersetzbar bleibt.
**15 gezielte Tests bestanden**, einschließlich realer
Radar-Koordinaten und Status-/Inspector-Rückwege.

**SBX-START-01 – unzuverlässiges erstes Öffnen:**
Ein nativer Tk-/Qt-Gesamttest scheiterte zunächst am
10-Sekunden-Start-Checkpoint, **bevor** die eigentlichen
Sandbox-Prüfungen begannen. Die instrumentierte Wiederholung
zeigte `Notebook.select()==Sandbox` bei noch unmapped
`tab.winfo_ismapped()==False` / `host.winfo_ismapped()==False`.
Ein späterer Wiederholungslauf mit demselben Code
bestand vollständig (`QA_PASS`, Exit 0) – das belegte
eine zeit-/layoutabhängige Erstöffnung.
Daher wurde der Startpfad `Universal.open_sandbox_studio()`
korrigiert: vor `ensure_studio()` wird die ausstehende
Tk-Layoutberechnung verarbeitet. `SandboxTab.ensure_studio()`
prüft den bereits ausgewählten Host erneut nach dem
Idle-Layoutpass, bevor es einen verzögerten Retry einplant.
Ein neuer Test mit einem **wirklichen Tk-Notebook** bestätigt,
dass die Host-Seite vor Erzeugung des nativen Kindes
gemappt ist. **4 gezielte Start-/Kompatibilitäts- und
Speicher-Routingtests bestanden**.

Mit der Startkorrektur meldete die echte Windows-Suite
erneut **QA_PASS**, Exit 0, Runtime 117,73 Sekunden.
Der instrumentierte `SANDBOX_INITIAL_OPEN_STATE`
belegt beim ersten Öffnungsvorgang `tab_mapped=True`,
`host_mapped=True`, `bridge=True`.
Alle vier Arbeitsansichten mit drei Fenstergrößen,
Herkunftsgrafiken, Navigation, Rahmen, Katalog,
Sicherheits-Gates, Test-BC7- und Qt-Close-Rückweg
wurden im nativen Tk-/Win32-Hauptfenster durchlaufen.
Dies ist ein überprüfter Startlauf, **keine** Langzeit-
oder Cold-Start-Statistik.

**SBX-PIXEL-01 – bislang fehlender GUI-End-to-End-Nachweis:**
Neuer `tests/sandbox/test_pixel_editor_integration.py`
öffnet den realen Qt-Pixeleditor aus dem **Testfeld**
mit einem isolierten 12×12-Testframe. Benutzeraktionen:
Mausmalen, Undo, Redo, Save in `tmp_path`,
geschützte Quelldatei (SHA-256), Abbruch eines weiteren
nicht gespeicherten Strichs, Bestätigung des bewussten
Verwerfens und Dialoglebenszyklus. Ein zweiter Test
prüft den Ansichtswechsel ohne verstecktes Speichern.
Zusammen mit den bisherigen Pixel- und Live-Reload-
Tests: **10 bestanden**. Kein installiertes Spielasset,
kein veröffentlichter Atlas und kein echtes Nutzer-
Arbeits-PNG wurde für diesen Test bearbeitet.

**Quellen-/Schreibschutz-Audit:**
Die offensichtlichen lokalen Schreibstellen
`sandbox_pixel_editor.py` und
`sandbox_engine_assets.py` wurden anhand der
Dateioperationen inventarisiert. Die Editor-PNG-
Speicherung arbeitet mit temporärer Datei und
`os.replace()` auf die **Arbeitskopie**; die
Engine-Originalpixel bleiben im Original-Only-Modus
lesend. Auch die Szenen- und Overlay-Save-Aktionen
verwenden unterschiedliche Ziele.
**Noch offen:** eine vollständig instrumentierte
Dateisystem-Berechtigungs- und Negativeingabeprüfung
für *alle* Projekt-, Import-, Export- und Sidecar-Pfade.

**Regressionsstand für das neuere Codepaket:**
`work/reports/ui-audit/sandbox-full-system-postfix-20261021.log`
und `sandbox-full-system-postfix-20261021.xml`
sind die vorgesehenen Endbelege eines anschließend
neu gestarteten vollständigen Testlaufs. Dessen Ergebnis
ist **erst nach abgeschlossenem Exit/JUnit** als
nachgewiesener Stand zu behandeln.

**Gesamtfreigabe bleibt NEIN**: ursprüngliche
Shader-/Engine-/Animationen-/Berater-Parität und die
historische Juni-Werkzeugpipeline sind unabhängig
von diesen integrativen UI-Korrekturen zu belegen.


## Headless-Fortsetzung – 21.10.2026, ab 23:15 Uhr

**Nutzeranweisung:** Ohne sichtbare GUI-Interaktion fortarbeiten.
Seit dieser Anweisung wurden **keine neuen Tk-Fenster oder interaktiven
Windows-Desktopaktionen gestartet**. Die Modellprüfungen laufen
ausschließlich via Python/PowerShell mit
`QT_QPA_PLATFORM=offscreen`; es gab weder Spiel-/Release-/Installations-
noch Atlas-Exportaktionen.

### Bestätigte neue Datenverlust- und Validierungsfehler

**SBX-SAVE-02 (P0, im Modell korrigiert):**
Sowohl `save_scene` als auch `save_overlay` akzeptierten bisher
jedes beliebige `.json`-Speicherziel. Ein bereits existierendes
Suite-Settings-JSON oder ein fremder Katalogindex konnte dadurch
**ohne Typprüfung überschrieben werden**. Der Fehler wurde vor
der Korrektur in einem reinen Modelltest reproduziert.
Die Speicherroutinen akzeptieren weiterhin neue beliebig benannte
`.json`-Ziele, ersetzen bestehende Dateien aber **nur dann**,
wenn sie gültige JSON-Daten **des richtigen Sandbox-Typs** enthalten.
Beim Overlay müssen darüber hinaus Quellkartenname **und**
Originalkarten-SHA-256 übereinstimmen.
Fremde, beschädigte oder auf eine andere Karte zeigende Dateien,
Symlink-Ziele und unpassende Erweiterungen werden abgelehnt;
bestehende Inhalte bleiben erhalten. Die atomischen
temporären Schreibvorgänge bleiben unverändert.

**SBX-SCHEMA-01 (P1, im Modell korrigiert):**
`EditableScene.deserialize` und `NativeOverlay.deserialize`
ließen bisher unbekannte zukünftige JSON-Kopffelder ohne Fehler
fallen. Ein anschließender Speicherlauf entfernte diese
Informationen **dauerhaft**. Beide Datentypen verweigern nun
solche unbekannten Felder, anstatt sie stillschweigend zu
verwerfen. Listen über **10.000 Elemente** werden schon vor
der Objektkonstruktion abgewiesen; Spritegruppennamen sind
auf 256 Zeichen begrenzt.

**SBX-TYPE-01 (P1, im Modell korrigiert):**
Python behandelt `True`/`False` als `int`; daher konnten
boolesche JSON-Werte in Frame-/Kachel- und Szenengrößenfelder
gelangen. Strenge `type(value) is int`-Kontrollen
in `SpritePlacement`, `EditableScene`,
`NativeOverlay` sowie der gemeinsamen
`map_sections.tile_index`-Funktion schließen dies nun aus.
Ein Vollbereichstest durchlief **alle 320.800 originalen
Diamantkachelpositionen** und bestätigte ihre eindeutigen,
lückenlosen Indexzuordnungen.

**SBX-SAVE-03 (Sicherheits-Negativtest):**
Mit künstlich verweigertem `os.replace` wurde geprüft, dass
bei einem Scheitern des atomaren Speicherschritts sowohl eine
existierende Szene als auch eine existierende Overlay-Datei
**byteidentisch** bleiben. Die ursprünglichen
Fake-`.map`-Bytes bleiben ebenfalls unverändert, und
temporäre Dateien werden im Abbruchpfad gelöscht.

### Wiederholbarer Headless-Regressionslauf

Neuer lokaler Startbefehl:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/qa_sandbox_headless.ps1
```

Der Starter wählt **19 konkrete Daten-/Mapping-Testmodule**,
verweigert Tk-basierte Tests und erzwingt den unsichtbaren
Qt-Backendmodus `offscreen`. Es wird keine echte GUI
angezeigt. Testumfang: Kartenformate, Originalkarten-Laufzeit,
Radar/Projektion, Terrain, Oberflächen und Layer,
Originalobjekte/Keystarts, visuelle Zuordnungen,
Import, BC7-Cache, Szenen-/Overlay-Modelle, Schreibzielschutz,
unbekannte Payloads, atomare Fehlerpfade und den vollständigen
nativen Kachelindex.

**Ergebnis (neuer aktueller Modellstand): 210 bestanden,
0 fehlgeschlagen, 0 übersprungen** in 32,48 Sekunden.
Exit 0.

- JUnit: `work/reports/ui-audit/sandbox-headless-system-20261021.xml`.
- Textlog: `work/reports/ui-audit/sandbox-headless-system-20261021.log`.
- Maschinenlesbarer Integritätsbericht:
  `work/reports/ui-audit/sandbox-headless-integrity-proof-20261021.json`.
- Prüfgenerator (nur lokal): `work/qa_sandbox_headless_integrity_summary_20261021.py`.

Der Beleggenerator prüfte die Dateihashes von drei realen
Originalspiel-Dateien (installierte
`globalgamemanagers.assets`, `Antioch.map`,
`Crusader Demo.map`) gegen bereits frühere unabhängig
aufgezeichnete Prüfwerte: **alle unverändert**.
Git-HEAD blieb **`00276ec`**; bestehende lokale
uncommittete Änderungen wurden nicht pauschal
zurückgesetzt oder eingecheckt.

### Wichtige nicht erledigte Gesamt-Abnahmepunkte

**SBX-TK-LONG-01 (P1, OFFEN):** Das vor dieser Headless-Phase
ausgeführte read-only Werkzeug
`work/qa_suite_repeated_roots_20261021.py`
bestätigte **20 vollständige Suite-Start-/Schließzyklen**
ohne Absturz. Windows-GDI-Handles stiegen dabei jedoch
von **29 auf 87** (Delta +58). Das ist ein objektiver
Hinweis auf nicht vollständig freigegebene Windows-Ressourcen,
nicht der nachgewiesene Entstehungsort eines Lecks.
Eine unabhängige Gegenprobe mit **80 nackten Tk-Roots**
lief erfolgreich. Die Ursache und Langzeitfolgen bleiben
offen. Wegen der expliziten Headless-Anweisung wurden
diese Fensterprüfungen **nicht** erneut gestartet.

**TK-TEST-ISOLATION (OFFEN):** Der letzte komplette
gemischte GUI-/Sandbox-Testlauf hatte **745 Testfälle:
743 bestanden, 2 Tcl/Tk-Skips**. Die beiden
übersprungenen Tests bestehen einzeln beziehungsweise mit
vor Python-Start gesetzten korrekten Tcl-/Tk-Pfaden.
Ein größerer GUI-Testlauf meldete dennoch nach
42 bestandenen Sitzungen einen Tcl/Tk-Fehler.
Solange die Ursache nicht isoliert ist, darf die
komplette gemischte GUI-Suite **nicht** als 745/745 grün
ausgegeben werden. Die reine Headless-Modellsuite
ersetzt diese Prüfung ausdrücklich nicht.

**HUD-01/MAP-01/PIPE-01 (P0):** Originalspiel-
Berater/Video-/Zeit-Zustandsmaschine,
Shader-/Kamera-/Wasser- und Echtzeitparität
sowie die vollständige historische Juni-Pipeline
bleiben ohne echte Gesamtabnahme.

**Freigabe der GESAMTEN Sandbox: weiterhin NEIN.**
Die nachweislich geprüften Modellfunktionen sind
weiter abgesichert, aber GUIs, Performance,
historische Workflows und originale Spieltreue sind
eigenständig offen.


### Abschluss der erweiterten headless-Daten- und Qt-Offscreen-Prüfung

**Weitere bestätigte, im Datenmodell korrigierte Datenverlustpfade
SBX-SAVE-04 (P0 im Modell korrigiert):** Die ursprünglich für
`scene_model.save_scene` und `native_overlay.save_overlay`
reproduzierte Gefahr, fremde bestehende `.json`-Dateien ohne
Typprüfung zu überschreiben, bestand **auch** in vier weiteren
Speicherwegen der Sandbox:

- `native_visual_mapping.save_mappings` – bestätigte Sprite-Grafikzuordnungen.
- `native_terrain_mapping.save_terrain_tests` – Rohkanal-3005-Tests.
- `native_surface_mapping.save_surface_tests` – Rohkanal-3037-Tests,
  die denselben gesicherten Terrain-Schreibpfad verwenden.
- `hud_command_bindings.save_bindings` – manuelle XAML-Befehlsbindungen.

Der Headless-Test
`tests/sandbox/test_mapping_save_destination_safety.py`
reproduzierte das ursprüngliche Fehlverhalten **vor**
der Behebung. Neuer, gemeinsamer Schutz
`src/stronghold_europe_de/sandbox/save_target_guard.py`:
Ein bestehendes Ziel wird nur bei gültigem
**passendem Schema, vollständig gültigen Nutzdaten
und – für 3005/3037 – exakt gleicher Originalkarten-SHA-256**
ersetzt. Beschädigte, unbekannte, ungewöhnlich große
oder verknüpfte Ziele werden nicht überschrieben.
Unerwartete zukünftige JSON-Kopffelder werden nicht
stillschweigend verworfen; `SurfaceTestMappings`
behandelt `section=3037` separat, bevor der
gemeinsame 3005-Validator aufgerufen wird.

**Negativeingaben:** Die Tests prüfen fremde Settings-JSONs,
beschädigte Dateien, unbekannte Header, andere Karten-
SHA-Versionen, gültiges erneutes Speichern,
verbotene `.map`-Endungen, wo vom Dateisystem erlaubt
symbolische Links sowie künstlich blockiertes
`os.replace`. Bei Schreibfehler bleibt die
bisherige Datei byteidentisch und es bleibt
keine temporäre Restdatei zurück.
Die nachfolgenden gezielten Modelldateien ergaben
**85 bestanden** (inklusive der älteren Mapping-/HUD-Tests).
Ein ergänzender Lauf mit weiteren Atomizitäts- und
Symlinkfällen ergab **56 bestanden**.

**Reproduzierbarer finaler Headless-Teststarter:**

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools/qa_sandbox_headless.ps1
```

Die endgültige, explizit ausgewählte Liste enthält
nun **28 Testmodule**: die Karten-/Szenen-/Originaldaten-
und Speichermodelle sowie die UI-Workflows in
`QT_QPA_PLATFORM=offscreen` für den echten
`NativeMapCanvas`, Sprite-Testfeld, Editor, Animation,
Pixel-Undo/Redo, Katalog-/Moduswechsel und verifizierte HUD-Art.
Tk-Imports bzw. `Tk()`-Aufrufe in diesen Testmodulen
werden bereits vom Teststarter abgewiesen.
Es wurden in dieser Headless-Phase **keine sichtbaren
Windows-/Tk-Fenster gestartet**.

**Abschließender aktueller Lauf: 300 bestanden,
0 fehlgeschlagen, 0 übersprungen**, Exit 0,
197,24 Sekunden.

Belege:
- `work/reports/ui-audit/sandbox-headless-system-20261021.xml`
  – vollständiges JUnit mit 300 Testfällen.
- `work/reports/ui-audit/sandbox-headless-system-20261021.log`
  – Textprotokoll mit 0 fehlgeschlagenen Tests.
- `work/reports/ui-audit/sandbox-headless-integrity-proof-20261021.json`
  – erneute unabhängige JUnit-Auswertung, Git-HEAD,
  Umfang/Skips und Originalprüfsummen.
- `tools/qa_sandbox_headless.ps1` –
  wiederholbarer Starter ohne interaktive Fenster.

Der Integritätsbericht vergleicht die SHA-256-Werte
von **drei unveränderten Originaldateien**
(`Antioch.map`, `Crusader Demo.map`,
`globalgamemanagers.assets`) mit ihren zuvor
gesicherten Baselines. **Alle drei stimmen überein.**
Branch `feature/sandbox-studio`, HEAD
unverändert `00276ec`; unfertige Git-Dateien
wurden nicht zurückgesetzt oder pauschal eingecheckt.
Es gab keine Build-/Release-/Mod-Installationsaktionen.

**WICHTIGE GRENZE:** 300/300 gilt ausdrücklich nur
für die 28 spezifizierten Headless-/Qt-Offscreen-Module,
**nicht** für den letzten vollständigen 745-Testfall-
Bestand einschließlich nativer Tk-Suite. Die beiden
dortigen Tcl/Tk-Skips, der gemessene GDI-Handle-Anstieg
um 58 über 20 reale Starts, Windows-DPI/Screenreader,
Original-Simulation und der historische Juni-
Produktionsworkflow bleiben offene Abnahmeaufträge.

**Gesamte Sandbox: WEITERHIN NICHT FREIGEGEBEN.**


## Zusatzprüfung 22.10.2026 – FACHLICHE Originalwerkzeug-Parität (headless)

Der Wunsch nach vollständiger Werkzeug-Korrektheit wurde nicht auf
HUD/UI-Optik reduziert. **Verbindliche Detailmatrix**:
`docs/SPRITESUITE_ORIGINALTOOLS_FACHABGLEICH_2026-10-22.md`.

**Tatsächlich geprüfte Quellen und Outputs:** 108 historische
Executable-Dateien inventarisiert (74 byteidentisch, 6 geändert,
28 nicht im aktuellen tools/, 42 neue Tools), 13 identische
getestete CLI-Hilfe-/Optionsverträge, 216 Original-vs.-Neu-RGBA-/
Pivot-/Frame-/Pfad-/ORA-Testfälle, 8 abgefangene
Original-vs.-Neu-Pipeline-Fehlerwege. Die neue Suite
verbessert die ursprüngliche Falschmeldung beim
nicht-strengen Build mit gescheiterter Endvalidierung
(Original Exit 0, neue Suite Exit 23).

Der Fachvergleich prüfte 135.352 gemeinsame Sprite-IDs
beider Mapping-Dokumente (2.7 vs. 2.80):
**0 geänderte Quellmetadaten, 0 Transformationsregeln,
0 Ersetzungsaktionen, 0 geänderte Ziel-Pivots**.
2 neue anim_drawbridge-Frames und erwartete
Versionsänderungen von 100.112 Ziel-path_ids
sowie Zielatlas-X/Y-Positionen.
Die zugehörigen echten Spielinstallationen und
die gemeinsame Stronghold-1-Quelle wurden mit
**15 von 15 vollständigen SHA-256-Quelldatei-Hashes**
gegen `config/supported-builds.json` nachgewiesen.
Dies ist ein echter Datenvertrag, **kein Pixel-/Ingame-
oder fertiger Build-Vergleich**.

**Headless-Endlauf nach Erweiterung auf 61 Module:**
`623 passed, 0 skipped, 0 failed`, Exitcode 0,
Laufzeit 445,59 Sekunden. Die 623 JUnit-Testfälle
wurden separat auf Fehler/Skips kontrolliert:
`work/reports/ui-audit/sandbox-headless-combined-20261022.xml`
und `sandbox-headless-original-tools-20261022.log`.
Die Tests sind im Gegensatz zum früheren Tk-Mischlauf
ohne native Desktopfenster reproduzierbar.

**Noch tatsächlich NICHT korrekt/vollständig:**
1. **P0 TARGET/CONFIG:** Die aktuelle Suite hat keine
   `config/ziele.json` und
   `config/installations.local.toml`.
   Das identisch erhaltene Tool `ziel_se211.py`
   meldet 0 statt historisch 2 Ziele; `e-27`
   wird sicher abgewiesen. Das historische Ziel war
   2.7, das aktuelle Mapping gehört zu 2.80.
   Weder ein Zielwechsel noch eine Installation wurde
   eigenmächtig vorgenommen.
2. **P0 SBX-V1:** Die alten Szenen
   `beispieldorf.json` und `katalog-vorschau.json`
   enthalten originalen prozeduralen Boden, GM1-
   Kompositobjekte und animierte Frames (680/681
   sichtbare Referenzen). Die neuere V2-Szene kann
   diese Inhalte noch nicht verlustfrei laden/bearbeiten.
   Explizite Ablehnung vor Datenverlust ist geprüft,
   aber keine fertige Migration.
3. **P0 Pipeline/Ingame:** 28 frühere Spezialprüfer
   nicht sämtlich als gleichwertig ersetzt belegt,
   historische Juni-Baseline nicht vorhanden;
   echte Originalspiel-Shader, Animationen, Gameplay-
   HUD-Zustände sowie vollständige BC7-Build-/Output-
   und Installations-Hashes weiter offen.

**Gesamtstatus bleibt: NICHT FREIGEGEBEN.**
Weder Original-`.map`/Unity/XAML-Dateien noch
installierte Spielstände wurden in diesem Durchgang
geschrieben; Git-HEAD `00276ec` bleibt erhalten.


## Fortsetzung am 22.10.2026 – vollständiger erweiterter UI-/Originaltool-Headless-Lauf

**Ausgangspunkt:** Der unmittelbar vorangegangene 61-Modul-Lauf war
**624 bestanden, 1 fehlgeschlagen, 0 übersprungen**.
Die einzige fehlgeschlagene Prüfung
`test_qt_language_accessibility.py::test_qt_file_menu_tabs_hud_combo_and_accessible_names_roundtrip`
nahm für F5 nach DE→EN→DE→EN eine konstante Beschriftung an.
Tatsächlich ist F5 nun absichtlich **arbeitsflächenabhängig**:
Radar zeigt `Kartenansicht neu laden` / `Reload original map`,
das Testfeld `Sprite-Grafiken neu laden` / `Reload test sprites`.
Der Test wurde auf unveränderliche QAction-Identität,
Shortcuts sowie fachlich richtige, reversible DE/EN-Beschriftungen
der sichtbaren Arbeitsfläche korrigiert. Es wurde nicht die
korrekte F5-Routenlogik zurückgenommen.

**Gezielter Kontrolllauf:** 26 bestanden, 0 Fehler.
Die drei neuen offscreen-sicheren Module
`test_original_gui_command_parity.py`,
`test_studio_action_wiring.py` und
`test_sandbox_png_export.py` sind dauerhaft in die
zusätzliche Headless-Liste aufgenommen.
Der Systemstarter erzwingt jetzt genau **64 eindeutig gelistete Module**
und schreibt in ein neues XML, sodass das frühere
Fehlerergebnis als Beleg erhalten bleibt.

**Vollständige Wiederholung:** **642 bestanden, 0 fehlgeschlagen,
0 Fehler, 0 übersprungen, Exit 0** in 356,59 Sekunden.
Keine Tk-/Win32-Fenster wurden gestartet; Qt lief offscreen.
Anschließend wurde die JUnit-Datei **unabhängig** überprüft:
642 einzelne `testcase`-Elemente, dieselben JUnit-Gesamtzahlen,
exakt dieselben 64 Modulnamen wie in den beiden Testlisten.
Erneut wurde Git-HEAD `00276ec` nachgewiesen.
Alle **drei** früher dokumentierten Spielquellen-Prüfsummen
(2 Originalkarten und `globalgamemanagers.assets`) stimmen
nach dem Lauf weiterhin bytegenau mit der Referenz überein.

**Maschinenlesbare Belege:**

- `work/reports/ui-audit/sandbox-headless-wiring-64modules-20261022.xml` – JUnit
- `work/reports/ui-audit/sandbox-headless-wiring-64modules-20261022.log` – Konsolenlauf
- `work/reports/ui-audit/sandbox-headless-wiring-proof-20261022.json` – unabhängige Zählung/64-Module- und 3-Quellhash-Prüfung
- `work/qa_verify_ui_wiring_20261022.py` – reproduzierbarer Verifizierer

**Einschränkung:** Die 642 Tests sind eine **reproduzierbar grüne
Modell-/Qt-Offscreen-Teilabnahme**. Sie ersetzen weder den vollständigen
Tk-/Windows-GUI-Langlauf noch die offenen P0-Blöcke:
verlustfreie V1-Szenenbearbeitung, freigegebenes versionsgebundenes
Produktionsziel, reale Original-/BC7-/Ingame-Buildparität,
Shader-/Gameplay-/HUD-Zustandsabgleich sowie DPI, Screenreader und
Tcl/Tk-/GDI-Ressourcenprüfung. **Gesamtfreigabe: weiterhin NEIN.**

## Community-Mod-Kompatibilität – Abgleich 22.10.2026

Verbindlicher Detailnachweis: `docs/SPRITESUITE_COMMUNITY_MOD_KOMPATIBILITAET_2026-10-22.md`. Die komplette weitergeführte 67-Modul-Qt-/Headless-Regression wurde nach Korrektur eines nativen V1-Auswahl-Reentranzfehlers **677/677 bestanden**, Exitcode 0, 0 Skips. JUnit und unabhängiger Proof liegen unter `work/reports/ui-audit/sandbox-headless-community-67modules-qt-stable-20261022.xml` und `shcde-community-integrity-proof-qt-stable-20261022.json`.

**Getrennte Community-Freigabe: NEIN.** Das vorhandene QA-Spiel hat SE 1.44.0, die Suite-Quellpins fordern 2.11.0, das ausgelieferte Runtime-Audio-Profil belegt 1.44.0.0 und APIShared 0.9.2 fordert SE >=2.14.0. Auflistung/Originalspiel-Dateien wurden nur gelesen. Ein isolierter, SHA-gepinnter Neubau plus reale APIShared-/Fixes-/Tweaker-/Serpens-Ingame-Kombinationsprüfung ist vor jeder Freigabe notwendig. Die gezielte Regression bestätigt Schutz und Fehlererkennung, **keine** originale gemeinsame Gameplay-ABI.
