# Gemeinsamer SpriteSuite-Integrationsstand – 6. November 2026

Dieser Stand wird in einem getrennten Git-Worktree unter
`E:\SpriteSuite_SharedIntegration_20261106` auf dem Branch
`integration/spritesuite-all-workstreams-20261106` vorbereitet.
Er baut auf dem geprüften Sprite-Editor-Commit
`10c79bef6f62335fbe46c0a9ad121292fc99729a` auf und schließt damit
den vorher veröffentlichten Python-3.15-/Guide-Quellstand
`dffce3f07b221cca6a308079e2cb6c2fc1be6474` ein.

## Getrennte Arbeitszweige – Koordination zwischen Chats

- `feature/sprite-editor-seam-overlap-20261106`: der abgeschlossene
  1-Pixel-Überlappungsfix, deckungsgleich mit `10c79be`. Tests für
  64-Pixel-Breite, sämtliche hinteren Reihen, Alpha/Materialmasken,
  verlustfreie Wiederausgabe, 155 Zufallsraster und Browserprüfungen.
- `feature/building-damage-workflow-20261106`: eigenständiger
  Gebäudeschaden-Workflow mit HP-Schwellen, mechanischen/Feuer-Stufen,
  Klonen der Basis-Tiles, sicherem Kandidatenimport und getrenntem
  Schadensmanifest. Nach dem ersten Snapshot hat der parallel arbeitende
  Zweig die echte Revision `76728355d3960c98e3c5c3691008ba783756d393`
  veröffentlicht. Sie wurde anschließend mit Merge-Commit `4a3d9c1`
  in die Integration übernommen; die neueren Browser-Tests und die
  eigene Gebäudeschaden-Anleitung stammen aus diesem Commit.
- `feature/stronghold-tool-consolidation-20261106`: kuratierte
  Spezialwerkzeug-Registry, navigierende Strg+K-Erweiterung und historische
  SHA-256-Werkzeugmatrix. Auch hier wurde ausschließlich der vorhandene
  **uncommittete** Stand als Snapshot übernommen.
- `feature/real-game-runtime-qa-20261105`: native Spielprüfung hat noch
  einen uncommitteten Noesis-Log-Analyzer. Dieser ist **nicht**
  Teil dieses Integrationsstands und darf ohne Test/Review nicht pauschal
  als sichere ABI-Freigabe interpretiert werden.
- Die älteren UX-/Handbuch-/Python-Arbeitszweige sind bereits in der
  aktuellen Basis enthalten; nicht erneut mit veralteten Dateien
  überschreiben.

Der erste Entwicklungs-Snapshot der Gebäudeschadenarbeit ist historisch
weiter protokolliert. **Aktuell gilt der echte, spätere Commit `7672835`
als Quelle für diesen Teil.** Der Werkzeugkonsolidierungsstand wartet
noch auf einen eigenen abgeschlossenen Git-Commit, bleibt aber als
nachvollziehbarer Snapshot im Integrationszweig.

Die unveränderten Ursprungsstände befinden sich unter
`E:\SpriteSuite_BuildingDamage_20261106` und
`E:\SpriteSuite_ToolConsolidation_20261106`.
Die zum Schnappschusszeitpunkt beobachteten Patch-Hashes:
- Werkzeugkonsolidierung `5752a19b3f3d87d85eb9390f48622854d8995968076293366407c8cc5be2c190`
- Gebäudeschaden `a7e6538c7aaae4644bc95043abb919c723ab53331fc5c9b437243d3f7080e557`

Die abgenommenen Eingangs-Patches liegen separat unter
`E:\SpriteSuite_SharedIntegration_QA_20261106\source_snapshots`;
die SHA-256-Inventur unter `SOURCE_SNAPSHOT_MANIFEST.json`.

Die anderen Bearbeitungs-Chats sollten **ihren jeweiligen** Branch fertig
committen und die exakte Commit-SHA sowie ihre Testausgaben angeben.
Erst danach die abgeschlossenen Unterschiede mit diesem Integrations-Branch
vergleichen. Nicht parallel in den Integrations-Worktree schreiben,
kein Force-Push, keine Änderung an `main`, Steam-Originalen oder fremden
Arbeitsverzeichnissen. Ein integrierter Snapshot übernimmt den
momentanen Entwicklungsstand, garantiert aber nicht, dass spätere
Änderungen auf dessen Quellbranch bereits enthalten sind.

## Zusammengeführter Funktionsumfang

Die zentrale SpriteSuite-Werkbank, DE/EN-Anleitungen und PDF,
Python-3.13-/3.15-Laufzeitanpassungen, der interaktive 26-Modul-Demo-Modus,
alle vorhandenen Grafikwerkzeuge sowie der Stronghold Sprite Editor bleiben
bestehen. Hinzu kommen der vollflächige 1-Pixel-Tile-Overlap,
der Gebäudeschaden-Workflow und die neue Werkzeugnavigation.

Gebäudeschadensausgaben sind zurzeit **Daten- und Grafikpakete**.
Ein echter Gameplay-HP-Hook, ein neuer nativer Unity-/Noesis-ABI-Nachweis,
ein autorisierter Ingame-Schadensstufen-Test und das Atlas-Rollback
werden durch den Codex-Kandidatenprozess oder den Browserexport
nicht ersetzt. Ein API-Test mit einem externen Bildmodell wurde
nicht durchgeführt. Die vorgesehenen Tests verwenden kontrollierte
Quellbilder und die absichtlich getrennte Bestätigung.

## Beobachtete QA nach dem Schnappschuss

- Kombinierter Node-Testlauf: **123 bestanden, 0 Fehler**. Darin
  enthalten sind Editor-Schnitt-/Alpha-/Overlappingschutz, 9 neue
  Gebäudeschadens-Tests, Format-/Export-/Projektroundtrips.
- Kombinierte Python-Werkzeug-/Codex-Gruppe: **29 bestanden, 0 Fehler**.
- Eigener vollständiger Edge-/file://-Gebäudeschadens-Test:
  12 nachvollzogene Stationen, einschließlich bewusst verweigerter
  Freigabe eines unveränderten Bildkandidaten; keine Netzwerkanfragen.
- Vorhandene Editor-Browserregression: **49 bestanden, 0 Fehler**
  einschließlich Downloads, Undo, Export, 64px-Overlap und
  Bildschirmgrößen.
- Sprite-Editor-Paketmanifest: **158 geprüfte Dateihashes**,
  einschließlich der eigenen Gebäudeschaden-Anleitung und des
  tatsächlichen Edge-Browser-Abnahmeberichts. Deutsch/Englisch
  werden reproduzierbar gebaut.
- Die erste größere Python-3.15-Kombinationsprüfung des neuen
  Integrationsstands zeigte einen **Tcl/Tk-9-Windows-Zugriffsfehler
  beim Schließen eines erneut geöffneten Lernassistenten**. Die
  bereits früher separat geprüfte experimentelle Python-3.15-
  Distribution wird dadurch nicht automatisch zur freigegebenen
  gemeinsamen Laufzeit. Es bleibt ein eigenständiges QA-Gate.
- Die vollständige Python-3.13-GUI-Suite und ein neu aus
  diesem Integrations-Commit gebautes Windows-Paket werden
  getrennt geprüft. Ein geschlossener Release-Gate-Bericht
  muss immer die tatsächlichen Ergebnisse enthalten.

## Gemeinsame Abnahme vor einem finalen öffentlichen Release

1. Node: alle Editor-, Overlap- und Gebäudeschadensverträge im
   zusammengeführten Quellstand.
2. Echte Browser: vorhandener 49-Prüfungen-Flow sowie zusätzlicher
   Gebäudeschaden-End-to-End-Lauf (DE/EN, HP, Codex-ZIP, Kandidat,
   manuelle Abnahme und separater Export).
3. Python/Tk/Qt: Gesamt-GUI-Regressionsgruppe plus neue
   Spezialwerkzeug-/Codex-Tests in der gebündelten Python-3.13-Laufzeit;
   ergänzende Python-3.15-Tests.
4. Git-Audit: eindeutig committed und sauber; Versionen aus
   reproduzierbarer Quelle, keine geheimen oder privaten Spieldaten.
5. Windows-Portable: neu aus exakt diesem Commit erstellt,
   SHA-256/CRC vollständig geprüft; frische Entpackung an kurzem
   Pfad samt GUI und Mod-ZIP-End-to-End.
6. Zusätzliche native Ingame-/Noesis-/Unity-, Rückbau-, Hardware-DPI-,
   unabhängige Windows-Zweitgeräte- und Rechteprüfungen bleiben bis
   zu ihrer tatsächlichen Durchführung ausdrücklich **offen**.

Die gemeinsame Codebasis ist ein **Release-Kandidat**, solange
diese Gates nicht abgeschlossen sind; es erfolgt keine automatische
native Spieleinstallation, kein `main`-Merge und kein Stable-Tag.
