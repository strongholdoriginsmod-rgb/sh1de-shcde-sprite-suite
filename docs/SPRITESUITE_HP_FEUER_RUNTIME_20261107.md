# HP- und Feuerschäden im Spiel

Das optionale BepInEx-Plugin beobachtet Gebäude-HP und Brandticks über SHCDE-SE.
Ein Postfix von `SpriteMapping.setGenericBuildingTileGraphic` ordnet die
ausgegebenen Grafikzellen dem gewählten Gebäudemodell zu. Das Plugin wählt die
passende Schadensstufe und aktualisiert die betroffene Unity-Tilemap. Die
Laufzeitkomponente schreibt keine Spiel-HP oder Brandwerte.

## Vom Sprite-Editor zur Runtime

1. Die mechanischen und feuerabhängigen Stadien im Sprite-Editor anlegen und
   als Schadensbibliothek exportieren. Entwürfe sind als Mod-Grafik verwendbar.
2. Mit `tools/building_damage_bindings.py` ein editierbares `runtime.json` aus
   einem gemessenen SpriteMapping-Protokoll erzeugen. `--global-id` wählt die
   beobachtete Referenzinstanz im Protokoll. Die Option `buildingGlobalId` in einer
   Bindung schränkt die Laufzeitzuordnung auf eine konkrete Gebäudeinstanz ein.
   Fehlt sie oder steht sie auf 0, gilt die Bindung für die passende Gebäudeart.
   Die vorgeschlagene Orientierung und überhängende Zellen anhand des
   tatsächlichen Grafikraster prüfen.
3. `tools/building_damage_package_check.py --archive <ZIP> --runtime-json <JSON>`
   zeigt fehlende Grafikdateien, abweichende Prüfsummen und fehlende Slots.
4. `tools/suite_building_damage_live_mod.py --game-root <Spielordner> --output <Buildordner>`
   kompiliert das Plugin gegen die Bibliotheken des gewählten Spiels. Für die
   Installation `--install --damage-archive <ZIP> --runtime-config <JSON>` ergänzen.
   Die gleichen Werkzeuge sind im Spezialwerkzeug-Index der Suite verfügbar.

Die Installation speichert das Plugin in
`BepInEx/plugins/SpriteSuiteBuildingDamageRuntime` und entpackt die Grafik in
`damageDirectory` aus der Konfiguration. Ohne Angabe heißt der Grafikordner
`DamageAssets`. Ein vorhandenes Grafikziel führt zu einem Fehler vor Austausch
der Plugin-Dateien. Bei einem fehlgeschlagenen Dateiaustausch stellt das
Installationsskript die vorherigen Dateien wieder her. Die Runtime benötigt
die entpackte Bibliothek, damit sie im Spiel ohne ZIP-Framework-Assembly läuft.

Die Bindung enthält bei Bedarf Eigentümer-Offsets für Grafikkacheln außerhalb
der Gameplay-Grundfläche sowie eigene Pivot- und PPU-Werte. Ohne diese
Überschreibungen übernimmt das Plugin die Werte des Originalsprites. Das
Bildmaterial verwendet seine PNG-Transparenz. Separate Masken und Teamfarben
sind im Laufzeitersatz noch offen.

Im laufenden Spiel werden `enabled`, der optionale Vorschaumodus, `pollFrames`
und `firePersistsUntilRepaired` aus einer aktualisierten Konfiguration übernommen.
Ein Austausch von Bindungen oder Bildbibliothek benötigt einen neuen Pluginstart.
Die Wiederherstellung schreibt das Originalsprite zurück, wenn die Tilemap
weiterhin das zuvor von SpriteSuite gesetzte Bild hält. Bei einer neuen
Engine-Zuordnung übernimmt das Spiel wieder die Kontrolle über die Grafik.

## Getrennte QA für echte Spielwerte

`runtime/StrongholdEuropeDE.BuildingDamage.LiveMod/qa/build_health_canary.ps1`
kompiliert einen separaten Testtreiber gegen die Spielbibliotheken. Er gehört
ausschließlich in eine Spielkopie mit eigenem Windows-/Steam-Spielerprofil und
einem kopierten QA-Spielstand. Der Treiber aktiviert sich nur, wenn
`SPRITESUITE_HEALTH_QA_ROOT` auf genau die gestartete Kopie zeigt und in deren
Stammverzeichnis eine Datei `.spritesuite-health-qa` mit dem Text
`SpriteSuite HP/fire QA with isolated player profile.` liegt. Für echte
HP-Beobachtung in `runtime.json` `previewEnabled` auf `false` setzen.

Der Testtreiber sucht im QA-Spielstand Instanz 661027 des Gebäudetyps 104 und
setzt nacheinander 60 Prozent HP, 30 Prozent HP mit Brand, 35 Prozent HP nach
dem Löschen und schließlich die Anfangswerte. Er protokolliert die
zurückgelesenen Spielwerte unter `SPRITESUITE_HEALTH_QA`. Die
`SPRITESUITE_DAMAGE`-Zeilen der Produktions-Runtime protokollieren unabhängig
davon den beobachteten Gesundheitszustand und den Austausch der Spritefelder.

## Prüfstand vom 7. November 2026

- Produktions-DLL und separater QA-Treiber gegen die Bibliotheken des markierten
  SHCDE-QA-Klons kompiliert. 33 C#-Assertions zur Stufenauswahl und Brandhistorie
  sowie 26 zur JSON-Verarbeitung bestanden.
- Der Paketaudit des synthetischen 8×8-Tests bestätigte 128 PNGs und 64 zugeordnete
  Slots. Der Installationsversuch mit Kopien der ABI-Bibliotheken bestand
  Neuinstallation, Unicode-Pfade, Zielkonflikt, erzwungenen Rollback und
  erneute Installation unter Erhalt der Grafikdateien.
- Das vorhandene In-Game-Protokoll mit SHA-256
  `57ec6022cc47d79ee19ee41caf4ee0383e94537c0c8b9304dda9e4dd02baf164` weist für
  den früheren Vorschaulauf je 128 mechanische und Feueranwendungen sowie
  Wiederherstellungen nach. Spielwerte in diesen Zeilen sind 100/100 HP und
  0 Brandticks. `tools/qa_hp_fire_live_log.py` reproduziert die Zählung.
- Der aktuelle Testtreiber wurde kompiliert. Die Profilisolation der
  vorhandenen Spielkopie ließ sich auf dem Rechner nicht bestätigen. Der
  Spieltest mit geänderten HP und Brandticks, die visuelle Prüfung sowie
  Kartenwechsel und Gebäude-Neubau im Spiel sind offen.
