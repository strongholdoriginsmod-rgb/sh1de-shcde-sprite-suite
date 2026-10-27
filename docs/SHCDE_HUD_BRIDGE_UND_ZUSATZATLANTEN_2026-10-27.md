# Sprite Suite: SH1-HUD-Übertragung und eigene zusätzliche SHCDE-UI-Atlanten

**Stand:** 27. Oktober 2026 – fachlich und technisch geprüfte **Offline-Arbeitswege**.
Keine automatische Spielinstallation, keine vollständig geprüfte Ingame-HUD-Zustandsmaschine.
Keine proprietären Texturen oder Original-XAML-Dateien werden im Git gespeichert.

## 1. Was die echten Spielstrukturen verbindlich vorgeben

Die Noesis-Ressourcen des geprüften SHCDE-Referenzstands (`E:\SSGameQA`)
enthalten vier native Unity-Texturen in `globalgamemanagers.assets`:

| Textur | PathID | Größe | Unity-Format |
|---|---:|---:|---:|
| UI-MasterAtlas | 13 | 8192 × 8192 | BC7 (25) |
| UI-TrailAtlas | 21 | 8192 × 8192 | BC7 (25) |
| UI-Colour1Atlas | 23 | 4096 × 4096 | BC7 (25) |
| UI-Colour2Atlas | 47 | 4096 × 4096 | BC7 (25) |

Native Referenzdatei SHA-256:
`84acb0f8fce92551872b004c51bf7201ed07ebc0de85837ef0af0e14c0841fc3`.

Die vier Noesis-XAML-Dateien liegen unter
`BepInEx/plugins/000shcdese/Override/Assets/GUI/Sprites`.
Die Datei `XAMLResources/ApplicationResources.xaml` registriert sie in
`ResourceDictionary.MergedDictionaries`. Neue GUI-Atlanten benötigen
deshalb jeweils eine **neue PNG**, ein **neues Ressourcendictionary mit
BitmapImage/CroppedBitmap** und eine **erweiterte ApplicationResources-Kopie**.
Nur eine PNG-Datei in einem Modordner abzulegen wäre fachlich unzureichend.

Aus den nativen Dictionaries und dem übrigen XAML-Ordner wurden **4.084
eindeutige x:Key-Namen** für die Kollisionsprüfung gelesen.
Die Datei `FRONT_Story.xaml` enthält am Dateiende zusätzliche Nicht-XML-Bytes.
Die Schlüsselprüfung behandelt sie vorsichtig lesend, ohne dieses Original zu
reparieren, abzuschneiden oder an die Ausgabe anzuhängen. Die vier echten
Atlas-Dictionaries und `ApplicationResources.xaml` müssen dagegen selbst
gültige XML-Dokumente sein.

Wichtig: Der historische SHCDE **GM-Sprite-AtlasBuilder** erzeugt
`Override/Atlas/<Gruppe>/atlas.json` für vorhandene GM-Gruppen. Er ist
kein Ersatz für das hier benötigte **Noesis-GUI-Ressourcendictionary**.

## 2. Geprüfter SH1→SHCDE-Zielarbeitsstand

**Programm:** `tools/ui_sh1_to_shcde_bridge.py`

**GUI:** `tools/ui_sh1_to_shcde_gui.py`, im Suite-Reiter *Oberfläche* über
**„7. SH1 → Crusader DE übertragen ...“**.

Der Konverter erstellt aus einem SH1-HUD-Arbeitsstand und einem unveränderten
SHCDE-UI-Export zunächst einen **Zuordnungsplan ohne automatische Freigaben**.
Gleiche Schlüssel können Kandidaten sein; gleiche Schlüssel oder Pixelmaße
gelten **nicht** als Beweis identischer HUD-Funktion oder Spielzustände.
Größendifferenzen erfordern eine ausdrückliche Regel `contain` oder `stretch`;
`exact` lässt nur gleiche Maße zu. Manuell gewählte Aliase müssen ausdrücklich
als solche freigegeben werden.

Für die echte Kandidatenerstellung werden SHA-geprüfte Originaldateien beider
Spiele und die originale SHCDE-Noesis-XAML-Geometrie benötigt. Aus der Quelle
werden nur freigegebene Einzelbilder übernommen. Das Zielprojekt bleibt ein
gewöhnlicher Crusader-Export mit **unverändertem index.json** und den originalen
Crusader-Zielrechtecken. Nicht freigegebene PNG-Dateien bleiben **bytegenau**
unverändert.

**Echter Offline-Beleg:** 1 SH1-HUD-Grafik testweise übernommen, alle übrigen
**2.221 von 2.222** SHCDE-Bilder unberührt. Alle drei nativen SH1-Dictionaries,
drei ursprünglichen SH1-Atlanten, die Original-SHCDE-XAML und
2.222 SHCDE-Pixelrechtecke wurden nachgeprüft.
Die unveränderte Original-SHCDE-Atlasprüfung akzeptierte die Kandidatenkopie
mit genau **einer** bearbeiteten Crop-PNG. Die Freigabe dieses Beispiels war
bewusst nur **simuliert**; daraus folgt keine semantische Ingame-Freigabe.

Die vollständige UI-MasterAtlas-Referenz enthält 2.222 SHCDE-Zielslots.
Damit gibt es 1.242 namensgleiche Zuordnungsvorschläge (849 maßgleich,
393 maßverschieden). Das darf **nicht** mit der früheren auf 354 HUD-Crops
begrenzten Vergleichsmenge (290 gleiche Namen) vermischt werden.

### Beispielbefehle

```powershell
.venv\Scripts\python.exe tools\ui_sh1_to_shcde_bridge.py plan --sh1 work\sh1-hud-editierbar --shcde work\ui --out work\sh1-shcde-plan.json
.venv\Scripts\python.exe tools\ui_sh1_to_shcde_bridge.py approve --plan work\sh1-shcde-plan.json --source-key "UI-HUD 007" --target-key "UI-HUD 007" --fit exact --state-note "Funktion und Bildzustand manuell geprüft"
.venv\Scripts\python.exe tools\ui_sh1_to_shcde_bridge.py apply --plan work\sh1-shcde-plan.json --out work\shcde-hud-weiterbearbeitbar --source-game "D:\Pfad\SH1DE_Data\globalgamemanagers.assets" --target-game "D:\Pfad\SHCDE_Data\globalgamemanagers.assets" --target-xaml "D:\Pfad\BepInEx\plugins\000shcdese\Override\Assets\GUI\Sprites"
.venv\Scripts\python.exe tools\ui_sh1_to_shcde_bridge.py verify --from work\shcde-hud-weiterbearbeitbar
```

Danach im Reiter *Oberfläche* über **Bilder laden** den neuen Crusader-Arbeitsstand
öffnen. Der zusätzliche Knopf **„Crusader-PNG extern bearbeiten“** öffnet das
gewählte Einzelbild im System-PNG-Editor. Pixelmaße und Ressourcennamen bleiben
unverändert. Danach **Bilder laden**, **Alles prüfen** und den bestehenden
`ui_atlas.py check/import`-Weg verwenden. Ein Import in Produktionsprofile
braucht wie bisher eine gesonderte Entscheidung.

Der übliche SHCDE-Quell-/Buildvalidator verlangt eine tatsächlich vorhandene
`config/installations.local.toml`. Dieser lokale Konfigurationsnachweis war im
geprüften öffentlichen Projekt noch **nicht** eingerichtet. Die isolierten
nativen Testabläufe verwenden deshalb gesondert gepinnte lokale QA-Quellen.
Für einen produktiven Build muss die eigene SHCDE-Installation erst korrekt
konfiguriert und versionsgebunden geprüft werden.

## 3. Neue zusätzliche Noesis-UI-Atlasblätter

**Programm:** `tools/ui_extra_atlas.py`

**GUI:** `tools/ui_extra_atlas_gui.py`, im Suite-Reiter *Oberfläche* über
**„8. Zusätzliche SHCDE-UI-Atlanten ...“**.

Der Benutzer legt eigene PNG-Dateien unter einem beliebigen **neuen**
`work/`-Unterordner ab. Die Dateinamen werden zu neuen,
namespaceten Noesis-Schlüsseln, beispielsweise
`OriginsExtra.CustomBanner`. Native Schlüssel dürfen weder ersetzt noch
versehentlich dupliziert werden. Der Builder packt PNGs ohne Rotation oder
Transparenz-Verlust in 256–4096 Pixel große RGBA-Atlanten (maximal 32 Seiten,
frei wählbarer Abstand von 2–64 Pixeln) und prüft **Pixel für Pixel** die
gesamten neuen PNG-Seiten einschließlich transparenter Zwischenräume.

### Beispielbefehle

```powershell
.venv\Scripts\python.exe tools\ui_extra_atlas.py build --source work\neue-ui-assets --gui-reference "D:\Pfad\BepInEx\plugins\000shcdese\Override\Assets\GUI" --target-game "D:\Pfad\SHCDE_Data\globalgamemanagers.assets" --out dist\neue-shcde-ui-atlanten --stem OriginsNewUi --namespace OriginsExtra --size 2048 --gutter 4
.venv\Scripts\python.exe tools\ui_extra_atlas.py verify --from dist\neue-shcde-ui-atlanten
```

Die getrennte Ausgabe enthält
`Override/Assets/GUI/Sprites/OriginsNewUi-001.png`,
`.../OriginsNewUi-001.xaml`, weitere Seiten, eine kopierte
`Override/Assets/GUI/XAMLResources/ApplicationResources.xaml` mit den neuen
Merge-Einträgen und ein SHA-256-Prüfmanifest. Bestehende Originalatlanten
werden **nicht** ersetzt. Änderungen an den neuen PNG-Eingaben werden durch
bewusstes Neu-Bauen mit `--replace` übernommen; niemals automatisch.

### Grenzen zusätzlicher UI-Ressourcen

Die neue Bildressource wird lediglich in Noesis bekannt gemacht. Neue
Schaltflächen, Mausereignisse, HUD-Zustände, ViewModel-Bindings, Animationen und
Spielaktionen entstehen dadurch nicht automatisch. Dafür sind kontrollierte
Änderungen an den tatsächlichen Noesis-Views nötig. Ob die verwendete
Script-Extender-/Noesis-Version **zusätzliche BitmapImage-PNGs zur Laufzeit
auch wirklich lädt**, ist durch die Originalstruktur allein noch nicht
bewiesen. Ohne isolierten Ingame-Test ist das Paket ein **Offline-Kandidat**,
keine produktive HUD-Erweiterung.

## 4. Wiederholte technische QA

- Zwei neu hinzugefügte Backendtestsuiten:
  `tests/sandbox/test_ui_sh1_to_shcde_bridge.py` und
  `tests/sandbox/test_ui_extra_atlas.py`.
  Im öffentlichen Entwicklungszweig **2 × 49 Tests bestanden**.
- Eigenständige Zusatzatlas-Regressionsserie: zunächst
  **3 × 32 Tests bestanden**; nach nativer Quellbindung
  zusätzliche negative Tests für fremde Unity-Dateien und
  manipulierte Herkunftsmetadaten: **34 Tests bestanden**.
- Echte neue Atlasblätter: 4 lokale SH1-PNGs auf 1 zusätzlicher Seite,
  6 lokale PNGs auf 2 zusätzlichen Seiten (5 + 1).
  Beide Fälle originalgetreu erzeugt, gespeichert und erneut geprüft.
- Native SHCDE-Bindung: die 4 Unity-UI-Texturen/PathIDs,
  Abmessungen, BC7-Format und Quellasset-SHA bestätigt.
- GUI-Smokeprüfungen unter Windows: neues Zusatzatlas-Fenster,
  reales lesendes Vorschaufenster, SH1→SHCDE-Mapping mit
  1.242 Vorschlägen und zwei echten Bildvorschauen, die
  zwei neuen Suite-Schaltflächen und der sichere externe
  Crusader-PNG-Bearbeitungsweg bestanden.
- Kein Schreibzugriff auf die Originalspielinstallationen oder
  auf vorhandene BC7-Produktionspakete; der neue Code und die
  Testausgaben liegen getrennt in neuen Projekt- und QA-Pfaden.

**Erforderlicher Schlussnachweis:** Erstmals geladene zusätzliche UI-Atlanten
im laufenden SHCDE, ggf. XAML-View-Einbindung, Spielzustände, Maus/Tastatur,
Transparenz/Shader und Rückbau; vor diesem Nachweis keine Releasefreigabe.

## 5. Abschließende Nachprüfung im aktuellen Arbeitsstand

Die zusammengefasste Backendregression vom 27.10.2026 ergab **86 bestandene
Tests** (Exitcode 0) über die neuen Bridge-/Zusatzatlasmodule und die
bestehenden SH1-HUD-/Unity-Module. Hinzu kamen **7 bestandene Tests** des
SH1-HUD-Studios. Die GUI wurde zusätzlich in getrennten echten
Windows-Tk-Prozessen geprüft:

- Der *Oberfläche*-Reiter startet die beiden neuen Editorfenster über
  den bestehenden Suite-Runner.
- Der importierte Crusader-Arbeitsstand mit 2.222 Elementen lässt sich
  laden; **Crusader-PNG extern bearbeiten** wählt die geprüfte Arbeitskopie.
- Der visuelle Zuordnungsdialog öffnet den realen Plan mit 1.242 Vorschlägen
  und lädt zwei originalgetreue Bildvorschauen.
- Manuelle Freigabe und anschließender Widerruf wurden auf einer **separaten
  QA-Kopie** des Plans geprüft; es entstand keine automatische Freigabe.
- Das Zusatzatlas-Fenster prüfte vier echte SH1-Originalkopien und meldete
  die benötigte Atlaszahl, ohne beim Vorschauen eine Ausgabedatei zu erzeugen.

Ein älterer automatisierter Windows-Tk-Test wurde in einer gemischten
Testkonfiguration wegen fehlgeschlagener Tcl-`init.tcl`-Initialisierung
übersprungen (2 bestanden, 1 übersprungen). Dies wird **nicht** als
abgeschlossene Gesamt-GUI-Regression ausgegeben. Die separaten echten
Fensterprüfungen waren erfolgreich.

Die abschließende SHA-256- und Integritätsprüfung hat beide unveränderten
Original-Unity-Dateien bestätigt und die neuen Noesis-Pakete mit
**1 Seite/4 Bildern** und **2 Seiten/6 Bildern** sowie die
native SH1→SHCDE-Kandidatenkopie erneut geöffnet. Protokoll:
`E:\Stronghold_1_GUI_Uebergabe_2026-10-26\QA_EXTRA_UI_ATLAS_20261027\FINAL_INTEGRITY_QA_20261027.json`.

**Nicht ausgeführt:** automatisierte Installation oder Laufzeittest im
Originalspiel. Keine Behauptung, dass zusätzliche PNG-`BitmapImage`-Ressourcen
ohne separate Noesis-/Script-Extender-Kompatibilitätsprüfung bereits
im Spiel sichtbar sind.
