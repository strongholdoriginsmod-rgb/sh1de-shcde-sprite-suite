# SpriteSuite – gemeinsamer Geometrieeditor, Umgebungserkennung und KI-Werkstatt
Stand: 2026-11-08 · Zweig: `feature/spritesuite-editor-ai-discovery-20261108`

## Ausgangspunkt und nachgewiesene Projektstände

Die bestehende SpriteSuite hat bereits wichtige Querschnittsfunktionen: bildgenaue
Pivots/Versätze, isometrische Szenen, Referenzüberlagerung, Differenzbilder,
PNG/Masken und Undo, Damage-Profile mit HP/Feuer sowie Script-Extender-Build- und
QA-Werkzeuge. Eine Parallel-Implementierung von Zinnenlineal, Pivot-Schieber
und Spriteverschiebung erzeugt unklare Pixelkoordinaten, doppelte Fenster und
abweichende Qualitätsregeln.

Bei der Inspektion vom 08.11.2026 wurden unter anderem beobachtet:
- `E:\SpriteSuite_FinalUnified_20261108` – FinalUnified, SHA `46250d2`,
  zahlreiche **uncommittete** Runtime-/Tooländerungen;
- `E:\SpriteSuite_UNIFIED_RELEASE_20261108` – älterer, sauberer Release-Stand
  `673eb09`;
- `E:\SpriteSuite_ToolIntegration_20261108` – Tool-Integration mit sehr
  vielen uncommitteten Dateien;
- `E:\SpriteSuite_SHCDE_Expansion_20261108` – SHCDE-Erweiterungszweig,
  ebenfalls viele uncommittete Dateien;
- `E:\SpriteSuite` – ursprünglicher Sandbox-/Studio-Zweig.

Diese Liste ist ein **Standort- und HEAD-Audit**, noch **kein** vollständiger
funktionaler Diff jeder uncommitteten Datei. Für uncommittete Arbeit dürfen
weder `git reset --hard`, `git clean -fd` noch `git worktree remove --force`
als automatisierte Aufräumverfahren eingesetzt werden. Der neue Zweig wurde
aus `46250d2` per `git worktree add` isoliert. Er kann später unter
Reviewbedingungen in den vereinbarten Releasezweig übernommen werden.

## Konsolidierung: ein Canvas statt N Speziallineale

Das editierbare Ursprungssystem bleibt `extras/sprite-editor/src/` mit
`core.js` (reine Pixelgeometrie), `io.js` (Datenmodell und Undo),
`app.js` (Browser-Canvas) und `damage_io.js` (HP-/Feuer-Spezialist).
Neue gemeinsame Funktionen:

- `snapCoordinate`: ganzzahliges Snap auf frei definierte Pixelabstände;
- `pivotFromPixel`: Wandlung von Canvas-Pixeln (oben links) zu
  Spiel-Pivots (unten links), mit Bounds-Prüfung;
- `measurePoints`: Abstand `dx`/`dy`, Länge und Winkel in Bildpixeln;
- zentraler Geometrie-Inspektor: Pivots, Bodenanker, Fangraster, Messlinie
  und optional nach bestätigter Sichtprüfung übernommener Sprite-Versatz;
- vorhandenes Overlay, Originalvergleich, Pixel-Differenz, Ebenenansicht
  und Undo werden **wiederverwendet**, nicht nachimplementiert;
- Messprotokoll als JSON inklusive Original-PNG-SHA-256 (keine Spiel-Freigabe).

**Alte Zinnenlineal-Dateien** dürfen nicht blind gelöscht werden: sie sind
weiterhin im jeweiligen historischen Format prüf- und importierbar zu halten.
Ein struktureller Migrationsimport für alle älteren Messformate ist noch
nicht implementiert; verlässliches Mapping benötigt echte Beispieldateien
und kann nur danach als Migration bestätigt werden.

### Weitere sinnvolle Zusammenlegungen

1. Anker-/Pivot-, Ebenen-, Raster-, Mess- und Zinnenwerkzeuge in einen Canvas;
2. Sprite-/Atlas-/BC7-/Unity-Materialprüfungen in einen Asset-Inspector mit
   gemeinsamen Bild-/Masken- und Provenienzkontrakten;
3. AIV-/AIC-/AIP-/KI-Grafikeditoren mit einem gemeinsamen
   Arbeitsbereich-/Diff-/Commit-/Rollback-Protokoll statt eigenen Versionskopien;
4. Script-Extender-, APIShared- und Serp-Anbindung in **einen**
   versionsgebundenen Runtime-Adapter mit Capability-Manifest;
5. Spiele- und Toolchain-Erkennung als gemeinsame, nur lesende Diagnosesicht,
   nicht als verschiedene starre Pfadtabellen.

## Nur lesende Umgebungserkennung

`tools/suite_environment_discovery.py` kann:
- explizite und gespeicherte Pfade, Umgebungsvariablen und Steam
  `libraryfolders.vdf` mit begrenzten Listen durchsuchen;
- SH1DE/SHCDE anhand existierender `*_Data/resources.assets` erkennen;
- SHCDE Script-Extender-DLL und in deren Nähe APIShared/Serp-DLL-Dateien
  auffinden, einschließlich einer **nicht verifizierten** Versionsdeklaration;
- Unity-Editor-, .NET-SDK- und Python-Pfade vorschlagen;
- zweifelhafte/multiple Spielordner als `null` vorschlagen statt
  unbemerkt ein falsches Ziel zu benutzen.

In `tools/suite_center.pyw` ist der Button „Automatisch erkennen“ integriert.
Er ergänzt nur **leere** Eingabefelder. Spiel/Runtime werden nicht gestartet;
Konfigurationsdateien werden nicht gespeichert; die explizite
„Pfade speichern“-Aktion bleibt erforderlich. Dateifunde sind **keine**
ABI-/Versionsfreigabe. Für echte Builds und In-Game-Aktionen sind Checks
gegen Hashes, Asset-Layout, Unity-Version, BepInEx-/Script-Extender-ABI
und ein isolierter QA-Spielklon verpflichtend.

Beispiele:
```powershell
$env:PYTHONPATH="src;tools"
python tools/suite_environment_discovery.py
python tools/suite_environment_discovery.py --game-root "C:\Pfad\zur\Spielkopie"
```

## Allgemeiner KI-Workflow (zusätzlich zu HP-/Feuer-Schaden)

**Eingabe → Planung → Modell-Arbeitsfläche → Requestbundle → externer
Generator → normalisierte PNGs → getrennte Varianten → Vergleich →
manuelle Abnahme → Undo/Projekt → QA-Export.**

### 1. Präzise Aufgabenformulierung

Im Inspector `KI-Werkstatt` vorgeben:
- Assetklasse (Gebäude, Einheit/Animation, Vegetation, HUD, UI, andere),
- textliches Änderungsziel und explizite Erhaltungsregeln,
- GPT Image 2.6 Flare oder Sunburst, 1–4 getrennte Varianten,
- vorhandenes Sprite als unveränderliche Referenz samt SHA-256.

Die UI verspricht **keine automatische** KI-Erzeugung und ruft keine API auf.
Das ZIP enthält `reference.png`, `model_reference.png`,
`request.json` und `WORKFLOW.txt`. Ein festes Arbeitsrechteck
innerhalb einer transparenten Modell-Arbeitsfläche und
Nearest-Neighbor-Registrierung erhalten die spätere Zuordnung zum
Originalpixelraster. Die vollständigen Original-PNG-Daten und
projektinternen Originale werden nicht verändert.

Die KI kann Form-/Alpha-/Silhouettenabweichungen machen. Registrierungs-
und Größenangaben sind darum **Wünsche/Prüfvorgaben**, keine Garantie.

### 2. Externer Generator mit Kostenbremse

`tools/suite_ai_codex.py` verarbeitet ausschließlich das geprüfte ZIP.
Der Normalmodus ist offline:
```powershell
python tools/suite_ai_codex.py --bundle ".\auftrag.zip" --output ".\ki-kandidaten" --dry-run
```

Erst eine ausdrücklich ausgelöste Zahlungsschleife darf die Image-API
aufrufen; zusätzlich müssen die voraussichtlichen Einzelaufrufe bestätigt sein:
```powershell
$env:OPENAI_API_KEY="...in der sicheren Umgebung setzen..."
python tools/suite_ai_codex.py --bundle ".\auftrag.zip" --output ".\ki-kandidaten" --execute --confirm-paid-requests 2
```
Die Zahl muss exakt `variants` in der Anfrage entsprechen. Keine
API-Schlüssel im Projekt, keine Kostenfreigabe im Editor, keine Spielinstallation
oder Modveröffentlichung, nur neue/leerstehende Ausgabeordner. Ein bereits
vorhandener Generator `tools/building_damage_codex.py` bleibt **für
sequenzielle HP-/Feuer-Schadensstufen** zuständig und liefert seine speziellen
Quality-/Gate-Verträge. Die generische Werkstatt importiert dessen Bilder nicht
ungeprüft in die freigegebene Damage-Library.

Der generische Adapter nutzt denselben validierten
`multipart`-Transport und dieselbe inverse
Nearest-Neighbor-Registrierung wie das Schadenstool. Die PNGs
`variant_01.png`, `variant_02.png` usw. sind normalisierte Arbeitsbilder,
die ungeschnittene Modellausgabe und ein SHA-256-Metadatensatz bleiben
getrennt erhalten. Bei Layout-/Alpha-Verstößen wird kein normalisiertes PNG
ausgegeben.

### 3. Abnahme und Herkunft

1. Unabhängige Kandidaten-PNGs im Sprite Editor laden (bis vier pro Durchlauf).
2. Größe und Pixel-/Alpha-Differenz automatisch prüfen, Original und Kandidat
   im Abnahmedialog nebeneinander betrachten.
3. „Ich habe … geprüft“ explizit bestätigen und einen konkreten
   Abnahmevermerk (mindestens acht Zeichen) eingeben.
4. **Nur die aktuelle Arbeitskopie** wird in einer Undo-Transaktion ersetzt;
   Originale und Masken bleiben erhalten.
5. Provenienz in der `.shsprite`-Datei: Quell-SHA, Bildkandidaten-SHA,
   **decoded RGBA-Inhalts-SHA inklusive Abmessung**, Anfragemodell als
   *Behauptung, nicht API-Signatur*, Abnahmevermerk.
6. Veränderte Arbeitsbild-ID oder manipulierte Pixel löschen/ungültig
   machen den Abnahmebeleg. Gameplay-/HP-/Feuer-Freigabe bleibt separat.

**Stoppbedingungen**: Kandidatenformat falsch, Größe/Alpha unbrauchbar,
Quelle gewechselt, Referenz unpassend, Bildbudget überschritten,
fehlender Zustimmungshaken oder Abnahmevermerk. Für den externen
Modelladapter werden zusätzlich Archive-/Hash-/Pfadsicherheit und
die kostenpflichtige Aufrufzahl geprüft.

### 4. Noch nicht als erledigt deklarieren

- Reale API-Aufrufe nicht gegen ein Nutzerkonto ausgeführt (keine
  Kostenfreigabe oder Schlüssel vorliegend).
- KI-Ausgaben noch nicht im konkreten SHCDE-QA-Spiel bewertet.
- Browserintegration wurde nach dem HTML-Neubau real unter Edge 157 geprüft:
  49 allgemeine Szenarien, 16 HP-/Feuer-Szenarien und der getrennte
  DE-/EN-KI-End-to-End-Test bestanden. Der Bericht belegt ausschließlich
  Browserfunktionen, keine tatsächliche Spiel-/Runtime-Anbindung.
- Unity-AssetBundle-/BC7-/Script-Extender-ABI-Freigaben benötigen
  separate Live-/Buildtests; eine Datei allein ist kein Hook-Nachweis.
- KI-Sprites dürfen nicht automatisch als HP-/Feuer-Ruinen exportiert
  oder in ein laufendes Spiel kopiert werden.
- Der alte Zinnenlineal-Spezialcode ist aus Rückwärtskompatibilitätsgründen
  noch nicht physisch gelöscht.

## Validierung und Übergabe

Gültige isolierte Tests:
```powershell
$env:PYTHONPATH="src;tools"
python -m pytest -q tests/sandbox/test_suite_environment_discovery.py tests/sandbox/test_suite_ai_codex.py
node --test extras/sprite-editor/tests/test_ai_workflow.cjs
python extras/sprite-editor/build.py
python extras/sprite-editor/sprache/einbauen.py
```

Die früheren Browserberichte wurden **nach** dem neuesten HTML-Build neu
aufgenommen: 49/49 allgemeine Prüfungen, 16/16 HP-/Feuer-Prüfungen
und ein zusätzlicher DE-/EN-KI-Workflow im realen Edge-157-Browser,
ohne JavaScript-Fehler oder unerwartete Netzwerkanfragen. Darüber hinaus
bestanden 63 Python- und 142 Node-Kerntests. Die SHA-256-Summen in den
Berichten gehören zu genau diesem neuen Editorstand; Änderungen daran
erfordern erneut Tests und aktualisierte Prüfsummen.

Für die **spätere** Konsolidierung aller Branches:
`git worktree list --porcelain`, `git status --porcelain=v1`,
`git log --all --graph --oneline`, `git diff --stat`,
uncommittete Änderungen vorab je Worktree separat archivieren,
mit `git range-diff` und Datei-Hash-Prüfung vergleichen, sinnvolle
Funktionen in einem Review-PR übernehmen, dann alle bekannten
Tests/QA-Matrizen durchführen. Erst nach gesichertem Archive-Hash,
PR-Abnahme und schriftlich dokumentierter Branch-Freigabe
darf ein **alter** Entwicklungszweig gelöscht werden. Der Final- oder
andere ungesicherte Zweige sind vom vorliegenden Feature-Commit unberührt.

## Aktuelle externe API-Quellen

- [OpenAI Image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
- [OpenAI Images edit endpoint](https://developers.openai.com/api/reference/resources/images/methods/edit)

Diese Dokumentation beschreibt **Funktionalität**, keine
komplette SHCDE-/Unity-Engine-Kompatibilitätsfreigabe.
