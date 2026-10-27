# Isolierte Pivot-/BC7-V2-Unity-Projektprobe

**Stand: 11. Oktober 2026 – synthetischer Test, keine Auslieferungsfreigabe.**

## Ziel und Bedienung

Die BC7-Ausgabe verwendet echte Unity-Sprite-Metadaten und eingefrorene
Geometrienachweise, nicht einfach den Katalogindex. Die neue
**synthetische Projektprobe** testet die Pivot-/Cache-Schlüsselwirkung
im tatsächlichen V2-Vorbereiter, ohne Produktionsbilder oder vorhandene
BC7-Dateien zu verändern.

Unter **Suite starten.cmd → Diagnose & Reparatur** die Funktion
**Synthetische BC7-Pivot-Probe vorbereiten** wählen. Die Probe verwendet
zwei selbst erzeugte RGBA-Testgrafiken, nicht die lokalen Spielgrafiken.
Eine frühere Messfreigabe ist dafür nicht erforderlich.

Alternativ im Projektverzeichnis:

~~~powershell
.\.venv\Scripts\python.exe tools\qa_pivot_bc7_rehearsal.py
.\.venv\Scripts\python.exe tools\qa_pivot_bc7_rehearsal.py --old-y 1.10909091 --new-y 1.0
~~~

Die Ausgabe liegt ausschließlich unter
work/pivot-bc7-rehearsals/<lauf-id>/.
Dort werden zwei getrennte Unity-Projekte und ein SHA-256-gebundener
Bericht vorbereitet. Ein unveränderter, identischer Lauf wird nach
vollständiger Verifikation aller gespeicherten Dateien und Ordner
wiederverwendet. Manipulierte Ergebnisse werden nicht überschrieben.

## Welche Bestandteile der echten Pipeline werden ausgeführt?

1. Zwei kleine synthetische PNG-Spritegruppen erzeugen:
   anim_castle als Pivotänderung und anim_drawbridge als unveränderte
   Kontrollgruppe.
2. Mit fingerprint_atlas_groups_v2 und preflight_atlas_groups_v2
   Quelle, Framegeometrie und V2-Atlaspacking vollständig prüfen.
3. Mit prepare_unity_asset_bundle_project_v2 den realen
   C#-Editor-Baustein, Unity-Projekt-Dateien, Atlas.v3,
   Index-Template, PNG-Seiten und Build-Eingabe für **beide**
   Pivotstände erzeugen.
4. Mit validate_prepared_project_v2 beide Projekte gegen den
   vorhandenen V2-Vertrag prüfen.
5. Mit build_group_cache_descriptors die synthetischen
   V2-Frame-Metadatenhashes und Gruppencache-Eingangsschlüssel
   aus denselben Eingängen berechnen und miteinander vergleichen.
6. Pixel-/Masken-, Geometrie-, Kontrollgruppen- und
   Cache-Unveränderlichkeits-Gates vor dem Export bestätigen.

## Nachgewiesenes Beispiel

| Eigenschaft | Ausgang | Vorgeschlagen |
| --- | --- | --- |
| Synthetischer Pivot anim_castle | (0, 1.1090909242630005) | (0, 1.0) |
| V2-Build-ID | ea52106c3583... | 66aa48483ba4... |
| Gruppencache-Key anim_castle | 018dff96dfa2... | 94a9add3d760... |
| Kontrollgruppe anim_drawbridge | Schlüssel stabil | Schlüssel stabil |
| Eingangs- und Atlas-Seitenpixel | identisch | identisch |
| Framegröße / PPU | identisch | identisch |
| Build-Projekt-Validator | bestanden | bestanden |

Der Cache-Deskriptor verwendet bewusst einen **künstlichen,
aus 64 Nullziffern bestehenden Unity-Executable-Hash**. Diese
hypothetischen Cache-Keys sind keine echten Release-Keys und dürfen
nicht in Produktionsmanifeste kopiert werden.

## Warum noch kein echter BC7-Bundle-Neubau?

Die produktive Pipeline verlangt Unity **2021.3.45f2** (Revision
88f88f591b2e) und einen festgeschriebenen Executable-SHA-256-Wert
aus config/unity-assetbundle-toolchain.json. Am lokalen vorgesehenen
Pfad ist diese genaue Version derzeit nicht vorhanden. Die installierte
Unity-6000er-Version ersetzt diesen gepinnten Vertrag nicht.

Die Projektprobe liest und prüft die exakten Unity-Vorgaben und meldet
den fehlenden Editor ausdrücklich. Sie **startet Unity nicht**,
enthält keine neue komprimierte BC7-Bundle-Datei und verwendet
die nicht freigabefähige V2-Qualitätsstufe
measurement_nonpromotable.

Der nächste tatsächliche Produktionsschritt setzt voraus, dass der
geprüfte native SH1DE-/SHCDE-Quellmappingpfad Metadatenkorrekturen
übernehmen kann, alle eingefrorenen Geometrie-/Review- und Cachebeweise
neu berechnet sind und die **gepinnten** Unity-, BC7-Roundtrip-,
Qualitäts-, Release- und Ingame-Prüfungen bestanden haben.

## Grenzen und Sicherheitsregeln

- Keine Sprite-/Atlas-, Katalogindex-, Profil-, Cache-, Dist-
  oder Spieländerungen. Nur neue Dateien unter work.
- Atomische Veröffentlichung erst nach vollständiger
  V2-Projekt- und Quellenprüfung.
- Alte Ausgaben sind inhaltsgebunden; zusätzliche Dateien,
  geänderte Bytes, fremde/leere Verzeichnisse oder Links/Junctions
  werden verweigert.
- Ungültige Pivotzahlen, veränderte Builder-Quellen und
  unpassende Unity-Identitäten blockieren.
- Vollständiger CLI-/V2-Packing-/Cache-Digest-Test:
  tests/sandbox/test_pivot_bc7_rehearsal.py
- Test der asynchronen Hauptfenster-Bedienung:
  tests/sandbox/test_pivot_bc7_rehearsal_gui.py
- Echter Windows-Tk-/Qt-Smoke-Test:
  tools/qa_suite_embedded.py; Kennzeichen SYNTHETIC_BC7_V2_PREPARED.

**Ergebnis:** Validierte V2-Unity-Eingabeprojekte, kein gestarteter
Encoder und keine Produktions- oder Installationsfreigabe.
