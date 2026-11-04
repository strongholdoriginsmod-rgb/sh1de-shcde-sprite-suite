# SpriteSuite 2.0.0 – konsolidierter Release-Kandidat (4. November 2026)

**Status: technischer Release-Kandidat, nicht als Stable freigegeben oder veröffentlicht.**
Dies ist die Prüf- und Übergabegrundlage, nicht die Behauptung einer unabhängigen Ingame-Abnahme.

## Quellstand

- Integrationsbasis: `integration/spritesuite-unified-20261104`, Commit `7b778dc45972bfb24c2a9b4be584509d68dd45e3`.
- Geprüfter Arbeitszweig: `release/spritesuite-v2-reviewed-20261104`. Den exakten Commit vor einem Paketbau mit `git rev-parse HEAD` abgleichen.
- Anwendungsversion: unverändert `2.0.0`. Kein neuer öffentlich freigegebener Versions-Tag.
- Veröffentlichung und GitHub-Merge erfordern gesonderte Zustimmung und bestandene Freigabekriterien. Es wurde keine Originalspielinstallation verändert.

## Konsolidierung und Herkunft

Der Integrationsstand enthält die älteren, versionierten Funktionen der UI-Modernisierung, HUD-/Menüwerkstatt, Projektübertragung, Origins-/Noesis-Bearbeitung, Demo-Module, Windows-Portable-Laufzeit und lesenden Steam-Versionserkennung. Die separat überprüften älteren GitHub-Zweigspitzen sind Vorfahren des Integrationsstandes; ein blindes Cherry-Pick älterer Commits würde vorhandene Schutzprüfungen gefährden.

Die uncommitteten Änderungen der älteren Origins- und Steam-Arbeitskopien sind großteils bereits byteidentisch; die wenigen abweichenden Fassungen wurden anhand der neueren Eingriffe verglichen. Der ältere GitLab-Sandbox-Baum enthält abweichende historische Werkzeuge und Tests sowie temporäre HUD-Dateien; diese werden nicht ungeprüft in die aktuelle Fassung kopiert. Ein älterer HUD-Noesis-Editor steht dem neueren, umfangreicheren Layout-Editor gegenüber. Das Ausgangsprojekt bleibt unangetastet.

## Verbesserungen im geprüften Release-Zweig

- GitHub-Kernprüfung läuft für die offiziell unterstützten Python-Versionen 3.13 und 3.14 statt der nicht unterstützten Version 3.11.
- Jede CI-Python-Version installiert ihre eigene hashgesicherte, versionierte Abhängigkeitsliste anstelle einer unvollständigen Auswahl.
- Deutsche und englische Downloadhinweise unterscheiden die noch nicht freigegebene 2.0.0-Fassung ausdrücklich von dem früheren öffentlichen Portable-Paket.
- Getrennte, maschinenlesbare Release-Prüfungen und lokale Testlogs werden außerhalb der Paketquellen archiviert.

## Paketbau und Selbsttests

```powershell
python tools/build_portable_windows.py --python-home "<Windows-CPython-3.13-Home>" --venv "<dedizierte-3.13-venv>" --out "<NEUES-Ausgabeverzeichnis>"
# ZIP ganz entpacken, keine externen Python-Installationen voraussetzen
& ".\SpriteSuite\Suite starten.cmd" --self-test
```

Der Builder verpackt ausschließlich versionierte Git-Quellen und explizit erlaubte Python-Laufzeit-/venv-Dateien. ZIP-Hash, ZIP-CRC, die Commit-Bindung in `PORTABLE-BUILD.json`, Launcher, GUI, Projektarchive und Mod-Exporte sind gesondert zu prüfen. Ein grüner Test mit synthetischen Daten beweist keine native Spielintegration.

## Dokumentierte Freigabesperren

Eine **öffentliche Stable-Freigabe** bleibt gesperrt, solange nicht nachweisbar:

1. Unabhängiger grüner GitHub-Windows-CI-Lauf auf dem endgültigen Commit für Python 3.13/3.14 (inklusive aller Tests und begründeter Skips).
2. Start- und Bedienprüfung auf einem zweiten, unabhängigen Windows-Rechner mit vollständig neu entpacktem Paket.
3. Native Noesis-/C#-ABI- und echte Ingame-Prüfung für die konkret unterstützten Spiele-/Script-Extender-Builds; keine bloße Buildkennungs- oder Renderbehauptung.
4. Sicherer Mod-Installations- und Atlas-Rollback-Nachweis in einer autorisierten QA-Spielkopie.
5. Manuelle HUD-/DPI-/Tastatur-/Screenreader-/Langzeit-Abnahme sowie fachliche Rechteprüfung für weiterzugebende Projektassets.

Der maschinenlesbare `tools/suite_distribution_gate.py` blockiert fehlende oder übersprungene Nachweise absichtlich. Menschliche Freigabe ist zusätzlich erforderlich. Vorgehen: `docs/MANUELLE_RELEASE_ABNAHME_2026-10-31.md`.

## Start und Grenzen

Windows-x64: `SpriteSuite\Suite starten.cmd`. Projekt und eigene Bilder/XAML bearbeiten, Revision und Projekt-ZIP sichern, Export anhand des Manifests prüfen. **Kein** automatischer Mod-Einbau in Originalspiele. Unbekannte Steam-Builds bleiben ohne bestätigtes Mapping schreibgeschützt.

Die Ergebnisse des aktuellen technischen QA-Laufs (Commit, Testzahlen, Hash und eventuelle Fehlschläge) werden mit dem gebauten Paket in einem **separaten Release-Auditbericht** dokumentiert, damit diese Datei nicht durch sich selbst den Quellcommit verändern muss.
