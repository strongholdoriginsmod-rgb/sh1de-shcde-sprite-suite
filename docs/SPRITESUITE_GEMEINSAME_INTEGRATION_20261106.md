# Gemeinsamer Stronghold-/SpriteSuite-Integrationsstand – 06.11.2026

Diese Datei ist der Übergabepunkt für weitere Claude-, Codex- und ChatGPT-Arbeitszweige. Alle Pfade liegen auf DESKTOP-O008GV9. Andere Chatverläufe erhalten nicht automatisch den Gesprächskontext dieses Chats; der gemeinsame, überprüfbare Stand wird daher ausschließlich über Git-Commits, Tests und diese Datei koordiniert.

## Kanonischer Integrationszweig

- Worktree: `E:\SpriteSuite_Integrated_Final_20261106`
- Branch: `integration/spritesuite-unified-damage-tools-20261106`
- Startstand: `7672835` (Gebäudeschäden), darin enthalten `10c79be` (1-px-Tile-Overlap) und `dffce3f` (Python-3.15-Basis).
- Zusätzlich in diesen Worktree übernommen: nichtdestruktiver Diff des lokalen Zweigs `E:\SpriteSuite_ToolConsolidation_20261106`, Stand 06.11.2026 mit Registry, Inventur, Risikoetiketten, Tests und Strg+K. Dessen eigener uncommitteter Arbeitsstand bleibt ausdrücklich unberührt.
- Weiterhin nicht übernommen: die zahlreichen nicht eingecheckten Änderungen in `E:\SpriteSuite` (`feature/sandbox-studio`). Ohne isolierten Diff-/Versions- und Testabgleich dürfen diese nicht in den gemeinsamen Stand gelangen.

## Bereits vereinheitlichte Funktionspfade

| Bereich | Quelle | Ergebnis |
| --- | --- | --- |
| Sprite-Zerlegung | `10c79be` | 1px an allen Tile-Grenzen, hintere Reihen, max. 64px, Alpha-/Maskenschutz |
| Gebäude-Schaden | `7672835` + Integrationsfixes | Gebäudeauswahl; Feuer und mechanische Pfade; sortierte HP-Schwellen; eigene Stufen-Szenen |
| Generator | `tools/building_damage_codex.py` | offline erstelltes GPT-Image-2.6-Bundle; optional expliziter API-Aufruf; reversible Bildregistrierung |
| Qualität | `extras/sprite-editor/src/damage_io.js` | Pixel-/Anker-/Canvas-Prüfung, Mindeständerung, Originalvergleich, manuelle Freigabe |
| Export | `damage-manifest.json` | nur freigegebene Stufen; SHA-256, Sprites, HP; **kein** dynamischer Runtime-Hook |
| Tool-Katalog | `tools/suite_tool_registry.py` | existierende Spezialwerkzeuge; reine Navigation ohne Ausführung |
| Bestandsvergleich | `tools/suite_tool_inventory.py` | historische Stronghold-Tools mit SHA-256-Diff, ohne Übernahme/Kopie/Ausführung |
| Navigation | `tools/suite_command_search.py` | vorhandenen HTML-Editor und neuen Codex-Adapter über Schlüsselwörter erreichen |

## Schnittstellen und Nichtveränderung

1. Nur Quellen/Tests/Docs im isolierten Worktree ändern; keinen Write-Zugriff auf Spielinstallationen, `E:\SpriteSuite`, `E:\SU_base`, Claude-/Codex-Quellarbeitsordner oder historische Portable-Releases.
2. Veraltete Script-Extender- oder native Runtime-Tools weder austauschen noch ohne versionsgebundenen Test importieren.
3. Die vorhandene Onlinefreiheit des HTML-Editors mit `connect-src 'none'` behalten. GPT-Image-Aufrufe erfolgen ausdrücklich nur über externen CLI-Adapter, nicht beim Betrachten/Bearbeiten von Projekten.
4. Das SHSPRITE-Format bleibt Version 2 mit optionalem `damageProfiles`; Projekte ohne diese Daten müssen unverändert geladen werden.
5. Standard-Mod-Override darf zusätzliche Schadens-Tilegruppen nie als globales intaktes Gebäude installieren.
6. Ein `gameBuildingType` ist optional und **nicht automatisch verifiziert**; das Manifest kennzeichnet es als ungeprüft. Kein Spiel-Hook wird erfunden.

## Tests und Qualitätsgrenzen

Befehle aus dem gemeinsamen Integrationsworktree:

```powershell
python -m pytest -q -p no:cacheprovider tests/sandbox/test_suite_command_search.py tests/sandbox/test_suite_tool_policy.py tests/sandbox/test_qa_inventory.py tests/sandbox/test_suite_tool_inventory.py
Push-Location extras/sprite-editor
node --test tests/test_core.cjs tests/test_seam_overlap.cjs tests/test_split_integration.cjs tests/test_damage.cjs tests/test_damage_geometry.cjs
python build.py
python sprache/einbauen.py
node tests/test_damage_browser.cjs
Pop-Location
python -m unittest discover -s tests -p test_building_damage_codex.py -q
git -c core.whitespace=cr-at-eol diff --check
```

Die Browserprüfung benötigt Puppeteer und Edge bzw. einen kompatiblen Chromium-Browser. Sie läuft mit der echten lokalen `file://`-HTML-Datei ohne ausgehende Anwendungsanfragen. Das GPT-Image-API-Adapter-Modul wird ausschließlich per Mock getestet; es werden keine echten kostenpflichtigen Bilder erzeugt.

Begrenzungen, die vor einer echten Veröffentlichung aufzulösen sind:

- **Spielrendering:** Gebäudeinstanz, aktueller/maximaler HP-Wert, Feuerschadensursache, sichere SpriteRenderer-Zuordnung und der Asset-Lebenszyklus sind für SHCDE noch nicht als zusammenhängende, getestete API nachgewiesen. Hier existiert erst ein optionales Datenmanifest.
- **Konkrete Originalmodelle:** Ruinen/Abtei müssen an extrahierten echten SHCDE-Tiles und im Spiel visuell abgenommen werden; Synthetiktests sind kein Ersatz.
- **API-Live-Test:** GPT-Image-2.6-Edits im realen Konto erst bei ausdrücklich freigegebenen Kosten und bereitgestelltem Schlüssel testen.
- **Ältere QA/Release-Skripte:** Vor Release überprüfen, ob deren Checksums und HTML-Browserberichte noch zum neu erzeugten HTML passen.

## Vorgehen für andere parallele Arbeitszweige

1. `git -C E:\SpriteSuite_Integrated_Final_20261106 log -1 --oneline`, `status --short` und `diff --stat` lesen, bevor eine neue Änderung geplant wird.
2. Für die eigene Arbeit einen neuen Git-Worktree auf Basis dieses Integrationszweigs anlegen. Keine ungeprüften Worktree-Verzeichnisse kopieren.
3. Änderung als kleinen Commit mit Funktionsumfang, Referenz auf Tests und konkret betroffenen Dateien liefern; diese Integrationsdatei um Versions-/Risikoangaben ergänzen.
4. Neue Commits anhand `git merge-base` und `git diff` prüfen, dann selektiv `cherry-pick`/patchen, nicht per `git reset --hard`, `git clean -fd` oder ungesichertem Überschreiben fremder Worktrees.
5. Bei konkurrierenden Änderungen an `src/io.js`, `src/app.js`, `suite_command_search.py` und `suite_tool_policy.py` zuerst gemeinsam die Zustands- und Exportkontrakte vergleichen, dann Konflikte händisch auflösen und Regressionen vollständig neu ausführen.
6. Erst nach grünen technischen und visuellen Checks die gemeinsame Integrationsversion als Releasekandidat markieren. Ein offener Runtime-/In-Game-Punkt darf nicht als bestanden deklariert werden.

## Änderungsliste für diesen Integrationsdurchlauf

- Werkzeugkatalog und historische Inventur aus separatem Konsolidierungszweig integriert.
- Codex-Schadensbildadapter dem kuratierten Katalog hinzugefügt und externem Risikoprofil zugeordnet.
- Suche nach „Gebäudeschaden“, „HP“, „GPT Image“ usw. führt zu vorhandenem Editor bzw. Fachwerkzeug.
- Optionales numerisches Spiel-Gebäudetypfeld mit Duplicate-Schutz und Invalidation vormals freigegebener Modelle.
- Ursprüngliche 5×5-Canvas beim Tile-Splitting durch transparenten Headroom wiederhergestellt, dabei unveränderte sichtbare Pixel im Aufbau und im Projekt-Archive-Roundtrip nachgewiesen.
- Qualitätsprüfung um Mindestveränderung, Warnung bei potenziell nicht-monotoner Zerstörungsfolge und visuelle Gegenüberstellung ergänzt.

## Verifizierter Integrations- und QA-Stand

Abnahme am 06.11.2026 auf DESKTOP-O008GV9, getrennt vom uncommitteten Hauptarbeitsbaum:

- **127/127** Node-Tests (alte PNG-/Tile-/Overlap-Regressionen plus neue HP-, Modell- und echte 5×5-Steinhof-Geometrieprüfungen), **0 Fehler**.
- **22/22** Python-pytest-Suite-Tests (Katalogsuche, Risikoetiketten, alte QA-Inventur, neue SHA-Vollinventur), **0 Fehler**.
- **10/10** Python-unittest-Codex-Adaptertests (SHA, API-Mock, registrierte Rückprojektion, Fremdpixel, keine Schlüssel im Export), **0 Fehler**.
- **49/49** bisherige Browser-E2E-Prüfungen mit systeminstalliertem Edge und separatem temporären Playwright-Paket, **0 Fehler und 0 App-Netzwerkanfragen**.
- **13/13** neue direkte `file://`-Edge-Browserprüfungen für Gebäudeauswahl, HP, Brand/Mechanik, GPT-Bundle, unveränderte und veränderte Kandidaten, Abnahme, HTML-Sprache und Schadensmanifest. Keine API-Aufrufe. Details: `extras/sprite-editor/tests/results/damage-browser-report.json`.
- **160/160** SHA-256-Verifizierungen über `extras/sprite-editor/verify_release.py`; deterministischer DE-/EN-HTML-Build und Abgleich der beiden Browser-Reports erfolgreich.
- **0** Schreibzugriffe auf die SHCDE- oder SHDE-Spielinstallation und **0** echte GPT-Image-Aufrufe. Die native HP-gesteuerte Spielrenderer-Umschaltung bleibt ein separat zu implementierender und in-game zu testender Funktionsblock.

Alle Änderungen sind lokal im isolierten Integrationszweig. Andere Chats können dessen aktuellen HEAD lesen und ihre Änderungen über eigene Worktrees zurückführen. Eine tatsächliche Kommunikation zwischen Chats wird durch diesen Dateivermerk nicht behauptet.

## Fortsetzung: geprüfter HP-Runtime-Vertrag

Neuer isolierter Entwicklungszweig `feature/building-damage-runtime-contract-20261106` unter `E:\SpriteSuite_DamageRuntime_20261106`, ausgehend von `20bba53`. Er übernimmt die bestehende 1-px-Tile-Überlappung, die getrennten HP-Schadensmodelle und den Codex-Bildworkflow unverändert.

Umgesetzt sind ein vollständig prüfendes Preflight für das vom Sprite Editor erzeugte Schadens-ZIP, eine SHA-256-gebundene, nur lesende TSV-Übergabe, der exakte C#-HP-/Feuer-Selektor und ein fail-closed Leseadapter für die dokumentierten SHCDESE-Gebäudeabfragen. Das Runtime-Plugin und die SpriteRenderer-Kopplung bleiben unverändert. Der GameBuilding-API-Adapter ist ausschließlich bei expliziter Compile-Option `SHCDE_BUILDING_DAMAGE_READONLY_API` vorhanden; ohne diese Option besteht keine neue Spiel-DLL-Abhängigkeit.

Ein gemeinsamer Offline-Testlauf kann mit `python tools/qa_building_damage_runtime.py` gestartet werden. Der Test baut eine echte SpriteSuite-Schadensbibliothek aus dem synthetischen 5×5-Steinhof, prüft ZIP/PNG und generiert die TSV-Tabelle, kompiliert die C#-Entscheidungslogik sowie den API-Adapter gegen synthetische Methoden und beendet sämtliche Abläufe ohne Installations- oder Netzwerkanfrage. Details, Funktionsgrenzen und der nächste In-Game-QA-Nachweis stehen in `docs/GEBAEUDESCHADEN_RUNTIME_AUDIT_PLAN_20261106.md`.

Der tatsächliche Renderer- und Gebäude-Slot-Nachweis bleibt offen; insbesondere dürfen `GetOccupiedTileIds` und die SpriteSuite-Tile-Reihenfolge noch nicht ungeprüft gleichgesetzt werden. Das neue Manifest ist deshalb weiterhin kein installierbarer dynamischer Gebäudeschadens-Mod.
