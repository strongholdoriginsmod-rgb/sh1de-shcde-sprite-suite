# SHCDE-Radarkalibrierung und Kanal-3003-Wasserindikator

**Datum:** 2026-10-11. **Status:** Auf drei installierten Originalkarten
numerisch nachgeprüfte Koordinatenprojektion; **keine** pixelgenaue
Rekonstruktion des Terrain-Shaders.

## Beobachtung

Die Karten speichern 320.800 native Werte in einem 800-Zeilen-Diamantraster.
Die Spielfläche ist deutlich kleiner als die technische Datenhülle.
`3003 in {16,32}` bezeichnet bei den drei getesteten Karten unbesetzte
Außenflächen. Die übrigen Originalkacheln ergeben folgende logische Achsen:

| Karte | logischer u-Bereich | logischer v-Bereich | Radar-Pixelbereich |
| --- | --- | --- | --- |
| Antioch | 125–275 | 124,5–274,5 | ca. 148×149 |
| Crusader Demo | 125–275 | 124,5–274,5 | ca. 149×149 |
| A Mighty Oasis | 100–300 | 99,5–299,5 | ca. 198×199 |

Für eine native Kachel `(x,y)` gilt `u=(x+y-399)/2` und
`v=(y-x+399)/2`. Die bisherige Anzeige benutzte `u→Radar-X`,
`v→Radar-Y` und die gesamte scheinbare Ausdehnung 400. Das war
sowohl in der Orientierung als auch der Skalierung falsch.

Bei den drei genannten Karten ergibt sich stattdessen:

- **Radar-X:** `v` in umgekehrter Richtung, auf den tatsächlichen
  Nicht-Rand-Bereich normiert.
- **Radar-Y:** `u` in normaler Richtung, ebenfalls auf den
  tatsächlichen Nicht-Rand-Bereich normiert.
- Die Kartengrafik wird in ihrem tatsächlichen, nichtschwarzen Bereich
  aus der Original-`.map` gerendert. Ihre letzte Pixelposition wird
  `breite - 1` bzw. `höhe - 1` zugeordnet.
- Die Rücktransformation führt wieder exakt zur ursprünglichen
  nativen Kachelposition zurück.

## Quantitative Gegenprobe: vermutete Wasserflächen

Mit den exakt aus der Original-`.map` geladenen Flags wurde die
native Menge `flags & 0x100000 != 0` unter acht Achsen-/Spiegelungs-
Varianten in das authentische 200×200-Radarbild projiziert.

Als **prüfbarer Bildindikator**, nicht als Spiel-Engine-Klassifizierung,
gilt ein Pixel mit `Blau > 1,03×Rot` und `Blau > 0,96×Grün`.
Bei richtig orientierter/skalierter Projektion sind folgende Anteile
dieser Menge blau:

| Karte | Trefferrate der Wasser-Indikatorkacheln |
| --- | ---: |
| Antioch | ca. 81 % |
| Crusader Demo | ca. 78 % |
| A Mighty Oasis | ca. 85 % |

Die Fehlklassifikation der untersuchten repräsentativen
`3003 == 0x8000`-Landkacheln liegt dagegen unter 16 %. Die
anderen Ausrichtungsvarianten sind auf denselben Karten deutlich
schlechter. Dieser Befund wird in
`tests/sandbox/test_radar_calibration.py` automatisiert kontrolliert.

Die positive Korrelation begründet, im **vorläufigen** visuellen Renderer
bei gesetztem `0x100000`-Bit Wasser-Spritefamilien zu versuchen, anstatt
ausschließlich den Bytewert 3005 als Material zu raten. Sie **beweist
nicht**, dass `0x100000` die Engine-Bezeichnung „Wasser“ hat oder welcher
konkrete Wasser-Frame und Shaderzustand korrekt ist.

**Manuelle Terrain-Spritezuordnungen haben weiterhin Vorrang.**
Die getrennten `sandbox/terrain-mappings/`-Dateien sowie alle
Original-`.map`-Bytes bleiben bei der Kalibrierung unverändert.

## Oberfläche / Regression

- Native Minikarte navigiert anhand echter spielbarer Extrema.
- Gelbe Kameramarkierung wird auf den tatsächlich sichtbaren
  Radarbildbereich begrenzt, auch bei „Gesamte Karte anzeigen“.
- Bei Karten ohne auswertbare 3003-Randdaten wird die bisherige
  generische Geometrie verwendet und nicht eine erfundene
  originalgetreue Kalibrierung behauptet.
- Regression testet alle drei Originalkarten, numerische Achsengrenzen,
  Hin-/Rückprojektion, quantitativen Bildabgleich, Qt-Navigation,
  Kameramarkierungsbegrenzung und Vorrang manueller Sprite-Tests.

## Weiterhin offen

Exakte Material-/Höhen-/Wasser-/Klippen-Semantik aller 3003/3005-Bits,
Sprite-Frame-Identitäten, spezielle Noesis/Unity-Schattierung,
spielgetreue Wassereffekte sowie Rendering-Reihenfolge gegen Screenshots
der laufenden Spielengine. Die Radarkalibrierung ist eine empirisch
geprüfte Unterkomponente, keine 1:1-Gesamtparität.
