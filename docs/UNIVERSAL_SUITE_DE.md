# SH1DE → SHCDE Universal-Suite 2.0 (Stronghold Europe / ORIGINS)

Grafik aus **Stronghold: Definitive Edition** nach **Stronghold Crusader: Definitive Edition** übertragen, ansehen, ändern, prüfen und als Mod ausliefern – in einer Oberfläche. Mit **read-only SHCDE Script Extender v2.14.3-Prüfung**; die historische C#-Runtime bleibt an SE 2.11.0 gebunden. Oberfläche **Deutsch / English** (umschaltbar). English: [README.en.md](README.en.md)

## Herunterladen

| Variante | Inhalt | Wie |
|---|---|---|
| **Nackte Suite** (Standard) | Quelltext, alle Grafikwerkzeuge, Profile, Oberfläche, Editor – etwa 11 MB | Zweig `main` → *Code* → *Download source code (zip)* |
| **Komplett (Windows)** | wie oben, zusätzlich fertiges Python 3.13 mit allen Paketen und der BC7-Encoder für SE-Atlanten – kein Einrichten nötig | Zweig `komplett` herunterladen |
| Frühere Versionen 1.x | Sprite Suite 1.0–1.1.3 mit Installern | Tag `v1.1.3` |

Spielgrafik wird **nicht** verteilt. Sie entsteht beim Einlesen und Bauen aus den eigenen, installierten Spielen.

## Einrichten

1. Ordner an einen **kurzen Pfad** entpacken, z. B. `D:\SU` (Unity legt tiefe Pfade an).
2. **`Suite starten.cmd`** doppelklicken.
   - *Komplett:* startet sofort.
   - *Nackte Suite:* beim ersten Start legt `setup.ps1` die Python-Umgebung aus einem installierten **Python 3.13** an (Pakete hashgeprüft aus `requirements-py313-win_amd64.lock`).
3. Für den BC7-Paketbau: **Unity 2021.3.45f2** über Unity Hub installieren (`unityhub://2021.3.45f2/88f88f591b2e`) und ein **.NET SDK ab 8** (empfohlen 10). Im Reiter *Einrichten* eintragen.
4. Den bereits vorhandenen **SHCDE Script Extender** über **Ziel & SE 2.11 → Script Extender 2.14.3 prüfen (nur lesen)** prüfen. v2.14.3 ist der jüngste bestätigte Release (19.10.2026). Kein automatisches Upgrade; der historische SE-2.11-Installer ist **kein** aktueller Updater und verhindert ein Downgrade. Die eigene Runtime erfordert einen getrennten ABI-/Ingame-Test.
5. *Einrichten* → Spielordner eintragen → *Pfade speichern* → *Spiele einlesen*.

Oben rechts: **Sprache / Language** und **Streng**. Die diagnostische Einrichtungskontrolle kann im Nachsichtmodus Warnungen melden, während *Streng* dort blockiert. Beim **Paketbau** gilt unabhängig davon: neue Bauvoraussetzungen müssen erfüllt sein, der Benutzer bestätigt den Start und die abschließende Buildvalidierung muss erfolgreich sein.

## Die Reiter

| Reiter | Zweck |
|---|---|
| **Einrichten** | Spiel- und Werkzeugpfade, Umgebung prüfen, Spiele einlesen |
| **Asset-Katalog** | alle Grafikgruppen thematisch geordnet (Gebäude, Burg, Einheiten, Tiere, Vegetation, Landschaft, Effekte …), je Frame vier Ansichten: ausgeliefert, Crusader, Stronghold 1, Arbeitskopie. Ersetzen (wird am Fußpunkt eingepasst), übernehmen, Richtungs-/Schadensblöcke kopieren, ganze Objekte umlenken, eigene Kategorien und neue Assets |
| **Diagnose & Reparatur** | prüft bekannte Fehlerklassen: Kantenanker (verschobene Zinnen), teilweise umgelenkte Kachelobjekte, Spender-Identität, Frame-Drift zwischen Spielständen, Leinwände, Bundle-Integrität |
| **Sandkasten** | **Vollständig eingebettetes Sandbox Studio im gleichen Sprite-Suite-Hauptfenster** (Tk/Qt unter Windows): echte Originalkarten-Enginegrafiken, interaktives Platzieren, Grafikkatalog-Verknüpfung, Pixeleditor, Live-Reload, Minikarte und Spiel-HUDs im vorhandenen Reiter. Kein separater GUI-Prozess. Details: `docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`. Vollständige Unity-Shader-/Gameplay-HUD-Parität bleibt offen. |
| **Editor & Austausch** | HTML-Sprite-Editor hin und zurück, SE-Atlas mit dem AtlasBuilder (`Override/Atlas`, PNG oder BC7-DDS), Gebäude als Ebenen (ORA) |
| **Ziel & SE 2.11** | mehrere Spielinstallationen, SE 2.11.0 und Mods installieren – jeweils mit Sicherung und Zurückspielen |
| **Sprites bearbeiten / Paket bauen** | Europa-BC7-Paket über Unity, inkrementeller Gruppencache |

## Drei Lieferwege

1. **Europa-BC7-Paket** – alle Gruppen als BC7-AssetBundles mit Laufzeit-DLL für SE 2.x.
2. **Einzelbilder** – `Override/Sprites/<name>.png`, überlagern den Atlas nach Namen.
3. **SE-Atlas** – `Override/Atlas/<gruppe>/atlas.dds|png`, lädt der Script Extender selbst.

## Grenzen

- Der Sandkasten nähert Teamfarbe (Rot-Kanal der Maske) und Wind an; Licht und Nebel fehlen.
- Bilder, die das Spiel nie anfragt, erscheinen nicht; neue Plätze brauchen Laufzeitcode.
- Die UI-Texturliste (128 Einträge) und der Laufzeitprüfer der UI-Spur (114) sind noch nicht vereinheitlicht; beim Validieren mit UI-BC7 gibt es daher eine Warnung.
- Protokollausgaben der Kommandozeilenwerkzeuge sind deutsch.

## Beigaben

- **AtlasBuilder** von Serpens66 (`extras/atlasbuilder`, mit Erlaubnis); BC7-Encoder `texconv` von Microsoft DirectXTex (im Zweig `komplett`, sonst über `fetch_texconv.py`).
- **Stronghold Sprite Editor** 1.0 (`extras/sprite-editor`, MIT), mit zweisprachiger Fassung.
- Atlasvertrag (`extras/atlas-contract`).


### Werkzeuge aus jeder Ansicht finden

**Strg+K** oder die Schaltfläche **Suche (Strg+K)** öffnet die
werkzeugübergreifende Suche: alle 14 Bereiche sowie beispielsweise
Zinnen-/Pivot-Vermessung, AtlasBuilder, Spiel-HUD, Animation und Pixelvergleich.
Das funktioniert auch mit Tastaturfokus in der eingebetteten Qt-Spielkarte.
Eingabe und Pfeiltasten wählen Ergebnisse, **Enter navigiert**, **Esc schließt**.
Die Suche verändert keine Dateien und startet keine Builds oder Installationen.
Deutsch/Englisch kann während des geöffneten Suchfensters umgestellt werden.

Weitere Einschränkungen und Testgrenzen: [Script Extender v2.14.3](SCRIPT_EXTENDER.md).
