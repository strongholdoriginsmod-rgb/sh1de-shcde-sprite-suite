# Runtime-Konsolidierung vom 8. November 2026

Der kanonische Arbeitsstand übernimmt RC3 mit den zusätzlichen Nachweisen aus
dem lokalen Abschlussaudit `b91e3a7`. Die öffentlichen RC3-Quellen enthalten
bereits Originalreferenz, native SHSprite-/ORA-Projekte und unabhängige
Schadensentwürfe. Der direkte Git-Vergleich von `46250d2` und `673eb09`
ergab für diese Werkzeuge und die Runtime-Tests gleiche Inhalte.

## Übernommene Verbindungen und Korrekturen

- Die Live-Runtime protokolliert die Zuweisung an `GameMapTile.tileImage` als
  `sprite_field_written=true`. Erst ein passender Rücklesewert von
  `Tilemap.GetSprite` erzeugt `stage_tilemap_verified`.
- Beide Protokollauswertungen verknüpfen den Nachweis mit der richtigen
  Gebäudeinstanz, Phase und Grafikzelle. Der allgemeine Logprüfer verlangt eine
  vorausgegangene passende Zuweisung mit denselben HP-/Brand-/Vorschauwerten.
  Wiederherstellung und Kartenwechsel beenden diese Zuordnung.
- Der RC3-Beobachter behält seine Zählung je Instanz, bis zu 40 Grafikberichte,
  die Unterstützung für 8×8-Gebäude, die Stichprobengröße und die Behandlung
  einzelner fehlgeschlagener Tilemap-Abfragen.
- Die allgemeine Bindungs-CLI kann ein Schadensarchiv oder explizite
  `--grid-a`/`--grid-b` verwenden. `--expected-log-sha256` ist optional.
  Unvollständige Grafikprotokolle und unaufgelöste Überhänge bleiben als
  editierbare Vorschläge mit ihrer Provenienz erhalten. Eine neu erzeugte
  Vorschlagsdatei startet mit `enabled=false`.
- `building_damage_native_bindings.py` bietet zusätzlich den spezialisierten,
  SHA-geprüften 16-Slot-Kornkammer-Nachweis aus dem Abschlussaudit. Er ergänzt
  das allgemeine Zuordnungswerkzeug.
- Die Beispielkonfiguration startet leer und deaktiviert. Eine solche noch
  unkonfigurierte Installation kann ohne Bildbibliothek geladen werden.
  Bisherige explizite Konfigurationen und ihre Aktivierung bleiben verwendbar.
- Grafikdateien aus der Bibliothek werden innerhalb ihres konfigurierten
  Assetordners aufgelöst. Der gewählte Assetordner kann weiterhin an einem
  eigenen absoluten oder relativen Pfad liegen.
- Der Installer-Test behält den Unicode-tauglichen ASCII-CMD-Aufruf des
  aktuellen Python-Interpreters über eine Umgebungsvariable.

## Ausgeführte Prüfung

Im zusammengeführten Arbeitsstand bestanden 104 fokussierte Pytests sowie
zwei weitere Tests für die erweiterte Bindungs-CLI. Die fünf nativen
SHSprite-/ORA-/Schadensentwurf-Tests unter Node bestanden ebenfalls.
Die beiden C#-Konsolenprüfer bestätigten 33 HP-/Brand- und 26 JSON-Assertions.

Produktionsplugin, getrennter Health-QA-Treiber und Readonly-Rendererbeobachter
wurden gegen die vorhandenen SHCDE-Bibliotheken kompiliert. Die Spielassembly
hat SHA-256 `bc8b6a395f01d48557db413600c8dd8d1fdfd3abdf97bfbbb68a3c56b04fd789`,
SHCDESE `5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498`.
Die Kompilierung installierte keine Plugins und startete keinen Spielprozess.

## Vorhandene Spielnachweise und offene Arbeit

Das am 8. November bereits vorhandene QA-Protokoll mit SHA-256
`a67f7dad80fb33124725e323c3917078713413c67ff89d128195eb2e8a329ad9`
enthält den nativen Übergang des Testobjekts von 100 auf 60 HP. Die
Mechanical-Phase brach anschließend ab. 36 unabhängig abgetastete
Footprint-/Terrainzellen zeigten keine passenden Schadenssprites. Das
Baseline-Bild zeigt den Ladebildschirm. Die komplette HP-/Feuer-/Reparatur-/
Kartenwechsel-/Neubau-Sequenz bleibt damit offen.

Der Spielstand der QA-Kopie hat weiterhin SHA-256
`d29716f6fa72fc440607b3910f16eefb0abb8ee0743d060e3e93fd13f1fb24c7`.
Historische 128 Vorschauzyklen belegen die beobachteten Feldwechsel. Für
einen erfolgreichen visuellen Gebäudeschaden-Nachweis müssen die tatsächliche
Grafikschicht, ihre Zuordnung und die sichtbaren Screenshots im Spiel
zusammenpassen.
