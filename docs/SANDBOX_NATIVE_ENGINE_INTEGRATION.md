# Sandbox Studio: Original-Engine statt geratener Terrainframes

Stand: 11.10.2026. Quelle der technischen Aussagen: die auf diesem PC
installierten SHCDE-Dateien, isolierte Funktionsaufrufe und aufgezeichnete
Original-Grafikbefehle. Keine Spielbibliothek und keine Spielgrafik ist
Bestandteil dieses Git-Changesets.

## Was sich grundlegend geändert hat

Die Sandbox muss die Auswahl von Gras-, Sand-, Wasser-, Fels- und
Gebäude-Frames nicht mehr aus unvollständig bekannten Map-Bytes raten.
Sie kann den **installierten nativen Spielkern** in einem getrennten,
kurzlebigen Prozess eine Kopie der Originalkarte öffnen lassen. Ein erster,
**pausierter Editor-Frame** liefert dieselben Grafikentscheidungen, die
auch der installierte Unity-Renderer als Eingabe erhält.

Der neue Pfad ist standardmäßig aktiv, wenn exakt die verifizierte
Spielbibliotheksversion verfügbar ist. Der frühere Näherungsrenderer
bleibt als bewusst auswählbarer Fallback und für nicht unterstützte
Installationen erhalten.

## Verifizierte Schnittstelle und Herkunft

Es wurden die Rollen der öffentlich sichtbaren Managed-Typen
`EngineInterface`, `GameMap`, `SpriteMapping`, `spriteLoader`, `gameTile`
und `TilemapManager` in der installierten `Assembly-CSharp.dll` analysiert.
Private Analyseausgaben bleiben unter `work/engine-render-probe/` und
werden nicht in Git übernommen. Der Interoperabilitätsvertrag speichert
nur benötigte numerische Indizes, Ressourcennamen und Größen:

`config/sandbox-native-render-contract-v1.json`

Er ist an zwei SHA-256-Prüfsummen gebunden:

- `CrusaderDE.dll`:
  `1e6d4c2e10cc35a7b8082a7e2bcd8bb20680ebeda803d9b943257b948145cb2b`
- `Assembly-CSharp.dll`:
  `01da4c57f8a0e04a77804e78f79bacb1ae63d934d6d391f0dcaf3742bcca5de3`

Eine unbekannte oder geänderte Bibliotheksversion wird vor dem Laden
abgewiesen. Es gibt kein automatisches Vertrauen in eine beliebige DLL
oder in willkürliche Funktionssignaturen.

### Sicherer Ablauf

1. Original-Map und Bibliotheken werden gehasht.
2. Die Map wird in einen temporären Arbeitsordner **kopiert**.
3. Ausschließlich im getrennten Workerprozess wird die passende lokal
   installierte Bibliothek geladen. Arbeits-/Autosave-/Save-Pfade zeigen
   auf isolierte temporäre Ordner.
4. `DLL_PreInitMap_Editor` und `DLL_LoadSaveGame` laden die Kopie.
5. `DLL_RunTick` erzeugt bei aktivem Pausenflag einen vollständigen
   Grafikbefehls-Frame. Es werden **keine** Save-, Bau-, Multiplayer-
   oder sonstigen Spielaktions-Entrypoints aufgerufen.
6. Original und Kopie müssen danach dieselben SHA-256-Prüfsummen haben.
7. Der Worker beendet sich; die Sandbox erhält nur abgeleitete Daten.
   Timeout oder Prozessabsturz wird als Fehler gemeldet, nicht im
   GUI-Prozess ausgeführt.

Der lokale Cache unter `work/sandbox-engine-cache/` ist an Kartenhash,
DLL-Hash und Aufnahmeprotokollversion gebunden. Länge, Datensatzanzahl,
SHA-256 und native Koordinaten werden vor jeder Verwendung validiert.

## Was aus der Original-Engine stammt

Ein Grafikdatensatz besteht aus **21 signed 16-Bit-Werten**. Der
bestätigte Maximalpuffer enthält 14.700.000 solcher 16-Bit-Werte;
pro Frame sind höchstens 700.000 Grafikdatensätze erlaubt.

Für Kacheldatensätze liefert der Spielkern insbesondere:

- native X-/Y-Koordinaten;
- GM-Spritefamilie und Bildindex;
- tatsächlichen Höhenwert;
- Beleuchtungs-/Farbindizes;
- gesonderte Kanten-/Felsseiten-Grafikbefehle;
- Gebäudeteile und ihre Höheninformationen.

Zusätzlich erzeugt er originale Vegetations-, Einheiten- und
Gebäudeanimationsbefehle. **Die Rohdatensätze einer .map und die
sichtbaren Objekte eines initialisierten Spielframes sind nicht
identisch:** Der Originalkern kann beim Laden beispielsweise Lords
initialisieren oder nur aktuell sichtbare Baumzustände ausgeben.

### Reproduzierbar gemessene Referenzaufnahmen

| Originalkarte | Sichtbare Tile-Grafikbefehle | Weitere Zeichenbefehle |
| --- | ---: | ---: |
| Antioch.map | 44.104 | 1.040 |
| Crusader Demo.map | 44.104 | 1.080 |
| A Mighty Oasis.map | 78.804 | 1.242 |

Die Zahlen beziehen sich auf den **ersten pausierten Editor-Frame** des
verifizierten Spielkerns, nicht auf jeden denkbaren Spielstand.

Beispiel aus `Antioch.map`:

- Kachel `(400,400)`: **GM55 / Bild305 / Höhe8 / Licht3**.
  Die Familie GM55 entspricht laut Original-Sprite-Loader
  **`tile_land_macros`**. Der bisherige vereinfachte `tile_land8`-
  Terrainansatz war damit als allgemeine Originalzuordnung falsch.
- Kachel `(505,385)`: **GM52 / Bild732 / Höhe8**,
  also ein tatsächlicher `tile_castle`-Teil.
- Kachel `(505,388)`: **GM52 / Bild717 / Höhe8**.

Die verschiedenen Original-Bildindex-Konventionen werden getrennt
behandelt: Terrainfamilien indexieren ihre Arrays direkt, die meisten
Einheiten- und Baumfamilien verwenden `Bildindex - 1`. So wird etwa der
native Kaktusbefehl GM200/Bild17 korrekt zum Originalsprite
**`tree_cactii-16`**, nicht zum nicht vorhandenen `tree_cactii-17`.
Die seitenübergreifenden GM166-Meer-/Uferbereiche sowie die beobachteten
Wasserlicht-/Frame-Normalisierungen werden ebenfalls berücksichtigt.

## Sichtbarer Kartenrenderer

`tools/sandbox_runtime_renderer.py` setzt die Original-Grafikentscheidungen
mit den lokalen Spritebildern um. Kartenhöhe wird nach der im installierten
Renderer beobachteten Skalierung dargestellt: **64 Pixel je Welt-Einheit**,
Höhenwert geteilt durch **32**, also zwei Bildpixel je Höheneinheit.

Die bisher vorhandenen Chunk-Caches, Kamera, Minikarte und Editor-Overlays
bleiben verwendbar. Auch die vollständige herausgezoomte Kartenansicht
wird im Engine-Modus aus echten Spriteentscheidungen aufgebaut, nicht
mehr nur aus nachgeahmten Radarfarben.

### Zwei Grafikquellen bei denselben Original-Engine-Befehlen

Im Sandbox-Spiel-HUD gibt es die Auswahl:

- **Engine + Arbeitsgrafiken**: verwendete Sprite-Suite-Grafiken aus
  Arbeitskopie/Auslieferung, mit Original-Engine-Tile-/Objektentscheidungen.
- **Engine + Originalgrafiken**: unveränderte lokal installierte
  `resources.assets`-Sprites als visuelle Referenz. Manuelle Terrain-
  Sprite-Ersetzungen werden für diesen Referenzmodus nicht angewendet.
- **Näherungs-/Testansicht**: früherer offline rekonstruierter Renderer,
  weiterhin für Diagnose und manuelle Experimente zugänglich.

Fehlende Originalgruppen in einem ausgelieferten Mod, etwa Kaktusgrafiken,
werden direkt und read-only aus der passenden lokalen `resources.assets`
gelesen. Fehlende gewöhnliche Katalog-Frames können in den abgeleiteten
Crusader-Katalog exportiert werden. Existierende Arbeitsbilder, PNGs und
Indexeinträge werden dabei nicht überschrieben.

Die Originalobjekt-Markierungen bleiben als auswählbare Datenobjekte
vorhanden. Im Engine-Modus verdecken sie die echten Originalsprites nicht
mehr als bunte Ersatzkreise. Manuelle eigene Overlay-Sprites bleiben
auswählbar, verschiebbar und separat speicherbar.

## Interaktiver Grafiktest

1. `Sandbox Studio starten.cmd` öffnen; eine unterstützte installierte
   Karte wie `Antioch.map` wird im Kartenmodus angezeigt.
2. Im Sandbox-Spiel-HUD **Engine + Arbeitsgrafiken** bzw.
   **Engine + Originalgrafiken** wählen.
3. Eine Kachel oder ein durch die Engine ausgewähltes Gebäudeteil
   anklicken. Der Inspector zeigt GM-Datei, Original-Bildindex,
   aufgelöste Spritegruppe, Frame, Höhe und Licht.
4. **Grafik dieser Engine-Kachel direkt bearbeiten** öffnet den
   Pixeleditor für genau diesen ermittelten Frame statt für einen
   beliebigen manuell gewählten Testframe.
5. PNG speichern: Der native Kartenrenderer invalidiert seine
   abgeleiteten Bilder/Chunks und übernimmt die Arbeitskopie.
   Ein vorheriger Original-Referenzmodus wechselt dafür bewusst
   zurück auf Arbeitsgrafiken, damit die Änderung sichtbar wird.

Das Original-XAML-HUD wurde außerdem bei dynamischem Docking korrigiert:
Die Originalgrafiken werden nach dem tatsächlichen Viewport-Resize
angepasst, statt bei einem frühen 0-Pixel-Layout als winziger Streifen
stehenzubleiben. Der Inspector ist scrollbar, damit die Werkzeuge auch
bei niedrigeren Fensterhöhen erreichbar bleiben.

## Prüfungen und Sicherheitsgrenzen

Neue Regressionen prüfen:

- numerische Datenformate, doppelte Koordinaten, beschädigte Cachedateien;
- Originalbibliotheks-Hashes und sichere/kanonische ABI-Tabellen;
- alle drei echten Originalkarten und unveränderte Kartenbytes;
- tatsächliche GM-/Frame-Identitäten ausgewählter Kacheln;
- Sonderfälle und Grenzen der Wasser-, Ufer- und Körperframe-Indizes;
- echte Original-Kaktusgrafiken und Ableitung ohne Veränderung der Quellen;
- Height-Offsets, Felsseiten, Quellwahl, Cache-/Live-Reload;
- originales Bild versus Arbeitskopie, pixelgenauen Frame-Aufruf im Editor;
- nachträgliches Dock-Layout des Originalgrafik-HUDs.

Private lokale Sichtprüfungen befinden sich unter `work/`, unter anderem
`native_engine_original.png`, `native_engine_original_cliff.png`,
`native_engine_working.png` und `native_engine_full_map_original.png`.
Diese Spielbilder gehören nicht ins öffentliche Repository.

## Präzise verbleibende Abweichungen

**Die Auswahl der Tile- und Objekt-Grafiken wird jetzt tatsächlich vom
Original-Spielkern geliefert.** Sie ist nicht mehr eine Heuristik aus
3003/3005/3037. Das bedeutet trotzdem noch keine bewiesene vollständige
Pixelparität zur Unity-Ausgabe:

- Die Qt-Seite ersetzt nicht sämtliche Unity-Materialien, Wind-/Masken-
  Shader, Wasseranimationen und Spezialeffekte.
- Spezielle Layer/Partikel, einzelne Animations-/Subpixelzustände und
  vollständige dynamische Tiefenüberlagerung müssen gegen Spielbilder
  weiter geprüft werden.
- Der Snapshot ist ein initialisierter **pausierter** Editorzustand,
  keine laufende Stronghold-Wirtschafts-/Kampf-Simulation.
- Exakte Gameplay-HUD-Zustände sind weiterhin nicht vollständig durch
  die rekonstruierte XAML-Testoberfläche ersetzt.
- Andere Bibliotheksversionen benötigen einen separat geprüften ABI-
  Vertrag; Karten ohne den bislang unterstützten Offline-Containerpfad
  können in der GUI weiter auf die Radarvorschau zurückfallen.

Die Original-Engine-Anbindung beseitigt damit den größten bisherigen
Engpass – geratenes Material-/Objekt-Sprite-Mapping – und stellt die
verbleibenden Grafikabweichungen erstmals auf eine direkt messbare,
spielseitig erzeugte Datenbasis.

## Erweiterung 2026-10-11: tatsächliche Pixel anklicken, RGB-Tilefarben

**Originalgrafik unter dem Mauszeiger.** Die bisherige Auswahl funktionierte
primär nach native Kachelkoordinaten. Bei hohen Gebäuden, Cacti, Bäumen und
Einheiten wählte sie damit oft das **Bodenbild unter dem Objekt**, obwohl
das gewünschte Sprite deutlich höher oder über einer Nachbarkachel lag.

Jetzt prüft die Engine-Ansicht in umgekehrter nativer Zeichenreihenfolge die
tatsächlich gerenderten Alpha-Pixel von Boden-, Höhen-/Klippen-, Baum-,
Truppen- und Gebäudeanim-Grafiken. Durchsichtige Pixel gelten ausdrücklich
**nicht** als Treffer: Ein darunter sichtbares Sprite bleibt auswählbar.
Die Treffer enthalten Spritegruppe, natives Originalbild, resultierenden
Katalogframe, Höhe/Licht/Deckkraft und Originalposition. Es findet dabei
**keine** Simulation oder Änderung der Originalkarte statt.

Ein linker Klick aktualisiert den sichtbaren Originalkarten-Inspector und die
Sprite-Grafikvorschau. Die erkannte Grafik kann über **Strg+E** oder den
Button **„Grafik dieser Engine-Kachel direkt bearbeiten“** als separate
Arbeitskopie verändert werden. Der Pixel-Editor bleibt bei der bestehenden
atomischen PNG-Speicherung und beim nachfolgenden Frame-Live-Reload.

Die Suche grenzt Kandidaten zunächst per Vektoroperation auf benachbarte
Original-Engine-Grafikkommandos ein und prüft erst nach günstigem Anker-/
Bildgrenzenfilter deren echte Alpha-Kanäle. Bei der lokalen Antioch-Karte
lagen sechs Realgrafik-Klicks nach dem ersten Laden überwiegend bei
**0,06–0,30 Sekunden** (der erste durch Sprite-Asset-Nachladen etwa
0,5 Sekunden). Durch Überlappung kann dabei korrekt der **vordere**
Pine-/Cactus-Frame statt des direkt darunter gespeicherten Objekts
ausgewählt werden. Das ist eine lokale Messung, kein garantierter
Framerate-Wert für alle Karten/Bildgrößen.

**Original-Unity-Farb-/Lichtregeln.** Aus der zum ABI-Vertrag passenden
`Assembly-CSharp.dll` wurden die tatsächlich verwendeten
`gameTile.setTileColour`- und `TilemapManager`-Multiplikatoren
in `runtime_graphics.tile_tint_components` übernommen:

- 1–7: sieben gleichmäßige Schattenstufen von 0,9 bis 0,3;
- 11–17: Schattenstufen von 0,94 bis 0,58;
- 50–55: Wasserlichtstufen, 51=0,95, 52=0,90, 53=0,85,
  54=0,80 und 55=0,85;
- Float-Farbkanal 55–63: exakte, **kanalunterschiedliche RGB-Faktoren**
  für Rot, Grün, Blau, Tan, Grau, Braun und weitere Engine-Farben.
  Ein aktiver `floatColour`-Wert hat wie im GameTile-Code Vorrang
  vor dem normalen Lichtwert.

Der Renderer bewahrt Alpha beim Einfärben. Er führt die Farbkomponenten
jetzt im Frame-Cache separat, sodass verschiedene Original-Tints
nicht irrtümlich dieselbe schon eingefärbte QPixmap verwenden.
Die drei geprüften spielbaren Karten lieferten zunächst ausschließlich
`floatColour=0`; der Effekt des Sonderkanals wird deshalb zusätzlich
synthetisch getestet und **nicht** als schon sichtbare Verbesserung
dieser drei Karten ausgegeben. Durch Qt-Premultiplikation können RGB-Werte
mit Alpha um 1–2 Einheiten vom idealen PIL-Ergebnis abweichen.

### Tests und Grenzen

- `tests/sandbox/test_engine_sprite_picking.py`: transparenter
  Baum über Boden, korrekte Zeichenreihenfolge, ausgeblendete Objekte,
  reales Snapshot-Frame und GUI-Mausklick bis zum Pixel-Editor.
- `tests/sandbox/test_engine_tile_colours.py`: Originalschatten,
  RGB-Einzelfaktoren, Farbvorrang, separate Frame-Cache-Einträge,
  unverändertes Alpha und gemeinsame Einfärbung von Fels-/Klippenflächen.
- Lokale Bildkontrolle: `work/native_engine_actor_selected.png`.

**Die Grenzen bleiben:** Kein vollständiges visuelles Eins-zu-eins-Rendering
der Unity-Material-/Wind-/Wasser-/Partikelshader. Der Hit-Test und die
Farbfaktoren folgen den im gepinnten Engine-Snapshot sichtbaren
Grafikkommandos. Besonders große oder bisher unbekannte Spriteabmessungen
und animierte Zwischenzustände brauchen gesonderte Abnahmetests.
