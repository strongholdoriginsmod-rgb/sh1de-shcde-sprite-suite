# Testbericht – Schnittüberlappung vom 06.11.2026

Die aktualisierte Version des Stronghold Sprite Editors besteht **114 von 114**
Node-Kern-/Schnitt-/Formatprüfungen und **49 von 49** echten Windows-Edge-
Browserprüfungen. Die Browserprüfungen exportieren ein reales Split-ZIP,
lesen `schnitt.json` und die PNGs zurück, verifizieren
`overlap=1`, `rearShare=true`, Bildbreiten von genau 64 Pixeln und eine
pixelgenaue Zusammensetzung. Der Windows-Test wurde über Microsoft Edge
(Chromium) im normalen Browserkontext ausgeführt, ohne Netzwerkanfragen oder
ungefangene JavaScript-Fehler. Zusätzlich wurden die fertigen deutschen und
englischen Einzeldateien tatsächlich über `file://` geöffnet, die 1-Pixel-
Einstellung angezeigt und die Demo-Gruppe über die Benutzeroberfläche in den
Schnitt überführt.

Für das mitgelieferte, unveränderte Beispiel `Steinhof.png` (336×256,
5×5-Raster) werden 25 Tiles mit **exakt 64 Pixel Breite** ausgegeben.
Davon werden beim neuen Schnitt 3.975 sicher deckende Pixel im 1-Pixel-
Rand und 4.200 zusätzliche Pixel in den gemeinsamen Bildflächen aller
hinteren Reihen übernommen. 3.798 vollständig transparente Pixel
erhalten RGB-Farbwerte angrenzender Pixel; ihre Alpha-Werte bleiben 0.
Die 25 rekonstruierten Tiles ergeben pixelgenau das Quellbild, unabhängig
von der Reihenfolge der Zeichnung. Tests gegen teiltransparente Pixel,
Masken, ungültige Breiten und alte Projekte sind enthalten. PNG-, SHSPRITE-
und ZIP-Roundtrips sind reproduzierbar.

Die deutschsprachige gebaute Ein-Datei-HTML-Fassung besitzt den SHA-256-
Wert:

```
e0aa5662d45e262bda59c6efa4698e5bce4ce452d4495686c0c6a8eb792d4b65
```

Der Quelldateistand und die aktuellen Testberichte liegen
unter `E:/SpriteSuite_TileOverlap_20261106/extras/sprite-editor`;
Testlogs, echte Browser-Aufnahmen, visuelle Überlappungsmaske und
Bildvergleich der Steinhof-Zerlegung unter
`E:/SpriteSuite_TileOverlap_QA_20261106`.

Unity unterscheidet die Komposit-Ebenenüberlappung von Atlas-Padding,
Alpha-Dilation und Sprite-/Texturfilterung. Deshalb verändert diese
Implementierung weder Texturatlasabstände noch den originalen
Ownership-Index. Sie dupliziert ausschließlich ungefährliche, voll
deckende Farbpixel innerhalb bestehender Tile-Grenzen. Gegen doppelt
aufgetragene halbtransparente Pixel ist der Schnitt explizit geschützt.

Die drei Ruinen aus dem Anwender-Screenshot sind **nicht** als separate
Original-Tile-Dateien Bestandteil dieses Testdatensatzes; ihr konkreter
Ingame-Lauf ist daher kein bereits abgezeichnetes Testergebnis.
Das dokumentierte Verfahren wurde gegen den tatsächlichen Editorcode,
die generierten deutschen und englischen HTML-Dateien und die
mitgelieferte 5×5-Tile-Referenz geprüft.

---

# Historische Freigabeprüfung vom 29.09.2026

Version 1.0.0 · Prüfstand 29.09.2026

## Ergebnis

**99 von 99 Kern-/Format-Tests bestanden; 49 von 49 Browser-Prüfungen bestanden.** Im abschließenden Browserlauf wurden keine unbehandelten JavaScript-Ausnahmen und keine Anwendungs-Netzwerkanfragen beobachtet. Die Counts sind benannte Testfälle bzw. Prüfpunkte, keine Coverage-Prozentsätze und keine formale Verifikation.

Getestete HTML-Datei, SHA-256:

```text
943ccd1fce856abbc28ab2ca1d4f0550da910d9b616d46e4b5cd86d11f45fb0f
```

Die Ergebnisse sind als `tests/results/core-report.tap`, `browser-report.json` und `browser-run.log` beigepackt. Der Browserbericht enthält denselben HTML-Hash. `python verify_release.py` prüft den reproduzierbaren Build und die Paketdateien gegen `SHA256SUMS.txt`.

## Kritische Gegenprüfung vom 06.11.2026

Die erste Umsetzung berücksichtigte beim großflächigen Teilen von
Bildinformation nur die **allerletzte** Diagonale. In der vorletzten
Diagonale fehlten damit 840 von 1.024 möglichen voll deckenden
Bildproben, in der davorliegenden 1.260 von 1.536. Ein zusätzlich
entwickelter Negativtest schlug deshalb erwartungsgemäß fehl.
Anschließend wurde die Implementierung auf die gesamte hintere
Rasterhälfte verallgemeinert. Die ursprünglichen 64-Pixel-Bitmaps,
Anker, Ownership-Indizes und anderen Rasterteile bleiben unverändert.

Nach der Korrektur besitzen im 5×5-Steinhof sämtliche 4 hinteren
Diagonalen die verfügbaren gemeinsamen Proben (die vorher fehlenden
Proben sind nun vorhanden). Rechteckige Raster der Größen 1×5, 5×1,
2×3 und 3×5 wurden ebenfalls gezielt geprüft.

155 deterministisch zufällig gewählte Raster- und Alpha-/Maskenfälle
bestanden mit identischem sichtbaren Quellbild bei Vorwärts- wie
Rückwärtszeichnung. 24 vergleichende Simulationen mit bilinearer
Filterung und verschiedenen Skalierungen/Verschiebungen zeigten
gegenüber dem alten Schnitt keine Zunahme der Abweichung zum
Original; alle 24 verbesserten sich. Die simulierte Abtastung ist
ein Softwarevergleich, kein bereits abgeschlossener Engine- oder
Ingame-Test.

Besondere Sicherheitsgrenze: Teiltransparente Pixel und Pixel mit
bedeutungstragenden Materialmasken dürfen nicht einfach doppelt
gezeichnet werden. Die Statusanzeige nennt jetzt die Anzahl solcher
ausgelassenen Duplikate; bei ausschließlich maskiertem oder
teiltransparentem Bildinhalt kann die Überlappung numerisch 1 px
sein, ohne dass die Grafik zusätzliche deckende Proben erhält.

Der 4096×4096-Stresstest mit 1.024 Tiles und 15.467.008
Ausgabepixeln bestand. Nach einer Optimierung unnötiger Ownership-Prüfungen lag die alte
Splitberechnung im vergleichbaren Lauf bei rund 0,8 Sekunden,
die korrigierte Überlappungsverarbeitung bei rund 1,9 Sekunden;
der Prozess belegte ungefähr 370 MiB RAM. Das ist innerhalb des getesteten
Editorbildbudgets, aber ein bewusst gemessener Performanceaufschlag.
Für extrem große Bilder bleibt die Bearbeitung im Hauptthread.

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
