# SHCDE Gebäudeschaden – echter In-Game-QA-Start, 06.11.2026

Implementiert: `runtime/StrongholdEuropeDE.BuildingDamage.LiveAudit/BuildingDamageLiveAudit.cs` als separater, **nur lesender** BepInEx-Beobachter. `tools/qa_building_damage_live.py` kann ihn mit der exakt geprüften QA-Spielkopie kompilieren, optional ausschließlich dort installieren, Logs auswerten und anhand SHA-256-gebundener Belege vollständig zurückbauen. Sechs Offline-Tests kontrollieren Version, Marker, eindeutige Installation, Rückbau und Logbewertung.

## Tatsächlich getesteter lokaler Spielstand

- Isolierter QA-Klon: `E:\SSLiveGame_20261105` mit exakter Markerdatei `.sprite-suite-qa-copy.marker`.
- Script Extender SHCDESE 2.14.3, SHA256 `5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498`.
- Game Assembly-CSharp SHA256 `bc8b6a395f01d48557db413600c8dd8d1fdfd3abdf97bfbbb68a3c56b04fd789`.
- Der lokale Compiler erzeugte ein 13-KiB-Plugin gegen echte lokale BepInEx, Harmony, Unity, Game- und SHCDESE-DLLs. Das Plugin änderte keine Originaldateien.
- Erster realer QA-Start: BepInEx lud den Plugin-Typ, aber seine eigene Versionsprüfung verweigerte die Aktivierung, da `Assembly.Location` im laufenden Script Extender nicht lesbar war. Behoben durch auf die Marker-QA-Kopie beschränkte Dateiprüfungen und vollständige `info.json`-Metadaten.
- Zweiter und dritter realer QA-Start: BepInEx bestätigte `SHCDE_DAMAGE_QA|event=start|status=read_only|...|renderer_modified=false`; nach Start wurde jedoch `event=shutdown|status=unpatched|sprite_writes=0` protokolliert. `DontDestroyOnLoad(gameObject)` allein änderte dies nicht.
- Die Windows-Sitzung war gesperrt; die Bildschirmaufnahme zeigte nur die Anmeldemaske. Es konnte **keine Spielkarte mit Gebäuden** geöffnet werden. Im archivierten BepInEx-Log existieren **0** `tile_graphic`- und **0** `building_footprint`-Messungen. Keine Pixel-/HP-/Spielwert-Schreibzugriffe.
- Das QA-Spiel wurde jeweils regulär mit WM_CLOSE beendet. Der Diagnose-Plugin wurde danach über SHA- und Receipt-gebundenen `--remove-qa` vollständig deinstalliert, ohne die Originalinstallation zu verändern. Logs liegen unter `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA`.

## QA-CLI

```powershell
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --build-only
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --install-qa
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --verify-log E:\SSLiveGame_20261105\BepInEx\LogOutput.log
python tools/qa_building_damage_live.py --qa-root E:\SSLiveGame_20261105 --remove-qa
```

Das neue Logformat unterscheidet das bloße Laden des Plugins von tatsächlichen Messungen. Die Zuordnung ist nur als **Beobachtung** bestätigt, wenn tile-ID, global-ID und building-ID zwischen einer `tile_graphic`- und einer `building_footprint`-Zeile tatsächlich übereinstimmen. Auch dann bleibt `liveGraphicMappingProved=false`, denn ein Tile-Ereignis ist kein validierter Ersatzrenderer.

## Ausstehende letzte technische Belege

Eine interaktiv zugängliche QA-Spielkarte muss für mindestens ein einfaches und ein mehrkacheliges Gebäude belegen, welche Tile-/SpriteRenderer-/Material-/Masken-Objekte mit welcher HP-/Feuerursache verknüpft sind. Insbesondere muss die Lebensdauer des BepInEx-Beobachters über den Mapwechsel überprüft werden. Danach erst per-Instanz- und per-Kachel-Spriteumschaltung implementieren, Vanilla-Rollback, Feuer/Mechanik/Reparatur/Mapreload prüfen und erst dann Runtime-Hook aktivieren.

**Ein vollständiger aktivierter und spielgetesteter Schadensrenderer ist mit diesem QA-Stand nicht belegt.**
