# Codex-Auftrag – vollständiges SpriteSuite-/SHCDE-Audit mit sicherer Zusammenführung

Du arbeitest an der echten autorisierten Windows-Arbeitsstation mit mehreren
SpriteSuite-Worktrees. Dies ist ein **Ausführungsauftrag** mit strikten
Erhaltungs-, Vergleichs- und Test-Gates, kein bloßer Entwurf. Entwickle
in einem abgeschlossenen, nachvollziehbaren Durchgang so weit wie sich
sicher beweisen lässt; nenne jede verbleibende Lücke, keine fiktiven
Spieltests oder pauschalen „perfekt“-Versprechen.

## A · Schutz der Entwicklungsarbeit (nicht verhandelbar)

1. Gerätezugriff, freie Laufwerke, Git-Repository(s), Worktree-Topologie,
   Commit-Hashes, Remotes, Submodule, Tags, Git-LFS und Konfigurationszustände
   ausschließlich **lesend** entdecken.
2. In **jedem** Worktree `git status --porcelain=v1`, `git diff --stat`,
   `git diff --cached --stat`, untracked-Dateien, stashes, Merge-/Rebase-
   Zustände, Branchtracking und Basishashes protokollieren.
3. Vor einer Bearbeitung uncommittete, auch untracked und ignored-relevante
   Quell-/Konfigurationsänderungen in einem getrennten archivierten
   Schnappschuss mit SHA-256-Manifest sichern. Keine Spiel- oder
   Benutzerprofile im Archiv sammeln, sofern nicht nötig.
4. Einen separaten Arbeitszweig/Worktree am abgesprochenen Release-Basishash
   erzeugen; bestehende Arbeitsstände weder überschreiben noch bereinigen.
5. **Nicht ausführen:** `reset --hard`, `clean -fd(x)`,
   `worktree remove --force`, rekursive Löschung, blindes `git branch -D`
   oder pauschales Cherry-Pick aller Änderungen.

## B · Vollständiger Versions- und Funktionsvergleich

Erstelle ein maschinenlesbares Inventar von:
- Quellversionen, Commitgraph, Branch-Inhalten, uncommitteten Modulen,
  Konfigurationsdateien, Dokumentation, kompilierten Artefakten;
- Quellhash, Herkunftsbranch, Erstellungsdatum (wo nachweisbar),
  funktionalen Einstiegspunkten, Nutzern, Ausgabeverträgen und Tests;
- gleichnamigen Tools mit anderen Funktionen sowie unterschiedlich benannten
  Implementierungen identischer Funktionen;
- Features, die im neueren Stand fehlen, aber in alten Branches nutzbar
  und getestet waren.

Vergleiche nicht bloß Dateinamen: untersuche Funktions- und API-Verträge,
CLI-Parameter, Tk-/Web-GUI-Routen, Runtime-Callbacks, Ressourcenmanifest,
BC7-/DDS-/PNG-Verhalten, Spiel-IDs, Unity-Objektadressen, Export-/Import-
Provenienz und Auswirkungen auf Undo/History/QA. Für uncommittete Varianten
erstelle separate synthetische Patch-Diffs, nicht stillschweigend Git-Commits
in fremden Worktrees.

Kategorisiere jedes Feature:
**übernehmen / vereinheitlichen / weiter als Adapter behalten /
aufgeben mit Beleg / zurückstellen mit Blocker**.
Bewerte nach Nutzerwert, Codequalität, Regression, Risiko, Wartung
und Nutzungsbeleg. Verlinke genaue Hashes/Testnachweise.

## C · Architektur mit geteilten Primitive-Komponenten

Ziel sind wenige stabile, öffentlich gut dokumentierte Funktionen:
- Pixelkoordinaten, Anker/Pivot, isometrische Grundlinie,
  Raster/Zinnenmaß, Snap/Geometrie, Überlagerung, Messungen,
  Layers und Bildtransformationen;
- Sprite-/AIV-/AIC-/AIP-/Animation-/Audio-/UI-Datenmodelle,
  Vorschau, Metadaten, Validatoren, Diff, History, Transaktionen;
- Game-Asset-Discovery, Script-Extender- und BepInEx-Adapter,
  Capability-Manifest und nicht-invasive Runtime-Instrumentierung;
- gemeinsame Renderer-/Tile-/HP-/Feuer-Adapter für Gebäudezustände;
- gemeinsame Build-, Diagnose-, QA-, Paket- und Provenienzschicht.

**Nicht** alle historischen Toolnamen sofort löschen: saubere
Kompatibilitätswrapper mit klaren Deprecation-Hinweisen erhalten
bestehende Batchskripte, Savegames und Im-/Exporte. Jede neue gemeinsame
Funktion benötigt ein einziges fachliches Zuständigkeitsmodul.

## D · Automatische Spiel-/Toolchain-Erkennung

Übernimm `tools/suite_environment_discovery.py` und
`tools/suite_center.pyw` aus dem Zweig
`feature/spritesuite-editor-ai-discovery-20261108` nach Review.
Ergänze kontrollierte Erkennung für:
SHDE, SHCDE und QA-Klone, Steam-Libraries und explizite Overridepfade,
Unity-Editor/IL2CPP-/Mono-Layout, BepInEx, Script Extender, APIShared,
Serp/baseline, Python-Interpreter/virtuelle Umgebungen,
.NET-SDK und native Compiler.
Aus Datei-/Pfadfunden niemals API-Kompatibilität behaupten:
Hash, Versionsmanifest, binäre Metadaten, tatsächliche
Export-Signaturen, sichere C#-Kompilierung und QA-Spielstart trennen.
Keine automatische Installation, keine Ausführung gefundener EXE/DLL
und keine Anpassung von Windows-Policies.

## E · SHCDE-Modding-Schnittstellen erforschen

Codebasiert und mit aktueller Maintainer-/Projektquelle prüfen:
Script-Extender-Hooks, APIShared-Settings, Serp-/baseline-Erweiterungen,
Daten-Prefab-/Gameplay-Änderungen, Einheiten, Lords, AIC, AIV,
Trigger, Kamera, HUD (Noesis), AssetBundle, Audio, Pfadsuche,
Tilerenderer, HP/Feuer und Savegame-Sicherheit.
Capability-Tabelle mit:
`Name | unterstützte Version | Fundstelle | Signatur | Read/Write |
Risiko | Plugin-Build | QA-Beleg | Fallback`.
Keine nicht belegten API-Aufrufe oder erfundenen DLL-Methoden.
Alle Runtime-Hooks nur im isolierten QA-Klon testen.

## F · Durchdachter KI-Asset-Workflow

Übernimm und überprüfe `extras/sprite-editor/src/ai_workflow.js`,
`tools/suite_ai_codex.py`, den gemeinsamen Geometrie-Inspector,
`io.js`-Herkunftsdaten und `tests/test_ai_browser.cjs`.
Führe einheitlichen Workflow für Gebäude, Einheiten, Animationsframes,
Vegetation, HUD/UI, Texturnachbearbeitung ein:
`Briefing → Referenz-SHA → Prompt/Erhaltungsregeln → registrierte
Modellvorlage → explizite Kostenfreigabe → Varianten → Nearest-
Neighbor-/Alpha-Prüfung → side-by-side-Review → Abnahmevermerk →
Undo → Export/QA`.
Jede Variante und jede Produktionsstufe erhält getrennte Prüfdaten,
kein direkter bezahlter Netzwerkzugriff aus dem Offline-HTML,
keine gespeicherten Schlüssel, keine automatische Spieländerung.
Geschützte Originale und Frame-Anker dürfen nicht stillschweigend
transformiert werden. Spezifische HP-/Feuer-Freigaben bleiben strenger.
Modelle, Endpunkte und Preise an aktueller API-Dokumentation
verifizieren; Dry-run vor jeder bezahlten Ausführung.

## G · Änderungen in kleinen, testbaren Paketen übernehmen

Nur Änderungen mit positivem funktionalem/technischem Befund und
Einzeltests in den isolierten Integrationszweig übernehmen.
Statt pauschalem Branch-Merge gezielt `git show`/`git apply`/
`cherry-pick` auf bewiesene Commits oder geprüfte Patch-Hunks
verwenden. So bleiben uncommittete Paralleländerungen unberührt.
Ergänze Migrationstests für alte Projekt-/Mess-/Sprite-Dateien,
Einheitentests, CLI-Regressionsmatrix, Buildprüfungen,
Sprachumschaltung und UI-Tests auf großen und mobilen Viewports.

## H · Verifikationsgates

Mindestgates:
1. Python-/Node-Syntax, Datenmodell- und Parser-Fuzz-/Adversarial-Tests.
2. Browser: echte `file://`-Starts DE/EN ohne JS- oder Netzfehler,
   alle vorhandenen 49 UI-Szenarien + 16 Damage-Szenarien sowie
   den KI-/Geometrie-Smoketest; Rebuild-Hashes exakt festhalten.
3. Native C#-/Unity-Plugin-Builds mit dokumentiert passender Toolchain.
4. Kein unbeabsichtigtes Gameplay- oder Original-Asset-Overwrite;
   Rollback reproduzierbar.
5. SHCDE-Build/HP-/Feuer- und Rendering-Tests nur auf QA-Klon;
   Lognachweis plus überprüfte Vorher-/Nachhergrafik.
6. Release-Manifest, DE/EN-Artefakte, Hashliste und Benutzeranleitung
   reproduzierbar und intern konsistent.

Bei fehlender Abnahme nicht „produktionsfertig“ behaupten.
Unklare Capability als `unverified` kennzeichnen, nicht raten.

## I · Finalintegration, Archive und späteres Löschen

Erst nach vollständigen Grün-Gates:
- Übersicht der im Zielzweig enthaltenen Funktionen samt
  Provenienz der Altzweige und bewusst ausgelassenem Code ausgeben.
- Gemeinsam genutzte Module und GUIs als eine testbare Release-App bauen,
  differenzierte Kosten-/QA-Gates beibehalten.
- Archivierbare, gehashte Backups aller aufgegebenen Worktrees
  separat ablegen und deren Restore-Probe dokumentieren.
- Exakte zu löschende Branch-/Worktree-Liste mit Reviewstatus,
  verbleibenden Referenzen und gesicherten Dateihashes erzeugen.
- Löschung **nur** für nachweislich redundant gewordene und freigegebene
  alte Zweige; produktiven Final-Zweig nie löschen. Bei ausstehenden
  Nutzdaten keine Löschung, auch wenn Branchname „old“ enthält.

## J · Abschlussartefakte

Erstelle `docs/BRANCH_AUDIT.md`, `docs/FEATURE_MATRIX.md`,
`docs/SHCDE_CAPABILITY_MATRIX.md`, `docs/AI_PIPELINE_QA.md`,
`docs/RELEASE_GATES.md`, `docs/KNOWN_LIMITATIONS.md`;
einen Statusbericht mit neuen Commit-IDs, tatsächlichen Tests,
Risiken, Backup-SHA-256, nicht migrierten Funktionen und exakter
Merge-/Delete-Entscheidung.

**Wichtig:** Perfektion ist kein überprüfbarer Endzustand. Ziel sind
nachweisliche Funktionsvollständigkeit für definierte Anwendungsfälle,
geringe Code-Duplikation, nachvollziehbare Fehlergrenzen, sichere
Freigaben und eine reproduzierbare funktionierende SpriteSuite.
