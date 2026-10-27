# Reproduzierbare Prüfungen

`node --test tests/test_core.cjs` führt die Kern-/Formatprüfungen ohne npm-Abhängigkeiten aus. Die gelieferten PNG-Referenzen wurden unabhängig mit Python-Standardbibliothek erzeugt; `python tests/generate_fixtures.py` erstellt sie erneut. Der Legacy-Datensatz stammt aus dem tatsächlichen bisherigen v0.1-Beispiel. `generate_capacity.cjs` erzeugt ein synthetisches 4096-Frame-Projekt, nicht 4096 echte Spielgrafiken.

Für Browserprüfungen Python-Abhängigkeiten aus `requirements-test.txt` in einer eigenen Umgebung installieren und einen Chromium-Pfad angeben:

```sh
python build.py
node --test tests/test_core.cjs
python tests/test_browser.py --browser /path/to/chromium
```

Der Browserlauf benötigt Playwright und Pillow; die Anwendung selbst nicht. Er lädt die unveränderte HTML-Datei per `page.set_content`, benutzt echte Datei-Eingaben und Downloads und verändert keine Browser-Sicherheitsrichtlinien. Die vorliegende Ausführung hatte einen opaken Dokumentursprung. Dadurch sind direkter `file://`-Start und native IndexedDB-Dauerhaftigkeit nicht abgedeckt.

Testausgaben und Berichte werden in `tests/results/` geschrieben. Dateien mit den synthetischen Namen `body_source`, `body_target`, `body_capacity` oder `tile_beispiel` sind keine installierbaren Referenzmods für reale Spiel-IDs. Negative ZIP-/PNG-Fixtures enthalten absichtlich ungültige Strukturen; sie sind ausschließlich Parser-Testdaten und dürfen nicht als Assetarchiv verwendet werden.

99 benannte Tests sind keine Aussage über vollständige Codeabdeckung oder formale Verifikation. Browser-Prüfungen ergänzen, ersetzen aber keine Tests in einer Spielinstallation. Einzelheiten und verbleibende Grenzen stehen in `dokumentation/TESTBERICHT.md`.
