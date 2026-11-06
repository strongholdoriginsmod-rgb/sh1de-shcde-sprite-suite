# Gebäudeschäden im Stronghold Sprite Editor

Stand: 06.11.2026. Enthält eine editierbare **Asset- und HP-Schadensbibliothek**. Die dynamische Umschaltung des Spielrenderers bei HP-Verlust ist noch **nicht** integriert.

## Gebäude und Schadensstufen
1. Im Sprite Editor eine Gebäude-PNG-Serie öffnen oder ein vorhandenes `.shsprite` laden.
2. Rechts **Schaden** öffnen. Im Feld **Gebäude** die gewünschte Gebäude-/Tilegruppe auswählen.
3. **Neue Schadensstufe…** wählen, **Mechanisch** oder **Feuer**, HP-Schwelle 0–99 % und einen eindeutigen Titel angeben.
4. Für weitere Abstufungen wiederholen. Die Liste ist je Schadensart absteigend nach HP sortiert. Die einschließende Schwellenregel lautet: ab 75 % verbleibenden HP Stufe 75, ab 40 % Stufe 40, bei 100 % die intakte Basis. Optional kann nach Anlegen einer Stufe der **Spiel-Gebäudetyp** (numerische Zielspiel-ID) zugeordnet werden. Seine Bedeutung ist im Zielspiel gesondert zu prüfen; doppelte Zuordnungen werden abgelehnt.
5. **Tiles bearbeiten** öffnet die eigenständige Szene dieser Stufe. Die Originalszene wird nicht verändert. Jede Ausgangskachel bleibt kopiert oder später als eigenes Asset gespeichert. Über den normalen Sprite-Editor sind Bild- und Maskenimporte, Pivots und Layoutbearbeitung möglich.
6. Über die HP-Testvorschau können mechanische und Feuerzustände getrennt durchgespielt werden. Feuer fällt nur dann auf mechanische Modelle zurück, wenn für das Gebäude **keine** Feuerstufe definiert ist.

## GPT Image 2.6 in Codex
1. In der gewünschten Stufe **Sunburst** für den Feinschliff oder **Flare** für schnelle Vorlagen wählen. Im Feld **Nachbesserung** präzise Korrekturwünsche ergänzen.
2. **Codex-Prompt + Original exportieren…** erzeugt ein ZIP mit `request.json`, `reference.png`, der pixelgenau registrierten `model_reference.png`, ggf. früheren freigegebenen Stufen, Kandidaten und `CODEX.md`.
3. Das ZIP im Codex-Arbeitsbereich bereitstellen. Codex kann den vom Projekt mitgelieferten Adapter `tools/building_damage_codex.py` ausführen. Er benötigt Python 3.11+ und für registrierte Bildgrößen Pillow, speichert keine API-Schlüssel und verändert keine Installationsdateien. Beispiel (aus dem SpriteSuite-Projektverzeichnis):

   `python tools/building_damage_codex.py --bundle "C:\Downloads\steinhof_mechanical_75_codex.zip" --output "C:\Temp\steinhof_stufe_75" --dry-run`

   Bei korrektem Bundle und bewusst freigegebenen API-Kosten folgt gesondert:

   `python tools/building_damage_codex.py --bundle "C:\Downloads\steinhof_mechanical_75_codex.zip" --output "C:\Temp\steinhof_stufe_75" --execute`

4. Den API-Schlüssel ausschließlich als `OPENAI_API_KEY` außerhalb des Quellcodes bereitstellen. Der Editor führt **keine** HTTP-Anfragen aus, damit sein offlinefähiges Sicherheitsmodell unangetastet bleibt.
5. Das Modelloriginal bleibt als `model_candidate_raw.png` erhalten. Der Adapter registriert die Ausgabe auf das ursprüngliche Pixelraster zurück. Nach Größen- und Fremdpixelprüfung entsteht `candidate.png` für den Editor. `candidate-meta.json` enthält die Prüfdaten und SHA-256-Prüfsummen. Falls die Ausgabe die Registrierungsfläche verletzt, wird kein bearbeitbarer Kandidat erzeugt.
6. Das generierte `candidate.png` über **Generiertes PNG importieren…** in die Stufe laden, gegebenenfalls erneut nachbessern. Ohne explizites **PNG als Tiles zerlegen** verändert es die Stage-Tiles nicht.

## Qualitätsabnahme
- Die Pixelgröße, Bodenanker und transparente Registrierung müssen exakt passen. Aus dem Gesamtbild wird ausschließlich unter der bestehenden 1-px-Overlap-/Hinterreihenlogik zerlegt. Die gesamte sichtbare Rekonstruktion muss pixelgleich sein. Tiles werden nie breiter als 64 px.
- Im Abnahmedialog erscheinen Original und Schadensmodell nebeneinander. Der Editor verhindert auch praktisch unveränderte Modelle: je nach HP-Stufe ist eine Mindestanzahl sichtbarer Pixeländerungen erforderlich (ab 75 % HP mindestens 0,75 %; bei schwereren Schäden entsprechend mehr). Diese Messgröße ist nur ein Mindestbeleg, keine visuelle Bewertung der Zerstörung. Perspektive, Architektur, Material, beleuchtete Flächen, Doppelkonturen, schwarze Nahtpixel und Fortschritt gegenüber früheren Stufen müssen **visuell** gegen Original und vorangegangenes Schadensmodell geprüft werden.
- Falls die Original-Tiles `_m.png`-Masken haben, dürfen materialrelevante Kanäle nicht automatisch erfunden oder entfernt werden. Fehlende Masken blockieren die Abnahme. Einen nicht mehr passenden KI-Kandidaten kann man unter **Kandidat verwerfen** entfernen, ohne die bereits bearbeiteten Tiles zu löschen.
- **Qualität abnehmen…** erfordert eine bewusste Bestätigung. Änderungen an Stufen-Tiles, Raster, HP-Zuordnung oder dem Original setzen zuvor erteilte Freigaben zurück.

## Export
**HP-Schadensmodelle exportieren…** erzeugt ein separates ZIP mit `damage-manifest.json` und ausschließlich freigegebenen Tile-Bildern. Das Manifest enthält Ursache, HP-Schwelle, Tile-Zuordnungen und Geometrie. Es implementiert bewusst noch **keinen** C#-Runtime-Hook. Der bestehende Export von Mod-Overrides schließt diese zusätzlichen Schadensstufen aus, um nicht versehentlich das intakte Standardgebäude zu überschreiben.

## Grenzen
- Die Engine-Integration erfordert einen nachweislich funktionierenden Zugriff auf konkrete Gebäudeinstanz, deren aktuelle/maximale HP, Brandursache und den zugeordneten Renderer sowie eine sichere Asset-Lebensdauer. Die vorhandenen Schadens-Events allein beweisen diese Schnittstelle nicht.
- Ein zweidimensionales PNG ersetzt keine Spielkollision, Brandanimation, Laufzeit-Physik oder echte Geometrie.
- Prompts garantieren keine Originaltreue. Pixelgenaue Rückregistrierung verhindert nicht jedes visuelle Artefakt. Ein echter SHCDE-In-Game-Test muss vor Installation/Veröffentlichung folgen.

## Reproduzierbare Prüfungen
- `node --test tests/test_core.cjs tests/test_seam_overlap.cjs tests/test_split_integration.cjs tests/test_damage.cjs` im Verzeichnis `extras/sprite-editor`.
- `python -m unittest discover -s tests -p test_building_damage_codex.py -q` im SpriteSuite-Projektverzeichnis.
- `node tests/test_damage_browser.cjs` im Verzeichnis `extras/sprite-editor`; benötigt lokal verfügbare Puppeteer-/Edge-Bibliotheken.
