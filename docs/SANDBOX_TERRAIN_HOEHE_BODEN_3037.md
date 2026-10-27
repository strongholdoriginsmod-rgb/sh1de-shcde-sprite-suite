# Originales Terrain: Höhenkanal 3005 und Texturkanal 3037

**Datum:** 2026-10-11. **Status:** Echte SHCDE-Daten ausgewertet,
Sandbox-Renderer angepasst. Die vollständige Engine-Sprite-/Shaderparität
ist weiterhin **nicht** erreicht.

## Beleglage

Die Reverse-Engineering-Dokumentation des klassischen Stronghold Crusader
ordnet Abschnitt **1005** den Höhenwerten einschließlich Stufen und
Abschnitt **1037** den Bodenfarben/-Texturen zu:
https://github.com/sourcehold/sourcehold-wiki/blob/master/Map-sections-overview.md

Die bisherige Sprite Suite las dieselben 320.800-Byte-Strukturen aus den
SHCDE-Originalabschnitten **3005** und **3037**, verwendete aber fälschlich
**3005 für die gesamte Materialauswahl**. Die Section-ID-Verschiebung um
2000 ist eine plausible, aber vom Spielhersteller hier nicht bestätigte
Formatfortsetzung. Sie wird durch die Analyse der drei wirklich installierten
Originalkarten gestützt:

| 3037-Rohwert | Beobachtung in Radar/3005 | Vorläufige Renderfamilie |
| ---: | --- | --- |
| 0 | Hauptsächlich hellbraune Bodentöne; auch Wasserlagen | Erde/Sand, Wasser nur mit 3003-Indikator |
| 1 | Mehr grünlich-olive Regionen | Grün-/Erdvariante |
| 2 | Helle trockene Sand-/Erdgebiete | Erde/Sand |
| 8 | In Antioch und Crusader Demo durchgehend 3005=130; helle Hügel-/Felsregionen | Fels |
| 16 | Deutlich grünere Radargebiete | Grün |
| 64 | Wenige, hoch gelegene Gebiete; Antioch durchschnittlich 3005≈120 | Fels/Klippe |
| 128 | Mehr grünlich-olive Regionen | Grün-/Erdvariante |

Diese Labels sind **Messbeobachtungen**, keine bewiesenen historischen
Materialnamen. Bei A Mighty Oasis sind nur 0/1/2/16/128 vorhanden.
Der 3005-Bytewert **8** wird in den meisten begehbaren Bereichen aller
drei Karten benutzt. Auf Antioch variieren die Höhenwerte dagegen zwischen
0 und 130; auf A Mighty Oasis im sichtbaren Gelände fast nur 0 und 8.
Derselbe 3037-Oberflächenwert kommt auf einzelnen Karten bei verschiedenen
3005-Höhen vor. Damit ist eine texturgenaue Zuordnung **nur aus 3005**
widerlegt.

## Implementierung

- Das detaillierte Terrain rendert bekannte 3037-Rohwerte mit
  **vorläufigen** lokalen Spritefamilien. Die echten Grafikframes können
  weiterhin nicht aus 3037 selbst abgeleitet werden.
- Der in drei echten Radarbildern verifizierte Indikator
  `3003 & 0x100000` bevorzugt Wasser-Grafikversuche.
- Die Gesamtansicht benutzt 3037 für die diagnostische Bodenfarbe,
  3005 als separaten zurückhaltenden Höhen-/Helligkeitshinweis und
  die echte 3003-Randmaske. Es handelt sich ausdrücklich **nicht**
  um die originalen Unity-Materialien.
- Original-3005-Mappingdateien aus älteren Sandbox-Studio-Versionen
  bleiben **unverändert** und behalten ihren bisherigen Vorrang.
- **Neu:** Originalkachel anklicken, im Inspector
  **Bodenart 3037** und **Höhe 3005** separat anzeigen.
  **Palette-Sprite für Bodenart 3037 testen** weist allen
  Kacheln derselben Textureinheit die gewählte Spritegruppe und Frame-ID zu.
  Rücksetzen steht direkt darunter bereit.
- Die Boden-Testdateien werden pro Originalkarte und vollständigem
  SHA-256 unter `sandbox/surface-mappings/<karte>-<sha>.surface-3037.json`
  atomisch gespeichert. Defekte Dateien bleiben unberührt und neue
  Bearbeitungen verwenden getrennte Recovery-Dateien.
- Das bestehende Datei-/Pixel-Live-Reload berücksichtigt die neuen
  Oberflächenzuordnungen. Original-`.map`- und installierte Atlas-Dateien
  werden nicht verändert.

## Abnahmetests

`tests/sandbox/test_native_surface_mapping.py` deckt Formatvalidierung,
Kartenprüfsummen, tatsächliche Quellwerte aller drei Karten,
getrennte Testframewahl, Priorität historischer 3005-Testzuordnungen,
Inspector-Bedienung, Rücksetzen, Wiederladen und beschädigte Datei ab.

`tests/sandbox/test_native_layers.py` prüft zusätzlich mit nativen
vollgroßen synthetischen Kachelarrays: gleicher Höhenwert,
unterschiedliche Bodenfarbe; gleiche Bodenart, unterschiedliche
Höhenhelligkeit; separater Wasserindikator; korrekte Randmaske.

## Für endgültige 1:1-Parität weiterhin offen

Alle 3037-Codes anhand der **tatsächlich in Unity geladenen SHCDE-Atlanten**
eindeutig einem Spriteframe samt Pivot und Übergangsregeln zuordnen.
Höhengeometrie, Stufen, Felsseiten, Wasser-/Küstenübergänge, Shader,
Animation, Z-Layer und automatische Tile-Nachbarschaftsvarianten
gegen reale Spielreferenzbilder verifizieren. Ein passender Radarfarbton
oder der korrekte Datentyp allein beweist **keine** Spielrenderparität.
