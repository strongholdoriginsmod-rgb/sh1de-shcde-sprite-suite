# Sprite Suite – HUD-GUI-Konvertierung, tatsächliche Nachweise

**Prüfung:** 26. Oktober 2026, `E:\SpriteSuite`, Branch
`feature/sandbox-studio`. **Status: geprüfte Teilkorrektur; keine
vollständige Spiel-HUD-, Shader-, Release- oder Ingame-Freigabe.**

## Der genaue Unterschied

Die **grafische GUI-Konvertierung des HUDs** bedeutet mehr als ein
erfolgreich eingebettetes Qt-Fenster: Original-XAML-Ressourcen müssen
einem korrekten Quellausschnitt und sichtbaren interaktiven Bedienelement
zugeordnet sein, ihr Bildmaß muss stimmen, bedingte XAML-Alternativen
dürfen sich nicht überlagern und UI-Befehle dürfen nur ihre fachlich
belegten Arbeits-/Spielhandlungen auslösen. Die statischen Quellen
liefern **keine** Beweise für dynamische Beraterzustände,
Wirtschaftssimulation, echte Build-Availability oder Unity-Shader.

Die vier historischen Originalspielreferenzen zeigen ein HUD am rechten
unteren Bildschirmrand, dessen untere Zone sich mit der Spielauswahl
verändert. Die bestehende Qt-Sandbox ist bisher eine absichtlich
bezeichnete **HUD-Teilrekonstruktion**. Eine statische Porträtkopie wäre
kein korrekter Ersatz.

## Reproduzierte/festgestellte Probleme

1. **HUD-Hintergrund wurde geometrisch verzerrt:** Der tatsächliche
   SHA-geprüfte Original-Ausschnitt `UI-HUD 007` ist **1752 × 206** Pixel,
   Qt zeichnete aber stets das **gesamte** Originalrechteck in die
   unabhängig größenveränderbare Bedienleiste. Unterschiedliche
   X-/Y-Skalierung entstellt die Originalproportionen.
2. **Originalpixel-Zuordnung separat nachzuweisen:** Die XAML-
   Befehlsdefinition enthält **141** Kommandovarianten auf
   **14** Kategorien. In der privaten, ursprünglichen SHCDE-Pixelablage
   sind ihre Normal- und Hover-Key-Referenzen vorhanden. Ein
   Dateinachweis alleine belegt nicht, dass die Qt-Auswahl alle
   Varianten korrekt aktiviert.
3. **UI-Atlas-Konverter nicht mit HUD-Spielsteuerung verwechseln:**
   `ui_atlas.py` exportiert, prüft und baut gepinnte Bildrechtecke
   transaktional zurück; `ui_sh1_umstellung.py` rechnet die
   namensgleichen SH1-Grafiken ins Projekt. Beides ersetzt keine
   spielabhängige HUD-Zustandsmaschine.

## Implementierte Änderung und automatisierte Belege

Die Qt-Pergamentleiste verwendet
`hud_backplate_source_rect()` aus
`tools/sandbox_hud_chrome_geometry.py`: Ein zentrierter Quellausschnitt
wird mit **einem einzigen Skalierungsfaktor** auf die aktuelle Leiste
gezeichnet. Überstehende Quellpixel werden beschnitten, das Original
weder neu gespeichert noch verändert. Das ist eine korrekte
*Rasterdarstellung*, noch keine vollständige XAML-Spielkomposition.

`tests/sandbox/test_hud_backplate_conversion.py` prüft:
- Geometrie, Seitenverhältnis, Zentrierung, kleine und große Ansichten
  und ungültige Quell- oder Zielgrößen.
- Qt-Pixelausgabe eines synthetischen mehrfarbigen Originalstreifens:
  Die Bildmitte bleibt unverzerrt; das ursprüngliche fehlerhafte
  Vollbild-Strecken würde einen anderen Bildausschnitt anzeigen.
- Alle **141 XAML-Varianten** werden über die tatsächlich erzeugte
  Qt-Kategorie- und Befehlsauswahl durchgeschaltet; die erwartete
  sichtbare Variante ist selektiert und verfügt über ihr Bild, ihre
  semantische Befehlsbezeichnung und den Hilfetext.
- Während dieser Auswahl entsteht kein unautorisierter
  Originalkarten-/Overlay-Schreibvorgang.

Die fünf zuvor bestehenden HUD-Quellen-/Geometry-/XAML-/
Bedien-Module ergaben **29 bestandene Tests**. Anschließend bestanden
**22 gezielte HUD-Tests** mit der neuen Geometrie und Originalpixel-
Zuordnung sowie **1 zusätzlicher Qt-Komplettauswahltest** über
alle 141 Befehle. Die zugehörigen Protokolle liegen unter
`work/reports/hud-core-reaudit-20261026.log`,
`work/reports/hud-conversion-focused-20261026.log` und
`work/reports/hud-141-controls-20261026.log`.

## Unverändert offene wichtige Nachweise

- Dynamische Original-HUD-Kompositionen pro Baugruppe, Spieler,
  Ressourcen-/Spielzustand, Berater/Bink-Folge und Animation.
- Visuelle Gleichheit zur tatsächlichen SHCDE-/SH1DE-Referenz bei
  identischer Kamera, Zeit und Originalspielversion, inklusive
  Clipping, Transparenz und Unity-spezifischer Shader.
- Echte Windows-/Multimonitor-DPI-, Screenreader-,
  Tastatur-/Maus- und stundenlange Zustandsübergangstests.
- Versionsgebundener echter Unity-/BC7-Neubau, geprüfte Ausgabe,
  Installation und Ingame-Freigabe.

**Schutz:** Keine Schreibänderungen an Spielinstallationen,
Originalkarten, XAML, Unity-Assets oder bestehenden
BC7-Produktionspaketen. Andere parallel uncommittete
Sandbox-/Runtime-Arbeiten wurden nicht als eigene Änderungen
übernommen oder zurückgesetzt.


## Weiterführende Abnahme vom 26. Oktober 2026: GUI-Konvertierung zwischen zwei Spielen

Neben der 141-Kommandobelegung im Crusader-HUD ist jetzt der **separate
Stronghold-1-HUD-Editor** im vorhandenen Sprite-Suite-Reiter **Oberfläche**
implementiert. Dort gibt es ausdrücklich zwei Innenreiter:

- **Crusader DE · UI-Atlas** – eigenständige Crusader-Exports,
  SHA-prüfende Crusader-Übernahme und Profilverwaltung.
- **Stronghold 1 DE · HUD** – originale, getrennte SH1-Atlas-PNGs,
  lokaler Pixeleditor, SH1-spezifische Prüfung und drei getrennte
  rekonstruierte Atlasblätter. Keine direkte Crusader-Installation.

Die gemeinsamen Bildlisten und das Verzeichnisfeld behalten bei
Reiterwechseln beide unterschiedlichen Arbeitsordner. Im SH1-Bereich
ist die Crusader-Testausgabe deaktiviert. Bei vorhandenem SH1-Export
wird nicht nur eine willkürliche Build-ID akzeptiert, sondern
`sh1_hud_source.json` gegen `index.json`, den ursprünglichen
Quelldigest und die drei erwarteten Atlanten abgeglichen. Die
verbindliche Prüfung erfolgt weiter im ursprünglichen
`tools/ui_sh1_hud.py check`; die Vorschau allein erzeugt niemals eine
Freigabe.

**Echte, unveränderte Stronghold-1-DE-Quelle:**
`globalgamemanagers.assets` besitzt SHA-256
`5810367d1ce4e87d63f8993f49b48243b2f3808f973e18f5c5a76c134913261f`.
Die unter `work/sh1-hud-editierbar` befindliche Kopie enthält
**1.391** XAML-benannte PNGs in
`UI-MasterAtlas` (1.323), `UI-ROL` (55) und
`UI-CandleAtlas` (13).
`ui_sh1_hud.py check --from work/sh1-hud-editierbar` endet mit
`SH1-HUD-CHECK_OK 1391 Bausteine; 0 bearbeitet` und Exitcode 0.
Die zuvor lokal aus dem Originalzustand erzeugte separate SH1-Ausgabe
enthält **drei PNGs mit korrekten Manifest-SHA-256-Werten** und den
Abmessungen **8192×4096, 4096×4096 und 2048×4096**.
Dieser Stand enthält **keinen** europäischen HUD-Overlay-Pixelumbau.

**Warum 1:1-Automatik eine fehlerhafte Behauptung wäre:**
Die originale SHCDE-HUD-Quelle im lokalen, SHA-geprüften
Crusader-Crop-Cache enthält **354** geprüfte Ausschnitte. Eine nur
lesende, streng nach Export-ID und Dateihashes geteilte
Namens- und Geometrieprüfung ergab:

| Eindeutige Kategorie | Anzahl |
|---|---:|
| SH1-Elemente | 1391 |
| dokumentierte SHCDE-Crops | 354 |
| identischer Ressourcenname | 290 |
| identischer Name und identische Breite/Höhe | 139 |
| identischer Name, aber verschiedene Breite/Höhe | 151 |
| namens- und größenidentisch, aber **unterschiedliche Originalpixel** | **139** |
| namens-, größen- und pixelidentisch | **0** |
| SH1-Namen ohne SHCDE-Crop-Gegenstück | 1101 |
| SHCDE-Namen ohne SH1-Gegenstück | 64 |

Die 151 Dimensionskonflikte gehören zu `UI-Buildings`.
Zu den maßgleichen, aber pixelverschiedenen Elementen gehören
49 `UI-Buildings`, 89 `UI-Scribe` und der bekannte
HUD-Pergamentstreifen `UI-HUD 007` (1752×206).
Es gibt **keine automatische Anwendungsfreigabe**. Der lesende
vollständige Befund liegt unter
`work/reports/ui-audit/sh1-to-shcde-hud-name-geometry-20261026.json`
und beinhaltet den gehashte Ursprung, alle 139 Kandidaten und alle
151 Konflikte. Kein Original und kein Asset wurde dafür verändert.

**Zusätzliche Validierung:** Ein synthetischer SH1-Drei-Atlas-Durchlauf
hat das Bearbeiten eines einzelnen Ausschnitts und die daraus
rekonstruierten Pixel getestet; falsch große PNGs blockieren
den Rückbau ohne Beschädigung einer vorherigen Ausgabe.
Die echten Tk-Steuerungen wurden zusätzlich auf
1020×680 und 1320×800 dargestellt. Separate Windows-GUI-Tests
bestätigen auftragsgebundenen Exportabschluss, erforderliche
Bestätigungen vor dem Ersetzen einer vorhandenen SH1-Atlas-Ausgabe
und die Trennung vom Crusader-Profil. Zwei weitere
Pixeleditor-Tests bestätigen echte Mausklicks, Undo/Redo,
atomisches Speichern und die Ablehnung paralleler Dateiänderungen.
Auch die native Windows-Hauptfenster-QA hat den aktuellen
Sandbox-Spiel-/HUD-Bereich mit `QA_PASS` abgeschlossen.

**Weiter offene Grenzen:** Das eigentliche Importieren von
eigenen europäischen SH1-Pixeln in den Crusader-Spiel-Build mit
geprüftem Zielkoordinatenvertrag, Zustandslogik, Shader- und
Transparenzgleichheit ist noch **nicht** implementiert oder
freigegeben. Die getrennten originalen HUD-Grafik- und
Exportprüfungen sind kein Nachweis für einen funktionierenden
vollständigen Spiel-HUD-Umbau oder einen neuen Unity-BC7-Release.
