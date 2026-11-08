# SpriteSuite V2: Werkzeugkonvergenz, Auto-Discovery, KI-Evidenz

Aktueller Integrationsstand: Der allgemeine KI-Adapter verwendet die lokale, verwaltete ChatGPT-/Codex-Sitzung. Bedienung und aktuelle Tests stehen in `SPRITESUITE_KI_CHATGPT_KONSOLIDIERUNG_20261108.md`. Die folgenden älteren Entwicklungsbefunde dokumentieren ihren jeweiligen Zwischenstand.

Datum: 08.11.2026 · Ausgangscommit: `e6a413d` · Isolierter Zweig:
`feature/spritesuite-unified-tools-ai-v2-20261108`.

## Ergebnis: Funktionen statt Spezialfenster

**Gemeinsamer Editor statt Zinnenlineal:** Der bestehende Sprite-Editor
unter `extras/sprite-editor/` enthält bereits Raster, Pixelgeometrie,
Druck-/Maskenbild, Originalvergleich, Overlays, Frame-/Sprite-Versatz,
Anker und Undo. Neu kann der Geometrie-Inspektor nun das originale
`zinnenlineal.versatz.v1`-JSON importieren und dessen Vorschläge
gegen den aktuell ausgewählten Frame prüfen. Die Messung wird
nicht als generische Pixelverschiebung umgedeutet: `neu_pivot_x =
pivot_x - rechts / breite` und entsprechend Y, genau wie im
vorhandenen Python-Validator. Gruppennamen, Frame-IDs,
Bildgröße, Alter/Ziel-Pivot, Duplikate und Grenzen werden
vor jeder Darstellung kontrolliert.

Auf dem Canvas erscheint der vorgeschlagene Anker als eigener
Umriss bei *gleichem Weltanker*. Änderungen werden nur nach
manueller Sichtprüfung und Abnahmevermerk in der Arbeitskopie
gespeichert. Der Beleg enthält Quellmessungs-SHA, RGBA-Bild-SHA,
angewandten Pivot und Prüfnotiz; neue Bild-/Pivotänderungen machen
ihn ungültig. Spiel-/Atlasänderungen, Installationen und
Bauvorgänge folgen daraus **nicht**.

Die originale `pivot_review_gui.py` bleibt **als Experten-QA** für
bestimmte BC7-/Index-Quellprüfungen erhalten: Diese kontrolliert
zusätzlich veröffentlichte Dateien und SHA-gebundene Index-Pfade,
was der lokale Browser ohne Zugriff auf das Spiel nicht leisten
kann. Das alte Fenster ist kein notwendiger Standard-Bedienweg
mehr. Alte CLI-/Testverträge bleiben erhalten.

## Gemeinsame Referenzregistrierung

Vorher existierten zwei praktisch gleiche Funktionen zur
Nearest-Neighbor-Registrierung von Ausgangs-PNGs für
KI-Generatoren (`damage_io.js` und `ai_workflow.js`).
Neu: `SpriteCore.modelRegistrationPlan` und
`SpriteCore.modelRegisteredImage` sind die gemeinsame
Pixelimplementierung. Beide Generatorpfade nutzen sie.
Kein alternatives Downsampling, keine still veränderten
RGB-Werte in transparenten Pixeln und kein Zweitformat.

Die speziellen HP-/Feuer-Schwellen und sequenziellen
Schadensfreigaben bleiben **unverändert** und werden nicht
durch generische KI-Abnahmen ersetzt.

## Automatische Spiel- und Toolchain-Erkennung

`suite_environment_discovery.py` ist die read-only Fassade.
`suite_toolchain_inventory.py` erweitert sie mit abgegrenzter
Suche nach Unity-Hub-Versionen, Unity.exe-Overrides,
Python 3.13/3.14/3.15 in benannten Installationsordnern,
aktiven oder Projekt-venv-Pfaden und stabilen .NET-SDKs.
Game-, Steam-, Script-Extender-, APIShared- und Serp-Funde
bleiben in der bestehenden Erkennung.

Sie sucht **keine** ganzen Laufwerke ab, startet **keinen**
der gefundenen Interpreter/Compiler/Editoren und installiert
keine Packages. Symlinks, Junctions und Reparse-Points werden
abgewiesen. Unklare Mehrfachfunde werden als Kandidaten und
nicht als automatisch freigegebene Ziele angezeigt.
Versionsnamen im Ordner sind Hinweise, keine Prüfsiegel.
Die bisherige explizite Speicherung der Installation bleibt
eigenständig.

## Einheitliche Navigation in die Anwendung

`tools/editor_bruecke.py oeffnen --bereich geometry|ai|damage`
öffnet die vorhandene, weiterhin offline funktionierende HTML-
Werkstatt mit einem **reinen Navigationsfragment**.
Ohne `--bereich` bleibt der bisherige Einstieg unverändert.
`suite_universal.pyw` bietet die gemeinsame Geometrie
als regulären Pivot-/Zinnen-Einstieg und die KI-Werkstatt
als zusätzlichen direkten Link. Erweiterte historische
BC7-/Index-QA bleibt separat erreichbar, da sie zusätzliche
Quellenprüfungen und Freigaberegeln hat.

## KI-Generierung mit nachvollziehbaren Freigaben

1. Original-Arbeitsbild, Assetklasse (Gebäude, Einheit, Vegetation,
   HUD, UI), Gestaltungsziel, Erhaltungsregeln und Modell festlegen.
2. Offline ein ZIP mit `reference.png`, `model_reference.png`,
   `request.json` und Hilfetext erzeugen. SHA-256 des **genauen**
   request.json und der Bildquellen erfassen.
3. `tools/suite_ai_codex.py` prüft offline als Standard.
   Ein kostenpflichtiger Aufruf braucht zusätzlich
   `--execute --confirm-paid-requests <genaue Anzahl>`.
   API-Schlüssel nur aus Umgebung, keine Speicherung.
4. Jede Variante wird getrennt ausgegeben. Zusätzlich zu
   `variant_XX.png` gibt es `variant_XX_meta.json` mit
   Quelle, Modell-Behauptung, Request-SHA, Kandidaten-SHA und
   Rückregistrierungsangaben.
5. `run-status.json` wird atomar geführt. Die Zustände
   `running`, `partial_failure` und
   `candidates_ready_for_review` unterscheiden unterbrochene
   Aufrufe von vollständig erzeugten Varianten.
6. Der Editor akzeptiert bis zu vier PNGs, optional mit
   gleichnamigem `*_meta.json`. Manifest und beide Bilder
   müssen SHA- und schema-konsistent sein. Widersprüchliche
   Belege blockieren den Import, fehlende Belege bleiben
   ausdrücklich `unverified`.
7. Menschliche Sichtprüfung mit Original/Kandidat,
   Pixel-/Alpha-Differenz, dokumentierter Quelle und Vermerk.
   Erst dann wird **ein** Kandidat als neue Arbeitsbild-Version
   übernommen, mit Undo und SHA-gebundener Projekthistorie.
8. Niemals automatisches Patchen einer Spielinstallation,
   Signieren einer echten Provider-Antwort oder Freigeben
   einer HP-/Feuer-Schadensstufe aus einem generischen Sprite.
   Ein lokal kopierbares JSON-Manifest ist keine
   verifizierbare API-Signatur!

`run-status.json` enthält keinen API-Schlüssel und keine
Bildbytes, sondern nur Status und Quellnachweise. Der Adapter
verweigert Ausgaben direkt unter bekannten Spielverzeichnissen
und installiert keine Mods.

## Tests und Kompatibilität

Die vorhandenen Tests bleiben unverändert ausführbar.
Neue Tests:
- `extras/sprite-editor/tests/test_pivot_evidence.cjs`:
  exaktes Zinnenlineal-Format, Beschädigung, Doppelung,
  Pixel-/Pivot-Abgleich, geschützter SHA-Roundtrip und Undo;
- `extras/sprite-editor/tests/test_ai_workflow.cjs`:
  gemeinsame Referenzregistrierung, Auftrags-SHA,
  Kandidatenbelege, absichtlich gefälschte Metadaten;
- `extras/sprite-editor/tests/test_ai_browser.cjs`:
  echtes Offline-Edge mit Zinnen-Import, sichtbarer
  Ankerkorrektur, Undo/Redo, KI-ZIP, Metadatenabgleich,
  manueller KI-Abnahme und englischem Navigationsfragment;
- `tests/sandbox/test_suite_toolchain_inventory.py`,
  `test_suite_environment_discovery.py`,
  `test_editor_bridge_navigation_v2.py` und
  `test_suite_ai_codex.py`: synthetische Unity/Python/
  kostenpflichtige API-Schranken und unterbrochene Variantenläufe.

**Freigabestatus** wird nur aus im eigenen Zweig tatsächlich
ausgeführten Tests begründet. Alte Browserberichte gehören
zum jeweiligen früheren Build-SHA und dürfen nicht als
neue Tests gezählt werden.

## Explizit noch offen

- Ein vollständiges Review sämtlicher uncommitteter Funktionen
  aus allen anderen, teils großen Entwicklungszweigen;
- C#-Kompilierung und echte Script-Extender-/APIShared-/Serp-
  ABI-Bestätigung in der jeweiligen installierten Version;
- vollständige SHCDE-Spielklon-Abnahme der neuen Workflows;
- echte kostenpflichtige KI-API-Aufrufe ohne ausdrückliche
  Nutzerfreigabe (nicht ausgeführt);
- eine vollständige Vereinigung sämtlicher AIV/AIC/Audio/HUD-
  Spezialmodule. Diese benötigen separate Migrations- und
  Gameplay-/Build-Gates.

Alte Zweige und Spielinstallationen nicht löschen oder
überschreiben. Weiterführender Reviewauftrag:
`docs/CODEX_GESAMTAUDIT_KONSOLIDIERUNG_20261108.md`.
