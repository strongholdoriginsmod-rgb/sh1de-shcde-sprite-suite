# Sprite Suite – UI- und Pipeline-Wahrheitsprüfung, 14.10.2026

**Prüfurteil: Originaltreue der Gesamtanwendung NICHT NACHGEWIESEN.**
Ein technischer Funktionstest beweist weder korrekte Gestaltung noch
Spielverhalten noch eine identische historische Produktionspipeline.

## 1. Was wirklich verglichen wurde

Projekt: E:/SpriteSuite, Branch feature/sandbox-studio.
Vergleichsstände: E:/SU_base, E:/SS QA,
E:/GS/StrongholdEurope-Projekt und E:/SU_pub/main.
Alle Vergleiche erfolgten lesend anhand SHA-256 der jeweiligen Werkzeugdatei.

| Älterer tools-Bestand | Dateien | byteidentisch | verändert | fehlt im aktiven tools |
| --- | ---: | ---: | ---: | ---: |
| SU_base | 82 | 50 | 11 | 21 |
| SS QA | 83 | 59 | 6 | 18 |
| GS Europe | 74 | 45 | 14 | 15 |
| SU_pub/main | 77 | 71 | 6 | 0 |

Unter anderem tile_objects.py, ui_atlas.py, unit_pipeline.py und
backgrounds.py sind weiterhin byteidentisch. Spezielle frühere Build-,
Installations-, Full152-, Speicher- und DLL-Prüfwerkzeuge fehlen teilweise.
Das ist nicht automatisch ein Fehler: manche dürfen wegen Versionspins
gerade NICHT als beliebig startbare Standardfunktionen eingebaut werden.

Alle sieben explizit im derzeitigen suite_universal.pyw mit statischen
tool-Namen erkannten Kommandoziele existieren. Deren Parameter,
Abbruch-/Ausgabeverhalten sowie dynamische Aufrufe sind damit NICHT geprüft.
Diese Referenzen stammen überwiegend aus August und September 2026;
ein vollständig belegter Juni-Originalworkflow konnte bisher nicht
ermittelt werden. Weder Skripthash noch Testpass garantieren dieselben
Buildausgaben unter anderer Unity-/SE-/Spielversion.

Maschinenlesbare Einzeldateien:
E:/SpriteSuite/work/reports/ui-audit/historic-tool-comparison.json.

## 2. Sichtbare Sandbox: klare Regression beim Spielgefühl

Historisches Bild: E:/SU_merge/gui_sandkasten.png.
Neue Vergleichsbilder:
E:/SpriteSuite/work/suite_embedded_sandbox_qa.png,
E:/SpriteSuite/work/sandbox_compact_hud_workflow.png,
E:/SpriteSuite/work/sandbox_compact_hud_display.png und
E:/SpriteSuite/work/sandbox_compact_hud_gallery.png.

Die frühere Sandbox hat eine zusammenhängende isometrische Testwelt,
unten ein Spiel-HUD mit Baumenü, Berater, Ressourcen und Minikarte.
Sie ist deshalb visuell näher an der gewünschten Stronghold-Ansicht.
Das ist KEIN Beweis für korrekte Engine-Simulation.

Der neue Qt-Kern rendert echte Originalkarten und Engine-Spritekommandos,
aber die eigentliche Spielleiste wurde durch Qt-Inspector-Formulare und
eine rechtsstehende Icon-Galerie ersetzt. Damit gingen die visuelle
Zusammengehörigkeit und die vertraute Bedienung verloren. Die
Original-XAML-Iconstudie ist nicht dasselbe wie das Original-Gameplay-HUD.
Das derzeitige manifestierte HUD bezeichnet sich auch selbst als
teilrekonstruiert und verwendet lokale, abgeleitete Europa-Overrides,
keinen vollständig unveränderten Original-Unity-HUD-Atlas.

Tatsächliche gemessene QA-Geometrie: Bei einem Windows-Hauptfenster
1500×930 ist das Qt-Fenster etwa 1168×542, die Kartenfläche 872×451.
Bei 1020×680 sind es etwa 784×342 und nur 505×251 Kartenpixel.
Die technisch bestandene Mindestgrößenprüfung genügt deshalb
nicht als visuelle oder praktische Spielmodus-Abnahme.

Lokaler Vorher/Nachher-Nachweis:
E:/SpriteSuite/work/reports/ui-audit/sandbox-visual-regression.png.

## 3. Wiedergefundene Original-Spiel-HUD-Referenz

E:/SU/projekt/sandbox/hud/hud.png und hud.json sind noch vorhanden.
Die Metadaten nennen Original-Spielbilder in 2560×1440 vom
04./05.09.2026; alle vier Originaldateien existieren auf D: unter
Stronghold Crusader Definitive Edition COPY/Fehlerberichte/gepackt.
Diese Quelle ist eine echte visuelle HUD-Referenz. Sie wurde im
älteren tools/sandkasten.py als teilweise statisches HUD-Bild
komponiert. Die heutige Sprite Suite enthält nicht automatisch
diese lokale private HUD-Datei.

Die Quellbilder sollten für einen reproduzierbaren Test von
HUD-Positionen, Proportionen, UI-Zuständen, Clipping und Minikarte
benutzt werden. Ein bloß drübergelegtes Bild ist KEINE vollständige
interaktive Spieloberfläche.

Lokale verkleinerte Prüfvorschau:
E:/SpriteSuite/work/reports/ui-audit/gameplay_reference_2026-09-05_review.jpg.

## 4. Aktuelle Tests und was sie NICHT abdecken

28 gezielte Tests zu kompaktem HUD, XAML-Komposition,
Runner-Sicherheit und nativen Kachelgrenzen bestanden.
tools/qa_suite_embedded.py meldete QA_PASS und prüfte
1500×930 / 1020×680, Qt/Tk-Elternschaft, Workspace- und
Inspector-Geometrie und Navigationsaktionen.
tools/qa_suite_guided_home.py meldete HOME_QA_PASS für
14 Startaktionen und zwei Bildschirmgrößen auf DE und EN.

Die Tests beweisen NICHT dieselben HUD-Pixel, aktive Spielzustände,
vollständige Benutzeraufgaben oder ursprüngliche Unity-Shader.
Ein neuer vollständiger Regressionstest aller derzeit UNCOMMITTETEN
Änderungen ist hier nicht als bestanden behauptet worden.

## 5. Abnahmeblocker (priorisiert)

| ID | Stufe | Problem | Abschluss nur nach |
| --- | --- | --- | --- |
| HUD-01 | P0 | Spiel-HUD unten fehlt als zusammenhängende, dynamische Bedienfläche | Original-HUD-Lage, Layer, Baukategorien, Zustände, Klickregionen, Ressourcen/Minikarte bei echter Originalkarte geprüft |
| HUD-02 | P0 | Qt-Icon-Galerie ersetzt keine Gameplay-HUD-Funktion | Teilrekonstruktion klar benannt, echter Spielmodus getrennt vom Qt-Werkzeugmodus |
| MAP-01 | P0 | Engine-Snapshot ist pausiert, Shader, Wasser/Wind/Animation sind nicht vollständig rekonstruiert | Gleiche Kamera, Zoom, Auflösung und Zeit/Zustände direkt gegen Original-Spielbilder geprüft |
| PIPE-01 | P0 | Vollständige Identität aller historischen Pipelines und Juni-Baseline unbewiesen | Je Workflow Eingangsdaten, Versionen, CLI-Aktionen, Ausgabemanifest, Fehlerbehandlung und Rückweg gemeinsam geprüft |
| UI-01 | P1 | Mini-Ansicht erlaubt kaum Platz für Spielwelt und HUD | Echte Bedienaufgaben bei 1020×680, 1320×800, 1500×930 + DPI bestehen, nicht bloß Dock-Sichtbarkeit |
| WORK-01 | P1 | Katalog, Editieren, Animieren, Pivot, ORA, BC7, Sandbox, Import/Export nicht voll abgenommen | Derselbe Frame läuft Quelle -> Arbeitskopie -> Test -> Build -> Prüfer -> kontrollierte Freigabe |
| PERF-01 | P1 | Langzeittauglichkeit und Ressourcen unbekannt | Mehrstündige Karten-/Zoom-/Save-/Tab-/Sprite-Wechsel mit Speicher- und Reproduzierbarkeitsprotokoll |
| LANG-01 | P2 | Technische Kommandonamen, kleine Felder und DE/EN-Wörter teils zu eng | Sichtprüfung für Benennungen, Fokus, Tastatur, Abbruch und Erreichbarkeit |

## 6. Verbindliche Reihenfolge

1. Gameplay-Modus mit echtem unteren HUD und klar getrenntem
   Experten-/Editor-Modus konzipieren und mit Original-Spielreferenz
   nachweisen. Der wahre Kartenrenderer soll erhalten bleiben.
2. Original-Spielbild-Paare bei identischer Kamera und Auflösung
   aufnehmen, Abweichungen getrennt für Karte/HUD quantifizieren.
   Fehlende Referenzen sind NICHT GEPRÜFT, nie automatisch GRÜN.
3. Den früheren Arbeitsablauf als Daten- und Tool-Vertrag rekonstruieren:
   Quelle, Frame, Geometrie, Pivot, Maske, BC7, installierte Version
   und Ausgabehash inklusive sicherem Abbruch.
4. Realistische End-to-End-Aufgaben mit Fehler-/Undo-/Reload-Wegen
   abschließen. Erst danach vollständige Systemabnahme.

## 7. Arbeitsstand und Schutz

Der aktive Branch enthielt bei der Prüfung zahlreiche noch nicht
committete Änderungen, darunter die derzeitige Überarbeitung von
Spiel-HUD, XAML-Komposition und Sandbox-Layout. Diese Änderungen
wurden in dieser Analyse nicht zurückgesetzt, bearbeitet oder als
erfolgreich endabgenommen. Die historische Spieleingabe bleibt
read-only. Originalscreenshots/Spielassets bleiben ausschließlich lokal.

**Fazit:** Ein technisch brauchbarer Originalkartenkern existiert,
aber die Gesamtanwendung ist weder als historisch exakte Pipeline
noch als 1:1-Sandbox bewiesen. Das bisherige Erfolgsvokabular war
stellenweise deutlich zu optimistisch.
