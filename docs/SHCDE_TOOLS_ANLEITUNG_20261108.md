# SpriteSuite – integrierte Arbeitsabläufe (08.11.2026)

Die Konsolidierung liegt ausschließlich in der isolierten Quellkopie E:\SpriteSuite_ToolIntegration_20261108. Es handelt sich um eine Entwicklungs-/Abnahmekopie, nicht um ein bereits ins Spiel installiertes Paket.

## Einstieg: Ein Projekt statt mehrere Programme

1. Die vorhandene Suite aus dieser isolierten Quellkopie starten (nur nach Prüfung der persönlichen Spiel- und Python-Pfade; keine Installation durch diese Dokumentation).
2. Im Hauptfenster „Projekt & Dateien“ ein Projekt neu anlegen oder vorhandenes Projekt auswählen. Originalgrafiken und Quelldateien bleiben vom modifizierten Arbeitsprojekt getrennt.
3. Im Projekt Quelle/Original auswählen, Bild und XAML bearbeiten, anschließend „Änderungen prüfen“ und das Mod-ZIP mit Byte-/SHA-Prüfung erzeugen.
4. Pixel-/Layout-/Noesis-Editor verwenden denselben Projektzustand. Ein editorinternes Speichern beeinflusst noch keine Spielinstallation.
5. Mit Strg+K einen bestehenden Editor, die Sandbox, Diagnosen oder ein kuratiertes Fachwerkzeug suchen. Ein Treffer öffnet lediglich den vorhandenen Reiter bzw. das Expertenformular.
6. Im Reiter „Alle Werkzeuge“ die Liste nach Programmname, Aufgabe oder deutschen/englischen Fachbegriffen filtern. Bei der Auswahl wird das Tool noch nicht gestartet.
7. „CLI-Hilfe anzeigen“ liest sichtbare Parseroptionen aus dem Python-Quelltext, ohne das Programm auszuführen. Bei dynamisch erzeugten Argumenten die Fach-Dokumentation ergänzend prüfen.
8. Erst „Ausführen“ startet ein Werkzeug. Bei möglichen Änderungen, Spielinstallationen oder unbekannten Seiteneffekten erscheint eine gesonderte Bestätigung mit Standard „Nein“. Die Fach-Sicherungen des Tool-Backends bleiben zusätzlich bestehen.

## Zwei bewusst getrennte Mod-Paketverträge

**Statischer Export:** Alle PNG-, DDS-, XAML- und geprüften Medien-/Sprachdateien unter den bekannten Resource-Pfaden müssen durch die Format- und Strukturprüfungen. Ein statisches Paket nimmt keine beliebigen DLLs auf.

**Freies Mod-Projekt:** Im gemeinsamen Projektworkflow dürfen ausdrücklich gewählte Dateien unter eigenen gültigen Unterordnern als unveränderte Bytes archiviert werden, darunter native DLL-, Lua- und Audiodateien. Liegt ein selbst verfasstes info.json vor, wird es bytegetreu beibehalten. Ohne ein solches Manifest dürfen native Dateien nur als ausdrücklich gekennzeichnetes Offline-ENTWURFS-ZIP ausgegeben werden. Es gibt dadurch weder Spiel-ABI- noch Installations-/Ingame-Freigabe.

**„Speichern unter“:** Das Gesamtpaket wird zuerst innerhalb des geschützten work/-Ordners erzeugt und vollständig geprüft. Danach darf ausschließlich die freigegebene ZIP in ein vom Benutzer ausgewähltes, neues Ziel geschrieben werden. Vorhandene Dateien, Links/Junctions, BepInEx- und *_Data-Ziele werden nicht ersetzt. Projekt- und Spiel-Originale bleiben unverändert.

## Historische Werkzeugmatrix (nur lesen)

Der Quellvergleich verwendet Datei-Byteumfang, SHA-256, Namen und eine kuratierte Risiko-Kategorie. Byteidentisch heißt nicht funktionsgleich oder für das aktuell installierte Spiel kompatibel.

Im Projektwurzelordner beispielsweise:

    E:\SpriteSuite\.venv\Scripts\python.exe tools\suite_tool_inventory.py --root . --compare "E:\SS QA" --compare "E:\GS\StrongholdEurope-Projekt" --compare "E:\GS\StrongholdOrigins-Projekt" --recursive --format markdown

Die Option --recursive liest eigene direkte und verschachtelte tools/-Quellen, folgt keinen Symbolic Links/Junctions und überspringt generierte sowie fremde Bibliotheken. Dieser Aufruf importiert und startet keines der untersuchten Programme. Für den vollen achtfachen Vergleich den im work/-Ordner vorhandenen run_real_inventory.py verwenden; die JSON- und Markdownberichte liegen unter work\reports\tool-integration.

## Bleibende Grenzen

- Keine automatische Übernahme der alten Programmdateien aus SS QA, SU_base oder Stronghold Origins in eine aktuelle Runtime- oder SE-Installation.
- Keine automatische Native-RVA-/Script-Extender-Versionserkennung allein aus Dateinamen oder alten PASS-Protokollen.
- Kein automatisches Löschen früherer Releases, QA-Verzeichnisse oder Arbeitszweige.
- Ein erfolgreiches ZIP-Gate bedeutet nur geprüfte Dateiintegrität. Einheitentest, Sandbox-Vorschau, native Plugin-Kompatibilität, vollständiger Spielstart und echter Ingame-Modtest sind unterschiedliche Abnahmen.
- Der historische 96-Wurzeln-Scan umfasst nicht sämtliche externen Medien oder jede jemals existierende Binärversion. Für diese wäre eine weitere gesonderte Inventur notwendig.

## Reproduzierbarkeit

- Stand und Architektur: docs\SHCDE_TOOLS_ANALYSE_20261108.md
- Detaillierte Umsetzung: docs\SHCDE_TOOLS_IMPLEMENTIERUNGSPLAN_20261108.md
- Abnahme, geänderte Dateien und Einschränkungen: docs\SHCDE_TOOLS_ABNAHME_20261108.md
- Referenzalterstände: unverändert an ihren bisherigen E:-Orten, ohne automatisches Installieren oder Zurücksetzen
