# Script Extender

Die Suite verwendet den bereits im Zielspiel installierten kompatiblen Script
Extender. Setup, Prüfen und Bauen ersetzen weder seine Dateien noch seine
Konfiguration. Das fertige Modpaket samt eigener Runtime wird bei Bedarf
von Hand nach `BepInEx/plugins/StrongholdEuropeDE` kopiert.

Beim Runtime-Bau werden die benötigten Schnittstellen der vorhandenen
Bibliotheken geprüft und deren Identitäten im Ergebnis festgehalten.
**SE 2.10.0** ist der geprüfte Referenzstand; andere Versionen müssen dieselben
benötigten Schnittstellen bereitstellen. Eine bestimmte Versionsnummer allein
ist kein Grund für einen Austausch. Nach einem selbst vorgenommenen Spiel-
oder SE-Update das Modpaket neu bauen.

## Früheren SE-Wechsel zurücknehmen

Nur für Installationen, bei denen mit einer älteren Suite **Mit Sicherung
installieren** ausgeführt wurde: Dieser Vorgang hat den Extender ausgetauscht.
Ein Update oder eine Deinstallation der Sprite Suite macht das nicht rückgängig.

Bei geschlossenem Spiel im damaligen Suite-Ordner ausführen:

```powershell
./.venv/Scripts/python.exe tools/shcdese_current_install.py rollback --game-root '<SHCDE-Spielordner>'
```

Dafür müssen die Sicherung und das Journal unter
`state/shcdese-2.10-installer` vorhanden sein. Die Rücknahme stellt den
gesicherten Extender, dessen Konfiguration und den damaligen Stand des eigenen
Modpakets wieder her; zwischenzeitliche Dateien werden separat aufbewahrt.
Es erfolgt keine automatische Rücknahme.

Die früheren SE-Installationsskripte bleiben für Wiederherstellung und
Nachvollziehbarkeit im Quellpaket erhalten. Sie sind nicht Teil der Oberfläche
oder des Werkzeugkatalogs. Die ursprünglichen 1.44-Quellen und Pins liegen unter
`reference/shcdese-1.44` und `reference/shcdese-1.44-native`.

## Script Extender v2.14.3 (27. Oktober 2026)

**Offizieller letzter GitLab-Tag:** `v2.14.3`, veröffentlicht am
19. Oktober 2026; Quellcommit
`4014ca67c96974a5e6d697665baf5351cbfebde6`.

Das ursprüngliche **Stronghold-1-DE-HUD** benötigt den Crusader Script
Extender nicht. Erst der SH1-zu-SHCDE-Atlas- und Modpaketweg verwendet ihn.

Die **read-only** Vorprüfung wird im Reiter Ziel & SE 2.11 über
**Script Extender 2.14.3 prüfen (nur lesen)** gestartet oder per:

```powershell
.venv\Scripts\python.exe tools\shcdese_compat_check.py --game "D:\Games\Stronghold Crusader Definitive Edition"
```

Sie liest ausschließlich den tatsächlich installierten PE-DLL-Stand, das
SE-`info.json`, BepInEx 5, einen Spiel-Build-Hash, die vom Extender
deklarierten Spielversionen sowie die Sicherheitsoption
`RequireSignedBepInExPlugins`. `--require-latest` lehnt
jede Version außer v2.14.3 ab. Kein Download, keine Installation.

**Statische Noesis-HUD-Kompatibilität:** Der geprüfte offizielle
v2.14.3-Code verarbeitet die bisherigen XAML-Patch-Wurzeln
`<Patch>` und `<XamlPatch>` mit
`<Operation>` und die bestehenden Sprite-Override-Pfade.
Das ist kein Nachweis eines erfolgreichen Spielstarts.

**Runtime-ABI noch offen:** Der bisherige C#-Runtime-Bau in dieser
Repository-Fassung ist auf die SE-2.11.0-DLL mit konkreten
MVID-/SHA-256-Werten gepinnt. Für SE v2.14.3 muss die eigene Runtime
gegen die echte neue DLL neu kompiliert und im Spiel getestet werden.
Eine Versionsnummer oder ein erfolgreicher HUD-PNG-Export reicht nicht.

Die alte SE-2.11-Installationsfunktion ist nur noch ein
**historisches Werkzeug**. Ein abweichender Paket-Hash und das
unbeabsichtigte Downgrade einer neueren Installation werden verweigert.
Die seit v2.13 optionale Signaturpflicht für BepInEx-Plugins lässt
sich nicht anhand vorhandener Manifestdateien allein freigeben.

Quellen:
- https://gitlab.com/rawra-stronghold-crusader/shcde-script-extender/-/releases/v2.14.3
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/bepinex-mod-guide.html
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/mod-types.html
