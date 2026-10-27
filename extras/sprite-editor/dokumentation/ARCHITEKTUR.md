# Architektur und technische Verträge

## Aufbau

Die Anwendung besteht aus vier getrennten JavaScript-Modulen, CSS und einem HTML-Gerüst. `build.py` setzt sie deterministisch zu einer offline verwendbaren HTML-Datei zusammen; es installiert keine Bibliotheken. Der gelieferte Quellcode enthält keine heruntergeladenen Frameworks, Fontdateien oder Fremdbinaries.

| Datei | Zuständigkeit |
|---|---|
| `src/core.js` | Reine Geometrie, Raw-RGBA-Operationen, Atlaspacking, Pixelzuordnung, Metadaten-, CSV- und Pfadvalidierung. |
| `src/codec.js` | PNG-/ZIP-Lesen und -Schreiben, CRC32, SHA-256, Base64, begrenzte Kompressionsstreams. |
| `src/io.js` | Projektmodell, AssetStore, History, validierte Importtransaktionen und Exportformate. |
| `src/app.js` | DOM, Canvas-Vorschau, Dialoge, Bedienung, Undo/Redo, native Datei-Downloads und optionale Wiederherstellung. |
| `src/style.css` / `src/shell.html` | Oberfläche, Layout und CSP. |

Kern, Codecs und Datenmodell sind auch unter Node mit `require()` ladbar. Canvas wird für Vorschau und Zeigereingaben verwendet. Dateiausgaben lesen keine Pixel aus einer gerenderten Canvas zurück.

## Pixel- und Positionsvertrag

Ein Bild ist `{width, height, data}` mit RGBA8 und oben links beginnenden Zeilen. `data` hat exakt `width*height*4` Bytes. Ein optionaler `bytes`-Puffer enthält die ursprüngliche PNG-Kodierung. Gespeicherte Pixelpuffer sind intern als unveränderlich zu behandeln; Operationen erzeugen neue Bilder. `AssetStore.fork()` teilt bestehende Bildobjekte, nicht seinen veränderlichen Index.

Der normalisierte Pivot beginnt unten links. Auf Bildpixel bezogen gilt `anchorX=pivot.x*width`, `anchorY=(1-pivot.y)*height`. Die Szenengeometrie arbeitet mit ganzen Pixelpositionen. Isometrische Nummerierung und Zeichenreihenfolge sind getrennte Algorithmen. Ein Source-over-Compositor verwendet explizite RGBA-Arithmetik statt browserabhängiger Canvas-Rücklesewerte.

Schnittflächen verwenden intern `Int32Array`, unzugeordnet ist `-1`. Als PNG wird `slot+1` in RGB gespeichert; 0 bleibt unzugeordnet. Die Prüfung zählt außer sichtbarer Farbe auch nichtleere Maskenkanäle bei Alpha 0. Die Ausgabe ist eine disjunkte neue Zerlegung, kein Wiederherstellungsalgorithmus für verdeckte Ebenen.

## Projektmodell

Formatkennung `stronghold-sprite-editor`, Schema `2`, Anwendungsstand `1.0.0`. `.shsprite` ist ein ZIP mit `project.json` und `assets/<id>.png`. Die Assetliste enthält IDs, Pfade und SHA-256. Fehlende Dateien, falsche Hashes, ungültige IDs, unpassende Maskengrößen oder nicht unterstützte Schemata führen zum Abbruch.

Das Modell enthält Projektmetadaten, Quellgruppen, Frames, separate Zielreferenzen, optionale Schnittquelle mit Zuordnung und Exporteinstellungen. Jeder Frame speichert Original- und Bearbeitungs-Asset-ID separat; ebenso Masken, ursprünglichen und aktuellen Pivot/PPU, Quellnamen, Zielnamen, Bestätigungsstatus, Rasterplatz, Versatz, Sichtbarkeit und Sperre. Automatische Trim-Kompensation wird separat gespeichert, damit „Originalzustand“ unabhängigen manuellen Versatz nicht entfernt.

Legacy-Projekte mit `format: shc-sprite-workbench`, Version 1 und eingebetteten PNG-Base64-Daten werden importiert. Nicht vorhandene Herkunfts- oder Zielangaben werden nicht als verifiziert ergänzt. Der tatsächliche Demo-Datensatz der vorigen Version ist Bestandteil der Regressionstests.

## Transaktionen, Historie, Speicher

Ein Import arbeitet auf einer Kopie des Metadatenmodells und einem Fork des Bildspeichers. Erst nach vollständigem Erfolg validiert `History.commit()` den neuen Stand. Ein Fehler lässt Modell, aktuelle Gruppe und Bildspeicher des Editors unverändert. Abbruchsignale werden vor und zwischen asynchronen Arbeitsschritten ausgewertet.

Undo/Redo speichert bis zu 50 Metadatenstände; Pixel werden über Asset-IDs geteilt. Garbage Collection erhält alle aktuell oder historisch referenzierten Bilder. Bei einer neuen Änderung nach Undo wird der verworfene Redo-Zweig freigegeben. Die lokale Browser-Sicherung verwendet einen separaten Snapshot und Generationsprüfungen. Sie wird nicht als alleinige Datensicherung zugesichert.

Grenzen: maximal 16384 Pixel je Bildkante und 16.777.216 Pixel je Bild, insgesamt 33.554.432 gehaltene Bildpixel, 4096 Frames, 4096 Zielreferenzen, 256 Gruppen, 12.288 Archiveinträge, 64 MiB je PNG, 128 MiB Eingabesumme, 192 MiB Archivgrenze. Abstände, Indizes, Pivots, PPU und Rasterplätze werden numerisch geprüft. Die 32-Megapixel-Grenze ist kein exakt zugesichertes RAM-Limit: kodierte Bytes, Temporärpuffer und Vorschau-Canvases benötigen zusätzlichen Speicher.

## Unterstützte Formatuntermenge

PNG: Graustufen 1/2/4/8 Bit, Palette 1/2/4/8 Bit, RGB8, RGBA8 und Graustufen+Alpha8; `tRNS`, alle fünf Filter und Adam7. 16-Bit-PNG und APNG werden bewusst abgelehnt. Chunk-CRC, Reihenfolge, kritische Chunks, Dimensionen und tatsächliche Entpacklänge werden geprüft. Neu erzeugte Dateien sind RGBA8 ohne automatische Profiltransformation. Originalbytes werden nur bei unveränderten Originalausgaben wiederverwendet; abgeleitete Bilder werden neu kodiert.

ZIP: Lesen von Store und Deflate, unterstützte Daten-Deskriptoren, UTF-8 sowie CP437-/Unicode-Namenspfade. Schreiben als deterministisches ZIP32/Store; PNG-Inhalte sind bereits komprimiert. Verschlüsselung, ZIP64, Symlinks, unsichere Flags, überlappende Datenbereiche, Pfadtraversal und Namenskollisionen werden abgewiesen. Diese Schutzmaßnahmen sind kein Anspruch, sämtliche denkbaren schadhaften Eingaben formal bewiesen abzudecken.

JSON: Schema- und Werteprüfung, kein `eval`; kritische Prototype-Schlüssel werden abgewiesen. CSV: korrekt zitierte Felder, Spaltentrenner-Erkennung und Schutz problematischer Tabellenformeln beim Export. Ausgabe-Namen werden auf sichere relative Archivpfade begrenzt. Importierter Text gelangt über Textknoten in die UI, nicht über dynamisches `innerHTML`.

## Zielpakete

Der Editor schreibt `info.json`, vorbereitete Sprite-/Atlas-Dateien und einen Portierungsbericht. Die Paketart entscheidet über die Wurzel: loses Installations-ZIP beginnt bei `BepInEx/plugins/<id>/`, SEMOD bei `info.json`. Die Erweiterungsabhängigkeit ist deklarativ und wird weder heruntergeladen noch im Browser ausgeführt.

Atlanten werden pro Ziel-GM-Gruppe gebildet. Alle zugehörigen sichtbaren Frames werden gemeinsam gepackt; gleiche Zielnamen sind unzulässig. Masken teilen dasselbe Layout. Ohne Rotation, mit kontrolliertem Padding/Extrusion und durch vier teilbaren Ausgabemaßen. `maxSide` und maximale Pixelzahl gelten auch nach dem Padding.

## Testbarkeit und Grenzen

`window.SpriteEditor.inspect()` liefert einen kopierten Diagnosezustand für reproduzierbare UI-Prüfungen; es gibt darüber keinen versteckten Projektsetter. Browser-Tests importieren über reale Datei-Eingaben und untersuchen tatsächlich heruntergeladene Dateien. Der Bytevergleich erfolgt zusätzlich mit unabhängigen Python-/Pillow-Routinen.

Nicht implementiert sind Worker-basierte Bildverarbeitung, GPU-Packing, DDS, AssetBundle-/Mesh-Dekodierung und vollständiges ICC-Farbmanagement. Das explizite Ressourcenlimit und die Abweisung ungeeigneter Formate sind Bestandteil des Produktumfangs, keine versteckte automatische Qualitätsreduktion.
