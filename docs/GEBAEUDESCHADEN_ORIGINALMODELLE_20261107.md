# Gebäudeschäden – echte SHCDE-Originalpixel, visuelle Ausrichtung und Stufenplanung

Stand: 7. November 2026. Sicherer Entwicklungszweig `feature/shcde-damage-visual-orientation-20261107` aus `d09397d`. Die dokumentierten Originale stammen aus der vorhandenen, versionsgebundenen QA-Spielkopie. Die Extraktion liest die Spieldateien.

## Verifiziertes Original und tatsächlicher Gebäudetyp

Der Kornkammer-Test verwendet das real im SHCDE-Spiel beobachtete Gebäude **172**, globale ID **7333542**, mit tatsächlich gezeichneten **16 Grafik-Tiles** (4×4). Den Native-Typ `19` liefert `GameBuildingManagerAPI.GetType`; das mit Mono.Cecil aus der tatsächlich installierten und SHA-geprüften `SHCDESE.dll` exportierte Enum `SHCDESE.Interop.eStructs` bestätigt **`19 = STRUCT_GRANARY`**.

Wichtige Korrektur älterer synthetischer Testzuordnungen: `104 = STRUCT_POND` (Teich), `55 = STRUCT_CAMPGROUND` (Lagerplatz), `108 = STRUCT_BEDOUIN_STOCKADE` (Beduinen-Palisade), **nicht** Abtei. Der Beispiel-Test mit Typ `108` war niemals eine verifizierte echte Abtei-ID. Die vollständige Enum-Abfrage mit **237 benannten Werten** liegt unter `docs/SHCDESE_GEBAEUDETYPEN_AUDIT_20261107.json`. Deren SHCDESE-DLL-SHA-256 ist `5cb1c33be5463086505a17f5c48aaa357d733cfff7240e101c821f0e3c668498`; die JSON-Datei hat SHA-256 `2f1389406a8443c9d16cfedf0c07226b24e566c5b1cc0f1200f0ad15af9ca8c1`.

Der original beobachtete Grafiklayer stammt aus `CorrelatedTileLayer_20261106.log` (SHA-256 `f6d4bf905053b16cbcb4facbc22bec057277a6623ffe98ea79e9bbf94bfa6cee`). Die Bilddateien kommen aus `resources.assets` (SHA-256 `9567ebdce10ef16baf12cf49a9cbdfa064d6b159cdbf3b2d180ea6d04c79730a`) über die durch das SpriteSuite-Projekt zuvor ermittelte Zuordnung `proposals.json.gz` (SHA-256 `60c4b823d183876f304d8ebd9d3ec3d7563dece89326853fc81d283ca79c6dab`). Es wird `UnityPy==1.25.3` aus einem getrennten temporären QA-Modulverzeichnis verwendet; keine Projekt- oder Spieldatei wird dafür überschrieben.

## Tatsächlich erzeugte Arbeitsstände

1. `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\OriginalGranary_19_Provenance_20261107`: 16 **unveränderte** Original-Sprite-PNGs (je nach Tile unterschiedliche Höhe, Breite ≤64 px), tatsächliche Unity-PathIDs/Pivots/PPU, acht vollständige, getrennte Isometrie-Montagen, Kontaktbogen und SHA-geprüfte `original_sprite_reference.json` inklusive Enum-Typbezeichnung.
2. `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\Granary_19_Provenance_Editable_20261107`: originales, **bearbeitbares** `SHCDE_Original_19.shsprite`, vollständige OpenRaster-Datei `SHCDE_Original_19.ora`, sichtbare PNG-Vorschau und SHA-Provenienz `SHCDE_Original_19_Provenance.json`. Die visuell geschlossen wirkende Ausgangsvariante `xy-u-v` wurde aus acht Montagen ausgewählt; ihre tatsächliche **In-Game-Slot-Ausrichtung** muss noch durch die visuelle Spielkontrolle bestätigt werden. Die sichtbaren Pixel des importierten/rückexportierten Projekts stimmen **kanalweise exakt** mit der nativen Montage überein; keine Alpha-Werte wurden verändert.
3. `E:\SpriteSuite_FinalAudit_20261106\LiveGameQA\Granary_19_Sequential_DamageDrafts_20261107`: `Granary_19_DamageDrafts.shsprite`, acht voneinander getrennte Szenen für mechanische und Feuer-Schadensstufen sowie acht individualisierte, offline validierte Anfrage-ZIPs für die Schadensstufen. Mechanische HP-Schwellen: **80, 45, 15 und 0 %**. Brand-HP-Schwellen: **85, 50, 20 und 0 %**.

Die acht Szenen enthalten jeweils das intakte Original als Ausgangspunkt. Der Entwurfsbericht erfasst die Stufen und ihre Prüfsummen. Die aktuelle Fassung erzeugt für jede Stufe ein separat nutzbares ZIP mit Referenzbild und Prompt. Die Reihenfolge kann frei gewählt werden. Für eng aufeinander abgestimmte Varianten kann eine frühere Stufe im Editor als Bildreferenz verwendet werden.

## Prüfschritte der Originalextraktion

- SHA-256 identifiziert die Original-Asset-Datei, das Spielprotokoll, den Typenkatalog und das historische Sprite-Mapping.
- Die rund 97 MiB große entpackte Zuordnungsdatei wird mit einer 128-MiB-Entpackgrenze verarbeitet. Die Extraktion prüft Unity-PathIDs, Sprite-Namen, Maße und RGBA-Pixel.
- Die Ausgabe verwendet einen neuen Ordner. Das SHSPRITE-Projekt und die OpenRaster-Datei enthalten die originalen Sprite-Pixel und können direkt bearbeitet werden.
- Die Originalgruppe enthält Tile-Geometrie, Pivots und PPU. Beim Aufbau eines Spiel-Overrides können die Zielnamen im Editor zugeordnet werden.
- Das Kornkammer-Preset verwendet STRUCT_GRANARY und darauf zugeschnittene Prompttexte. Andere Gebäudetypen können im Editor mit eigenen Schadensstufen und Prompts bearbeitet werden.

## Reproduzierbarkeit

```powershell
# Aus dem Hauptprojektverzeichnis:
python -m unittest discover -s tests\runtime -p test_building_damage_original_reference.py -q
node --test tests\runtime\test_building_damage_native_project.cjs
```

Die Spielprüfung der ausgewählten Slot-Ausrichtung und die In-Game-Abnahme der HP-, Feuer-, Reparatur- und Kartenwechselübergänge stehen für dieses Gebäude aus.
