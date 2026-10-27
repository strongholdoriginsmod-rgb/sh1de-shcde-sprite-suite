# Projektweiter Release-/Integritätsabgleich (nur lesend)

**Stand:** 11. Oktober 2026. Implementierung in Sprite Suite,
Branch: feature/sandbox-studio.

## Zweck

Der neue Abgleich prüft die **tatsächlich vorhandenen** BC7-Produktionsdateien,
statt lediglich einen älteren Testbericht oder Verzeichnisnamen als
Freigabe zu interpretieren. Er ist **kein** Builder, Installer oder Spieltest.

**In der Suite:** Suite starten.cmd → **Diagnose & Reparatur** →
Produktionsprofil wählen → **Gesamten Build prüfen (SHA-256)**.

Für zuvor ausdrücklich geprüfte Zinnenlineal-Korrekturen kann optional mit
**Pivot-Protokoll wählen …** genau eine Freigabedatei aus
work/reports/pivot-approval/ hinzugezogen werden.
**Ohne Pivot-Protokoll** ist der Standard. Historische Freigaben werden
nicht stillschweigend als aktueller Releasevertrag behandelt.

**Auf der Kommandozeile** (aus E:\SpriteSuite):

~~~powershell
.\.venv\Scripts\python.exe tools\qa_release_preflight.py --profile sprite-suite-world-bc7-v2 --check-only
.\.venv\Scripts\python.exe tools\qa_release_preflight.py --profile sprite-suite-world-bc7-v2
.\.venv\Scripts\python.exe tools\qa_release_preflight.py --profile sprite-suite-world-bc7-v2 --approval "work\reports\pivot-approval\FREIGABEBERICHT.json"
~~~

Der erste Befehl ist strikt lesend; die übrigen schreiben **ausschließlich
einen neuen Prüfbericht** unter work/reports/release-preflight/.
Identische Eingaben ergeben denselben inhaltsadressierten Bericht.
Keine Spieldatei, ursprüngliche Sprite-Quelle, Arbeitsgrafik, BC7-DLL,
Atlasdatei oder Profil wird geändert.

## Geprüfte Verträge

1. **Profil:** gültige Profil-ID, JSON-Schema, eindeutige GM-Gruppen,
   Mod-Metadaten und Atlas-Backend; SHA-256 der gesamten Profilquelle.
2. **Auslieferungsmanifest:** Schema, Profil-ID, Mod-Metadaten,
   eindeutig normalisierte relative Dateinamen und vollständige
   SHA-256-/Größenprüfung **aller** deklarierten Dateien einschließlich
   DLL und sämtlicher BC7-Bundles. Links/Junctions, Verzeichnisfluchten,
   zusätzliche Dateien und fremde leere Ordner werden abgelehnt.
3. **BC7-Index:** SHA-256 des echten
   Runtime/AssetBundles/index.json gegen das Manifest; jede Gruppe
   gegen das Profil und jedes Bundle gegen Pfad/Kategorie/SHA im Manifest.
   Nicht referenzierte oder fehlende Bundle-Dateien werden gemeldet.
4. **Frühere Validierung:** Das vorhandene
   work/reports/<profil>-validation.json ist ausdrücklich ein
   **historisches Testergebnis**. Weil es keinen SHA-256 des aktuellen
   Buildmanifests als Quellbindung enthält, kann es **nicht** beweisen,
   dass genau dieser Build die damaligen Prüfungen bestanden hat.
5. **Optionaler Pivot-Entscheid:** Nur ausdrücklich gewählte Berichte
   mit dem erwarteten Schema und Quelle „geliefert“ werden verglichen.
   Der Prüfer löst keine beliebigen Dateipfade aus dem JSON auf;
   stattdessen rekonstruiert er den realen Index/PNG-Pfad unter
   work/katalog/geliefert und prüft gespeicherte SHA-256-Werte
   und Ausgangs-/Zielpivots. Veraltete Daten blockieren,
   valide ausstehende Metadaten-Übernahmen bleiben eine **Warnung**.
   Eine Freigabe ist niemals eine unmittelbare Schreibberechtigung.

Die Ergebnisse erscheinen in der normalen Diagnose-Tabelle
(Prüfung „Release“, mit Status **Fehler/Warnung/Info**).
Ein Doppelklick auf einen Release-Befund startet kein Programm und
behandelt den Befund nicht als Sprite. Die Dateiüberprüfung läuft
in einem Hintergrundthread, damit Tk/Qt bedienbar bleiben.

## Lokaler Ausgangsstand

Der echte lokale --check-only-Aufruf am 11.10.2026 für das
Produktionsprofil sprite-suite-world-bc7-v2 bestätigte:

| Prüfbereich | Ergebnis |
| --- | --- |
| Manifest-Dateien | **154 / 154** SHA-256-/größenidentisch |
| Verifiziertes Gesamtvolumen | **675.908.516 Bytes** |
| Spritegruppen | **149**, in Profil/Index/Manifest konsistent |
| Fremde Dateien/Ordner | Keine |
| Frühere Validierung | **1.009 bestanden, 0 fehlgeschlagen** (historisch) |
| Explizites Pivot-Protokoll | Keines gewählt |
| Offline-Integrität | **offline_ok**, 0 Fehler, 0 Warnungen |

Das bestätigt die lokale Integrität des vorhandenen Baukandidaten,
**nicht** die grafische und funktionale Richtigkeit im laufenden Spiel.

## Bewusste Grenzen

- Keine Installation und kein Austausch von BepInEx/plugins.
  Kein Spielprozess-/Kartenwechseltest und kein Langzeittest.
- Kein erneuter Unity-/BC7-Encoder-Bau; keine neue Aussage über
  Shader-/Wasserparität und komplette Gameplay-HUD-Simulation.
- Keine automatische Pivotkorrektur. Ein eigenständiger, abgesicherter
  Metadaten-only-Pivot-Releasevertrag bleibt noch zu implementieren.
- Das Buildmanifest bindet nicht die **gesamte** Profilquelle
  bitgenau. Deshalb ersetzen Profilidentität und Quell-SHA-Snapshot
  keinen reproduzierten Neuaufbau.
- Das Pivotprotokoll ist eine dokumentierte Sichtprüfung, keine
  digitale Signatur der verantwortlichen Person.

**Sicherheit:** Manipulierte, fehlende, verlinkte oder zusätzliche
Artefakte und inkonsistente Bundlegruppen führen zu **blockiert**.
Ein fehlender alter Validierungsbericht ist eine Warnung. Ohne
explizites Freigabeprotokoll wird Pivot-Übernahme als **nicht geprüft**
ausgewiesen, nicht als freigegeben.

## Pivot-Metadaten als unveränderlicher BC7-Stufenentwurf

Auf den vollständigen Integritätsabgleich baut der separate
[Pivot/BC7-Stufenvertrag](PIVOT_BC7_STUFENPLAN.md) auf.
Er verlangt zusätzlich eine ausdrücklich ausgewählte Originalmessdatei,
rekonstruiert alle Freigabezeilen und prüft die ursprünglich
beabsichtigten Koordinaten gegen den aktuellen gelieferten Index.
Zusätzlich sucht der neue Prüfer **genau das Cache-Atlasobjekt**, das
sowohl in Bundle- als auch Atlas-SHA-256 zum veröffentlichten
Index passt. Bereits im echten BC7 korrigierte Frames werden
ausgeschlossen; nur für übrige wird eine theoretische V2-Metadatenhash-
und Gruppencache-Key-Änderung berechnet. Fehlt die unveränderliche
Cachequelle, bleibt deren Provenienz ausdrücklich **unverifiziert**.
Das Ergebnis ist weiterhin kein ausführbarer Bundle-/Indexpatch.

## Nativer Originalmapping-/Geometrieabgleich

Auf der SHA-gebundenen Releaseprüfung baut außerdem der
[originale Native-Geometrie-Beweis](PIVOT_NATIVE_PROVENANCE.md)
auf: Das in der Produktion verwendete Mapping wird mit dem
veröffentlichten, exakt cachegebundenen BC7-Atlas verglichen.
Die beiden im Profil eingefrorenen nativen Geometrie-/RGBA-
Nachweise und die Herkunfts-/Reviewpartition werden für
die 95 SH1DE- und 11 beibehaltenen Crusader-Frames erneut
exakt rekonstruiert. Das ist ein Nachweis des bestehenden
Ausgabestands, nicht eines neuen BC7-Neubaus.

## Tests

- tests/sandbox/test_release_preflight.py prüft vollständige und
  manipulierte Artefakte, unsichere Pfade, veränderte Dateimengen,
  unbenutzte Bundles, Profil- und Indexdrift, Pivot-Provenienz,
  Idempotenz und CLI.
- tests/sandbox/test_release_preflight_gui.py prüft die asynchrone
  Bedienung im Tk-Hauptfenster ohne Installationsbefehle.
- tools/qa_suite_embedded.py prüft zusätzlich echte Windows-Tk/Qt-
  Einbettung und Erreichbarkeit des Release-Prüfknopfs.
