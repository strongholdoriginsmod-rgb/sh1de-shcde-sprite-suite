# Abschließender Testbericht

Version 1.0.0 · Prüfstand 29.09.2026

## Ergebnis

**99 von 99 Kern-/Format-Tests bestanden; 49 von 49 Browser-Prüfungen bestanden.** Im abschließenden Browserlauf wurden keine unbehandelten JavaScript-Ausnahmen und keine Anwendungs-Netzwerkanfragen beobachtet. Die Counts sind benannte Testfälle bzw. Prüfpunkte, keine Coverage-Prozentsätze und keine formale Verifikation.

Getestete HTML-Datei, SHA-256:

```text
943ccd1fce856abbc28ab2ca1d4f0550da910d9b616d46e4b5cd86d11f45fb0f
```

Die Ergebnisse sind als `tests/results/core-report.tap`, `browser-report.json` und `browser-run.log` beigepackt. Der Browserbericht enthält denselben HTML-Hash. `python verify_release.py` prüft den reproduzierbaren Build und die Paketdateien gegen `SHA256SUMS.txt`.

## Umgebung und Methode

Node 22.16.0; Python 3.13.5; Playwright 1.57.0; Pillow 12.3.0; Chromium **144.0.7559.96**, Linux, Headless-Modus. Die Browserprüfung lud die **unveränderte erzeugte HTML-Datei** per `page.set_content` in einen opaken Dokumentursprung. Sie änderte weder Browserrichtlinien noch den Anwendungscode. Import und Export wurden über echte Datei-Eingaben, Dialoge und Downloads ausgelöst. Diagnosezustände wurden nur gelesen, nicht als versteckte Projektsetter verwendet.

Die PNG-Referenzdaten wurden unabhängig mit Python-Standardbibliothek erzeugt. RGBA-Samples, ausgeschnittene Atlasrechtecke, Masken, Einzeldateibytes und zusammengesetzte Schnittausgaben wurden zusätzlich mit Python/Pillow und Standard-ZIP-/XML-Lesern kontrolliert. Darstellungsprüfungen ergänzen diese Datenprüfungen, ersetzen sie aber nicht.

## Kern-/Formatabdeckung

32 unabhängige PNG-Fixtures decken unterstützte Farbschemata, Bittiefen, alle Filter und Adam7 einschließlich kleiner Randfälle ab. Weitere Fälle behandeln transparente RGB-Werte, geringe Alpha-Werte, Kodierungs-Roundtrips, CRC-Schäden, abgeschnittene Daten, verbotene kritische Chunks, APNG/16-Bit-Abweisung und übergroße Header.

ZIP-Prüfungen umfassen Store/Deflate, Deskriptoren, CRC, Größen, Pfadtraversal, Symlinks, Groß-/Kleinschreibungs- und Unicode-Kollisionen sowie deterministische Ausgabe. Hash-Tests vergleichen native und fallbackbasierte SHA-256-Berechnung mit Node-Kryptografie einschließlich Blockgrenzen; Base64 wird auch mit 2 MiB Daten geprüft.

Geometrieprüfungen behandeln die konkrete 5×5-Nummerierung der Vorlage, rechteckige Raster, variable Höhe, Zeichenreihenfolge, Alpha-Compositing, Spiegelung, Skalierung, ankererhaltendes Trimming, Pixelzuordnung, verlustfreie sichtbare Schnitt-Rekonstruktion und nicht überlappendes Atlaspacking. Formatmodelle werden auf Pivot-Ursprung, mehrdeutige Metadaten, Dimensions-/Maskenkonflikte und sichere CSV-/JSON-Verarbeitung geprüft.

Projekt- und Exporttests behandeln Originalbyte-Erhalt, getrennte Masken, SHA-Prüfung, Undo/Redo samt Garbage Collection, tatsächlichen v0.1-Demodatensatz, 4096-Frame-Grenze und Abweisung des 4097. Frames. Einzel-/Atlas-Modpakete, SEMOD-Wurzeln, OpenRaster, Metadaten, Zielnamen und Ausgabeberichte werden inhaltlich geprüft.

## Browserabdeckung

Alle fünf Ansichten; Original-/Projekt-/PNG-/OpenRaster-Downloads; exakte Aufbau→Schnitt-Geometrie; Pinsel und Undo; Übernahme neuer Tiles; Wiederöffnen des Projekts und unveränderte Originaldateien. Der tatsächliche v0.1-Datensatz wird über den Dateidialog importiert. Ein 4096-Frame-Projekt lässt sich öffnen; beim Scrollen bis Frame 4095 bleiben weniger als 50 Dateizeilen gleichzeitig im DOM.

Der synthetische SHDE→SHCDE-Ablauf umfasst Farb-/Maskenimport, Quell- und Zielmetadaten, Referenzen auch in umgekehrter Importreihenfolge, CSV-Zuordnung, formale Vorprüfung sowie reale ZIP-/SEMOD-Ausgaben. Die extrahierten Atlaspixel, Masken und Pivots entsprechen den unabhängigen Eingaben. Batch-Skalierung, PPU-Anpassung, Dimensionssperre, Undo/Redo, Trim→Originalzustand, Animation und atomarer Fehlerimport wurden über die Oberfläche geprüft.

Screenshots wurden bei 1920×1080, 1440×960, 1024×768, 768×1024 und 390×844 erzeugt. Kein Dokumentüberlauf in diesen Größen; mobile Seitenleisten öffnen. Die Hauptansicht und die schmale Ansicht wurden zusätzlich visuell kontrolliert. Vorschau-Bilder stehen in `tests/results/`.

## Nicht nachgewiesen

**Kein In-Game-Test und keine Prüfung an echten extrahierten Spielassets.** Ziel-IDs, Shaderwirkung, Teamfarben-/Vegetationskanäle, Engine-Sortierung, Gameplay-Rollen und die Kompatibilität einer konkreten Script-Extender-/Spielkombination sind damit nicht freigegeben.

**Kein direkter `file://`-Start in dieser Testumgebung.** Die HTML ist als lokale Einzeldatei ausgelegt, aber die tatsächlich geprüfte Startmethode ist oben genannt. Native Windows-/macOS-Tests, Firefox/Safari und Touch-Bedienung auf echten Geräten wurden nicht durchgeführt.

**Keine dauerhafte native IndexedDB-Prüfung.** Der Browser verweigerte am opaken Ursprung den Speicherzugriff. Der abgefangene Fehler und das Weiterarbeiten ohne Autosicherung wurden geprüft; die echte Wiederherstellung über Browserneustarts nicht. Projektdateien bleiben der primäre Sicherungsweg.

Der 4096-Frame-Test verwendet kleine, gemeinsam referenzierte Pixelbilder. Er ist ein Modell-/Listen-Kapazitätstest, kein Nachweis für flüssige Arbeit mit 4096 großen Original-Sprites. Es wurden keine langfristigen Speicher-Stresstests oder vollständigen Fuzzing-Kampagnen durchgeführt. Begrenzte Puffer, Parserprüfungen und Tests verbessern Zuverlässigkeit, beweisen aber keine Fehlerfreiheit für jede denkbare Eingabe.

## Reproduktion

```sh
python build.py
node --test tests/test_core.cjs
python tests/test_browser.py --browser /path/to/chromium
```

Nur die Tests benötigen die in `requirements-test.txt` bezeichneten Pakete. Nach einem erneuten Testlauf verändern sich Berichte, Laufzeiten und erzeugte Beispieldateien; die mitgelieferte Release-Prüfsummenliste beschreibt den gelieferten Stand und muss für einen eigenen Release neu erzeugt werden.
