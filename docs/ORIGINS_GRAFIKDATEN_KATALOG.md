# ORIGINS-Grafikdaten: vollständiger HUD-/GUI-Katalog

Stand: 27. Oktober 2026. Diese Integration ergänzt die Stronghold-1-HUD-
Bearbeitung und den historischen Stronghold-Origins-/Crusader-Atlasweg in
**derselben Universal-Suite**.

## Inhalt und Herkunft

Der lokale Katalog `config/origins-grafikdaten-inventory.json` enthält
**13.562 Originalpfade** aus dem GitLab-Projekt
`strongholdoriginsmod/stronghold-europe-grafikdaten`, gepinnt auf Commit
`66dd212217831016d454483f41859258d5d3dc89`.

Der Katalog umfasst **4.086 HUD-/GUI-Einträge**, weitere Sprite- und
Atlasdaten, Origins-Konzeptgrafiken, Projektmaterial und historische
Mod-/Baupakete. Alle Einträge führen ihre ursprüngliche Git-Blob-ID,
Kategorie, Dateiendung und Git-LFS-Kennzeichnung. Gefunden werden unter
anderem Origins-Blau/Silber-Atlanten, vier UI-Atlanten-Sätze,
`daten/origins/ui-blue-silver/index.json`, Menü-XAML und die
Sandkasten-HUD-Grafiken.

**Das Katalog-JSON enthält keine Pixel, DLLs, Videos oder LFS-Inhalte.**
Originale aus den installierten Spielen werden nicht ungefragt
öffentlich weiterverteilt. Die Binärdaten verbleiben im von
Mitwirkenden mit Zugriff verwendeten Grafikdaten-Repository.

## Einmaliges lokales Einrichten

Im Root der Sprite Suite in einem Terminal:

```powershell
git clone --filter=blob:none https://gitlab.com/strongholdoriginsmod/stronghold-europe-grafikdaten.git work/stronghold-europe-grafikdaten
git -C work/stronghold-europe-grafikdaten lfs pull
.venv/Scripts/python.exe tools/origins_grafikdaten.py audit --repo work/stronghold-europe-grafikdaten
```

Git LFS ist für die Binärdateien Voraussetzung; bei knappen
Platzverhältnissen können mit `git lfs pull --include="assets/ui/**"`
zunächst nur gewünschte Datengruppen heruntergeladen werden.
Ein nicht geladenes LFS-Objekt wird in der Suite **nicht als Bild**
interpretiert. Der Katalog selbst benötigt keinen vollständigen
LFS-Download und ist auch bei tausenden Originaldateien suchbar.

Für abweichende GitLab-Commit-Stände wird keine automatische
Positions-/Unity-ID-Übernahme behauptet. Der Katalog verlangt die
genannte Quellrevision, bis eine neue Version explizit abgenommen wird.

## Bedienung

1. **Suite starten.cmd** öffnen und **ORIGINS Grafiken** wählen.
2. Den lokalen Grafikdaten-Git-Klon wählen und **Git-Stand prüfen**.
3. Über **HUD & GUI** suchen, per Suchwort oder anderen Kategorien
   auf alle Elemente zugreifen und durch die 300er-Seiten blättern.
4. PNG/JPG mit gültiger Git- und LFS-Prüfsumme direkt vergleichen.
5. **Bearbeitungskopie erstellen** erzeugt eine getrennte Datei unter
   `work/origins-grafikdaten-edits/` samt
   `.source.json`-Nachweis. Bestehende Bearbeitungen werden nie überschrieben.
6. Für das native Stronghold-1-HUD zum **SH1 HUD-Studio** wechseln.
   Für freies Zeichnen, Maske und Import den bestehenden
   **HTML-Sprite-Editor** nutzen. Der alte Origins-Atlasverarbeitungspfad
   bleibt separat und prüfbar.

Technischer CLI-Rückweg für eine einzelne Datei:

```powershell
.venv/Scripts/python.exe tools/origins_grafikdaten.py verify --repo work/stronghold-europe-grafikdaten --path "sandbox/hud/hud.png"
.venv/Scripts/python.exe tools/origins_grafikdaten.py copy --repo work/stronghold-europe-grafikdaten --path "sandbox/hud/hud.png"
```

Die hier erzeugte Arbeitskopie ist **noch kein automatisch kompatibles
SHCDE-Modpaket**. Ein Crusader-HUD-/Atlas-Export muss weiterhin den
Noesis-XAML-Ressourcenschlüssel, Ziel-Größen und die passende
Script-Extender-Version prüfen.

## Veröffentlichung und Rechte

Dieses Suite-Repository enthält nur den originalgetreu erfassten
Dateikatalog und die verifizierende Software sowie bereits vorhandene
synthetische Beispiele. Große, teils aus dem Spiel abgeleitete Binär-
sammlungen verbleiben im separaten Grafikdaten-Repository. Ein späterer
Mirror in ein GitHub-Repository muss dessen **tatsächlich private**
Sichtbarkeit und die Weitergaberechte erfüllen – eine erst nach dem Upload
angekündigte Umschaltung schützt die Dateien vorübergehend nicht.

## Prüfstand

- Inventar: 13.562 Pfade, 4.086 HUD-/GUI-Klassifikationen
- SHA-/LFS-Prüfung gegen Git-Commit und Datei-Hash
- Dateinamen mit Traversal, reservierten Windows-Namen oder
  Arbeitsordner-Symlinks werden abgewiesen
- Windows-Universal-Suite-GUI mit Filtern und Navigation erfolgreich geöffnet
- **Nicht** nachgewiesen: Ingame-Parität sämtlicher Herkunftssets,
  Rechtefreigabe einzelner abgeleiteter Bilder oder C#-Runtime-ABI
  von Script Extender 2.14.3
