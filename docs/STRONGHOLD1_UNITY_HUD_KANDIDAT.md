# Stronghold 1 DE – Unity-HUD-Kandidat als geprüfte Kopie

## Zweck

Die Sprite Suite kann drei originalgetreu dimensionierte HUD-Atlanten bearbeiten.
Dieses Werkzeug ist der **nächste, isolierte Schritt**: Es nimmt die lokalen HUD-
Arbeitskopien und eine unveränderte globalgamemanagers.assets aus einer
rechtmäßig verfügbaren **Stronghold 1 Definitive Edition** und erzeugt eine
separate Kandidatendatei. Es **installiert nichts ins Spiel**.

Der Vorgang verändert ausschließlich nachweisbar betroffene Textur-Bytes.
Alle anderen Bytes des Unity-Containers werden vor und nach dem Schreiben
mit der Quelldatei verglichen. Dadurch bleiben die übrigen Unity-Objekte,
Container-Metadaten, Texturformate und unberührten Mipmap-Daten erhalten.

## Unterstützte Originaltexturen

| Textur | Originalformat | Größe | Strategie |
| --- | --- | --- | --- |
| UI-MasterAtlas | RGBA32 (Format 4) | 8192 × 4096 | Nur betroffene Byteabschnitte der RGBA-Zeilen ersetzen |
| UI-ROL | BC7 (Format 25) | 4096 × 4096 | Nur 16-Byte-Blöcke mit tatsächlich geänderten Pixeln neu kodieren |
| UI-CandleAtlas | BC7 (Format 25) | 2048 × 4096 | Nur betroffene 4×4-BC7-Blöcke neu kodieren |

Der Originalzustand muss pro Textur **genau eine Mipmap-Ebene** und
eingebettete, nicht extern gestreamte Bildbytes besitzen.
Alle anderen Containerlayouts oder unpassenden Versions-/Quelldigests
werden abgelehnt statt blind verändert.

## Bedienung

In der Sprite Suite unter **Oberfläche → Stronghold 1 DE – HUD-Editor**:

1. Das HUD aus der eigenen Installation exportieren und bearbeiten.
2. **SH1-HUD prüfen** ausführen.
3. Optional **SH1-HUD-Atlanten bauen**, um die drei PNG-Ausgaben zu erhalten.
4. **6. Geprüfte Unity-Kopie erzeugen** wählen.
5. Die ursprüngliche globalgamemanagers.assets auswählen und den
   Sicherheitshinweis bestätigen.
6. Die Ausgabe unter dist/sh1-hud-unity-kandidat und deren
   sh1_unity_hud_candidate.json kontrollieren.

Es ist **keine** Kopie in einen Spielordner, kein Eintrag in ein
Crusader-Produktionsprofil und kein automatisches Starten oder Patchen
des laufenden Spiels vorgesehen.

Alternativ per PowerShell aus der Sprite Suite:

~~~powershell
.venv\Scripts\python.exe tools\ui_sh1_unity_patch.py --source "D:\MeineSpiele\Stronghold 1 Definitive Edition_Data\globalgamemanagers.assets" --from work/sh1-hud-editierbar --out dist/sh1-hud-unity-kandidat
~~~

Eine bestehende isolierte Ausgabe wird ohne --replace nicht überschrieben. **Auch mit --replace werden überlappende Eingabe- und Ausgabepfade abgewiesen.** Der ausgegebene Unity-Container darf niemals aus einem Ordner stammen, den der Ausgabevorgang selbst ersetzt. Bei einem abgebrochenen atomaren Verzeichniswechsel bleibt die bisherige Version erhalten.
Das neue Quellprojekt-Format speichert Noesis-XAML **byteidentisch** mit
Unity; ältere editierbare Projekte bleiben ohne Konvertierung gültig,
solange ihre Dateien mit dem tatsächlichen Unity-Original übereinstimmen.
Für sehr große bewusst veränderte BC7-Bereiche begrenzt das Werkzeug
die Kodierung standardmäßig auf 8192 betroffene 4×4-Blöcke je Textur.
Mit --max-bc7-blocks kann diese Grenze nach eigener Prüfung bewusst
angepasst werden; Blind-Nachkompression des gesamten BC7-Atlas ist
nicht vorgesehen.

## Was wird kontrolliert?

- SHA-256 der gesamten Original-Unity-Datei muss zu dem
  zuvor aus demselben Spiel erzeugten HUD-Arbeitsprojekt passen.
- Zusätzlich werden die **drei originalen XAML-Wörterbücher** erneut direkt
  aus den MonoBehaviour-Ressourcen der eigenen Spielinstallation gelesen
  und auf byteidentischen Inhalt geprüft. Bei alten Windows-Exporten
  wird ausschließlich die bekannte CRLF-Doppelung akzeptiert.
- Die **drei ursprünglichen Atlas-PNGs** werden pixelgenau mit den
  aus genau dieser Unity-Datei decodierten Texturen verglichen. Ein
  lediglich neu berechnetes Projekt-JSON-Manifest reicht nicht aus.
- Alle 1.391 HUD-Ausschnitte, Bildgrößen, XAML-Positionen und die
  ursprünglichen PNG-Quellprüfsummen werden überprüft.
- Eingebettete Texturformate, Pfad-IDs, Bildgrößen, Mipmap- und
  Streaming-Metadaten werden auf einen unterstützten Aufbau geprüft.
- Patchbereiche dürfen sich nicht überschneiden, nicht über die
  Containergrenze ragen und müssen dieselbe Länge behalten.
- Jeder unveränderte Bytebereich des Containers muss mit der
  Quelldatei übereinstimmen.
- Die neue Datei wird mit UnityPy erneut geöffnet und die Bilder
  werden mit der beabsichtigten Grafik verglichen.
- Die tatsächliche BC7-Farbabweichung wird ins Manifest geschrieben.
  **BC7 ist verlustbehaftet**. Auch unveränderte Pixel *innerhalb*
  eines neu kodierten 4×4-Blocks können geringfügig abweichen.
- Eine zusätzliche Qualitätskontrolle lehnt BC7-Blöcke ab, wenn die
  sichtbare Abweichung nach Alphaverrechnung über dem Standardgrenzwert
  von **64 Farbkanalstufen** liegt. Unsichtbare RGB-Unterschiede bei
  vollständig transparenten Pixeln werden nicht fälschlich bestraft.
  Für einen bewusst abgenommenen Sonderfall lässt sich der Grenzwert
  per Kommandozeile mit --max-bc7-visual-error von 0 bis 255 anpassen.

## Isolierter Testnachweis

Auf einem separaten, lokalen Exemplar des Stronghold-1-Spielassets wurde
zunächst ein unverändertes HUD exportiert. Der Kandidat hatte danach
denselben SHA-256-Digest wie die Originaldatei.

Anschließend wurden in drei isolierten HUD-Arbeitskopien gezielt kleine
4×4-Grafikbereiche geändert. Bei der überprüften Kandidatenerstellung
wurden vier RGBA-Zeilenabschnitte und je ein BC7-Block in
UI-ROL und UI-CandleAtlas modifiziert. Die neue Unity-Datei ließ sich
mit UnityPy wieder öffnen; die geänderten Motive waren sichtbar.
Die BC7-Canary-Messung ergab maximal einen Farbkanalwert Abweichung
vom gewünschten Testpixel. Die Originalinstallation blieb unangetastet.

Dieser Test belegt den **Offline-Rückbau**, nicht die tatsächliche
Kompatibilität sämtlicher Spielszenen oder Spielversionen.
Insbesondere ist der **Live-Spielstart mit dem Kandidaten
nicht abgenommen**. Eine spätere Installation verlangt eine
gesonderte Sicherung, Freigabe und Rückwegprüfung.

## Urheberrecht

Die erzeugte globalgamemanagers.assets enthält weiterhin
urheberrechtlich geschützte Firefly-Spielressourcen. Sie bleibt
lokal und wird nicht in diesem öffentlichen Repository veröffentlicht.
Die veröffentlichten Quellcodes, Anleitungen und rein synthetischen
Tests enthalten keine originalen Stronghold-Grafikdaten.
