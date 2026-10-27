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
