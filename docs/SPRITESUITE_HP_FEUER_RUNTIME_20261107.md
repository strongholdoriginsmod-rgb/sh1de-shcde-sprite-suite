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
kompiliert einen separaten Testtreiber. Er gehört ausschließlich in eine frische
Spielkopie mit isoliertem Windows-/Steam-Spielerprofil. Der Treiber nutzt das
festgelegte QA-Beispiel mit Typ 104 (Teich) und Gebäudeinstanz 661027. Die beiden
Stufen des synthetischen Beispiels heißen `qa_mechanical75` und `qa_fire40`.

1. Den QA-Spielstand als `SpriteSuite_QA_Saves/SpriteSuite_Damage_Test.sav` in
   die Spielkopie legen. Die Datei bleibt lesend geöffnet. Der Test schreibt
   während des Spielbetriebs kontrolliert in die echten HP- und Brandfelder.
2. Das Produktionsplugin mit der 8×8-QA-Bibliothek und ihren 64 Bindungen
   installieren. In `runtime.json` `previewEnabled` auf `false`,
   `firePersistsUntilRepaired` auf `true` und `pollFrames` auf `6` setzen.
3. Den separaten Treiber in einen eigenen BepInEx-Pluginordner legen. Im
   Stammverzeichnis der Kopie `.spritesuite-health-qa` mit dem Text
   `SpriteSuite HP/fire QA with isolated player profile.` anlegen.
4. Für den Spielprozess `SPRITESUITE_HEALTH_QA_ROOT` auf den Pfad der Kopie
   und `SPRITESUITE_HEALTH_QA_SAVE_SHA256` auf die Prüfsumme des kopierten
   Spielstands setzen. Optional beendet `SPRITESUITE_HEALTH_QA_QUIT=1` das Spiel
   nach dem Ergebnis mit Rückgabecode 0 oder 1. Eine zweite automatische
   Ladehilfe würde mit dem QA-Treiber konkurrieren.
5. Nach dem Spielstart `SPRITESUITE_HEALTH_QA` und `SPRITESUITE_DAMAGE` in
   `BepInEx/LogOutput.log` beobachten. Der Treiber lädt den geprüften Spielstand,
   durchläuft 60 Prozent HP, 30 Prozent HP mit Brand, 35 Prozent nach dem
   Löschen und vollständige Reparatur. Danach prüft er erneutes Kartenladen
   mit aktiver Branddarstellung, entfernt und erstellt den Testteich in der
   laufenden Sitzung erneut und lädt abschließend die unveränderte Save-Kopie.
6. Mit `tools/qa_hp_fire_game_evidence.py --log <LOG> --evidence-root <SPIELKOPIE/SpriteSuite_QA_Evidence> --save-sha256 <SHA256> --output <JSON>`
   die Beobachtungen, nativen Ladeereignisse und PNG-Dateien prüfen. Die
   Auswertung unterscheidet nachprüfbare Unity-Tilemap-Zustände und
   vorhandene Screenshots von einer manuellen visuellen Abnahme.

Für jede beobachtete Phase werden Spielwerte, Gebäude-ID, Zahl der verglichenen
Spritefelder und passende Ausgaben von `Tilemap.GetSprite` aufgezeichnet.
Beim Kartenwechsel verwirft die Produktions-Runtime die alten Zuordnungen
und die Brandhistorie auch dann, wenn das Spiel dieselbe `GameMap`-Instanz
weiterverwendet. Der QA-Treiber speichert keine Veränderungen am Spielstand.

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
- Der erweiterte Testtreiber mit echtem Spielwertzugriff, Unity-Tilemap-Abfrage,
  Screenshotaufnahme, Kartenwechsel und Neubau wurde gegen den QA-Klon
  kompiliert. Der Test der Auswertungslogik verwendet synthetische
  Ereignisfolgen. Der reale Durchlauf und die manuelle Bildprüfung benötigen
  einen erfolgreichen Spielstart im isolierten Profil.
