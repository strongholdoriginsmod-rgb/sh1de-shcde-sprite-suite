# Einrichten

Kurzer lokaler Arbeitsordner **`SpriteSuite`** unter Windows x64.
Unity erzeugt tiefe Unterverzeichnisse; ein langer Checkout-Pfad kann an der
Windows-Pfadgrenze scheitern. Ausreichend freier Platz für dekodierte Texturen, Unity-Arbeitsprojekte
und Bundle-Cache. Die Build-Schritte lesen Quell- und Zielspiel. Das fertige
Modpaket wird bei Bedarf von Hand in den Spielordner kopiert.

| Bestandteil | Unterstützter Stand |
|---|---|
| SH1DE | Installierte Ressourcen; keine feste Versionsliste |
| SHCDE | Installierte Ressourcen und Bibliotheken; keine feste Patchversion |
| SHCDE-SE | Vorhandene kompatible Installation; **2.10.0** ist der geprüfte Referenzstand |
| Unity Editor | **2021.3.45f2**, Revision **88f88f591b2e**, Windows-Buildmodul |
| .NET SDK | Stabil **ab 8.0.100**, 10.x empfohlen; Runtime-Ziel **net481** |
| Python | Installer und aktueller Hash-Lock: **3.13.15 x64**; alter 3.14-Lock als Referenz |
| Python-Pakete | UnityPy **1.25.3**, Pillow **12.3.0**; weitere Pakete im Lock |

Ein anderer Editor kann andere BC7-Bytes erzeugen. Die Suite prüft deshalb
Version und Revision über die Produktversion von `Unity.exe`. Ein abweichender
EXE-Hash allein sperrt den Editor nicht; der tatsächliche Hash fließt in die
Cache-Identität ein. Encodercode und Qualitätsregeln bleiben erhalten.

`global.json` wählt mit `latestMajor` das höchste installierte stabile SDK
ab 8.0.100. Vorschauversionen werden nicht automatisch verwendet. [SDK herunterladen](https://dotnet.microsoft.com/download/dotnet/10.0).
Das SDK wird auch in portablen `work/toolchains/dotnet-*`-Verzeichnissen,
über `DOTNET_ROOT` und in üblichen Systemverzeichnissen gefunden, wenn
`PATH` fehlt oder dort nur eine Runtime liegt. Ein expliziter SDK-Pfad
ist weiterhin möglich; der echte Runtime-Builder prüft die Version vor
dem Build durch Ausführen von `dotnet --version`. Die Runtime wird über
den Python-Builder kompiliert, der alle Referenzen und den generierten
Vertrag übergibt; ein nacktes `dotnet build` der Runtime ist nicht der Bauweg.

## Installation

Den Release-Installer starten und einen kurzen lokalen Ordner wählen
(höchstens 65 Zeichen). Er benötigt keine
Administratorrechte. Python und sämtliche Python-Pakete werden offline
installiert und geprüft. Start anschließend über **Sprite Suite** im Startmenü.
Das Setup protokolliert seine Prüfung nach `work/setup.log`.

Im Reiter **Einrichten** Quellspiel, Zielspiel, `Unity.exe` und den
.NET-SDK-Ordner wählen und **Pfade speichern**. **Werkzeugpfade können
unabhängig von den Spielordnern gespeichert werden**, auch wenn die Spiele
noch nicht installiert bzw. ausgewählt sind. Es kann entweder der Spielroot
oder sein kanonischer `*_Data`-Ordner ausgewählt werden. Ebenso lassen
sich `Unity.exe`, ihr Editor-Ordner oder der Unity-Versionsordner wählen.
Fehlt bei der ersten Einrichtung noch einer der Spielpfade, fragt die
Suite, ob sie zunächst nur die Werkzeuge speichern soll.

Bestehende Einstellungen werden beim Speichern **ergänzt statt geleert**.
Eine echte Änderung zuvor gespeicherter Spielpfade muss im Hauptfenster
ausdrücklich bestätigt werden; alte Konfigurationsbytes werden unter
`config/*.local.*.bak-*` gesichert. Unveränderte Angaben bleiben unberührt;
ungültige neue Kombinationen werden **vor** dem Ersetzen geprüft.
Spiel-, Cache- und Produktionspaketdateien werden dadurch nicht verändert.

**Einrichtungsstatus** gibt eine **rein lesende Diagnose** zu gespeicherten
Spielpfaden, Unity, SDK und lokalen Werkzeug-Einstellungen aus – auch dann,
wenn Spiele oder einzelne Werkzeuge fehlen. Beschädigte oder veraltete
Werkzeugkonfigurationen erzeugen Warnungen statt die übrige Oberfläche
oder gewöhnliche CLI-Werkzeuge zu blockieren. Auch eine syntaktisch oder
strukturell ungültige **Spielpfad-TOML** verhindert nicht mehr das Öffnen
des Einrichtungsreiters: Die Felder bleiben bis zur manuellen Korrektur
leer und eine Warnung erklärt das Problem. Die ursprüngliche Datei
wird weder beim Lesen noch beim bloßen Öffnen verändert. Der Check startet weder
Unity noch einen Installer und ersetzt nicht die spätere BC7-Bauprüfung.

Eine passende Unity-Installation im Standardordner von Unity Hub wird
automatisch gefunden. **Einrichtung prüfen** zeigt die tieferen
Werkzeug- und Spielvoraussetzungen. **Spiele einlesen** erstellt Inventar
und Zuordnung in einem Schritt.

Der bereits im Zielspiel installierte Script Extender wird verwendet. Die Suite
prüft beim Runtime-Bau die benötigten Schnittstellen und baut gegen diese
Bibliotheken. Setup und Build ersetzen weder den Extender noch seine
Konfiguration. Fehlt eine benötigte Schnittstelle, meldet der Build sie.
Details stehen unter [Script Extender](SCRIPT_EXTENDER.md).
Der Installer liefert weder Unity Editor noch den .NET SDK oder Spieldateien.
Die benötigten Werkzeuge und eine kompatible SE-Installation müssen lokal
vorhanden sein; Unity muss für den unbeaufsichtigten Bundlebau ordnungsgemäß
lizenziert sein.

Die Deinstallation entfernt Programmdateien und die erzeugte `.venv`.
Eigene Pfade, Arbeitsstände, Cache und gebaute Mods bleiben im Suite-Ordner.
Eine Installation des Mods im Spiel und ein früher über die Suite ausgeführter
SE-Wechsel werden dadurch nicht zurückgenommen. Für einen früheren SE-Wechsel
steht die [Rücknahme aus der vorhandenen Sicherung](SCRIPT_EXTENDER.md#früheren-se-wechsel-zurücknehmen) separat bereit.

Alternativ aus dem Quellcheckout, mit vorhandenem Python 3.13 x64:

```powershell
./setup.ps1
# Offline mit dem zum Lock passenden Wheel-Verzeichnis:
./setup.ps1 -Wheelhouse '<Wheel-Verzeichnis>'

./.venv/Scripts/python.exe suite.py configure `
  --source '<SH1DE-Spielordner>' `
  --target '<SHCDE-Spielordner>' `
  --unity '<Unity-Editorordner>/Editor/Unity.exe' `
  --dotnet '<SDK-Ordner>/dotnet.exe'

./.venv/Scripts/python.exe suite.py doctor
./.venv/Scripts/python.exe suite.py verify
```

Die Pfade können auch **schrittweise** eingerichtet werden:

```powershell
# Nur das SDK speichern – noch ohne Spielinstallation:
./.venv/Scripts/python.exe suite.py configure --dotnet '<SDK-Ordner>'

# Später beide Spiele auswählen:
./.venv/Scripts/python.exe suite.py configure --source '<SH1DE-Spielordner>' --target '<SHCDE-Spielordner>'

# Nur einen vorhandenen Crusader-Spielpfad bewusst ändern:
./.venv/Scripts/python.exe suite.py configure --target '<Neuer-SHCDE-Ordner>' --replace
```

Ein erneuter Aufruf ohne `--unity` oder `--dotnet` **löscht keine
vorherigen Werkzeugpfade**. Bleiben beide Spielpfade gleich, wird die
bestehende Datei nicht neu geschrieben. Geänderte Spielpfade benötigen
`--replace`; vorher wird die bestehende Datei gesichert.

Bei einer beschädigten `config/toolchains.local.json` bleiben normale
Ansichten und lesende Werkzeuge benutzbar. Der portable Starter überschreibt
diese Datei **nicht automatisch**. Die Suite zeigt die fehlerhafte Stelle
und fragt beim erneuten Speichern eines Werkzeugpfads nach einer
**ausdrücklichen Reparaturzustimmung**, standardmäßig **Nein**.
Die alten Bytes werden vor der Reparatur gesichert.

```powershell
# Nur Bericht anzeigen (verändert keine Konfiguration oder Spiele):
./.venv/Scripts/python.exe tools/qa_suite_local_setup.py
./.venv/Scripts/python.exe tools/qa_suite_local_setup.py --json

# Explizite gesicherte Reparatur bei kaputtem Werkzeug-JSON:
./.venv/Scripts/python.exe suite.py configure --dotnet '<SDK-Ordner>' --repair-toolchain
```

Ein vorhandenes, aber nicht mehr erreichbares portables SDK darf der Starter
mit einem gültigen SDK ersetzen; dabei erhält er eine Sicherung der bisherigen
Konfiguration. Ungültige JSON-Strukturen werden dagegen nie still repariert.

`doctor` prüft Pfade und Struktur, `verify` erfasst die Identität der Spieleingaben.
Die Laufzeitabhängigkeiten werden zusätzlich beim Build geprüft.
`config/*.local.*` enthält die eigenen Pfade und bleibt außerhalb von Git.

Für direkte Werkzeugaufrufe ohne `suite.py`:

```powershell
$env:STRONGHOLD_EUROPE_UNITY_EDITOR = '<Unity-Editorordner>/Editor/Unity.exe'
./.venv/Scripts/python.exe tools/sprites.py --help
```

Die GUI startet mit `suite.py gui` oder dem installierten `SpriteSuite.exe`.
Die drei Ansichten heißen **Einrichten**, **Sprites bearbeiten** und
**Paket bauen**. Unter **Paket bauen** stehen **Kleines Testpaket**
(`sprite-suite-canary-bc7-v2`) und **Alle Spielsprites**
(`sprite-suite-world-bc7-v2`) bereit. **Paket bauen** baut und prüft das Ergebnis.
**Ausgabe öffnen** zeigt das fertige Paket, **Spiel-Modordner öffnen** das
Zielverzeichnis. Bei geschlossenem Spiel den Ausgabeordner `StrongholdEuropeDE`
nach `BepInEx/plugins` kopieren. Einen vorhandenen gleichnamigen Ordner zuvor
außerhalb von `plugins` aufbewahren, damit keine alten Dateien im Mod verbleiben.

Das unter **Paket bauen** gewählte Profil ist auch das Ziel der Profileinträge
aus **Sprites bearbeiten**. Importierte Einzelbilder bleiben PNGs; sie ersetzen
bei entsprechender Auswahl einzelne Frames aus den weiterhin BC7-komprimierten
Atlanten. Der genaue Importweg steht unter [Abläufe](WORKFLOWS.md#2-bestehende-sprites-bearbeiten).

**Erweiterte Werkzeuge anzeigen** blendet die ursprünglichen Zusatzseiten
und den Werkzeugkatalog ein. Die historische Seite **Bauen und Installieren**,
die Gruppenverwaltung und `pin_digests.py` verwenden weiterhin
`europe-production` beziehungsweise `europe-production.json`. Auch die separat
gestartete alte Werkstatt und CLI-Werkzeuge ohne `--profile` behalten diesen
Standard.

## Vollständige Produktionsprofile

Die beiden Sprite-Suite-Profile beziehen ihre Pixel direkt aus den Spielen.
Die historischen Gesamtprofile erwarten zusätzlich die konkreten Ablagen unter
`assets/sprites`, `assets/ui`, `work/hintergruende` und die UI-Quellen, die
`config/ui-textures-bc7-v1.json` nennt. Diese Projektgrafiken sind keine
Python-Abhängigkeiten und lassen sich nicht durch `pip install` ersetzen.
Jede Eingabe bleibt an ihren Hash gebunden; fehlende Eingaben werden abgelehnt.

Zur Wiederverwendung eigener Grafik werden die vorhandenen Importwege benutzt.
Nach einem Spielupdate Inventar und Mapping erneuern und das Modpaket neu bauen.
Die Suite verwendet dabei die aktuellen Asset-IDs und Bibliotheken.

## Projekteingaben importieren

Die Gesamtprofile benötigen zusätzlich ein passendes ProjectInputs-Archiv
mit den exakten referenzierten Grafiken. Dieses gehört nicht zum Setup. Unter
**Erweiterte Werkzeuge anzeigen → Alle Werkzeuge → project_inputs.py → install** das Archiv wählen. Ohne
`--write` wird nur geprüft; mit `--write` werden fehlende Dateien importiert.
Abweichende vorhandene Dateien werden abgelehnt und bleiben unverändert.

```powershell
python suite.py tool project_inputs.py install --archive '<Projektpaket.zip>'
python suite.py tool project_inputs.py install --archive '<Projektpaket.zip>' --write
```

Der Befehl `pack --source-project '<Originalprojekt>' --output '<Neues-Archiv.zip>'`
sammelt dieselben profilgebundenen Eingaben aus einer bestehenden Projektablage.
Das Archiv enthält relative Zielpfade und ein SHA-256-Inhaltsmanifest.

## Spielupdates und SDK-Auswahl

**Spiele einlesen** erfasst die installierten Ressourcen und ihre Zuordnung.
Unterschiede zu früheren Referenzständen verhindern den Build nicht. Der
CLI-Aufruf `suite.py verify` schreibt einen Bericht nach
`work/reports/build-compatibility.json`; er enthält keine Installationspfade.

Im .NET-Feld sind der Installationsordner, `dotnet.exe` und der Unterordner
`sdk/10.0.401` erlaubt. Die Suite ermittelt daraus automatisch den Hostordner.
