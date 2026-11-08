# SHCDE-Fachwerkbank: konsolidierter Quellstand vom 08.11.2026

Die Fachwerkbank ergänzt SpriteSuite um 16 Arbeitsbereiche für API-Suche,
Native-Baselines, Mod-Komposition, Gebäude, AIV, AIC, Einheiten, Wirtschaft,
Szenarien, Gelände, HUD, Objektinspektion, Audio, Multiplayer-Verträge,
Pfadprofilierung und QA. Sie ist im vorhandenen Werkzeugkatalog erreichbar.
`tools/shcde_workbench.py --self-test` prüft den Offline-Katalog. Ohne Argumente
öffnet derselbe Einstieg die Tk-Oberfläche. Das Wechseln eines Arbeitsbereichs
führt keine Werkzeuge aus. Die Ausführen-Schaltfläche ruft den gewählten
vorhandenen CLI-Einstieg auf und zeigt dessen Ausgabe und Exitcode an.
Der gesamte Formularbereich besitzt horizontale und vertikale Scrollleisten.
Mausrad, Umschalt-Mausrad und Tastaturfokus können untere oder seitlich
liegende Eingaben erreichen. Die Fenstergröße passt sich beim Öffnen dem
Bildschirm an. Die Layoutprüfung deckt 1020×680 und 820×560 mit jeweils
125 und 150 Prozent vergrößerten Standardschriften ab.

Die übernommenen 17 Quelldateien stammen aus dem lokalen Quellbaum
`SpriteSuite_SHCDE_Expansion_20261108` mit Git-Basis
`00276ec8d8fe5647f5341cb84f3cdcb398919042`. Sie waren dort nicht versioniert.
Die begleitende Datei `SPRITESUITE_SHCDE_EXPANSION_SOURCES_20261108.json`
zeichnet für jede Datei den ursprünglichen und den konsolidierten SHA-256 auf.
Proprietäre Spiele-DLLs, Spiele-Assets und private Laufzeitprotokolle werden
dabei nicht übernommen.

## Bestehende Projekte und neue Spielsystemdaten

Die zentrale Asset-Pipeline bleibt für bearbeitbare Grafik-, HUD- und
Moddateien zuständig. Das Fachprojekt `SpriteSuite-Project.json` speichert
zusätzliche Einstellungen und 16 Bereiche mit frei editierbaren JSON-Werten.
Sein `Payload/` enthält ausdrücklich importierte Moddateien und `info.json`.
Es akzeptiert eigene Dateiformate und Versionsbezeichnungen ohne API-Konto
oder fest eingebauten Spielversionsfilter.

Mit **Suite-Projekt verbinden** oder dem folgenden CLI-Aufruf verweist ein
Fachprojekt direkt auf die bearbeitbaren Dateien des Hauptprojekts. Diese
Verknüpfung erstellt keine zweite Asset-Kopie. Der Export liest jeweils die
aktuelle Hauptprojektdatei. Die bestehenden Regeln für Hauptprojekte unter
`SpriteSuite/work/` und deren verknüpfungsfreie Pfade gelten weiter.

```powershell
.\.venv\Scripts\python.exe tools\shcde_mod_project.py link-suite `
  --project work\mein-fachprojekt --suite-project work\mein-assetprojekt
.\.venv\Scripts\python.exe tools\shcde_mod_project.py inspect `
  --project work\mein-fachprojekt
.\.venv\Scripts\python.exe tools\shcde_mod_project.py export `
  --project work\mein-fachprojekt --output work\exports\mein-mod.zip
```

Der Composer nimmt Ordner und ZIP-Dateien entgegen. Konflikte können mit
`first`, `last` oder `error` aufgelöst werden. Er verweigert mehrdeutige
Windows-Pfade und verknüpfte Einträge. Während des Schreibens kontrolliert er
Größe und SHA-256 jedes Eingabemitglieds gegen den Plan. Er veröffentlicht
erst das vollständige ZIP und ersetzt keine vorhandene Ausgabedatei. Das
Prüfkommando kontrolliert CRC, Inventar und Inhalts-SHA. Eigene, bereits
geprüfte Composer-ZIPs können erneut kombiniert werden. Ihr Beleg wird als
SHA-Verweis im neuen Beleg verzeichnet.

## Native Funktionen und Beleggrenzen

Die API-Suche reflektiert die ausgewählten lokal installierten Assemblies.
Der gemeinsame Managed-Builder kompiliert die optionalen Inspektor- und
Gameplay-Plugins gegen diese konkreten Referenzen. Die Referenz-SHA werden
im Ergebnis ausgegeben. Der reine Build liest Spielebibliotheken und schreibt
nur in den gewählten Compiler-Ausgabeordner.

```powershell
.\.venv\Scripts\python.exe tools\shcde_game_inspector.py build `
  --game "D:\Meine separate QA-Spielkopie" --output work\builds\inspector
.\.venv\Scripts\python.exe tools\shcde_gameplay_rules.py build `
  --game "D:\Meine separate QA-Spielkopie" --output work\builds\gameplay
```

Eine Installation ist ein eigener ausdrücklich gewählter Vorgang. Beide
Installer prüfen die Pluginpfade und schreiben ein Dateiinventar. Beim
Entfernen werden ausschließlich unveränderte, inventarisierte Dateien
gelöscht. Diese Konsolidierung hat keine Plugins installiert und kein Spiel
gestartet.

Der Inspektor beobachtet Gebäude-/Einheiten-IDs, globale Identität,
Gesundheit und Zusatzwerte. Seine Protokollauswertung behauptet keine
Spriteänderung oder Gameplay-Schreiboperation. Das Gameplay-Plugin setzt
konfigurierte Standardgesundheit und Einheitenreichweite über die echten
Script-Extender-Methoden. Seine Standardkonfiguration ist auskommentiert.
Compilerfolg belegt die Kompatibilität der verwendeten Signaturen mit den
gewählten Assemblies. Ein Spielstart, Kartenwechsel, echte Wiederherstellung
und Sichtprüfung dieser neuen Plugins sind damit noch nicht nachgewiesen.

Szenariographen werden zu Callback-Lua-Modulen übersetzt. Die Ausführung
spielabhängiger Aktionen benötigt den passenden Laufzeit-Kontext.
Multiplayer-Einstellungen beschreiben APIShared-Rollen und erhalten fremde
Namensräume. Sie implementieren keine eigene Netzwerksynchronisierung.
Der Pfadprofiler wertet ausschließlich vorhandene gemessene Zeitwerte aus.
Er installiert keine nativen Hooks und erfindet keine Zeitmessungen.

Die bestehenden HP-/Feuer-Prüfer bleiben für echte Zustands- und
Tilemap-Belege zuständig. Die Fachwerkbank wertet einen erfolgreichen Build
oder ein korrektes Archiv nicht als visuelle Ingame-Abnahme.

## Überprüfung

`tests/shcde/test_expansion.py` prüft die Fachwerkzeuge einschließlich
Konfliktverhalten, Dateiintegrität, Teilfehlern beim Export, erneuter
ZIP-Komposition, gemeinsam bearbeitbaren Projektdateien, Pfadprüfungen,
Registry- und Policy-Anbindung sowie Navigation durch alle 16 GUI-Bereiche.
Die eigentlichen Spiel- und Mehrspielerprüfungen benötigen separat
bereitgestellte Laufzeitbelege. Die QA-Ausgabe weist diese Grenzen explizit
aus.
