# Gebäudeschäden im Stronghold Sprite Editor

Stand 07.11.2026. Der Editor erstellt bearbeitbare HP-/Feuer-Schadensbibliotheken für das getrennte Runtime-Modul.

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
5. Ein passend registriertes Bild wird auf die ursprüngliche Geometrie zurückgerechnet und in Tiles zerlegt. Bei abweichender Registrierung wird die Rohdatei als ZIP angeboten. Mit **Kopie ans Tile-Raster anpassen** werden sichtbare Pixel ohne Tile-Zuordnung nur in der bearbeiteten Fassung ausgeblendet. Das Kandidaten-PNG bleibt im Projekt. PNGs lassen sich auch nach manueller Ausrichtung importieren. Generierte Tiles und freie Schadenspakete lassen sich direkt weiterbearbeiten oder exportieren. Die optionale Qualitätsabnahme kennzeichnet überprüfte Varianten.
6. Das Bild wird mit der eingebauten Bildgenerierung des Codex-Clients erstellt. Der ChatGPT-Tarif bestimmt das enthaltene Kontingent, die verfügbaren Bilder und den möglichen Einsatz von Codex-Guthaben. [OpenAI Docs zur Codex-Anmeldung](https://learn.chatgpt.com/docs/auth) und [OpenAI Docs zur Bildnutzung](https://learn.chatgpt.com/docs/pricing#how-does-image-generation-count-toward-usage-limits).

Der eigenständige HTML-Editor bietet Dateiimport und Anfrageexport. **Codex-Prompt + Original exportieren…** speichert Prompt, Original und registrierte Referenz gemeinsam. Einen Auftrag aus einer ZIP-Datei kann man auch über die Kommandozeile starten.

```powershell
python tools/building_damage_codex.py --status
python tools/building_damage_codex.py --login
python tools/building_damage_codex.py --bundle "C:\Downloads\steinhof_codex.zip" --output "C:\Temp\steinhof_75" --execute
```

Die Ausgabe enthält das unveränderte Modellbild und Prüfsummen. Bei geometrisch passender Ausgabe entsteht zusätzlich `candidate.png`.

## Qualitätsabnahme
- Die Pixelgröße, Bodenanker und transparente Registrierung müssen exakt passen. Aus dem Gesamtbild wird ausschließlich unter der bestehenden 1-px-Overlap-/Hinterreihenlogik zerlegt. Die gesamte sichtbare Rekonstruktion muss pixelgleich sein. Tiles werden nie breiter als 64 px.
- Im Abnahmedialog erscheinen Original und Schadensmodell nebeneinander. Der Editor verhindert auch praktisch unveränderte Modelle: je nach HP-Stufe ist eine Mindestanzahl sichtbarer Pixeländerungen erforderlich (ab 75 % HP mindestens 0,75 %; bei schwereren Schäden entsprechend mehr). Diese Messgröße ist nur ein Mindestbeleg, keine visuelle Bewertung der Zerstörung. Perspektive, Architektur, Material, beleuchtete Flächen, Doppelkonturen, schwarze Nahtpixel und Fortschritt gegenüber früheren Stufen müssen **visuell** gegen Original und vorangegangenes Schadensmodell geprüft werden.
- Falls die Original-Tiles `_m.png`-Masken haben, dürfen materialrelevante Kanäle nicht automatisch erfunden oder entfernt werden. Fehlende Masken blockieren die Abnahme. Einen nicht mehr passenden KI-Kandidaten kann man unter **Kandidat verwerfen** entfernen, ohne die bereits bearbeiteten Tiles zu löschen.
- **Qualität abnehmen…** erfordert eine bewusste Bestätigung. Änderungen an Stufen-Tiles, Raster, HP-Zuordnung oder dem Original setzen zuvor erteilte Freigaben zurück.

## Export
**Alle HP-Schadensmodelle exportieren…** erzeugt ohne Pflichtfreigabe ein ZIP mit allen Stufen, auch Entwürfen und verworfenen Varianten. Im `damage-manifest.json` stehen die HP-Schwelle, Ursache, Pixeldateien, Geometrie, `reviewStatus` und `contentApproved`. Für nicht oder nicht mehr inhaltsgebundene Stufen ist `approvalDigest` null. Die Erstellung dieses Pakets setzt keine bestimmte Bildveränderung oder Qualitätsabnahme voraus.

**HP-Schadensmodelle exportieren…** bleibt als freiwillige geprüfte Ausgabe erhalten und enthält nur Stufen mit weiterhin gültiger Inhaltsfreigabe. Beide Ausgaben enthalten eigenständige Bilddaten und HP-Zuordnungen; ein aktiver C#-Runtime-Hook wird nicht vorgetäuscht. Der normale globale Sprite-Override-Export bleibt hiervon getrennt.

## Grenzen
- Die Engine-Integration erfordert einen nachweislich funktionierenden Zugriff auf konkrete Gebäudeinstanz, deren aktuelle/maximale HP, Brandursache und den zugeordneten Renderer sowie eine sichere Asset-Lebensdauer. Die vorhandenen Schadens-Events allein beweisen diese Schnittstelle nicht.
- Ein zweidimensionales PNG ersetzt keine Spielkollision, Brandanimation, Laufzeit-Physik oder echte Geometrie.
- Prompts garantieren keine Originaltreue. Pixelgenaue Rückregistrierung verhindert nicht jedes visuelle Artefakt. Ein echter SHCDE-In-Game-Test muss vor Installation/Veröffentlichung folgen.

## Reproduzierbare Prüfungen
- `node --test tests/test_core.cjs tests/test_seam_overlap.cjs tests/test_split_integration.cjs tests/test_damage.cjs` im Verzeichnis `extras/sprite-editor`.
- `python -m unittest discover -s tests -p test_building_damage_codex.py -q` im SpriteSuite-Projektverzeichnis.
- `node tests/test_damage_browser.cjs` im Verzeichnis `extras/sprite-editor`; benötigt lokal verfügbare Puppeteer-/Edge-Bibliotheken.

## Runtime-Übergabe zur späteren HP-Anbindung

Das freigegebene Schadens-ZIP kann jetzt mit `python tools/building_damage_runtime_preflight.py --package <gebaeudeschaden.zip> --dry-run` vollständig offline geprüft werden. `--prepare --output <neuer-ordner>` erzeugt eine SHA-gebundene, rein lesende Kandidatentabelle, sofern Gebäudetyp und Geometrie gültig sind. Eine nicht im Zielspiel bestätigte Gebäudetyp-ID wird nicht automatisch als verifiziert markiert. Im nächsten Schritt kann die C#-Auswahllogik die HP-/Feuerschwellen anhand dieser Tabelle prüfen. Die Sprite-Renderer-Umsetzung erfordert eine eigene In-Game-Abnahme; das ZIP wird nicht als unmittelbar installierbarer Runtime-Patch behandelt.

Die vollständige Offline-Prüfung kann über `python tools/qa_building_damage_runtime.py` aus dem SpriteSuite-Projektverzeichnis gestartet werden.

## Freiwillige Freigabeprüfung nach Änderungen

Abgenommene Stufen erhalten jetzt eine SHA-256-Zustandsprüfsumme (`approvalDigest`). Sie bindet die tatsächlichen RGBA-Pixel des intakten Gebäudes und aller Schadens-Tiles, die vorhandenen Materialmasken, Rasterkoordinaten, Pivots, PPU, HP-Schwelle, Gebäudetyp und gewählte Generierungseinstellungen. Die Zustimmung bleibt eine **manuelle visuelle Qualitätsabnahme**, die Prüfsumme ist ein Konsistenznachweis und keine digitale Unterschrift. Beim freiwilligen Export ausschließlich freigegebener Stufen wird sie erneut berechnet. Sind Bilddaten, HP oder relevante Einstellungen verändert worden, bleibt dieser geprüfte Export bis zur erneuten Abnahme zurückgestellt. **Der freie Export ist weiterhin möglich.**

Alte `.shsprite`-Projekte mit angeblich freigegebenen Schadensstufen, die noch keine Zustandsprüfsumme besitzen, werden weiterhin geöffnet. Ihre früheren Freigaben gehen aber aus Sicherheitsgründen in **Entwurf** über und müssen nach Sichtvergleich erneut bestätigt werden. Ein veränderter Prompt oder die Auswahl eines anderen GPT-Image-Modells setzt die Freigabe ebenfalls zurück; eine reine Änderung der Bezeichnung nicht.

Der **Vorschau-Modus** kann zwischen allen Entwürfen und ausschließlich freigegebenen, exportierbaren Modellen wechseln. Bei der Abnahme werden neben Original und aktuellem Modell auch andere bereits freigegebene Stufen derselben Schadensursache zum Vergleich angezeigt. Eine Prüfung markiert auffällig wiedererscheinende Gebäudeteile bei stärkerer Zerstörung sowie relevante Maskenpixel auf inzwischen transparenten Flächen. Solche Befunde erfordern einen bewussten Abnahmevermerk, da ein Pixelvergleich nicht entscheidet, ob z. B. ein Trümmerteil an derselben Stelle sinnvoll ist.

Der Offline-Runtime-Preflight gibt auch Entwürfe und Stufen ohne Zustandsprüfsumme als HP-Testkandidaten aus. `--prepare --output <neuer-ordner>` ist standardmäßig frei nutzbar. Wer ausdrücklich nur inhaltsgebundene Freigaben prüfen möchte, ergänzt `--require-bound-approval`. Die Tabelle stellt weder eine Spieldateiinstallation noch eine tatsächliche Zuordnung zu Game-Renderern dar.
