# Modding Studio

Das Modding Studio bietet zwölf Arbeitsbereiche für SHCDE-Entwürfe. Sie verwenden ein gemeinsames JSON-Projekt, eine Quellenprüfung und denselben Export. Die Oberfläche startet über „Modding Studio starten.cmd“ oder über die Werkzeugübersicht der Suite.

| Arbeitsbereich | Bearbeitung und Ausgabe |
| --- | --- |
| SDK und Kompatibilität | Durchsuchbarer APIShared-Katalog mit Quellen, Thread- und Versionshinweisen |
| Missionen und Trigger | JSON-Ereignisse und Aktionen, deterministische Tick-Simulation, Lua-Datenmodul |
| KI-Burgen | Gebäuderaster, Drehung, Baureihenfolge, Überlappungsprüfung und SVG |
| Noesis und HUD | XAML-Struktur, Ressourcenreferenzen und Vergleich mit den UI-Quellen der Suite |
| Balancing | Ganzzahlige Kosten, Gewichtungen und Materialgrenzen |
| Karten und Trails | Quellidentität, DE-AIVJSON-Prüfung und Adapter für separat ausgewählte Serp-Werkzeuge |
| Eigene Lords | Metadaten, DE-AIVJSON und referenzierte Bild- und Sprachdateien |
| Einheiten und Wege | Gewichtete A*-Wege auf einem frei bearbeitbaren Testraster |
| Audio und Effekte | PCM16-WAV-Metadaten, Prüfsummen, Ereignisse und Cue-Referenzen |
| Savegames und Multiplayer | Versionierte JSON-Datensätze, Erhalt unbekannter Recordfelder und Peer-Vergleich |
| Modpacks und Workshop | Plugin-GUIDs, Abhängigkeiten, Paketmetadaten und Konflikthinweise |
| Native Engine Lab | RVA-Bereiche, Überlappungen, Bildprüfsummen und lokale Quellsuche |

## Projekte und Revisionen

Ein Projektordner enthält „project.json“ und seine Quelldateien. Die Oberfläche bearbeitet die jeweilige Modulsektion und speichert Änderungen als neue Revision unter „revisions“. Die bisherige Datei behält ihren Inhalt.

~~~powershell
python tools/modding_studio.py modules
python tools/modding_studio.py catalog --query route
python tools/modding_studio.py new work/studios/meinprojekt --id meinprojekt --title "Mein SHCDE Mod"
python tools/modding_studio.py check work/studios/meinprojekt
python tools/modding_studio.py gui work/studios/meinprojekt
~~~

Der Katalog dokumentiert einen geprüften Quellenstand von APIShared 0.27.0 und Script Extender 2.14.0. Andere deklarierte Versionen können bearbeitet und exportiert werden. Die Analyse kennzeichnet Versionsabweichungen mit REVIEW und benennt die jeweils benötigte API-Fähigkeit. Für die Laufzeitprüfung sind die tatsächlich installierten Bibliotheken und deren Verträge maßgeblich.

## Export und Vorschau

~~~powershell
python tools/modding_studio.py export work/studios/meinprojekt --export-id entwurf_001
~~~

Die Ausgabe entsteht in einem neuen Ordner unter „exports“. Sie umfasst das Projekt, zwölf Modulberichte, einen HTML-Überblick, ein Burg-SVG, den Lua-Aktionsplan und ein C#-Projekt mit Diagnoseinitialisierung. Ein Manifest dokumentiert die SHA-256-Werte der Dateien. Struktur- und Quellfehler werden vor der Ausgabe geprüft.

Das C#-Gerüst verwendet den im Katalog dokumentierten APIShared-Vertrag. Es referenziert die lokal bereitgestellten Bibliotheken über GameDir und Private=false. Ein eigener Gameplay-Consumer kann auf diesem Gerüst aufgebaut werden. Die Tick- und Wegsimulationen führen das im Projekt beschriebene Modell aus. Für die Spielabnahme kommen die jeweiligen Ereignis-, Karten-, Reparatur-, Netzwerk- und Save-Vorgänge hinzu.

Ein synthetisches Beispiel mit XAML, Pluginmetadaten und einem kurzen Testton liegt unter „examples/modding-studio“.

~~~powershell
python tools/modding_studio.py check examples/modding-studio
python tools/modding_studio.py simulate examples/modding-studio --events events.json
python tools/modding_studio.py audit-suite-ui
~~~

## Externe Werkzeuge

Die Serp-Adapter nehmen eine ausführbare Datei, eine Quelldatei und deren erwartete SHA-256-Werte entgegen. Unterstützt sind die dokumentierten Prüf- und Exportkommandos von MapParser, AIVParser und TrailEditor. Exporte erhalten einen eigenen Ausgabeordner. Der Prozess verwendet ein isoliertes Arbeitsverzeichnis und ein Zeitlimit.

Die lokale Quellsuche kann außerdem PublicApi.txt, JSONL-Verzeichnisse und einen ausdrücklich gewählten nativen DLL-Stand lesen.

~~~powershell
python tools/modding_studio.py api-search --api-root X:/APIShared --query SimulationTickEvents
python tools/modding_studio.py native-search --baseline-root X:/Native-Baseline --query market
python tools/modding_studio.py native-image --dll X:/Spiel/CrusaderDE.dll
~~~

## Prüflauf

~~~powershell
python -m pytest -q -p no:cacheprovider tests/sandbox/test_modding_studio_core.py tests/sandbox/test_modding_studio_assets.py tests/sandbox/test_modding_studio_runtime.py tests/sandbox/test_modding_studio_integration.py tests/sandbox/test_modding_studio_gui.py
~~~

Die Suite prüft Projekt-Roundtrips, Dateiintegrität, zwölf Analysen, den Beispielablauf und die Tk-Oberfläche mit synthetischen Daten. Das Prüfprojekt unter „tests/modding_studio_csharp_syntax“ kompiliert die erzeugte C#-Quelle gegen isolierte Typ-Mocks.


## Gemeinsames Projekt und gespeicherte Revisionen

Der sichtbare Mehr-Eintrag „Modding Studio“ im gemeinsamen Projekt öffnet ein projektgebundenes Fenster. Seine Entwürfe werden bei Projektsicherung und Projektwechsel mit geprüft. Bei abgelehntem Wechsel bleiben das Fenster und sein Entwurf erhalten. Ein gespeicherter Entwurf erzeugt eine unveränderliche Revision und einen atomaren `current.json`-Verweis mit relativem Pfad und vollständiger SHA-256. Beim Wiederöffnen wird diese Revision geprüft und geladen. Ein beschädigter Verweis stoppt das Öffnen mit einer Fehlermeldung.

Beim direkten Schließen eines Studio-Fensters kann der Entwurf gespeichert, verworfen oder das Schließen abgebrochen werden. Die eigenständige CLI-/GUI-Nutzung behält ihre Projektwahl. Das in die Suite eingebundene Fenster verwendet das bereits aktive gemeinsame Projekt. Reguläre Studio-Exporte und Revisionen sind im bearbeitbaren Projektarchiv enthalten.
