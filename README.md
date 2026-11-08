# SpriteSuite 2.0 · Stronghold-Modding

Grafiken, Atlanten, HUDs, Noesis-Seiten, Gebäude, Animationen und eigene Mod-Dateien in einem gemeinsamen Projekt bearbeiten, prüfen und als Mod-ZIP ausgeben. Hinzu kommen Fachwerkzeuge für Script Extender, Lua, C# und SHCDE-Spielinhalte. Deutsch und Englisch sind in der Oberfläche umschaltbar. [English](README.en.md).

## Aktueller Stand

**RC5** entwickelt RC4 auf `main` weiter: Ein direkter **PNG-plus-XAML-Atlas-Arbeitsbereich** und ein **ChatGPT-Chat auf der Startseite** verbinden die vorhandenen Werkzeuge mit dem gemeinsamen Projekt. Pflichtbegründungen und künstliche Qualitätsfreigaben für den SH1-Transfer, KI-Kandidaten und eigene Schadens-/Tile-Entwürfe sind entfernt. Die heruntergeladene RC4 enthält diese Änderungen noch nicht. [RC5-Änderungen und Prüfung](docs/SPRITESUITE_RC5_20261108.md).

**Echte HP-/Feuer-Spielabnahme ist weiterhin offen.** Die isolierte SHCDE-QA-Kopie scheitert am Steam-Start mit `Application load error T:0000065432`. Erfolgreiche Datei-, GUI- und ZIP-Tests ersetzen keinen beobachteten Sprite-Wechsel im laufenden Spiel. Alte Entwicklungszweige und Worktrees bleiben bis zur vollständigen Abnahme erhalten. [Konsolidierung und Abnahme](docs/SPRITESUITE_RELEASE_KONSOLIDIERUNG_20261108.md).

## Herunterladen und starten

Für Windows-Nutzer ist das **Windows-Startpaket** richtig. Es enthält Python; beim ersten Start lädt es die übrigen Abhängigkeiten anhand festgelegter Hashes in seinen eigenen Ordner. Dafür ist Internet nötig. Eine separate Python-Installation wird nicht benötigt.

- [Vorabversion RC5 mit Windows-Startpaket, Quellcode und SHA-256-Dateien](https://github.com/strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite/releases/tag/v2.0.0-rc.5).
- **Source ZIP** enthält den Quellcode für Entwicklung und eigene Builds, keine fertig eingerichtete Python-Umgebung.
- Das vollständige Offline-Paket mit vorinstallierten Qt-/FMOD-Komponenten ist ein lokal geprüfter Entwicklungsbuild und kein öffentliches Release-Asset.

Das ZIP vollständig in einen eigenen kurzen Ordner wie `C:/SpriteSuite` entpacken und `SpriteSuite/Suite starten.cmd` öffnen. Ein kurzer Pfad vermeidet Probleme mit langen Qt-Dateinamen unter Windows. Spielgrafiken und Spiele werden nicht mitgeliefert.

## UI-MasterAtlas bearbeiten

Ab RC5: **Strg+K → UI-Atlas · PNG + XAML**. Alternativ **Projekt & Dateien → Mehr → UI-Atlas (PNG + XAML)…** oder **Oberfläche → PNG + XAML öffnen…**.

1. Atlas-PNG und passende XAML wählen. Die XAML liefert Sprite-Namen und Rechtecke. Bei mehreren Bildblättern gegebenenfalls den `BitmapImage`-Key angeben.
2. **PNG + XAML als Arbeitsstand öffnen**, Sprite-Eintrag suchen und auswählen. Ein zweiter Atlas kann als Quelle dienen.
3. **Auswahl ersetzen**: `exact` verlangt die Zielgröße; `contain` und `stretch` passen die Quelle ausdrücklich an. Zielrechtecke bleiben erhalten.
4. Rückgängig, Wiederholen und Original wiederherstellen sind dauerhaft verfügbar. Originaldateien bleiben erhalten.
5. **Ins Mod-Projekt übernehmen** schreibt PNG und unveränderte XAML nach `Override/Assets/GUI/Sprites/` des aktiven Projekts. Anschließend prüfen, sichern und Mod-ZIP bauen. Der Export installiert nichts ins Spiel.

Der neue Arbeitsbereich unterstützt unter anderem 8192 × 8192 Pixel große MasterAtlanten. Für die Tk-Anzeige werden nur ausgewählte Ausschnitte verwendet. Zusätzliche Bildblätter derselben XAML müssen separat verfügbar sein; dazu erscheinen Warnungen. [Atlas-Anleitung](docs/UI_ATLAS_PNG_XAML.md).

Crusader-DE-XAML liegt gewöhnlich unter `<Spiel>/BepInEx/plugins/000shcdese/Override/Assets/GUI/Sprites/UI-MasterAtlas.xaml`. Originalpixel können in `globalgamemanagers.assets` liegen; dafür bleibt der Spieleexport unter **Oberfläche** verfügbar. XAML aus einer Mod wie `Stronghold1Textures` muss zu deren Atlas passen. Eine Atlas-XAML ist eine Ressourcenliste und keine HUD-Layoutdatei.

Das ältere Fenster **Stronghold 1 HUD → Crusader DE** ordnet bereits exportierte SH1-DE-Elemente Crusader-Zielen zu. Für SH1 Classic gelten die gesonderten GM1-Werkzeuge. [Aktuelle Workflows](docs/WORKFLOWS.md).

In diesem Transferfenster ab RC5 die gewünschten Zeilen mehrfach auswählen und direkt übertragen. Eine Pflichtbegründung, Mindesttextlänge oder Einzelfreigabe gibt es dort nicht mehr. Originalquellen können zusätzlich geprüft werden; für die normale Übertragung sind installierte Spiele nicht erforderlich.

## ChatGPT auf der Startseite

Der Chat bietet Eingabe, lokalen Gesprächsverlauf sowie Optionen für Modell, Denkstufe und Arbeitsmodus. Modelle werden aus der tatsächlich angemeldeten Codex-Sitzung geladen. Die Anmeldung erfolgt über den offiziellen lokalen Codex-Client mit ChatGPT-Konto, ohne API-Schlüssel. Google-Anmeldung erfolgt gegebenenfalls im offiziellen Anmeldefenster. Verfügbarkeit und Verbrauch richten sich nach dem Konto und seinem Codex-Kontingent.

- **Fragen**: Projekt und angebotene Werkzeuge lesend untersuchen.
- **Aufträge**: standardmäßig alle nativen Werkzeuge einschließlich eigener Programmierung verwenden.
- **Programmieren**: dieselben Werkzeuge gezielt für Projektcode verwenden, Dateien mit Änderungsprüfung schreiben und Revisionen aufbewahren. Lokale Python-Ausführung ist in den Arbeitsmodi eingeschaltet und kann in den Optionen abgeschaltet werden.

Ausgeführter Python-Code besitzt die Rechte des Suite-Prozesses; es besteht keine Betriebssystem-Sandbox. Der Assistent kann seine Ausführungsoption nicht selbst einschalten. Stop verwendet die vorhandenen Abbruchpfade. Der lokale Verlauf ist kein synchronisierter ChatGPT-Webverlauf. [Chat-Bedienung und Grenzen](docs/KI_CHAT_STARTSEITE.md).

Für Sprite- und Schadensvarianten bleibt die KI-Werkstatt angebunden: Original auswählen, Anzahl und Art beschreiben und passende Prompts an Codex übergeben. Ein erfolgreicher Generierungsauftrag beweist keine passende SpriteSlot-/Gameplay-Zuordnung im Spiel.

## Projekt, Layout und weitere Werkzeuge

**Projekt & Dateien** verbindet Import, Pixel-/Textbearbeitung, Layout, Prüfung und Mod-ZIP. Eigene DLLs, Lua, Konfigurationen, Audio und andere Mod-Assets können unverändert importiert werden. Archive ungeprüfter Runtime-Dateien bleiben als Entwurf kenntlich. Originale, Revisionen und bearbeitbare Metadaten gehören zur Projektsicherung; Wiederherstellen erstellt ein neues Projekt.

**Strg+K** findet Arbeitsbereiche und Fachwerkzeuge. Ein Suchtreffer öffnet den Arbeitsbereich oder das Formular; die Aktion wird dort ausgelöst. Scrollbare Arbeitsflächen und eigene Werkzeugfenster halten überlaufende Bereiche erreichbar. Der Startseiten-Chat kann eingeklappt werden.

Native Spiel-Plugins benötigen passende API-/ABI-Nachweise und echte Spieltests. Neue Spiel- oder Script-Extender-Versionen sind kein pauschales Modding-Verbot. Ein erfolgreich gebautes ZIP ist keine allgemeine Ingame-Freigabe.

## Dokumentation und Entwicklung

- [Aktuelle Kurzanleitung](docs/KURZANLEITUNG.md) und [aktuelle Workflows](docs/WORKFLOWS.md).
- [PNG-plus-XAML-Atlas](docs/UI_ATLAS_PNG_XAML.md) und [Startseiten-Chat](docs/KI_CHAT_STARTSEITE.md).
- [Projekte sichern und übertragen](docs/PROJEKTARCHIVE_2026-10-29.md).
- [Historische README bis RC4](docs/README_HISTORISCH_BIS_RC4_DE.md) und [historische Workflows](docs/WORKFLOWS_HISTORISCH_BIS_20261107.md). Release-, Versions- und Menüangaben dort beschreiben den damaligen Stand.

Das illustrierte PDF vom 4. November bleibt ein historisches Teilhandbuch. Für neue Funktionen gelten die aktuellen Anleitungen oben.

Quellstart im Repository: `python tools/suite_start.py`. Abhängigkeiten stehen in den Requirements-Dateien; der Windows-Startpaketbau verwendet einen Hash-Lock. CI prüft Kern- und Fachwerkzeuge auf Python 3.13 und 3.14. Native Spieltests benötigen eine gültige Spiel-/Steam-Umgebung.
