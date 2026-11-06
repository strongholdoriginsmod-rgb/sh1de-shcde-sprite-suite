# Gebäudeschadens-Workflow – Bestandsanalyse (06.11.2026)

## Verifizierte Grundlage
- Isolierter Ausgangspunkt: Git-Commit `10c79be`, Zweig `feature/sprite-editor-seam-overlap-20261106`; Arbeitsverzeichnis des Hauptprojekts mit 162 uncommitteten Änderungen bleibt unberührt.
- Offline-Sprite-Editor: `extras/sprite-editor/src/{core,codec,io,app}.js`, `shell.html` und `build.py`; Projektformat `stronghold-sprite-editor`, Version 2, speichert validierte Frames/Scenes/Referenzen und PNG mit SHA-256 in SHSPRITE.
- Gebäude sind bislang `scene.settings.category === 'building'` und enthalten Tile-Frames mit Slot, Pivot, PPU, DX/DY. Eine HP- oder Schadensarten-Zuordnung existiert nicht.
- `core.split` implementiert Pixelbesitz-Maske und separate, nur für voll deckende Pixel zulässige 1-px-Überlappung inklusive sämtlicher hinterer Diagonalen; bei aktiver Überlappung höchstens 64 px Tilebreite. Transparenz und Masken dürfen nicht unkontrolliert dupliziert werden.
- `io.exportMod` exportiert globale Sprite/Atlas-Overrides für benannte SHCDE-Ziele, ohne geschützte dynamische Auswahl nach HP. Eine neue Stufe darf nicht als globaler Default-Override ausgegeben werden.
- C#-Runtime enthält Gebäudeschadensereignisse und SpriteRenderer-bezogene Asset-Streaming-Lanes. Verifizierte HP->Sprite-Wechselschnittstelle für konkrete Gebäude samt Feuerschaden fehlt. Keine ungetestete Runtime-Manipulation.
- Editor-CSP blockiert bewusst Netzwerkzugriffe (`connect-src 'none'`). Modellaufrufe müssen außerhalb des Browsers erfolgen.
- GPT Image 2.6 ist seit 04.11.2026 verfügbar. Gültige Modelle: `gpt-image-2.6-sunburst` (Final) und `gpt-image-2.6-flare` (Iteration). Offizielle Image-Edits-API akzeptiert Referenz-PNGs, Prompts und Base64-PNG-Antworten.
- Ein lokales `codex`-Kommando ist auf dem Zielrechner aktuell nicht im PATH; eine reproduzierbare Codex-kompatible CLI ist als Integrationsgrenze vorzusehen.

## Ziel und Invarianten
1. Gebäude nach bestehender Scene auswählen, darunter Schadensmodelle mit eigenen Tile-Szenen (keine zweite Sprite-Engine).
2. Für mechanische und Feuerzerstörung getrennte Schwellen: Prozentwert 0..99, bei HP <= Schwelle gilt die zuletzt erreichte (am stärksten zerstörte) Stufe. 100 % bleibt Basis.
3. Jede Stufe erhält eine eigene Szene; Pixelpuffer sind zunächst geteilt/immutable, spätere Änderungen isoliert. Automatische Modellübernahme bleibt solange Entwurf, bis die Qualitätskontrolle und manuelle Freigabe erfolgen.
4. Bestehender Scene-/Frame-Workflow, History/Undo, SHSPRITE-Import/Export und 64px-Tile-Overlap bleiben intakt.
5. Mod-Export darf nicht aus Versehen Stage-Tiles als Standard-Overrides installieren. Eigener Schaden-Export ist ein **Daten-/Assetpaket** ohne behaupteten Runtime-Hook.
6. Prompts enthalten Original-Referenz, Schadensart, Schweregrad, Fortschrittslogik, Perspektive, Silhouette, Palette, Alpha und geometrische Verbote. Das Original wird nicht überschrieben.
7. Ein Codex-CLI-Adapter führt optional kostenpflichtige GPT-Image-Edits gegen eine Referenz aus; keine Schlüssel im Projekt, kein automatischer API-Aufruf ohne explizites Kommando.
8. Qualitätskontrolle: exakte Canvasgröße, Alpha, Silhouette/Bodenanker, 64px-Tile-Grenzen, Maskenverlust, Rekonstruktion, manuelle visuelle Beurteilung und Nachbesserung.

## Nicht nachgewiesen / bewusst nicht enthalten
- In-Game-Umschaltung nach HP oder Erkennung mechanischer vs. Brandursache durch das Spiel: erfordert gesondert getestete Runtime-Pfad-Integration.
- Behauptete garantierte KI-Originaltreue; Referenzen und Prüfungen reduzieren Fehler, ersetzen keine Abnahme.
- Automatisches Resampling generierter 1024px-Bilder auf beliebige Tile-Raster: nicht pixel- und pivot-sicher.
- Installation/Überschreibung der SHCDE-Spieldateien.
