# Nativer BC7-Geometrienachweis aus dem echten Produktionsmapping

**Stand: 11. Oktober 2026.** Nur-Lesen-Prüfung der tatsächlich
veröffentlichten Stronghold-Europe-Sprite-/BC7-Daten. Keine
Modinstallation, kein neuer Unity-Build, keine automatische Pivot-Übernahme.

## Warum dieser Schritt wichtig ist

Der native anim_castle-Pfad umfasst mehr als einen Pixel-/Pivotwert.
Eine beliebige Änderung im gelieferten Katalogindex würde die
ursprüngliche Baugeometrie nicht ändern und könnte den im Produktionsprofil
eingefrorenen Quell- und Zielnachweisen widersprechen.

Die neue Prüfung verbindet deshalb fünf konkrete Quellen:

1. Das originale, generierte SH1DE-/SHCDE-Mapping:
   work/mapping/proposals.json.gz, inklusive Quell-/Ziel-Build-IDs.
2. Das unveränderte Produktionsprofil
   sprite-suite-world-bc7-v2 mit dem Geometriemodus
   native_source_reanchored_v1 und dem
   source_native_geometry_else_keep_v3-Reviewvertrag.
3. Das vollständige Auslieferungsmanifest mit SHA-256 für
   sämtliche vorhandenen BC7-Dateien.
4. Genau das vollständig verifizierte unveränderliche
   Gruppencache-Atlasobjekt, dessen Bundle-SHA und Atlas-SHA
   zum veröffentlichten Index passen – keine beliebige
   ältere Version dieser Gruppe.
5. Die offiziellen native_reanchored_pivot,
   native_source_geometry_proof und
   validate_review_frame_partition-Funktionen der Produktionspipeline.

Für alle Frames werden Mappingaktion, Geometrie, PPU,
Frame-Reihenfolge und float32-Ausgabepivot neu geprüft.
Anschließend werden die nativen Geometrie-, Herkunfts-,
Quell-RGBA- und Review-Partitionsnachweise vollständig
rekonstruiert und exakt gegen das Produktionsprofil verglichen.

## Echt gemessener Ausgangsstand

Für die Gruppe anim_castle des aktuellen Produktionsprofils:

| Prüfpunkt | Ergebnis |
| --- | --- |
| Veröffentlichten BC7-Atlasframes | 106 |
| Native SH1DE-Quellframes | 95 |
| Unveränderte Crusader-Fallbackframes | 11 |
| Erwartete versus tatsächliche native Ausgabe-Pivots | 95 / 95 identisch |
| Max. Runtime-Anker-Restfehler | 0,0000036955 px |

Die erneut berechneten SHA-256-Werte stimmen genau mit den
im Produktionsprofil eingefrorenen Werten überein:

| Nachweis | SHA-256 |
| --- | --- |
| Geometrie | f0be1cb1beb096ff4d518bd48dfa4ee23ec86382a1e7ea14edd1b07a8dd88152 |
| SH1DE-Quellherkunft | 7fc71756f809738686a270b71d3a107e7eae97dfd913c729bd3ad5be72468298 |
| Quell-RGBA-Proof | 4a08b4309e74089447d082b75411fe31956a9a2107bfc809cda4ebb7d590cf20 |
| Review-Partition | dfede86203e0ac0aed794bdc9ab73a70da0663b7034ad4151f5e88d293c5e39c |

Das überprüfte Originalmapping trägt den GZIP-Dateihash
60c4b823d183876f304d8ebd9d3ec3d7563dece89326853fc81d283ca79c6dab.

Der konkret untersuchte Frame anim_castle 002 hat eine
SH1DE-Quellgröße von 333×165 und eine Crusader-Zielgröße von
377×183 Pixeln. Der native Eckanker errechnet daraus schon den
Unity-Zielpivot (0,1); der veröffentlichte BC7-Atlas
enthält denselben Pivot. Eine weitere Korrektur wäre fehlerhaft.

**Einordnung:** Die Quell-RGBA-Nachweise stammen aus den originalen,
SHA-256-gebundenen, vor der BC7-Kompression aufgezeichneten
Frame-Digests des veröffentlichten Cacheatlas. Die unveränderten
originalen Spiel-resources.assets wurden **nicht** unabhängig
neu dekodiert. Das ist ein echter Nachweis für den existierenden
Build, aber keine Neuabnahme aller Originalspielpixel.

## Bedienung

**Im Hauptfenster:** Suite starten.cmd →
Diagnose & Reparatur → BC7-Releaseprofil
sprite-suite-world-bc7-v2 wählen →
**Nativen Zinnen-Geometriebeweis prüfen**.
Die Prüfung läuft in einem Hintergrundthread und zeigt
Frames, Geometrie-Proofs und die Herkunft im Befundfenster.

**CLI ohne Schreibzugriff:**

~~~powershell
.\.venv\Scripts\python.exe tools\qa_native_pivot_provenance.py
~~~

**Optionaler separater Prüfbericht:**

~~~powershell
.\.venv\Scripts\python.exe tools\qa_native_pivot_provenance.py --profile sprite-suite-world-bc7-v2 --group anim_castle --save-report
~~~

Nur mit --save-report bzw. der GUI-Funktion wird ein
inhaltsadressierter Bericht unter
work/reports/pivot-native-provenance/ gespeichert.
Er kann unverändert wiederverwendet werden; vor jedem Export
werden Quellen und Build erneut geprüft.
Es werden keine Spiel- oder Produktionsdateien geändert.

## Sicherheitsgrenzen

- Ausschließlich der separat nachgewiesene anim_castle-
  Native-Review/Keep-Vertrag ist aktuell freigeschaltet.
- Die komprimierte Mappingdatei wird mit Größenobergrenzen,
  strikter UTF-8-/JSON-Dekodierung und Ablehnung doppelter
  Felder oder nicht-finiten Zahlen gelesen.
- Falsche Gruppennamen, Loader-Reihenfolgen, Quellpivots,
  Zielgrößen, Ausgabepivots, RGBA-Digests und
  Frameaktionen lösen eine Sperre aus.
- Profil, Mapping-GZIP, Manifest, BC7-Index,
  veröffentlichtes Bundle und zugehöriger Cacheatlas
  werden SHA-256-gebunden und bei Abschluss nochmals geprüft.
- Kein automatisches Umschreiben eingefrorener Proofs;
  keine Cache-Veröffentlichung, keine Unity-Kompilierung,
  kein neuer BC7-AssetBundle-Bau, keine Installation.
- Die echte Neuberechnung nach einer zukünftigen Korrektur
  verlangt außerdem erneutes Originalsprite-Decoding
  und die gesonderte BC7-/Ingame-Abnahme.

## Tests

- tests/sandbox/test_pivot_native_provenance.py:
  echte Produktionsquellen plus manipulierte Mappingdaten,
  Pivots, Frame-Reihenfolgen, Geometrien, Quell-RGBA,
  Action-Drift, ungültige GZIP/JSON-Werte und
  verweigerte veraltete Berichte.
- tests/sandbox/test_pivot_native_provenance_gui.py:
  asynchrone Bedienung und Sperre für Installations-
  oder Katalogaktionen.
- tools/qa_suite_embedded.py:
  tatsächliche Windows-Tk-/Qt-Suite-Abnahme.

**Ergebnis:** Der bereits vorhandene native anim_castle-
Geometrievertrag ist aus der echten Mapping-/BC7-
Herkunft vollständig rekonstruierbar. Ein neuer
Produktionsbuild bleibt separat freigabepflichtig.

## Neu: Einzelbilder im nativen Nachweis kontrollieren

Im Reiter **Diagnose & Reparatur** die Prüfung
**Nativen Zinnen-Geometriebeweis prüfen** starten. Nach erfolgreichem
SHA-/Cache-/Herkunftsabgleich zeigt die Tabelle nicht mehr nur vier
Gruppenzusammenfassungen, sondern **zusätzlich alle 106 konkret
geprüften anim_castle-Frames**:

- `Nativ-Frame` enthält Atlasname, Bildgröße, tatsächlichen
  Produktionspivot und Herkunft (95× SH1DE-Quelle, 11× beibehaltener
  Crusader-Fallback).
- **Doppelklick** auf `Nativ-Frame` öffnet **genau diesen Frame**
  im integrierten Asset-Katalog. Ein Doppelklick auf die
  Zusammenfassung oder andere technische Prüfnamen bleibt wirkungslos.
- Angezeigt werden ausschließlich die Frames des bereits vollständig
  SHA-geprüften nativen Beweises, nicht frei geratenen
  Frame-IDs. Externe/ungültige Diagnosenamen werden nicht als
  Katalogaktion interpretiert.
- `tests/sandbox/test_pivot_native_proof_rows.py` prüft unter
  anderem die Vollständigkeit aller 106 echten Cacheframes,
  die 95/11-Aufteilung, doppelte Namen, ungültige Pivots,
  nichtkanonische Framereferenzen und widersprüchliche Herkunft.
  `test_pivot_native_provenance_gui.py` testet die tatsächliche
  Tk-Auswahl und den sicheren Doppelklick.

**Abgrenzung:** Die Liste ist ein lesbarer Nachweis des bereits
vorhandenen BC7-Atlas. Ein nachträglicher Pivotvorschlag benötigt
weiterhin eigenständige Freigabe, einen neuen BC7-Build und
einen gesonderten Spieltest. Der Katalog-Doppelklick
wendet **keine** Grafik- oder Metadatenänderung an.
