# Bedienung

Version 1.0.0 · Stand 29.09.2026

## 1. Dateien und Projekte

Ein Projekt kann mehrere Quellgruppen enthalten. Im Dateibereich oben zwischen den Gruppen wechseln; die Suche berücksichtigt Quell- und Zielnamen. Ein Klick wählt einen Sprite. Strg-/Cmd-Klick ergänzt die Auswahl, Umschalt-Klick einen Bereich. „Alle“ bezieht sich auf die aktuelle Gruppe. Unsichtbare Bilder bleiben im Projekt und im Originalexport, werden aber nicht in normale Bild-/Modausgaben übernommen.

PNG-Serien lassen sich als Einzeldateien, Ordner oder ZIP importieren. Der numerische Dateisuffix wird als Nummer ausgewertet, nicht lexikografisch sortiert. Mit „Nummernlücken als freie Rasterplätze erhalten“ bleiben fehlende Indizes als freie Plätze bestehen. Farb- und Maskenbild müssen denselben Basisnamen besitzen, beispielsweise `body_source-7.png` und `body_source-7_m.png`. Eine unzuordenbare Maske, eine beschädigte Datei oder ein ungültiger Name führt zum Abbruch des gesamten Imports; es wird keine halbe Serie übernommen.

Dateien verschiedener Quellgruppen dürfen dieselben Quellnamen besitzen. Beim gemeinsamen Tile-Export legt der Editor dafür getrennte Gruppenordner an. Innerhalb eines Exportordners werden Namenskollisionen nicht still überschrieben. Metadaten- und CSV-Import auf die richtige aktuelle Gruppe anwenden. Mehrdeutige Quellzuordnungen werden zurückgewiesen.

„Speichern“ gibt eine `.shsprite`-Datei aus. Es wird nicht still dieselbe Datei auf der Festplatte überschrieben; der Browser verwaltet den Download. Die Browser-Sicherung ist lediglich eine zusätzliche Wiederherstellungshilfe. Nach dem Öffnen eines gespeicherten Projekts sind die aktuellen Bearbeitungen und die Originale verfügbar, nicht die vorherige Undo-Historie.

## 2. Gebäude zusammensetzen

Unter **Aufbau → Eigenschaften** „Links“ und „Rechts“ für die beiden isometrischen Rasterachsen einstellen. Die Platznummerierung läuft über horizontale Diagonalen von vorne nach hinten, innerhalb jeder Diagonale von links nach rechts. Sie folgt der mitgelieferten ODT-Vorlage. Die Zeichenreihenfolge ist unabhängig davon umschaltbar.

Die Startwerte 64×32, „Unten mittig“ und „Niedrige Nummer zuerst“ sind Arbeitsvorgaben. Insbesondere Rautenhöhe, Anker und Ebenenreihenfolge anhand der jeweiligen exportierten Assets kontrollieren. Die Anwendung erzwingt keine 64-Pixel-Breite für Einheiten, Bäume oder beliebige Custom Assets. Der Assettyp beeinflusst Hinweise, ersetzt aber keine Zielreferenz.

Ein Sprite kann über seine Bodenraute hinausragen. Seine PNG-Höhe wird nicht auf die Rautenhöhe beschnitten. Versatz X/Y verschiebt das Bild, ohne seinen Rasterplatz umzunummerieren. Draggen auf der Arbeitsfläche und die Pfeiltasten ändern den Versatz; mit Umschalt wird in 10-Pixel-Schritten verschoben. „Gesperrt“ verhindert diese Bearbeitungen. Rasterplätze über das Zahlenfeld oder „Plätze zuordnen…“ korrigieren. Rasterverkleinerungen, die belegte Plätze ausschließen, werden nicht still abgeschnitten.

„Gesamtbild · PNG“ enthält die sichtbare aktuelle Gruppe ohne Hilfslinien. „Ebenen · OpenRaster“ bewahrt die getrennten Ebenen, Namen, Positionen und Sichtbarkeit. ORA ist in dieser Version ein Ausgabeformat, kein Projektimport.

## 3. Quelle und SHCDE-Ziel abgleichen

**Importieren → Quellmetadaten (JSON)** übernimmt passende Pivots und PPU für die aktuelle Quellgruppe. **SHCDE-Zielreferenzen (PNG / ZIP)** und **SHCDE-Zielmetadaten (JSON)** speichern dagegen separate Zielvorlagen. Bei einzelnen Referenz-PNGs darf die Metadaten-Datei vor oder nach den Bildern geladen werden. Ein bereits bebilderter Referenzeintrag wird nicht still durch einen zweiten Import ersetzt.

Unter **Ziel** einen einzelnen Zielnamen eingeben oder mehrere ausgewählte Frames mit **Serie zuordnen…** auf eine bekannte SHCDE-GM-Gruppe und deren ersten Index abbilden. „Abstände der Quellnummern erhalten“ ist optional. Zielnamen erst nach tatsächlichem Abgleich bestätigen. Als Alternative eine CSV importieren:

```csv
source,target,pivot_x,pivot_y,ppu,offset_x,offset_y
body_source-7.png,body_target-0,0.375,0.25,64,0,0
body_source-8.png,body_target-1,0.375,0.25,64,0,0
```

Diese Namen sind ein synthetisches Formatbeispiel und keine verifizierten Spiel-IDs. Das CSV-Format verwendet Dezimalpunkte. Komma oder Semikolon als Spaltentrenner und korrekt zitierte Felder werden unterstützt. Bei mehrfach vorkommenden Quellnamen jede Quellgruppe separat zuordnen.

Die **Sprite**-Ansicht zeigt Bearbeitung, Original, Zielreferenz, eine am Pivot ausgerichtete Überlagerung oder die absolute Kanaldifferenz zum Original. Die Überlagerung ist ein Pixelvergleich, keine Größen-/Shader-Simulation der Spielwelt. Pivot und PPU daher zusätzlich numerisch vergleichen. „Pivot setzen“ übernimmt einen Klick im Bild als normalisierten Anker mit Ursprung unten links.

**Animation** spielt die sichtbaren ausgewählten Frames ab; ohne Mehrfachauswahl die sichtbare Gruppe. Die Reihenfolge folgt den Rasterplätzen. Mit Einzelschritt, FPS-Feld und dem vorherigen Frame lassen sich Sprünge erkennen. Der Editor erfindet keine Zuordnung von Blickrichtungen, Lauf-, Arbeits-, Kampf- oder Todesanimationen: Diese Rollen müssen aus den Zielassets hervorgehen.

## 4. Bilder und Masken bearbeiten

**Transformieren…** arbeitet auf der ungesperrten Auswahl. Verfügbar sind Nächster-Nachbar-Skalierung, horizontale/vertikale Spiegelung, Entfernen transparenter Ränder sowie Helligkeit, Kontrast, Sättigung und explizite Alpha-Umrechnung.

Geometrische Änderungen betreffen Farbbild und `_m` gemeinsam. „PPU mitskalieren“ skaliert bei der Größenänderung auch den PPU-Wert; bei nicht exakt ganzzahlig skalierbaren Maßen werden Pixelabmessungen auf ganze Pixel gerundet. Bei einer ankerbasierten Beschneidung bleiben Pivot und Platzierung erhalten. Für den Schnittbereich werden auch nichtleere Maskenkanäle berücksichtigt, nicht allein die Sichtbarkeit des Farbbilds. „Originalzustand“ stellt Bilder, Masken, importierten Originalpivot und Original-PPU wieder her und entfernt die automatische Trim-Kompensation; unabhängig gesetzter manueller Versatz bleibt bestehen.

Farbkorrekturen verändern die Maskenkanäle nicht. Die Ansichten „Maske · R/G/B/A“ zeigen Datenkanäle, keine interpretierte Teamfarbe oder Windwirkung. Keine Maske wird automatisch aus dem Farbbild geraten. „RGB mit Alpha multiplizieren“ bzw. die inverse Operation nur bei einem nachgewiesenen Bedarf einsetzen; die Umrechnung kann durch 8-Bit-Rundung irreversibel sein.

**PNG ersetzen…** ersetzt den aktuellen Bearbeitungsstand eines ausgewählten Sprites; **Maske laden…** ersetzt seine aktuelle Maske. Die ursprünglichen Dateien bleiben gesondert im Projekt erhalten. Eine noch vorhandene, nicht passende Maske muss mit ersetzt werden: inkonsistente Größen werden abgewiesen.

## 5. Gesamtbild in neue Tiles zerlegen

Unter **Schnitt** ein Gesamtbild laden oder **Aufbau übernehmen** wählen. Der zweite Weg überträgt bei einer unmaskierten Gruppe den exakt bekannten Frontanker; er vermeidet eine Schätzung. Bei Gruppen mit Masken ist diese flache Übernahme bewusst gesperrt, weil überlappende Datenmasken nicht ohne Kenntnis des Zielshaders sinnvoll zusammengesetzt werden können. Ein extern vorbereitetes Gesamtbild mit passendem `_m.png` kann als Schnittquelle importiert werden.

Raster, Frontanker und „Hintere Flächen nach oben verlängern“ anpassen. Nach Änderung von Anker oder Verlängerung **Raster anwenden** anklicken. Eine Rastergrößenänderung erzeugt sofort eine neue Zuordnung. Beides ersetzt vorhandene manuelle Zuordnungen; die Operation bleibt rückgängig machbar.

**Zuordnen** aktiviert den Pinsel. Tile-Nummer und Radius einstellen, anschließend Pixel der gewählten Fläche zuweisen. „Entfernen“ setzt Pixel auf nicht zugeordnet. Die farbige Flächenansicht ist eine Hilfe und gelangt nicht in die eigentlichen PNGs. Überbreite Tiles sowie unzugeordnete sichtbare Farb- oder bedeutungstragende Maskenpixel blockieren die Ausgabe.

„Schnittmaske · PNG“ ist eine **Indexdatei**, kein normales Farbbild: Wert 0 bedeutet nicht zugeordnet; die 1-basierte Tile-Nummer wird als `R + 256*G + 65536*B` gespeichert, Alpha muss 255 bleiben. Keine Farbprofile, Skalierung, Glättung oder verlustbehaftete Speicherung auf diese Datei anwenden. Eine zuvor ausgegebene Maske kann wieder importiert werden.

„Schnitt · ZIP“ enthält die neu geschnittenen PNGs und `schnitt.json` mit ihren Positionen. „Als Tiles übernehmen“ erzeugt daraus eine neue bearbeitbare Gruppe. Ein Split ist eine neue Zerlegung der sichtbaren Fläche; er kann verdeckte Teile des ursprünglichen Gebäudes nicht rekonstruieren.

## 6. Atlas und Modpaket

Unter **Ziel** den Ersetzungsweg wählen. Ein **Einzel-Override** benötigt Zielabmessungen als Referenz und identische Bildmaße. Bei **Atlas** müssen PPU innerhalb derselben Zielgruppe konsistent sein. Zielgruppen umfassen beim Modexport sämtliche sichtbaren Frames des Projekts, auch wenn sie aus unterschiedlichen Quellgruppen kommen.

Material, Abstand, Randwiederholung und maximale Atlas-Kantenlänge festlegen. Es wird nicht rotiert; Masken verwenden dieselben Packpositionen. Randwiederholung darf den Abstand nicht übersteigen. Die tatsächliche maximale Bildfläche von 16 Megapixeln gilt zusätzlich zur eingestellten Kantenlänge. Ein größerer Wert hebt diese Schutzgrenze nicht auf.

Unter **Projekt → Projekteinstellungen** Autor, Mod-ID und Version eintragen. **Prüfung** zeigt blockierende Fehler getrennt von Warnungen. Ein fehlerfreier Bericht bestätigt lediglich die formalen Regeln dieser Anwendung. Er bestätigt weder die Existenz frei eingegebener Ziel-IDs noch die richtige Animationsrolle, Materialwirkung oder Spielkompatibilität.

„Modpaket · ZIP“ enthält den Pfad `BepInEx/plugins/<Mod-ID>/`. „Modpaket · SEMOD“ enthält dagegen `info.json` direkt an der Archivwurzel. Beide sind Varianten desselben vorbereiteten Assetmods; nicht gleichzeitig installieren. Der mitgelieferte `port-report.json` enthält Zuordnungen, Metadaten, Prüfergebnisse, Hashes und ausdrücklich `inGameTested: false`. Voraussetzung und Abnahmeverfahren stehen im Recherchebericht. Originale Spieldateien werden durch den Editor nicht geöffnet oder verändert.

## 7. Tastatur

Strg/Cmd+O öffnet, Strg/Cmd+S speichert. Strg/Cmd+Z macht rückgängig, Strg/Cmd+Umschalt+Z oder Strg+Y wiederholt. F passt ein, 1 setzt den Zoom auf 100 %, Plus/Minus ändern ihn. Leertaste mit Ziehen verschiebt die Ansicht; in der Animationsansicht schaltet Leertaste die Wiedergabe. Pfeiltasten verschieben ausgewählte Sprites im Aufbau, Umschalt erhöht den Schritt auf 10 Pixel. Tastenkürzel können vom Browser oder Betriebssystem reserviert sein; die entsprechenden Menüeinträge bleiben verfügbar.
