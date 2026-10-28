# SH1DE → SHCDE Universal-Suite 2.0 (Stronghold Europe / ORIGINS)

Grafik aus **Stronghold: Definitive Edition** nach **Stronghold Crusader: Definitive Edition** übertragen, ansehen, ändern, prüfen und als Mod ausliefern – in einer Oberfläche. Statische HUD-/Sprite-Pakete entstehen **ohne feste SE-Version und ohne eigene C#-DLL**; für optionale C#-Plugins gelten getrennte ABI-Schutzprüfungen. Oberfläche **Deutsch / English** (umschaltbar). English: [README.en.md](README.en.md)

## Herunterladen

| Variante | Inhalt | Wie |
|---|---|---|
| **Nackte Suite** (Standard) | Quelltext, alle Grafikwerkzeuge, Profile, Oberfläche, Editor – etwa 11 MB | Zweig `main` → *Code* → *Download source code (zip)* |
| **Komplett (Windows)** | wie oben, zusätzlich fertiges Python 3.13 mit allen Paketen und der BC7-Encoder für SE-Atlanten – kein Einrichten nötig | Zweig `komplett` herunterladen |
| Frühere Versionen 1.x | Sprite Suite 1.0–1.1.3 mit Installern | Tag `v1.1.3` |

Spielgrafik wird **nicht** verteilt. Sie entsteht beim Einlesen und Bauen aus den eigenen, installierten Spielen.
**Spiel- und Script-Extender-Versionsnummern sind keine pauschale Sperre:**
Unbekannte Versionen können inventarisiert, als Ziel registriert und
mit passendem Mapping bearbeitet werden. Native ABI-Integritätsprüfungen
bleiben unabhängig von der Versionsnummer bestehen.
[Details zur versionsoffenen Verarbeitung](docs/VERSIONSOFFENE_SH1DE_SHCDE_SE_2026-10-28.md).

## Stronghold 1 DE: HUD im Sprite Suite Editor bearbeiten

Dieser Zweig erweitert **Oberfläche** um einen eigenen Stronghold-1-HUD-Editor: 1.391 original benannte und pixelgenau editierbare UI-Ausschnitte, sichere Größen-/Quellprüfungen, drei rückbaubare PNG-Atlanten und eine **isoliert erzeugte Unity-Kandidatendatei** mit den bearbeiteten Bildern. Die originale Spielinstallation wird nicht verändert. Die Spielgrafiken bleiben auf dem jeweiligen Rechner und werden mit `tools/ui_sh1_hud.py export` aus der eigenen Installation gewonnen.

**[Anleitung: Stronghold 1 HUD bearbeiten](docs/STRONGHOLD1_HUD_SPRITESUITE.md)** — inklusive GUI, Original-XAML, Pixelbearbeitung und Atlas-Rückbau. **[Geprüfte Unity-Kopie als isolierter Kandidat](docs/STRONGHOLD1_UNITY_HUD_KANDIDAT.md)** — mit BC7-Blockänderungen, Byte- und SHA-256-Prüfungen sowie ausdrücklichen Grenzen des noch nicht im Spiel getesteten Einbaus.

## Einrichten

1. Ordner an einen **kurzen Pfad** entpacken, z. B. `D:\SU` (Unity legt tiefe Pfade an).
2. **`Suite starten.cmd`** doppelklicken.
   - *Komplett:* startet sofort.
   - *Nackte Suite:* beim ersten Start legt `setup.ps1` die Python-Umgebung aus einem installierten **Python 3.13** an (Pakete hashgeprüft aus `requirements-py313-win_amd64.lock`).
3. Für den BC7-Paketbau: **Unity 2021.3.45f2** über Unity Hub installieren (`unityhub://2021.3.45f2/88f88f591b2e`) und ein **.NET SDK ab 8** (empfohlen 10). Im Reiter *Einrichten* eintragen.
4. Den **vorhandenen Script Extender** beibehalten. Unter **Editor & Austausch** eigene Grafiken als **DLL-freies Asset-Modpaket** bauen. Kein separater Versionschecker, kein automatischer SE-Wechsel. Für Gameplay-C#-Mods bleiben API-/ABI-Schutzprüfungen bestehen.
5. *Einrichten* → Spielordner eintragen → *Pfade speichern* → *Spiele einlesen*.

Oben rechts: **Sprache / Language** und **Streng**. Bei der **diagnostischen Einrichtungskontrolle** werden Abweichungen im Nachsichtmodus weiterhin protokolliert; *Streng* blockiert dort. **Beim tatsächlichen Paketbau** sind fehlende Voraussetzungen und eine fehlgeschlagene Nachvalidierung immer blockierend – ein fehlerhaftes Paket wird nicht als erfolgreicher Bau gemeldet.

**Strg+K – Bereich/Werkzeug suchen:** Von überall schnell zum Katalog, zum Sandkasten-Spiel-HUD, zum AtlasBuilder, zum Pivot-Messwerkzeug oder zur Pixelvergleichsansicht springen; auch direkt aus der eingebetteten Qt-Spielkarte. Die Suche startet **keine** Builds oder Installationen. Enter öffnet die gewählte Ansicht, Esc schließt die Suche. Die Suche funktioniert in Deutsch und Englisch.

**Bedienung der gesamten Oberfläche:** Die acht wichtigsten Bereiche bleiben als
kurze Reiter sichtbar. Über **Bereich öffnen** kann jeder der 14 Bereiche,
auch ein historisches Werkzeug, direkt aufgerufen werden. **Alle Reiter**
zeigt bei Bedarf die vollständige Reiterleiste; **Reiter bündeln** stellt
die kompakte Ansicht wieder her. Das Protokoll ist über **Protokoll anzeigen**
jederzeit erreichbar und nimmt bei geschlossenem Zustand keine Arbeitsfläche
weg. Lange Aktionslisten sind in thematische Menüs sortiert, und die
Editier- und Buildformulare können gescrollt werden.
[Genauere Bedienungs- und Layoutabnahme](docs/WHOLE_SUITE_USABILITY_2026-10-13.md).
[Erweiterte UI-Prüfung: Deutsch/Englisch, Tastatur, Zugänglichkeit und 56 Ansichtsproben](docs/SPRITESUITE_UI_GESAMTPRUEFUNG_2026-10-13.md).

## Die Reiter

| Reiter | Zweck |
|---|---|
| **Einrichten** | Spiel- und Werkzeugpfade, Umgebung prüfen, Spiele einlesen |
| **Asset-Katalog** | alle Grafikgruppen thematisch geordnet (Gebäude, Burg, Einheiten, Tiere, Vegetation, Landschaft, Effekte …), je Frame vier Ansichten: ausgeliefert, Crusader, Stronghold 1, Arbeitskopie. Ersetzen (wird am Fußpunkt eingepasst), übernehmen, Richtungs-/Schadensblöcke kopieren, ganze Objekte umlenken, eigene Kategorien und neue Assets |
| **Diagnose & Reparatur** | prüft bekannte Fehlerklassen: Kantenanker (verschobene Zinnen), teilweise umgelenkte Kachelobjekte, Spender-Identität, Frame-Drift zwischen Spielständen, Leinwände, Bundle-Integrität |
| **Sandkasten** | **Vollständig eingebettetes Sandbox Studio im gleichen Sprite-Suite-Hauptfenster** (Tk/Qt unter Windows): echte Originalkarten-Enginegrafiken, interaktives Platzieren, Grafikkatalog-Verknüpfung, Pixeleditor, Live-Reload, Minikarte und Spiel-HUDs im vorhandenen Reiter. Kein separater GUI-Prozess. Details: `docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`. Vollständige Unity-Shader-/Gameplay-HUD-Parität bleibt offen. |
| **Editor & Austausch** | HTML-Sprite-Editor hin und zurück, SE-Atlas mit dem AtlasBuilder (`Override/Atlas`, PNG oder BC7-DDS), Gebäude als Ebenen (ORA) |
| **Ziele & Mods** | Spielziele verwalten und eigene Mods installieren – jeweils mit Sicherung und Zurückspielen |
| **Sprites bearbeiten / Paket bauen** | Europa-BC7-Paket über Unity, inkrementeller Gruppencache |

**Integrierter Sandkasten:** Der Reiter bietet **Karte öffnen**,
**Palette**, **Inspector**, **Fokus** und **Layout zurück**.
Unter **Weitere Werkzeuge** liegen Animation / Frames, Spiel-HUD,
Kartenordner wählen, Pixelvergleich und der Katalogsprung. Die
integrierte Qt-Werkzeugauswahl erreicht jeden Inspector und jedes HUD,
während die Spielkarte den Großteil der Fläche erhält. Bei Windows-DPI-
Skalierung stimmt die physische Qt-Kindfenstergröße mit dem Tk-Host überein.
Nach der Auswahl bleibt das Originalkartenverzeichnis
lokal in `config/sandbox-maps.local.json` gespeichert. Die
Original-Spiel-Dateien werden dabei nicht verändert. Qualitätstests:
`docs/SPRITESUITE_QUALITAETSPRUEFUNG_2026-10-11.md`.

**Neue Werkstatt-Erweiterungen:** Unter **Editor & Austausch** lassen sich Zinnenlineal-Pivots am Originalsprite überprüfen und einzelne Vorschläge ausdrücklich freigeben oder ablehnen (nur revisionsgebundene JSON-Protokolle, keine Atlasänderung). **Diagnose & Reparatur** bietet außerdem eine read-only QA-Altinventur und den **projektweiten Release-Abgleich**: alle ausgelieferten BC7-Dateien mit SHA-256 prüfen, Profil/Index/Manifest abgleichen und optional ein ausdrücklich gewähltes Pivot-Freigabeprotokoll gegenprüfen – ohne Installation. Details: `docs/HISTORISCHE_WERKZEUGE_INTEGRATION.md` und `docs/RELEASE_PREFLIGHT.md`.

**Neu: Pivot → BC7-Stufenentwurf.** Die Diagnose kann jetzt eine bewusst
freigegebene Zinnenlineal-Messung nochmals gegen Original-Messdatei, PNG,
Spriteindex und den gesamten aktuellen BC7-Produktionsbau verifizieren.
Der zugehörige tatsächliche, SHA-256-gebundene BC7-Atlas wird über
den exakt passenden Gruppen-Cache geprüft: Pivots, die darin bereits
richtig sind, erzeugen **keinen** weiteren Neubauvorschlag.
Im Pivot-Prüffenster steht dafür **Pivot im BC7-Atlas prüfen** bereit.
Nur ein nicht anwendbarer, quellgebundener Änderungsplan wird ausgegeben;
native Geometrie- und Cache-Proofs sowie das Bundle müssten für die
tatsächliche Umsetzung gesondert neu erstellt und geprüft werden.
Anleitung: [Pivot/BC7-Stufenplan](docs/PIVOT_BC7_STUFENPLAN.md).

**BC7-V2-Testprojekt (neu):** Unter **Diagnose & Reparatur →
Synthetische BC7-Pivot-Probe vorbereiten** lassen sich zwei
isolierte Unity-Eingabeprojekte mit echten V2-Builderprüfungen
erstellen: ein veränderter Pivot und eine unveränderte Kontrollgruppe.
Pixel bleiben identisch; Metadaten und Gruppencache-Keys werden geprüft.
**Es findet kein Unity-Encoderlauf statt.** Die exakt benötigte
Unity-Version 2021.3.45f2 ist derzeit nicht am gepinnten Werkzeugpfad
vorhanden. Details: [BC7-Projektprobe](docs/PIVOT_BC7_REHEARSAL.md).

**Echter nativer Zinnen-Beweis (neu):** Unter **Diagnose & Reparatur →
Nativen Zinnen-Geometriebeweis prüfen** vergleicht die Suite alle
106 veröffentlichten anim_castle-Frames mit dem ursprünglichen
SH1DE-/Crusader-Mapping und rekonstruiert **alle vier eingefrorenen
Geometrie-/Herkunftsnachweise SHA-identisch**. 95 SH1DE-Frames
und 11 Crusader-Fallbacks sind bestätigt, einschließlich des
bereits richtigen anim_castle 002. Kein Spiel- oder Atlas-Patch.
Anleitung: [Nativer BC7-Herkunftsbeweis](docs/PIVOT_NATIVE_PROVENANCE.md).

**Einrichtung ohne unnötige Sperren:** Unity- und .NET-Pfade können im Reiter
**Einrichten** auch ohne bereits konfigurierte Spielordner gespeichert
werden. Alte Werkzeugpfade bleiben bei Teiländerungen erhalten;
Spielpfadänderungen verlangen eine Bestätigung und erhalten Sicherungen.
Ungültige neue Einstellungen ersetzen keine funktionierende Konfiguration.
**Einrichtungsstatus** zeigt fehlende Voraussetzungen rein lesend an.
Beschädigtes Werkzeug-JSON unterbricht andere Suite-Funktionen nicht
mehr und lässt sich nach Sicherung ausdrücklich reparieren. Auch
fehlerhafte Spielpfad-TOML-Dateien verursachen beim Öffnen des
Einrichtungsreiters keinen Absturz mehr, sondern einen Warnhinweis.
[Einrichtung und schrittweises Speichern](docs/EINRICHTEN.md).

**Bauvoraussetzungen vor dem Paketbau (neu):** Unter **Paket bauen →
Bauvoraussetzungen prüfen** werden das gewählte Profil, Originalspielpfade,
Mapping, der exakt festgeschriebene Unity-Editor, das .NET-SDK und eine
möglicherweise schon vorhandene Paketausgabe getrennt geprüft.
Fehlende Voraussetzungen erscheinen ausdrücklich als **Blockaden**
mit konkreten Einrichtungsschritten. Der Check startet keinen
Builder oder Installer und ist **keine Releasefreigabe**.
Das .NET SDK kann auch aus portablen Installationen, DOTNET_ROOT
oder dem Systemverzeichnis erkannt werden; ein ungeeigneter
PATH-Eintrag führt nicht unnötig zur Sperre. Der echte Builder
prüft die SDK-Version vor dem Build nochmals durch Ausführen.
Der eigentliche Button **Paket bauen (mit Vorprüfung)** führt denselben
Check frisch aus, verlangt bei erfüllten Voraussetzungen eine ausdrückliche
Startbestätigung (Standard **Nein**) und meldet eine fehlerhafte
Build-Nachvalidierung als Misserfolg – auch im Nachsichtmodus.
[Anleitung zur Bau-Bereitschaft](docs/BUILD_READINESS.md).

**Bauabschluss im Hauptfenster:** Nach einem in der Suite gestarteten
Paketbau werden Build-/Validator-Exitcode und anschließend der unabhängige
SHA-256-Release-Preflight getrennt ausgewertet. Die Statuszeile und
**Bauergebnis anzeigen** zeigen Fehler, Warnungen, geprüfte Dateien,
den Vergleich zum vorherigen Manifest und die stets noch
**ausstehende Ingame-Abnahme** – ohne automatische Installation.
Siehe [Paketbau-Abschluss](docs/BUILD_COMPLETION.md).

**Dauerhafter Bauverlauf:** Unter **Paket bauen → Bauverlauf anzeigen**
bleiben echte, aus der Suite gestartete BC7-Bauversuche über Neustarts
nachvollziehbar. Der lokale SHA-256-verkettete Verlauf unterscheidet
abgeschlossene, fehlgeschlagene und **nicht bestätigte** Starts und
ist ausdrücklich keine neue Release- oder Ingamefreigabe.
[Verlauf und Sicherheitsgrenzen](docs/BUILD_HISTORY.md).

## Drei Lieferwege

1. **Europa-BC7-Paket** – alle Gruppen als BC7-AssetBundles mit Laufzeit-DLL für SE 2.x.
2. **Einzelbilder** – `Override/Sprites/<name>.png`, überlagern den Atlas nach Namen.
3. **SE-Atlas** – `Override/Atlas/<gruppe>/atlas.dds|png`, lädt der Script Extender selbst.

## Grenzen

- Die historische Tkinter-Sandbox nähert Teamfarben, Wind und Licht lediglich
  an. Das neue Sandbox Studio nutzt bereits echte Spriteframes und originale
  Tilemap-Schatten-/Farbregeln; Wind-, Wasser- und Foliage-Shader sowie
  Nebel sind aber noch nicht vollständig spielidentisch.
- Bilder, die das Spiel nie anfragt, erscheinen nicht; neue Plätze brauchen Laufzeitcode.
- Die UI-Texturliste (128 Einträge) und der Laufzeitprüfer der UI-Spur (114) sind noch nicht vereinheitlicht; beim Validieren mit UI-BC7 gibt es daher eine Warnung.
- Protokollausgaben der Kommandozeilenwerkzeuge sind deutsch.

## Beigaben

- **AtlasBuilder** von Serpens66 (`extras/atlasbuilder`, mit Erlaubnis); BC7-Encoder `texconv` von Microsoft DirectXTex (im Zweig `komplett`, sonst über `fetch_texconv.py`).
- **Stronghold Sprite Editor** 1.0 (`extras/sprite-editor`, MIT), mit zweisprachiger Fassung.
- Atlasvertrag (`extras/atlas-contract`).

Weitere Einschränkungen und Testgrenzen: [Script Extender und Asset-Mods](docs/SCRIPT_EXTENDER.md).

## Stronghold Origins: vollständiger HUD-/GUI-Grafikkatalog

Der Arbeitsbereich **ORIGINS Grafiken** umfasst alle **13.562** bekannten Dateien aus dem versionierten [Stronghold-Europe-Grafikdaten-Projekt](https://gitlab.com/strongholdoriginsmod/stronghold-europe-grafikdaten), darunter **4.086 HUD-/GUI-Elemente**, Noesis-XAML, das Blau/Silber-HUD und die GUI-Atlanten. Über **Suite starten.cmd → ORIGINS Grafiken** lassen sich alle Dateinamen suchen, filtern und per Git-/LFS-SHA-256 prüfen. Berechtigte Mitwirkende wählen ihren lokalen Git-LFS-Klon und erzeugen daraus getrennte Bearbeitungskopien mit Herkunftsnachweis. Das originale Stronghold-1-HUD bleibt zusätzlich im eigenen **SH1 HUD-Studio** erreichbar.

Die großen, teilweise spielabgeleiteten Binärdaten verbleiben im zugangsverwalteten Grafikdatenprojekt. Im Sprite-Suite-Quellcode liegen der vollständige Katalog mit den Original-Git-IDs und die Verarbeitung. [Einrichtung und Grenzen](docs/ORIGINS_GRAFIKDATEN_KATALOG.md).
