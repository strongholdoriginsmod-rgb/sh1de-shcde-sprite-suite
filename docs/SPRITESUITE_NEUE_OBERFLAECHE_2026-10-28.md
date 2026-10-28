# SpriteSuite – Die neue Oberfläche

**Stand: 28. Oktober 2026.** Dieses Handbuch gilt für die neu gegliederte
Windows-Oberfläche. Der technische Funktionsumfang und vorhandene Projektdateien
bleiben erhalten. Die Bedienelemente entsprechen dem aktuellen Programmstand.

## Orientierung

Die **linke Leiste** zeigt die häufigsten Aufgaben:
- **Start:** Direkte Einstiege zu Bild, Layout, Vorschau und Paket.
- **HUD & Menüs:** Eigene Bilder einfügen, malen, anordnen und exportieren.
- **Sprites bearbeiten:** Einzelgrafiken und Frames ändern.
- **SH1 HUD-Studio:** Bestehende Stronghold-1-HUD-Bilder bearbeiten.
- **ORIGINS-Grafiken:** Herkunftsgeprüfte Grafiken durchsuchen.
- **Spielvorschau:** Grafiken in der Sandbox betrachten.
- **Prüfen:** Fehler und fehlende Voraussetzungen untersuchen.
- **Paket erstellen:** Geprüfte Dateien für den Modbau vorbereiten.
- **Ziele & Mods:** Zielspiel und bestehende Modpakete verwalten.

**Weitere Bereiche** öffnet auch die älteren Spezialseiten. Nichts wurde
gelöscht. Oben kann man jederzeit einen Bereich auswählen oder **Strg+K**
drücken und dessen Namen suchen. Über **Alle Reiter** erscheint bei Bedarf
wieder die klassische Reiterliste. **Protokoll anzeigen** öffnet die
Werkzeugausgaben; es ist im Alltag nicht notwendig.

## Projekt beim nächsten Programmstart fortsetzen

Unter **HUD & Menüs** steht jetzt immer **Aktives Projekt:** mit dem
Namen des Arbeitsordners. Nach einem Neustart öffnet die Suite den
zuletzt verwendeten, vorhandenen Arbeitsordner, markiert nach
Möglichkeit dieselbe Grafik und öffnet im Layout-Designer das
zuletzt **gespeicherte Layout** wieder. Beim Import mehrerer Dateien
wird die zuletzt erfolgreich importierte Grafik ausgewählt. Ein neu angelegter,
noch leerer Arbeitsordner bleibt ebenfalls als letzter Arbeitsstand
eingetragen.

Mit **Arbeitsordner anzeigen → Ordner …** kann man bewusst ein anderes
Projekt auswählen. Die Zuordnung steht unter
`SpriteSuite/work/.hud-menu-last-session.json`, enthält **nur relative
Pfade** und keine systemweiten Dateiverknüpfungen. Originaldateien
bleiben an ihrem alten Speicherort unverändert. Wenn das gespeicherte
Projekt gelöscht oder verschoben wurde, startet die Suite wieder mit
dem Standardarbeitsordner.

**4 Export vorbereiten** öffnet den Layout-Designer nun direkt beim
passenden nächsten Schritt. Ein zusätzlicher Erklärungshinweis
blockiert die Vorschau nicht mehr. Erst nach Betätigung eines
Exportknopfs wird wirklich eine Datei geschrieben.

Die Merkhilfe speichert nur **den Namen** des zuletzt gespeicherten
Layouts. Die tatsächlichen Ebenen und Positionen bleiben in den
Layout-Metadaten unter `work/.hud-menu-metadata/`. Wer Projekte auf
einen anderen Installationspfad oder Computer übertragen möchte,
muss diese Daten gesondert sichern; die Merkhilfe allein ist kein
vollständiger Projektarchiv-Export.

## Erste Übung: NeuesMenuBild.png bearbeiten

1. **HUD & Menüs** in der linken Leiste auswählen.
2. Ist `NeuesMenuBild.png` in der Liste sichtbar, diese Zeile anklicken.
   Wenn noch keine Grafik da ist: **1 Bild öffnen** drücken und eine
   eigene PNG-, JPG- oder WebP-Datei auswählen. Als Kategorie
   **Menüs / UI-Bilder** verwenden und die Importbestätigung annehmen.
   Die ursprüngliche Bilddatei wird nicht überschrieben.
3. Um direkt **Pixel zu zeichnen**, **2 Pixel bearbeiten** wählen.
   Im Pixeleditor links oben Pinsel, Radierer oder andere Werkzeuge
   auswählen. **Speichern (Strg+S)** sichert die bearbeitete Arbeits-PNG.
4. Um das Bild **zu verschieben und zu skalieren**, **3 Layout gestalten**
   wählen. Im geöffneten Layout-Designer rechts die PNG auswählen und
   **Bild einfügen** drücken. Eine markierte Ebene mit der Maus ziehen.
   Gelbe Griffe ändern die Größe; der grüne Griff dreht.
5. **Speichern · Strg+S** im Layout-Designer anklicken. Das bewahrt
   Ebene, Position, Größe, Anker, Drehung und Sichtbarkeit. Dann
   **Layout → PNG + Positionsdaten** wählen, einen neuen PNG-Namen
   eingeben und den Export bestätigen.
6. Für eine reine Vorschau ist der Vorgang nun abgeschlossen. Für eine
   konkrete Spieloberfläche **Spieloberfläche anbinden (Noesis)**
   wählen und erst dann einen im Zielspiel wirklich vorhandenen
   XAML-Container auswählen. Im Spiel selbst muss die Anzeige geprüft werden.

## Welcher Editor ist der richtige?

| Gewünschte Änderung | Richtiger Bereich |
| --- | --- |
| Farbe, Kontur, Transparenz oder einzelne Pixel ändern | Pixeleditor |
| Button-Bild bewegen, drehen, vergrößern, mehrere Bilder kombinieren | Layout-Designer |
| Vorhandene Stronghold-1-HUD-Grafik austauschen | SH1 HUD-Studio |
| Sprites auf einer Karte ansehen und vergleichen | Spielvorschau |
| Fertige Menü-/HUD-Grafik für Noesis verankern | Layout-Designer → Spieloberfläche anbinden |
| Eine eigene Moddatei prüfen und zusammenstellen | Prüfen / Paket erstellen |

**Wichtig:** Das Layout verschiebt zuerst nur die Grafik. Bestehende
anklickbare Spielschaltflächen behalten ihre bisherige Trefferfläche.
Eine neu gezeichnete Schaltfläche erhält nicht automatisch eine
Spielfunktion.

## Die Schaltflächen im Bereich „HUD & Menüs“

Die vier großen Schaltflächen oben führen in Arbeitsreihenfolge:
**1 Bild öffnen → 2 Pixel bearbeiten → 3 Layout gestalten →
4 Export vorbereiten.**

**Bildkategorie** bestimmt den Ordner, unter dem neue Grafikdateien
im Projekt geführt werden. **Transparentes PNG erstellen** legt ein
leeres eigenes Bild an. **Suche** filtert die darunterliegende
Bildliste; sie durchsucht nicht das Internet.
**Arbeitsordner anzeigen** blendet bei Bedarf die tatsächlichen Dateipfade ein.
**Weitere Grafikwerkzeuge anzeigen** blendet nur die Spezialaktionen
ein. Die meisten Bearbeitungen benötigen diese Aktionen nicht.

Im rechten Teil gibt es **Bild** (aktuelle Arbeitsgrafik),
**Original** (Importzustand, soweit vorhanden) und **Layout**.
Das Layoutfenster selbst öffnet sich über den dritten Hauptschritt.

## Im Layout-Designer

Direkt unter dem Fenstertitel zeigt der Editor, was als Nächstes nötig ist.
Ein Knopf rechts daneben führt genau diese Aktion aus:

- **1 / 4 – Bild platzieren:** Ist schon eine Werkstatt-PNG ausgewählt,
  **Bild einfügen** wählen. Ansonsten **PNG importieren**.
- **2 / 4 – Änderungen speichern:** Bild verschieben, Größe und Drehung
  ändern, anschließend **Layout speichern**.
- **3 / 4 – PNG erzeugen:** Nach dem Speichern die zusammengesetzte
  PNG samt Positionsdatei erzeugen. Die Schaltfläche öffnet die Namensabfrage.
- **4 / 4 – PNG bereit:** Letzter geprüfter Export passt zum gespeicherten
  Layout. **Spieloberfläche zuordnen** öffnet die Noesis-Anbindung.
  Das Spiel wurde bis hierhin nicht verändert.

In **Bildquelle auswählen** stehen die lesbaren Dateinamen vorn,
danach die Kategorie. Der vollständige Ressourcenpfad wird intern
weiterhin korrekt gespeichert. In der **Ebenenliste** sind Sichtbarkeit,
Sperre und Reihenfolge erkennbar. Unterhalb zeigt **Ausgewählt**,
wessen Zahlenwerte gerade bearbeitet werden. Leere Felder bedeuten,
dass keine einzelne Ebene ausgewählt ist.

**Weitere Aktionen** bündelt Kopieren, Einfügen, Duplizieren, Löschen,
Ebenen nach vorn/hinten bewegen, den gesonderten Asset-Paketbau und
**Exportstand prüfen**. Das Menü ist auch per Rechtsklick auf die
Arbeitsfläche oder die Ebenenliste erreichbar.

- **Neu:** neues, unabhängiges Layout mit eigener Größe erstellen.
- **Laden:** zuvor gespeichertes Layout wieder öffnen.
- **Speichern · Strg+S:** editierbares Layout inklusive Positionen speichern.
- **Bild einfügen / PNG importieren:** vorhandenes Bild als neue Ebene
  anlegen oder eine externe Bilddatei importieren.
- **Ebene nach vorne/hinten:** unter **Weitere Aktionen** die
  Ebenenreihenfolge verändern.
- **Kopieren / Einfügen / Duplizieren:** ebenfalls unter
  **Weitere Aktionen** oder per Rechtsklick verfügbar.
- **Raster / Snap:** beim Ziehen an Pixelabständen einrasten.
- **Position · Größe · Drehung:** exakte Zahlen für die gewählte Ebene.
  Nach dem Eingeben **Werte anwenden** anklicken.
- **Layout → PNG + Positionsdaten:** aktuelle Ansicht als
  zusammengefügte PNG und Positionsdatei ausgeben.
- **Spieloberfläche anbinden (Noesis):** eine geprüfte Spieloberfläche
  wählen und daraus ein statisches Spiel-Modpaket erzeugen.

Die Ebene muss ausgewählt und sichtbar sein. Bei einer gesperrten
Ebene sind Drag-Gesten gesperrt. Für Feinkorrekturen können die
Pfeiltasten und mit Shift die Zehnerschritte verwendet werden.

## Speichern, Exportieren und Weitergeben

**Speichern** behält eine editierbare Szene mit Ebenen. **Exportieren**
berechnet eine PNG, in der die Verschiebungen bereits enthalten sind.
Das sind zwei verschiedene Dateien. Ändert man später die Position
oder das Quellbild, muss **Layout → PNG + Positionsdaten** erneut
ausgeführt werden. Andernfalls ist der letzte PNG-Export veraltet und
der Paketbau darf ihn nicht übernehmen.

Arbeitskopien liegen unter `SpriteSuite/work/`. Persönliche
Spielinstallationen und originale Bilder werden nicht automatisch
überschrieben. Wer das Projekt auf einen anderen Rechner mitnehmen
möchte, muss sowohl den Arbeitsordner als auch die zugehörigen
Layout-Metadaten sichern; eine exportierte PNG ist kein editierbares
Ebenenprojekt.

## Häufige Probleme

**Keine Bilder in der Liste:** Die Filter-Suche leeren und prüfen, ob
das richtige Werkstattprojekt geöffnet ist. Danach **1 Bild öffnen**
verwenden oder über **Arbeitsordner anzeigen** den Ordner prüfen.

**Bild erscheint im Designer nicht:** Rechts eine PNG auswählen
und auf **Bild einfügen** klicken. Ein in der Werkstatt ausgewähltes
Bild ist im Designer zunächst nur als Quelle ausgewählt.

**Bild lässt sich nicht ziehen:** Ebene anklicken, in der
Ebenenliste auf **Sperren** und **Sichtbar** prüfen; gegebenenfalls
mit **Voransicht einpassen** den Arbeitsbereich zentrieren.

**Paket meldet veraltete Positionen:** Layout speichern und die
zusammengesetzte PNG noch einmal exportieren. Danach Paket neu bauen.

**Mod erscheint im Spiel nicht:** Die statische PNG allein macht kein
Spielmenü sichtbar. Für Stronghold Crusader DE eine passende Noesis-XAML
und einen tatsächlich vorhandenen Zielcontainer auswählen. Ohne
praktischen Spieltest ist die Anzeige nicht bestätigt.

**Schaltfläche ist nur optisch verschoben:** Das ist bei einem
statischen Overlay erwartbar. Die eigentliche Klickfunktion
gehört zur separaten UI-/ViewModel-Definition des Spiels.

**Einrichtung fordert Python an:** Für Windows den
[Portable-Release](https://github.com/strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite/releases/tag/windows-portable-resume-project-2026-10-28)
statt „Code → Download ZIP“ herunterladen. In der Portable-Version
wird Python mitgeliefert.

## Technische Grenzen

Ohne Einbau ins Spiel sind PNG und Positionsdaten nur ein bearbeiteter
Arbeitsstand. Die Noesis-Anbindung erzeugt ein statisches,
nicht anklickbares Overlay und überschreibt keine vorhandenen
Spielknöpfe. XAML- und Bild-Hashes werden vor dem Paketbau geprüft.
Manche weiteren Werkzeuge benötigen zusätzliche Spiel- oder
Buildkomponenten. Die Dateiformate der gespeicherten Layouts bleiben
mit dem vorherigen Editor kompatibel.
