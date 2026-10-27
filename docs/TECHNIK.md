# Technische Verträge

## Sprite-Geometrie

Ein Unity-Pivot ist normalisiert. Sein Pixelanker lautet `pivot * Bildgröße`.
Bei anderer Leinwand ergibt sich für einen beizubehaltenden Zielanker:

```
neuer_pivot_x = ziel_pivot_x * ziel_breite / quell_breite
neuer_pivot_y = ziel_pivot_y * ziel_hoehe   / quell_hoehe
```

Das ist für flache Rastergrafik richtig. Aufrechte Motive verwenden je nach
Gruppenvertrag den eigenen Quellanker. Bei echten oberen/rechten Eckankern
bleibt der Abstand zur betreffenden Kante maßgeblich. Der spätere
`anim_castle`-Fix hält diese Eckkonvention ein. Die Geometrie wird vor BC7 mit
RGBA-Rückschnitt, Pixelhash, Float32-Pivot und PPU nachgewiesen.

SHCDE behält Slotnamen, Reihenfolge und Arrayzuständigkeit. Von 195
Laderegistrierungen besitzen zwei kein unabhängiges Array:
`tile_sea_new_01` und `tile_sea_shore` teilen `GM_NEW_SEA` mit Offset und
Zusatzspeicher. Ein gewöhnlicher Einzelatlas würde diesen Vertrag zerstören.
Auch sparse Gruppen müssen die höchste Slotnummer erhalten; Frameanzahl und
Arraylänge sind verschiedene Größen.

## BC7 statt PNG im Grafikspeicher

Eine kleine PNG-Datei sagt nichts über den GPU-Verbrauch aus. Als RGBA32 kostet
eine 8192×8192-Seite ohne Mips **256 MiB**; als BC7 **64 MiB**. Eine gleich
große Maske benötigt dieselbe Menge zusätzlich. BC7 verwendet 16 Byte je
4×4-Block: `ceil(w/4) * ceil(h/4) * 16`.

Die Pipeline baut **Unity AssetBundles**, keine zur Laufzeit dekodierten
BC7-PNGs. Hauptseiten und erforderliche Masken werden mit dem gebundenen
Unity-Editor komprimiert. Die V2-Zellen sind auf 4×4-Blöcke isoliert, damit
Kompressionsblöcke nicht zwei benachbarte Frames mischen.

Unity kann nicht durch vier teilbare Texturen trotz angeforderter BC7-Einstellung
als RGBA32 importieren. Der Editorbuilder prüft deshalb das **tatsächlich
importierte Format**. Die UI-Pipeline erweitert Speichermaße auf volle Blöcke
und erhält die logischen Bildmaße getrennt.

BC7 ist verlustbehaftet. Bytegleiche Pixel sind das Gate vor der Kompression;
danach gelten eingefrorene Messgrenzen für Alpha, vormultiplizierte RGB-Werte,
Komposition auf verschiedenen Hintergründen und Maskenkanäle. Masken werden
mit `Point` abgetastet. Ein scheiterndes Qualitätsgate wird nicht still durch
RGBA32 oder weichere Grenzwerte ersetzt.

## Laufzeit, Teammasken und Vegetation

Der Runtime-Begleiter prüft Bundleindex, Hashes, Texturvertrag und Budget vor
der Übernahme. Gruppen werden transaktional geladen. Erforderliche Masken
werden pro Sprite und tatsächlicher Seite geroutet; das verhindert die früheren
weißgrauen Teammasken bei gemeinsam verwendeten Materialien. Materialzustand,
Maskenrouten und Ressourcenlebensdauer besitzen eigene Regressionstests.

Die sieben Vegetationsgruppen benötigen den passenden Foliage-Shader statt
eines pauschalen TeamColour-Materials. Ihre Sonderbehandlung gehört zur Suite.
SE 2.10 teilt seinen Scan-Snapshot bereits zwischen ScanRegion und
HookTransaction. Die Suite prüft diese gemeinsame Nutzung und verändert
den vom Extender gehaltenen Speicher nicht. Die früheren 1.44-Korrekturen
bleiben als historische Implementierung erhalten und sind in 2.10 inaktiv.
Die Freigabe ersetzter UI-Basistexturen bleibt profilgebunden; beim isolierten
Fortification-Canary ist sie bis zur Laufzeitabnahme weiterhin abgeschaltet.

## RAM ist nicht VRAM

BC7 senkt die Texturgröße auf der GPU. Dekodierpuffer, Mono-Heap, Bundledaten,
Audio und ursprüngliche Spieltexturen können trotzdem den Prozessspeicher
belasten. Deshalb misst die Pipeline sowohl residente Texturkosten als auch
Private Bytes, freien physischen Speicher, Commitreserve und Ladepeak.

Der heutige Profilvertrag nennt 3 GiB zusätzliches GM-Budget, 1 GiB UI,
16 MiB Audio-Stream, 12 GiB Prozess-Private-Ceiling, 4 GiB Commitreserve,
256 MiB freie physische Reserve und 2 GiB Peak-Admission. Das sind konkrete
Admission-Grenzen dieses Profils, keine zugesicherte Speicherbelegung und kein
allgemeines Hardwareminimum. Historische Berichte verwendeten andere Grenzen.

## Inkrementeller Bau

Der GM-Cache bindet Gruppeninhalt, Atlasvertrag, Editor und Qualität. Die
UI-Pipeline speichert ein Bundle pro Eintrag; zu ihren Cacheeingaben gehören
Quellhash, Importregeln, Filter, Editorcode und Werkzeugversionen. Änderungen
an einer Grafik erzeugen einen neuen Schlüssel. Unveränderte Einträge bleiben
wiederverwendbar. Der Composer kann geprüfte GM-Dateien per Hardlink oder Kopie
übernehmen. Cachetreffer werden geprüft, nicht allein nach Dateinamen vertraut.

Die Full152-Cold-A-Recoverywerkzeuge sind an **ein konkretes historisches
Artefakt** gebunden. Ihre Hashes sind Wiederherstellungsbelege, keine allgemein
gültigen Standardwerte. Für neue Projekte läuft der normale `build`-Pfad.
