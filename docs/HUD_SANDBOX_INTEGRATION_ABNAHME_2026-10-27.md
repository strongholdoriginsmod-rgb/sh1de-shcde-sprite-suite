# Integration SH1-HUD, SHCDE-UI, Sandbox und Diplomatie-Quellstand

**Entwicklungsstand:** 27.10.2026 · Branch `feature/integration-hud-sandbox-20261027`

**Status:** Quellcodeintegration und gezielte Offline-/GUI-Regression abgeschlossen.
**Nicht** als Ingame-Freigabe oder geprüfte Neuinstallation verstehen.

## Herkunft und Konfliktbehandlung

Die Git-Historien `feature/sandbox-studio` (Ausgangscommit `00276ec`)
und `feature/stronghold1-hud-spritesuite-20261026` (`e859d86`)
wurden in einem **separaten** Git-Worktree zusammengeführt.
Die bisherige lokale Arbeitskopie und der bestehende HUD-Featurezweig
blieben unverändert. Beim Git-Merge wurden die zwei Konflikte wie folgt
gelöst:

- `tools/suite_universal.pyw`: umfangreichere Sandbox-Oberfläche,
  einschließlich bereits integriertem `Sh1HudStudio`, erhalten
- `tools/suite_usability.py`: Schutz gegen nicht gestartete Folgeaktionen
  aus dem HUD-Zweig übernommen; der lokale Entwurf stimmte bereits überein

Ein SHA-geprüfter Schnappschuss übernahm anschließend die lokale, noch
nicht eingecheckte Arbeit: 184 Dateien (39 geänderte und 145 neue).
20 temporäre Sync-Dateien mit Endung `.tmp` wurden **nicht** übernommen.
Alle Python-/JSON-Dateien wurden statisch geprüft. Die Quellenprüfung
fand keine bekannten Zugangstoken- oder Private-Key-Signaturen in den
für den Commit vorgesehenen Quelldateien. Das ersetzt keine unabhängige
vollständige Sicherheitsprüfung.

## Sichtbare Funktionen und Verträge

- SH1-HUD-Originalextraktion, drei Atlanten, Herkunfts-/Pixel-SHA-Prüfung,
  indexierte Pixeleditor-Dateien, Rücksetzen mit Konfliktprüfung
- SH1→SHCDE: explizit freizugebende Namen/Geometrie/Zustände,
  nativer Ursprungvergleich, **bearbeitbares** Zielprojekt,
  unveränderte unbeteiligte SHCDE-Originalrechtecke und PNGs
- SHCDE-Editor: Bild laden, Einzelbild extern bearbeiten,
  Atlasprüfung und Weiterverarbeitung nur unter geprüften Arbeitsordnern
- Zusätzliche Noesis-Atlasblätter: PNG+XAML-Dictionary,
  MergedDictionaries, eindeutige Ressourcen-Keys, native SHCDE-Referenzprüfung
- Lokale Sandbox: Karten-/Ressourcenbrowser, HUD-Spielmodus, native
  Render-/Auswahl- und Speichersicherungen, GUI-Sprachen, Build-Preflight
- Diplomatie-V1/V2-Quellprojekt und geteilte C#-Quellstruktur.
  Die drei C#-Projektdateien sind XML-gültig, ihre **statisch benannten**
  Quelldateien sind vorhanden und enthalten keine eigenen MSBuild-Exec-Tasks.
  Native Referenzassemblies, generierte Verträge und echter .NET-Plugin-Build
  wurden hier **nicht** vollständig nachgewiesen.

Die Brücke erzeugt **keine** automatisch neuen HUD-Spielaktionen.
Neue Noesis-Keys benötigen zusätzliche View-/Binding-Konfiguration,
Spielzustandsprüfung und sichtbaren Ingame-Test.

## Testnachweis (isolierter Checkout)

Die gesamte `tests/sandbox`-Sammlung umfasst **1.043 test collection entries**
über 103 Module. Ein einzelner Monolithlauf ist auf dem Windows-Rechner
ressourcenintensiv; daher wurde die Sammlung in **17 getrennten,
quellpfad-gepinnten Testgruppen** geprüft. `PYTHONPATH` wurde
ausdrücklich auf `src` und `tools` dieses Worktrees gesetzt, da die
geteilte virtuelle Umgebung ansonsten per Editable-Installation Code
der alten lokalen SpriteSuite importiert hätte.

Die Erstgruppen waren überwiegend grün, aber **nicht** durchgehend:
- Zwei Qt-Tests setzten ein privates Original-Mapping voraus. Sie prüfen
  jetzt entweder den echten Mappinginhalt oder das korrekte Fehlen
  der Originalressourcen. Beide einzeln erneut bestanden.
- Ein GUI-Test für den Kartenordnerwechsel blockierte an einer
  Bestätigungsabfrage für ein möglicherweise verändertes Overlay.
  Der Test bestätigt jetzt explizit „Verwerfen“; isolierte Wiederholung
  bestand, die Anwendung schützt weiter vor stillem Datenverlust.
- Ein Editor-Lebenszyklustest setzte eine nicht veröffentlichte
  Einzel-PNG voraus und konnte an der Warnmeldung hängen.
  Der Test benutzt jetzt einen synthetischen Qt-Editor mit echten
  Signalen; echte Bildbearbeitung wird separat getestet.
  Anschließend bestanden **53 Tests**, vier nur wegen fehlender
  historischer Palettenquellen übersprungen.
- Wiederholte Tk/Tcl-GUI-Initialisierung erzeugte in mehreren
  Mischläufen sporadische Fehler. **Alle sieben** gezielt erneut
  geprüften problematischen Einzeltests bestanden in frischen Prozessen.
  Der abschließende kombinierte kritische GUI-Lauf ergab **10 bestandene**
  Tests. Das Tcl-Problem im langen Mischlauf bleibt eine
  *Testinfrastruktur-Grenze*, keine allgemeine Ingame-Freigabe.

**Wichtige Einordnung:** Aus diesen isolierten Nachprüfungen darf nicht
behauptet werden, ein einziger vollständiger `pytest tests/sandbox`-Lauf
sei mit 1.043/1.043 Tests fehlerfrei abgeschlossen worden. Die
resultierenden Protokolle befinden sich in einem **nicht veröffentlichten**
QA-Schnappschuss außerhalb des Repositories.

## Sicherheits- und Veröffentlichungsgrenzen

- In diesem Entwicklungsstand wurden weder originale Spiel-Assets noch
  installierte Spiele, Produktionspakete oder private Mapping-Caches
  in das Git-Repository übernommen.
- Lokale Benutzerkonfigurationen unter `config/installations.local.toml`
  bleiben ausgeklammert.
- Beide bisherigen Git-Worktrees bleiben erhalten. Zusammenführen bzw.
  spätere lokale Aktualisierung nicht als Dateiüberschreibung behandeln.
- Kein verifiziertes Ingame-Laden zusätzlich erzeugter Noesis-Atlanten,
  keine abgeschlossene HUD-State-/Input-/Shader-Abnahme.
- Kein nachgewiesener Kompatibilitäts-/Installationslauf der vollständigen
  V1-/V2-C#-Plugins gegen alle Zielversionen.
- Ein GitHub-Spiegel ist unabhängig von der GitLab-Historie erst nach
  Vorliegen eines freigegebenen GitHub-Repositories mit Schreibrecht
  möglich. Ein erstellter Integrationscommit allein ist **kein**
  erfolgreicher GitHub-Push.

## Weitere zielgerichtete Freigabeschritte

Vor einem Spiel-/Plugin-Release müssen eine saubere SHCDE-Installation
und der originale Noesis-Override, native Unity-Quelldateien, Script
Extender-Version, weitere Spielzustände, Save/Load und Rückbau im
separaten QA-Spiel nachgewiesen werden. Für Github zuerst Zielrepo mit
Schreibzugriff verbinden und den geprüften Integrationsbranch ohne
Force-Push übertragen.
