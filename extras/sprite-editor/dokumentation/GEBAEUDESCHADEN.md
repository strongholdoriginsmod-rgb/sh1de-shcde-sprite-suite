# Gebäudeschäden im Stronghold Sprite Editor

Stand 08.11.2026, neuer Main-Quellstand. Der Editor erstellt frei bearbeitbare und exportierbare HP-/Feuer-Schadensbibliotheken für das getrennte Runtime-Modul. Ältere RC4-Pakete enthalten die hier beschriebenen Vereinfachungen noch nicht.

## Gebäude und Schadensstufen
1. Im Sprite Editor eine Gebäude-PNG-Serie öffnen oder ein vorhandenes `.shsprite` laden.
2. Rechts **Schaden** öffnen. Im Feld **Gebäude** die gewünschte Gebäude-/Tilegruppe auswählen.
3. **Neue Schadensstufe…** wählen, **Mechanisch** oder **Feuer**, HP-Schwelle 0–99 % und einen eindeutigen Titel angeben.
4. Für weitere Abstufungen wiederholen. Die Liste ist je Schadensart absteigend nach HP sortiert. Die einschließende Schwellenregel lautet: ab 75 % verbleibenden HP Stufe 75, ab 40 % Stufe 40, bei 100 % die intakte Basis. Optional kann nach Anlegen einer Stufe der **Spiel-Gebäudetyp** (numerische Zielspiel-ID) zugeordnet werden. Seine Bedeutung ist im Zielspiel gesondert zu prüfen; doppelte Zuordnungen werden abgelehnt.
5. **Tiles bearbeiten** öffnet die eigenständige Szene dieser Stufe. Die Originalszene wird nicht verändert. Jede Ausgangskachel bleibt kopiert oder später als eigenes Asset gespeichert. Über den normalen Sprite-Editor sind Bild- und Maskenimporte, Pivots und Layoutbearbeitung möglich.
6. Über die HP-Testvorschau können mechanische und Feuerzustände getrennt durchgespielt werden. Feuer fällt nur dann auf mechanische Modelle zurück, wenn für das Gebäude **keine** Feuerstufe definiert ist.

## KI-Sprites mit Codex und ChatGPT

1. Den Editor über SpriteSuite oder `Sprite-Editor.cmd` mit der mitgelieferten Python-Laufzeit starten. Die optionale Codex CLI muss im `PATH` liegen. Im Reiter **Schaden** ein Gebäude wählen.
2. Unter **KI-Sprites mit Codex** auf **Bei ChatGPT anmelden…** klicken. Codex öffnet seinen offiziellen Anmeldebrowser. Wenn dein ChatGPT-Konto mit Google verknüpft ist, kannst du dort Google auswählen. Eine vorhandene ChatGPT-Sitzung wird wiederverwendet.
3. **Schadensmodelle mit Codex erstellen…** nimmt die gewünschten HP-Schwellen pro Schadensart sowie eigene Details entgegen. Jede Stufe erhält den Originalsprite, einen eigenen Prompt und, wenn vorhanden, das nächstmildere Modell. Vorhandene Stufen haben einen eigenen Generierungsbutton und können mit einem präziseren Änderungswunsch überarbeitet werden.
4. **Gebäudeversion mit Codex erstellen…** legt eine eigenständige bearbeitbare Szene an. Der Prompt erhält Gebäudetyp, Stil, Perspektive und Bodenanker. Die Version erhält eigene Tiles und eine separat zuweisbare Zuordnung zum Zielspiel.
5. Ein passend registriertes Bild wird auf die ursprüngliche Geometrie zurückgerechnet und in Tiles zerlegt. Bei abweichender Registrierung wird die Rohdatei als ZIP angeboten. Mit **Kopie ans Tile-Raster anpassen** werden sichtbare Pixel ohne Tile-Zuordnung nur in der bearbeiteten Fassung ausgeblendet. Das Kandidaten-PNG bleibt im Projekt. PNGs lassen sich auch nach manueller Ausrichtung importieren. Generierte Tiles und Schadenspakete lassen sich direkt weiterbearbeiten oder exportieren. Vergleich und Notizen sind freiwillig.
6. Das Bild wird mit der eingebauten Bildgenerierung des Codex-Clients erstellt. Der ChatGPT-Tarif bestimmt das enthaltene Kontingent, die verfügbaren Bilder und den möglichen Einsatz von Codex-Guthaben. [OpenAI Docs zur Codex-Anmeldung](https://learn.chatgpt.com/docs/auth) und [OpenAI Docs zur Bildnutzung](https://learn.chatgpt.com/docs/pricing#how-does-image-generation-count-toward-usage-limits).

Der eigenständige HTML-Editor bietet Dateiimport und Anfrageexport. **Codex-Prompt + Original exportieren…** speichert Prompt, Original und registrierte Referenz gemeinsam. Einen Auftrag aus einer ZIP-Datei kann man auch über die Kommandozeile starten.

```powershell
python tools/building_damage_codex.py --status
python tools/building_damage_codex.py --login
python tools/building_damage_codex.py --bundle "C:\Downloads\steinhof_codex.zip" --output "C:\Temp\steinhof_75" --execute
```

Die Ausgabe enthält das unveränderte Modellbild und Prüfsummen. Bei geometrisch passender Ausgabe entsteht zusätzlich `candidate.png`.

## Vergleich und optionale Notizen
- Die technische Rückregistrierung verwendet die festgelegten Pixelmaße und das Tile-Raster. Die bestehende 1-px-Overlap-/Hinterreihenlogik bleibt erhalten; Tiles werden höchstens 64 px breit. Ungültige Geometrie, doppelte Rasterplätze oder fehlende Bilddaten sind weiterhin Fehler.
- **Vergleich und Notiz…** zeigt Original und Schadensmodell nebeneinander. Transparente oder unveränderte Modelle, veränderte Bodenanker, Maskenauffälligkeiten und Unterschiede zwischen Schadensstufen ergeben Hinweise. Es gibt keine Mindestanzahl geänderter Pixel und keine geforderte Schadensquote.
- Wer einen eigenen Vergleichsmarker setzen möchte, kann eine **Notiz (optional)** eingeben und **Als geprüft markieren** verwenden. Weder eine Checkbox noch eine Mindesttextlänge ist nötig. Der Marker ist keine Voraussetzung für Bearbeitung, Verwendung oder Export.
- Fehlende Materialmasken werden im Vergleich als Hinweis behandelt; eine passende Maske wird nicht erfunden. Die gesonderten Materialverträge des normalen Modexporters gelten weiterhin, etwa wenn ausdrücklich `TeamColour` gewählt wurde. **Kandidat verwerfen** entfernt nur den Kandidatenverweis, nicht die bereits bearbeiteten Tiles.

## Export
**HP-Schadensmodelle exportieren…** ist die normale freie Ausgabe. Sie erzeugt ein ZIP mit allen Stufen, auch Entwürfen und verworfenen Varianten. Im `damage-manifest.json` stehen die HP-Schwelle, Ursache, Pixeldateien, Geometrie, `reviewStatus` und `contentApproved`. Für nicht oder nicht mehr inhaltsgebundene Marker ist `approvalDigest` null. Das Paket setzt keine bestimmte Bildveränderung, Prüfnotiz oder Qualitätsabnahme voraus.

**Nur markierte Schadensmodelle exportieren…** ist ein freiwilliger Filter nach gesetztem Vergleichsmarker. Ein älterer, nicht mehr passender Marker blockiert die aktuelle Grafik nicht: Die Ausgabe meldet ihn über `contentApproved: false`, einen leeren `approvalDigest` und einen Hinweis. Beide Ausgaben enthalten eigenständige Bilddaten und HP-Zuordnungen; ein aktiver C#-Runtime-Hook wird nicht vorgetäuscht. Der normale globale Sprite-Override-Export bleibt hiervon getrennt.

## Grenzen
- Die Engine-Integration erfordert einen nachweislich funktionierenden Zugriff auf konkrete Gebäudeinstanz, deren aktuelle/maximale HP, Brandursache und den zugeordneten Renderer sowie eine sichere Asset-Lebensdauer. Die vorhandenen Schadens-Events allein beweisen diese Schnittstelle nicht.
- Ein zweidimensionales PNG ersetzt keine Spielkollision, Brandanimation, Laufzeit-Physik oder echte Geometrie.
- Prompts garantieren keine Originaltreue. Pixelgenaue Rückregistrierung verhindert nicht jedes visuelle Artefakt. Die Grafikdateien und Pakete können direkt exportiert werden; ob und wie sie im Zielspiel erscheinen, ist damit noch nicht nachgewiesen.

## Reproduzierbare Prüfungen
- `node --test tests/test_core.cjs tests/test_seam_overlap.cjs tests/test_split_integration.cjs tests/test_damage.cjs` im Verzeichnis `extras/sprite-editor`.
- `python -m unittest discover -s tests -p test_building_damage_codex.py -q` im SpriteSuite-Projektverzeichnis.
- `node tests/test_damage_browser.cjs` im Verzeichnis `extras/sprite-editor`; benötigt lokal verfügbare Puppeteer-/Edge-Bibliotheken.

## Runtime-Übergabe zur späteren HP-Anbindung

Das exportierte Schadens-ZIP kann mit `python tools/building_damage_runtime_preflight.py --package <gebaeudeschaden.zip> --dry-run` offline geprüft werden. `--prepare --output <neuer-ordner>` erzeugt eine SHA-gebundene, rein lesende Kandidatentabelle, sofern Gebäudetyp und Geometrie gültig sind. Eine nicht im Zielspiel bestätigte Gebäudetyp-ID wird nicht automatisch als verifiziert markiert. Im nächsten Schritt kann die C#-Auswahllogik die HP-/Feuerschwellen anhand dieser Tabelle prüfen. Die Tabelle beweist noch keinen Zugriff auf den Renderer einer Gebäudeinstanz; das ZIP wird nicht als aktiver Runtime-Hook ausgegeben.

Die vollständige Offline-Prüfung kann über `python tools/qa_building_damage_runtime.py` aus dem SpriteSuite-Projektverzeichnis gestartet werden.

## Vergleichsmarker nach Änderungen

Ein freiwillig markierter Stand erhält eine SHA-256-Zustandsprüfsumme (`approvalDigest`). Sie bindet die tatsächlichen RGBA-Pixel des intakten Gebäudes und aller Schadens-Tiles, die vorhandenen Materialmasken, Rasterkoordinaten, Pivots, PPU, HP-Schwelle, Gebäudetyp und Generierungseinstellungen. Die Prüfsumme beschreibt den damaligen Stand und ist keine digitale Unterschrift oder Spielbestätigung. Bei Änderungen kann der Marker entfallen oder als veraltet erscheinen. Ein solcher Befund ist keine Exportsperre.

Alte `.shsprite`-Projekte mit Markern ohne Zustandsprüfsumme werden weiterhin geöffnet und als **Entwurf** behandelt. Sie können unverändert weiterbearbeitet und exportiert werden; eine erneute Bestätigung ist nicht nötig. Ein veränderter Prompt oder ein anderes GPT-Image-Modell kann ebenfalls den bisherigen Marker aufheben; eine reine Umbenennung nicht.

Der **Vorschau-Modus** kann alle Stufen oder nur markierte Modelle anzeigen. Der optionale Vergleich zeigt neben Original und aktuellem Modell weitere markierte Stufen derselben Schadensursache. Wiedererscheinende Gebäudeteile bei stärkerer Zerstörung sowie Maskenpixel auf transparenten Flächen werden als Hinweise angezeigt. Ob etwa ein Trümmerteil an derselben Stelle sinnvoll ist, entscheidet der Benutzer; eine Pflichtnotiz gibt es nicht.

Der Offline-Runtime-Preflight gibt auch Entwürfe und Stufen ohne Zustandsprüfsumme als HP-Testkandidaten aus. `--prepare --output <neuer-ordner>` ist standardmäßig frei nutzbar. Wer ausdrücklich nur inhaltsgebundene Freigaben prüfen möchte, ergänzt `--require-bound-approval`. Die Tabelle stellt weder eine Spieldateiinstallation noch eine tatsächliche Zuordnung zu Game-Renderern dar.
