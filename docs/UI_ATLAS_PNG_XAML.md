# UI-Atlas aus PNG und XAML bearbeiten

**Gilt für den neuen Main-Quellstand.** Ältere RC4-Downloadpakete enthalten
diesen freien PNG/XAML-Arbeitsbereich noch nicht.

Mit **Strg+K → UI-Atlas · PNG + XAML** den Atlas-Arbeitsbereich öffnen.
Weitere Einstiege sind **Projekt & Dateien → Mehr → UI-Atlas (PNG + XAML)…**
und unter **Oberfläche** der Knopf **PNG + XAML öffnen…**.
Für diesen Weg werden eigene PNG- und XAML-Dateien benötigt; eine eingerichtete
Spielinstallation und ein vorheriger Suite-Export sind nicht erforderlich.

## Zielatlas öffnen

1. Unter **1 · Zielatlas** bei **Atlas-PNG** und **Atlas-XAML** jeweils
   **Auswählen …** verwenden. Das PNG ist das Blatt, das geändert werden soll.
   Die XAML-Datei muss die dazugehörigen Atlas-Rechtecke beschreiben.
2. **BitmapImage-Key (optional)** zunächst leer lassen: Dann ordnet der
   PNG-Dateiname das passende Blatt im XAML automatisch zu. Heißt das
   extrahierte PNG anders oder ist die Zuordnung mehrdeutig, hier den
   tatsächlichen `BitmapImage`-Ressourcenschlüssel angeben.
3. **PNG + XAML als Arbeitsstand öffnen** anklicken. Die Suite kopiert beide
   Originaldateien in einen neuen Arbeitsstand und zeigt die `ResourceKey`-
   Einträge mit **Rechteck x, y · Breite × Höhe** an.
4. Mit **Einträge filtern** den gewünschten Schlüssel suchen und auswählen.
   **Original des Zieleintrags** und **Aktueller Zieleintrag** zeigen den
   Ausschnitt vor und nach den bisherigen Änderungen.

Ohne ausdrücklich gesetzten Schlüssel muss der PNG-Dateiname zum `UriSource`
genau eines `BitmapImage` im XAML passen. Die Ausschnitte müssen als
`CroppedBitmap` mit Ressourcenschlüssel, Verweis auf
dieses Blatt und ganzzahligem `SourceRect` innerhalb des Bildes vorliegen.
Ein beliebiges Menü-XAML ohne diese Atlasdaten genügt nicht. XAML wird als
Beschreibung gelesen; es wird kein UI-Code daraus ausgeführt.

Verweist eine XAML-Datei auf mehrere Atlasblätter, wird nur das passend
ausgewählte PNG geladen. Hinweise auf weitere, nicht mitgelieferte Blätter
bleiben sichtbar. Diese Dateien werden weder automatisch gesucht noch durch
Platzhalter ersetzt; für ein vollständiges Modpaket müssen die weiterhin
benötigten Ressourcen vorhanden sein.

## SH1-Ausschnitt in einen anderen Masteratlas übertragen

1. Den zu ändernden Masteratlas als **Zielatlas** laden, etwa den Crusader-
   Master. Unter **2 · Quellatlas oder Ersatz-PNG** das eigene SH1-PNG mit
   seinem passenden XAML öffnen. Bereits vorhandene Arbeitsstände lassen sich
   auf beiden Seiten mit **Arbeitsstand laden …** wieder öffnen.
2. In der Zielliste das Rechteck wählen, das ersetzt werden soll. In der
   Quellliste den gewünschten SH1-Ausschnitt wählen. Die Ressourcenschlüssel
   dürfen unterschiedlich heißen; entscheidend ist die bewusste Auswahl.
3. **Aus gewähltem Quellatlas-Eintrag** auswählen. Unter **Gewählte Quelle**
   den Ausschnitt und unter **Größenanpassung** das gewünschte Verfahren prüfen.
4. **Auswahl ersetzen** anklicken. Nur das ausgewählte Zielrechteck wird
   ersetzt. Danach den aktuellen Zieleintrag prüfen.

| Größenanpassung | Ergebnis |
| --- | --- |
| `exact` – Voreinstellung | Quell- und Zielgröße müssen übereinstimmen; sonst wird die Ersetzung abgelehnt. |
| `contain` | Seitenverhältnis erhalten, auf das Ziel einpassen und zentrieren. Freie Ränder sind transparent. |
| `stretch` | Auf die gesamte Zielgröße strecken; das Seitenverhältnis kann sich ändern. |

`contain` und `stretch` verwenden die nächste Pixelnachbarschaft. Transparente
Quellpixel ersetzen die Zielpixel ebenfalls; die Funktion mischt nicht bloß
eine neue Grafik über den alten Hintergrund. Das Ziel-XAML und seine Rechtecke
werden durch den Transfer nicht umgeschrieben. Ein übertragenes Bild übernimmt
dadurch noch keine Menülogik oder Bedienfunktion aus dem anderen Spiel.

## Einen Ausschnitt selbst bearbeiten

**Aktuellen Ausschnitt als PNG exportieren …** schreibt die gewählte Zielgrafik
in eine neue PNG außerhalb des Arbeitsstands. Diese Datei kann in einem
Bildeditor bearbeitet werden. Anschließend **Aus einzelner Ersatz-PNG** wählen,
bei **Ersatz-PNG** die bearbeitete Datei auswählen und **Auswahl ersetzen**
verwenden. Bei `exact` die ursprünglichen Pixelabmessungen beibehalten.

**Rückgängig** und **Wiederholen** ändern den gespeicherten Bearbeitungsverlauf.
**Original wiederherstellen** setzt das gewählte Rechteck auf seine
unveränderte Ausgangsgrafik zurück und ist selbst rückgängig machbar.
Überlappende XAML-Einträge können denselben Pixelbereich zeigen: Eine Änderung
dort ist daher auch in den anderen betroffenen Ausschnitten sichtbar.

## Arbeitsstand und Ausgabe behalten

Jede abgeschlossene Änderung wird automatisch im Arbeitsstand gespeichert.
Der angezeigte Arbeitsordner enthält `atlas-project.json`, die Quellkopien unter
`source` und die Ersetzungen unter `patches`. Zum Fortsetzen **Arbeitsstand
laden …** und diesen ganzen Ordner wählen. Für eine manuelle Sicherung den
gesamten Ordner behalten. Die einzelnen Patch-Dateien sind kein vollständiger
Projektstand.

**Vorgang abbrechen** fordert den Abbruch einer laufenden Arbeit an. Bereits
abgeschlossene, gespeicherte Änderungen bleiben erhalten und lassen sich über
**Rückgängig** zurücknehmen. Wird eine Projektübernahme vor ihrem eigentlichen
Übernahmeschritt abgebrochen, führt die Suite diesen später nicht nachträglich
aus.

**Aktuellen Atlas als PNG exportieren …** erzeugt das vollständige geänderte
Blatt in Originalgröße. Dafür einen neuen Dateinamen außerhalb des verwalteten
Arbeitsstands wählen; vorhandene Dateien werden nicht ersetzt. Die
Eingabeoriginale bleiben erhalten. Beim Neuaufbau bleiben die RGBA-Pixel
außerhalb der ersetzten Rechtecke gleich, die komprimierten PNG-Dateibytes
können sich ändern.

### In das Mod-Projekt übernehmen

Ist der Atlas-Arbeitsbereich an das aktuelle Mod-Projekt gebunden, steht
**Ins Mod-Projekt übernehmen** bereit. Dieser ausdrückliche Schritt erzeugt
zuerst eine geprüfte Paarausgabe aus geändertem PNG und bytegleich erhaltenem
Ziel-XAML. Beide Dateien werden unter `Override/Assets/GUI/Sprites` in das
aktuelle Projekt übernommen. Relative PNG-Unterordner aus dem XAML bleiben
erhalten. Bereits vorhandene Projektdateien werden vor dem Ersetzen als
Revision gesichert; eine zwischenzeitlich fremd geänderte Datei wird nicht
blind überschrieben.

Im Projekt anschließend **Geprüftes Mod-ZIP bauen** beziehungsweise
**Mod-ZIP speichern unter…** verwenden. Das Paket nutzt die normale
Projektpipeline. Die Übernahme ersetzt keine installierte Spieldatei und
ändert das XAML nicht passend zu einem anderen Spiel um. Hinweise auf weitere
benötigte Atlasblätter vor dem Paketbau klären.

## Größen und Grenzen

Der Atlas-Arbeitsbereich akzeptiert bis **134.217.728 Pixel pro PNG** und
**16 MiB XAML**. Damit liegen ein Master mit **8192 × 8192** sowie ein
SH1DE-Master mit **8192 × 4096** innerhalb seines Pixelbudgets. Die verkleinerte
Ausschnittvorschau verändert die gespeicherten Pixel nicht. Zum Lesen einer
PNG und beim vollständigen Export kann trotzdem ein ganzes Blatt im
Arbeitsspeicher decodiert werden; große Atlanten benötigen entsprechend RAM.

Die niedrigeren Einzelbildgrenzen des allgemeinen HUD-/Menüimports und des
HTML-Sprite-Editors gelten weiterhin für diese anderen Editoren. Das freie
Atlaswerkzeug ersetzt die ausgewählten Rechtecke; es ist kein Malprogramm für
das gesamte 8K-Blatt. Eine neue PNG-Ausgabe allein bestätigt weder die
Spielintegration noch eine sichtbare Prüfung im laufenden Spiel.

Der zusätzliche allgemeine Asset-Inspector hat ein eigenes XML-Lesebudget von
4 MiB. Bei größeren XAML-Dateien meldet er eine Warnung und bestätigt keinen
erfolgreichen XML-Parse. Das verhindert nicht das bytegleiche Archivieren über
die normale Projektpipeline. Fehlerhaftes kleines XML bleibt im Inspector
ein echter Fehler.

Für den alternativen Export aus einer eigenen Spielinstallation und die
zugehörigen Unity-/Script-Extender-Prüfungen siehe
[Aktuelle Arbeitsabläufe](WORKFLOWS.md#6-ui-atlanten-und-ui-bc7).
