# Sprite Suite – vollständige UI-Prüfung und Korrekturrunde

**Datum:** 13. Oktober 2026
**Projekt:** `E:\SpriteSuite`, Branch `feature/sandbox-studio`
**Gegenstand:** Tk-Hauptanwendung, alle Arbeitsbereiche, integrierter Qt-Sandkasten
**Wichtig:** Geprüfte UI-Bedienbarkeit ist nicht gleich vollständige Spielsimulation oder Unity-Shader-Parität.

## Was tatsächlich untersucht wurde

**1. Gesamte Tk-Anwendung:** Die Arbeitsbereiche

`Einrichten`, `Asset-Katalog`, `Diagnose & Reparatur`, `Sandkasten`,
`Editor & Austausch`, `Ziel & SE`, `Paket bauen`, `Werkzeugkatalog`,
`Sprites`, `Start & Anleitung`, `Sprite-Gruppen`, `UI-Fläche`,
`Texte` und `Bauen/Installieren`

wurden bei **1020 × 680** und **1320 × 800 Pixeln** kontrolliert,
einmal in **Deutsch** und einmal in **Englisch**. Das sind
**56 Ansichts-/Größen-/Sprachkombinationen**.

Die automatisierte Prüfung meldete für alle 56 Kombinationen **null
horizontal abgeschnittene sichtbare Eingabefelder oder Schaltflächen**.
Sie betrachtet vertikal nicht sichtbare Bereiche bewusst nicht als
Fehler, sofern dafür Scrollflächen vorhanden sind. Auch ein gutes
Ergebnis beweist nicht, dass alle langen Texte bei jeder DPI-Stufe
optimal lesbar sind.

**2. Echter eingebetteter Qt-Sandkasten:** Im aktuellen Windows-Hauptfenster
wurde über `tools/qa_suite_embedded.py` die ursprüngliche Spielkarte
`Antioch.map` mit nativer Qt-Kindfensterverknüpfung, Palette, Inspector,
Animation, HUD, Canvas-Fokus, Build-Funktionen und sicherer gemeinsamer
Schließlogik aufgerufen. Die Arbeit mit Quellkarten blieb read-only.
Bei Windows-DPI-Skalierung bleiben tatsächliche Host- und Qt-Rechtecke
korrekt zugeordnet. Außerdem wurden die Bedienelemente des Inspectors
auf horizontale Überbreite untersucht.

**3. Übersetzung und Datensicherheit:** Die Qt-Bedienelemente werden nun
separat von der Tk-Sprache und reversibel zwischen Deutsch und Englisch
übersetzt; das Erstellen von Qt-Dialogen während einer Sitzung ist
eingeschlossen. Für den HUD-Kategoriefilter und die Team-Combo-Boxen
werden die maschinenlesbaren Werte konsequent in `itemData` gespeichert,
statt sichtbare englische Anzeigetexte in Szenen/Overlays zu übernehmen.
Der deutsche und englische Wechsel verändert keine Original-GM-ID,
Framezahl, Teamkennung, Overlay-Position oder Karte.

## Konkrete Fehler und Korrekturen

| Problem | Umsetzung / Abnahme |
| --- | --- |
| Ursprüngliche Datei-/Ansichtsbefehle verschwanden beim Einbetten des Qt-Studios | Der kompakte Qt-Toolbar-Umbau hängt die ursprünglichen gemeinsam benutzten `QAction`-Objekte **nur aus der Toolbar aus** (kein `QToolBar.clear()`, das sie zerstören könnte). Datei-Menü, `Ctrl+O`, `Ctrl+S`, `F1`–`F4` bleiben erhalten. |
| Mehrere rechte Docks wurden zu kaum lesbaren Tabs zusammengepresst | Explizite **Werkzeugauswahl**, Funktionen für **Fokus**, **Palette**, **Inspector** und **Layout zurücksetzen**, plus kompakte Werkzeugnamen und scrollbarer Inhalt. |
| Kleine Fenster und DPI konnten die Kartenansicht verdrängen | Die Qt-Kindgröße folgt physischen Win32-Pixeln; interne Qt-Abmessungen werden bei DPI-Skalierung separat verwaltet. Fokus-/Inspector-Bereiche bleiben im Kartenfenster erreichbar. |
| Bedienelemente mit Symbol statt Text waren per Screenreader unklar | Für wichtige Karten-, Sprite-, HUD-, Animations- und Inspector-Steuerelemente wurden explizite **Accessible Names** ergänzt. |
| Kartenklicks waren ohne Maus nicht bedienbar | In der Originalkarte: **Pfeiltasten** bewegen einen nicht gespeicherten Kachelcursor, **Enter** wählt oder platziert in einer editierbaren Overlay-Szene, **Esc** beendet. Nicht bespielbare Randkacheln bleiben gesperrt. |
| Qt-Sandbox blieb nach Wechsel zur englischen Tk-Oberfläche deutsch | Eigene Qt-Übersetzung aus `config/sandbox-qt-sprachen.json`, einschließlich Menüs, Tooltips, Tabs, Dialogen und dynamischen Zählerzeilen. **Sprite-IDs bleiben absichtlich unübersetzt.** |
| Zwei kompakte Kartenreiter und die Qt-Statusleiste blieben im englischen Hauptfenster deutsch | Die reale Windows-Screenshotprüfung identifizierte **„Kacheldaten“**, **„Spielkarte“** und eine deutsche Originalkarten-Statusmeldung. Zusätzliche Qt-Übersetzungen und ein an `QStatusBar.messageChanged` gekoppelter, reversibler Statusübersetzer wurden eingeführt. Auch neu erscheinende Statusmeldungen bleiben zur gewählten Sprache passend. |
| Längere Erklärtexte der Tk-Hauptanwendung blieben englisch oder deutsch | Acht zusätzliche Textpaare wurden in `config/suite-sprachen.json` ergänzt, u. a. Diagnoseleerzustand, Zielspielhinweis, Grafikanweisungen und ein englischsprachiger Sprite-Tool-Hilfetext. |
| Ein Qt-Sprachfilter blieb auch nach Schließen eines Editors an der globalen `QApplication` hängen | Der Sprachfilter ist jetzt nur am lebenden Studio angemeldet: beim Schließen abmelden, beim Wiederöffnen erneut anmelden. Das verhindert, dass verwaiste Editorfenster spätere Dialoge eines anderen Studios übersetzen oder unnötig Ressourcen behalten. |
| Aktuelle Profilzahlen wurden nur statisch auf Deutsch angezeigt | Zahlen wie **149 Gruppen / 76.388 Frames** werden jetzt **dynamisch und reversibel** übersetzt; auch geänderte Zähler nach Aktualisieren bleiben korrekt. |

## Nachweise

- `tests/sandbox/test_sandbox_compact_layout.py`: Dock-Anordnung,
  Menüs, echte Tastaturkürzel und Sprachwechsel;
- `tests/sandbox/test_keyboard_navigation_gui.py`: echte
  Tastaturinteraktion mit Karte/Overlay, Undo und Randbereich;
- `tests/sandbox/test_qt_language_accessibility.py`: Qt/DE/EN,
  Dialoge, Kategorien, Teamwerte, Metadaten, Statusmeldungen,
  globale Qt-Sprachfilter-Lebensdauer und Accessible Names;
- `tests/sandbox/test_tk_dynamic_translation.py`: numerische
  Statuszeilen und lange Anleitungen, mehrfacher DE/EN-Wechsel;
- `tools/qa_suite_embedded.py`: realer Windows-Hauptfenstertest
  über die Bereiche Sandbox, Setup, Build, Diagnose, Katalog usw.;
- `work/qa_all_views_layout.py` und
  `work/qa_all_views_english.py`: die **56** Layout-Messungen;
- `work/qa_embedded_qt_bilingual.py`: der tatsächliche
  Windows-Qt-Sprachwechsel DE/EN/DE/EN.

Screenshots und Berichte liegen unter `work/reports/layout-all-views/`,
`work/reports/layout-all-views-en/` und
`work/reports/embedded-sandbox-*.png`. Dies sind lokale,
Git-ignorierte QS-Artefakte, keine Originalspielgrafikdateien.

## Was bewusst **nicht** als fertig behauptet wird

- **Bedienbarkeit:** Die Hauptoberfläche ist funktionsreich und weiterhin
  informationsdicht. Einige Bereiche verwenden vertikale Scrollflächen;
  die QA prüft Erreichbarkeit, aber nicht jede denkbare Mausfolge.
- **Barrierefreiheit:** Automatisierte Accessible-Name-Tests ersetzen
  weder einen echten Screenreader-Lauf noch Tests mit maximalem
  Schriftgrößen-/Hochkontrastprofil. Diese Punkte bleiben offen.
- **Sprachabdeckung:** Kern- und Werkzeugbedienung sind DE/EN;
  technische Original-GM-IDs, Produktnamen, Pfad-/Toolnamen und manche
  ausführliche Werkzeugsystem-/CLI-Ausgaben bleiben absichtlich
  unverändert. Keine pauschale Vollübersetzung aller Diagnoseberichte.
- **Visuelle Spieltreue:** Der Engine-Snapshot zeichnet echte
  Grafikbefehle, aber laufende Unity-Spezialshader, vollständige
  Simulation und exaktes Gameplay-HUD sind noch keine 1:1-Abnahme.
- **Langzeitnutzung:** Mehrstündige realistische Bearbeitungen,
  unterschiedliche Monitor-/DPI-Konfigurationen und der visuelle
  Nachweis aller ausgeklappten Unterdialoge bleiben weitere Prüfpunkte.

Der **normale Einstieg** bleibt `E:\SpriteSuite\Suite starten.cmd`.
Die Hauptanwendung behält ihren integrierten Sandkasten; es wird kein
zweiter Sandbox-Hauptprozess gestartet.


## Abschlussstand der aktuellen UI-Testschleife

Die gezielte UI-Regression wurde auf diesem Windows-Gerät mit
`26 passed` abgeschlossen (kompakte Qt-Layouts, Tastaturnavigation,
Status und Schriftumschaltung). Zusätzlich meldeten die zwei
realen Windows-Startprüfungen `QA_PASS`: das vollständige
Hauptfenster einschließlich Sandbox-Werkzeugen und der reversible
Qt-Sprachwechsel Deutsch/Englisch.

Der lokale Layoutreport enthält **28 Ansichtsprüfungen je Sprache**
(DE und EN), zusammen 56 Fälle, und meldet in den beiden
untersuchten Fenstergrößen keine horizontal abgeschnittenen
sichtbaren Schaltflächen oder Eingaben. Nicht sichtbare,
vertikal scrollbar angeordnete Werkzeuge sowie Hochkontrast
und Screenreader sind davon ausdrücklich nicht vollständig abgedeckt.

**Wichtige Einschränkung der Gesamtregression:** Der inzwischen
auf **609 Testfälle** angewachsene Projektbestand wurde in dieser
Schleife **nicht bis zum Ende** geprüft. Der Gesamtlauf wurde nach
mehreren hundert erfolgreichen Tests aufgrund erheblicher Laufzeit
und Speicherlast beendet; ein nachfolgender Teiltestbereich ebenfalls.
Diese unterbrochenen Läufe sind **keine vollständige grüne
Gesamtfreigabe**. Die genannten 26 UI-Tests und realen Windows-QA-Läufe
wurden jeweils erfolgreich abgeschlossen. Ein separater vollständiger
Testlauf bleibt eine offene Abschlussaufgabe.

## Fortsetzung vom 14. Oktober 2026: Strg+K über sämtliche Arbeitsbereiche

Bei der zweiten UI-Prüfung wurde eine wichtige Lücke zwischen der
kompakten Oberfläche und ihrer großen Werkzeugzahl geschlossen:

- **Globale Suche (Strg+K)** im Tk-Hauptfenster. Ein sichtbarer,
  lokalisierter Knopf *Suche (Strg+K) / Search (Ctrl+K)* steht direkt
  neben der bisherigen Bereichsauswahl.
- Alle **14 aktuellen Arbeitsbereiche**, die vier tatsächlich im
  Editor vorhandenen Abschnitte (HTML-Editor, AtlasBuilder,
  Zinnen-/Pivot-Messung und OpenRaster) sowie Karten-, Spiel-HUD-,
  Animations-, Kartenordner-, Palette-/Inspector- und Pixelvergleichs-
  Ansichten lassen sich mit gemeinsamen deutschen oder englischen
  Suchbegriffen finden.
- Die Suche dient **ausschließlich der Navigation**. Sie startet beim
  Tippen und beim Auswählen **keine** Build-, Release-, Installations-,
  Zurücksetzungs- oder Sprite-Schreibbefehle.
- Suchfelder verstehen deutsche Umlaute und Schreibweisen wie
  \`Zinnenlineal\`, \`Pivot\`, \`Game HUD\`, \`OpenRaster\`.
  Die Auswahl lässt sich mit **Enter**, Doppelklick und Pfeiltasten
  bedienen; **Esc** schließt das Fenster. Die offene Suche reagiert
  ebenfalls auf Sprachwechsel DE/EN.
- Eine Werkzeugauswahl zum *Öffnen* der Palette oder des Inspectors
  **versteckt diese nicht**, wenn das Werkzeug schon sichtbar ist.
- Die native Qt-Kartenoberfläche besitzt ein eigenes, an ihren
  Lebenszyklus gebundenes Tastaturfilter. Das ist nötig, weil das
  mit Win32 \`SetParent\` unter Tk eingebettete Qt-HWND seinen
  \`WindowShortcut\` nicht zuverlässig empfängt.
  Der tatsächliche **Strg+K-Tastendruck auf der Qt-Karte** leitet jetzt
  die Suche zurück an Tk. Beim Schließen oder fehlgeschlagenen
  Einbetten wird der globale Qt-Filter wieder abgemeldet.
- Neue gezielte Tests prüfen Sprach-/Umlautsuche, sämtliche Bereiche,
  Pivot- und HUD-Navigation, nicht auszuführende Aktionen,
  idempotentes Anzeigen von Palette/Inspector und das Öffnen eines
  einzigen Suchfensters.

### Verifizierte Tests und Einschränkungen

- \`tests/sandbox/test_suite_command_search.py\`:
  **7 gezielte Tests bestanden** (einschließlich echtem Tk-Dialog).
- \`tools/qa_suite_command_search.py\`: unabhängiger Windows-Test
  mit echter Qt→Tk-Tastaturübergabe, Pivot-Navigation ohne Toolstart,
  englischem HUD-Suchbegriff, kompakter Fenstergröße und
  kontrolliertem Filter-Abbau. Meldung **COMMAND_SEARCH_QA_PASS**.
- Im aktuellen Build wird weiterhin keine vollständige
  Qt-/Tk-Zugänglichkeitsabnahme mit einem echten Screenreader
  behauptet. Der vorherige breite Gesamttest von mehr als 600 Fällen
  war nicht vollständig beendet und wird dadurch **nicht** nachträglich
  grün erklärt.

Der Einstieg bleibt \`Suite starten.cmd\`. Die Suche ist eine
navigierende Oberfläche; Originalkarten, Grafik-/Overlaydateien
und Spielinstallationen bleiben durch diese Funktion unverändert.


### Abschlussmessung der Strg+K-Navigation (14.10.2026)

- **8/8 gezielte Tests bestanden** mit
  \`pytest -q tests/sandbox/test_suite_command_search.py\`.
  Hinzugefügt wurde eine Regression für die echte Ansichtsnavigation:
  die Suche nach **Spielkarte / Game map** wechselt im eingebetteten Qt
  tatsächlich auf den Kartenreiter, nicht nur auf den äußeren Tk-Sandkasten.
- **Echter Windows-GUI-Test:** \`tools/qa_suite_command_search.py\` meldet
  \`COMMAND_SEARCH_QA_PASS\` (Exitcode 0). Der Ablauf prüft
  Tastendruck auf dem Qt-Kartencanvas → Tk-Suchdialog, Pivot-Sektion,
  englisches Spiel-HUD, tatsächlichen Kartenreiter, Fenstergröße
  \`1020×680\` und Abmelden des Event-Filters beim Schließen.
- **Verhaltensregel:** „Palette öffnen“ und „Inspector öffnen“ sind
  idempotente *Anzeigen*-Operationen. Bereits sichtbare Seitenleisten
  werden durch ein gefundenes Suchziel nicht versehentlich ausgeblendet.
  Offene Suchfenster wechseln DE/EN ohne Verlust der aktuellen Suche.
- **Grenze der UI-Gesamtregression:** Ein breiterer, kombinierter
  Windows-GUI-Testlauf (60 Fälle) ergab **59 bestanden, 1 fehlgeschlagen**.
  Der fehlgeschlagene bestehende Katalogtest erwartete nach dem
  Gruppenwechsel die Treeview-Selektion \`g:anim_castle\`, beobachtete
  jedoch einmal eine leere Selektion. Bei separatem Test und zwei
  gezielten Testreihenfolgen bestand derselbe Fall jeweils erneut.
  Ursache / Reproduzierbarkeit ist noch ungeklärt. **Der kombinierte
  Lauf ist damit keine vollständig grüne Abnahme.**
- Der ältere 609+-Fall-Gesamtbestand wurde in dieser Runde nicht
  nochmals vollständig ausgeführt. Eine endgültige Releasefreigabe
  oder langfristige Barrierefreiheits-/DPI-Abnahme wird ausdrücklich
  **nicht** behauptet.

Das Feature verändert weder Originalspielgrafiken noch
Konfigurationen oder Build-/Installationszustände. Navigation ist
von allen potenziell verändernden Aktionen getrennt.
