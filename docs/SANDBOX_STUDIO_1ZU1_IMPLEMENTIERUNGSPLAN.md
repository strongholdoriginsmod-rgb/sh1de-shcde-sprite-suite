# Sandbox Studio – verbindlicher Weg zur spielgetreuen Kartenansicht

Stand: 11.10.2026. Implementierung direkt in `E:\SpriteSuite`, Branch `feature/sandbox-studio`.

## Abnahmedefinition: „endgültig“

Ein Kartenmodus gilt **erst** dann als originalgetreu, wenn (1) alle sichtbaren und
anklickbaren Kacheln der geladenen Originalkarte an richtigen Koordinaten liegen,
(2) Terrain, Höhen, Wasser, Wege, Übergänge und Gebäude in der richtigen
Z-Reihenfolge mit nachgewiesenen Original-Frames dargestellt werden,
(3) Originalgebäude, Mauern, Vegetation und relevante Einheiten mitsamt
sichtbaren Zuständen gerendert sind, (4) das HUD Layout, Zustand, Navigation,
Interaktionen und Framewechsel der Referenzversion repräsentiert und
(5) definierte Original-Screenshots bei identischer Kamera/Auflösung automatisch
und reproduzierbar verglichen werden. Die `.map` bleibt grundsätzlich read-only,
eigene Tests liegen separat in JSON-Arbeitskopien.

## P0 – Kartencontainer und tatsächliche Spielfläche

- [x] Drei installierte SHCDE-Karten haben validierte Abschnittsverzeichnisse,
  CRC32-geprüfte Dekodierung und 800 Reihen / 320.800 native Kacheleinträge.
- [x] Kanal 3003/3004/3005/3037/3043 werden native-indexgenau gelesen.
- [x] Empirische Analyse vom 11.10.2026: `3003==16` tritt in
  **Antioch** und **Crusader Demo** je 274.500 Mal auf, in
  **A Mighty Oasis** 239.600 Mal. Zusätzliche 3003-Werte `32`
  kommen 2.179, 2.152 bzw. 2.392 Mal ausschließlich in weit außen
  liegenden, unbelegten Randbereichen vor. 3004 ist **bei keiner
  dieser Randmarkierungen belegt**; es enthält 2.503, 2.407 bzw.
  1.541 Einträge im verbleibenden Bereich.
- [x] Die 3004-IDs können zusammenhängende 2×2-, 3×3- und 4×4-Fußabdrücke
  bilden. **Nicht** als tatsächliche Sprite-Bild-ID behaupten.
- [x] Für diese drei Formate gilt die getestete 3003-Abgrenzung
  `flags in {16, 32}` als nicht belegte Umgebung. Der Renderer zeichnet
  dort keine erfundenen Terrain-Sprites mehr. Kamera, Übersicht und
  Platzierwerkzeug beachten diesen Rand; das Qt-GUI und der Inspector
  haben reale Kacheltests gegen die drei Originalkarten.
- [x] Abschnitt-3004-Rohbelegungen werden separat als Diagnose-Layer
  gerendert und als individuelle 1×1- bis 4×4-Footprints inspiziert;
  **nicht** als bewiesene Sprite-Frame-ID interpretiert.
- [ ] Varianten ohne diesen Abschnitt separat analysieren; bei fehlender
  Aussagekraft nicht still den bekannten Datentyp vortäuschen.

## P0 – Originalterrain / Shader / Höhen / Übergänge

- [ ] 3003-Flagwerte und 3005-Bytewerte mittels Rohdatenstatistik,
  Karten-/Referenz-Screenshots und Quellspieldaten eindeutig klassifizieren.
- [ ] Unbestätigte Heuristik `3005=0⇒Wasser`, `3005=8⇒Gras`,
  `3005≥128⇒Fels` aus dem „originalgetreu“-Pfad entfernen;
  UI kennzeichnet jeden solchen Frame als *Näherung*.
- [x] 3004-Belegungs-Layer mit überprüften Fußabdrücken als
  Diagnose-Overlay anzeigen; verifizierte Positionen bleiben getrennt
  von sämtlichen Editor-Overlays und originalen Spritezuordnungen.
- [ ] Native Renderhöhe, Pivots, Isometrie und mehrlagiges Terrain mit
  nachprüfbarer Referenzreihenfolge und Kameraposition rekonstruieren.
- [ ] Wasser/Schattierung/Überhänge/Cliffs/Übergänge zur Spielreferenz prüfen.

## P0 – Originalobjekte

- [x] 1013-Gebäude und 1014-Vegetation an echten nativen Koordinaten gelesen.
- [x] Lokale Spritezuordnungen sind testbar, können aber noch nicht als
  Original-Engine-Mappings gelten.
- [ ] Objektarten, Richtung, Zustand, Animationsframe und Footprint aus echten
  Quelldaten ableiten und drei unterschiedlich belegte Karten abgleichen.
- [ ] Originale Einheiten sowie Mauern, Straßen und zerstörte Zustände erfassen.

## P0 – Exaktes HUD

- [x] Original-XAML-bezogene 141 Schaltflächen / 134 Befehle und 14 Kategorien
  mit autorisierten lokalen 265 Grafikausschnitten klickbar gemacht.
- [ ] Pixelgenaue Originalanordnung, Auswahlzustände, aktives Bauen,
  Rückmeldungen, Kosten, Tooltips, Cursorzustände und Einheitenbefehle
  nach tatsächlichen XAML-/Spielzuständen implementieren.
- [ ] Keine inaktiven Dekorationsknöpfe als funktional ausgeben.

## P0 – Objektive Endabnahme

- [x] Pixel-Differenzdialog ohne implizites Resizing vorhanden.
- [ ] Feste Screenshot-Referenzreihe für mind. drei Karten und mehrere
  Zoomstufen/Kamerapositionen erstellen und versioniert mit erlaubter
  Provenienz beschreiben.
- [ ] Vergleich gegen echte Spielbilder; Abweichungsfläche, Fehleranalyse,
  Restarbeiten und Performance-Budget dokumentieren.
- [ ] Qt-Maus-/Tastaturtests, Save/Reload, unbeschädigte Original-Assets,
  Memory-/Chunk-Caching und Start-Smoketest in einem QA-Report validieren.

## Implementierungsprinzip

Eine Entwicklungsphase ist erst als erledigt zu kennzeichnen, nachdem Tests
erfolgreich durchgelaufen und eine sichtbare Version überprüft wurde.
Beobachtete Rohdatenfakten, plausible Ableitungen und bestätigte
Spiel-Engine-Zuordnungen werden stets getrennt beschrieben. Kein Nachbauen
von Optik durch zufällige Wasser-/Grasfarben als behauptete Parität.


## Fortschritt 2026-10-11: Radarprojektion / Wasser-Gegenprobe

- [x] Die logischen u-/v-Koordinatengrenzen ergeben sich aus den
  nicht als Rand gekennzeichneten Originaldaten. Die 800er .map-Hülle
  war für die 200×200-Radarskalierung falsch.
- [x] Originalradar-Navigation in drei Karten anhand der aus den echten
  Kartenkanälen abgeleiteten Ausrichtung ausgerichtet: Radar-X
  entspricht gespiegeltem v, Radar-Y entspricht u.
- [x] Bildbasierte Kalibration bestätigt auf Antioch, Crusader Demo
  und A Mighty Oasis 81 / 78 / 85 % Wasser-Referenztreffer für das
  Daten-Indikatorbit `3003 & 0x100000`.
- [x] Qt-Kamera-, Navigation-, Maskierungs- und Wasserhint-Tests;
  Clip der Kameramarkierung auf den Radarausschnitt.
- [ ] Wassertextur inklusive optischer Transparenz, Shader,
  Animation und Flachwasser-/Küstenübergängen in der Spielengine
  verifizieren. Der Flag-Hinweis ist **nicht** der fertige Renderer.

Vollständiges Messergebnis: `docs/SANDBOX_RADAR_KALIBRIERUNG.md`.


## Fortschritt 2026-10-11: Semantik 3005/3037 korrigiert

- [x] Durch reale Daten aus drei installierten SHCDE-Karten abgesichert:
  Originaldatenbyte `3005` variieren als Höhe, `3037` sind getrennte
  Boden-/Texturklassen mit den vorkommenden Werten 0/1/2/8/16/64/128.
  Analog zu den dokumentierten älteren Stronghold-Abschnitten 1005/1037
  (Nummernverschiebung um +2000 für diese DE-Karten empirisch validiert).
- [x] Native Detailvorschau und herausgezoomte Diagnoseansicht verwenden
  Texturcode 3037 statt Höhenbyte 3005 für die vorläufige Bodenklassifizierung;
  der original-radargestützte Wasserindikator aus 3003 bleibt unabhängig.
- [x] Benutzerdefinierte 3037-Sprite-Testmappings, Inspector, Undo der
  Zuordnung per Reset, kartengebundene Speicherung mit SHA-256 und
  Recovery bei defektem JSON integriert. Bestehende manuelle Tests für
  3005 bleiben ohne Datenverlust erhalten.
- [x] Regression prüft Quellwerte dreier Originalkarten, unabhängige Höhen
  und Bodentypen, das Qt-Inspector-Workflow, Image-Array-Erstellung und
  Source-Map-Integrität.
- [ ] **Noch nicht fertig:** Zuverlässige, vom Spiel belegte Zuordnung
  *aller* 3037-Typen zu tatsächlichen Unity-Atlasframen und
  Renderingzuständen, exakte Gelände-Stufengeometrie, Wasser-/Küsten-Shader,
  Klippen- und Felsseiten und Nachbarschafts-Übergänge.

Detailprotokoll: `docs/SANDBOX_TERRAIN_HOEHE_BODEN_3037.md`.


## Umsetzung: Original-Engine-Snapshot als verbindliche Grafikquelle

- [x] Installierten nativen Spielkern im isolierten Worker mit hash-validiertem
  ABI laden; ausschließlich eine temporäre MAP-Kopie öffnen, keine Save- oder
  Spielaktionsfunktionen aufrufen; vor/nach Ausführung Originalhash prüfen.
- [x] Tatsächliche 21-Short-Grafikbefehle aus erstem pausiertem Editorframe
  inklusive Terrain-GM/Frame, Höhen und Originalobjekten abholen.
- [x] Native GM-IDs gemäß tatsächlich geladenem Sprite-Loader auf lokale
  Spritefamilien abbilden. Körper-/Baum- und Terrain-Indexkonventionen
  auseinanderhalten; Meer-/Uferbereich und Lichtumrechnung testen.
- [x] Original-/Arbeitsgrafik-Umschalter; fehlende Originalsprites direkt aus
  lokalem resources.assets read-only zugänglich; vorhandene Arbeitskopien
  niemals überschreiben.
- [x] Terrain-Chunks, native Höhen, Gebäudeteile, Originalvegetation und
  Einheitenzustand aus Engineentscheidungen rendern, nicht aus Materialraten.
- [x] Original-Kachel-Inspector zeigt konkreten GM/Frame und öffnet genau
  diesen Sprite im Pixeleditor. Pixel- und externes Datei-Live-Reload
  invalidieren native Renderbilder, ohne Original-MAP zu verändern.
- [x] Drei echte Kartenaufnahmen, Cache-/ABI-Sicherheit, Quellintegrität,
  Frame-Sonderfälle, Qt-Moduswahl und Pixel-Workflow automatisiert testen.
- [ ] Abschließende pixelidentische Unity-Material-/Masken-/Wind-/Wasser-
  Shaderparität, alle Partikel- und dynamischen Überlagerungsfälle.
- [ ] Vollständige Gameplay-HUD-Zustände und laufende Spielsimulation.
- [ ] Weitere Spielversionen über separat geprüfte ABI-Verträge sowie
  bislang nicht unterstützte MAP-Varianten im GUI-Ladepfad ergänzen.

Details: `docs/SANDBOX_NATIVE_ENGINE_INTEGRATION.md`.

## Fortschritt 2026-10-11: echte Objektpixel + Unity-Tilefarben

- [x] Nicht nur Bodenkacheln: der nativer Engine-Grafiktreffer
  berücksichtigt nun Alpha, Überhänge, Höhen-/Klippenteile und
  vordere Bäume, Einheiten und Objektanimationen.
- [x] Inspector, Vergleich und Strg+E-Pixelbearbeitung folgen dem
  tatsächlich angeklickten Originalframe aus dem pausierten Snapshot.
- [x] SHA-256-gepinnte `gameTile`-/`TilemapManager`-Regeln für
  Lichtsymbole 1–7, 11–17, 50–55 sowie Float-RGB-Farben 55–63
  werden getrennt von Actor-/Foliage-Materialien getestet.
- [ ] Exakte Unity-Schattierungs-/Shaderparität, Alpha-Blending in
  Wasser-/Foliage-Spezialmaterialien, Animationszwischenframes,
  vollständige dynamische Layer- und Gameplay-HUD-Zustände.

Technik und lokale Sichttests:
`docs/SANDBOX_NATIVE_ENGINE_INTEGRATION.md`.
