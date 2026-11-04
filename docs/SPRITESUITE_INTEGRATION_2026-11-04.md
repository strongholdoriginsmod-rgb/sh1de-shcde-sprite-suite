# SpriteSuite – integrierte Anwendung / Quellstand, 4. November 2026

**Status:** lokaler Integrationskandidat, keine freigegebene Stable-Version.
**Arbeitszweig:** `integration/spritesuite-unified-20261104`.
**Basis:** `45789b335ea342d107c1b87efbb76db4b9a11b5a`.
**Anwendungsversion:** unverändert `2.0.0`.

## Welche Entwicklungsstände tatsächlich zusammengeführt wurden

1. **Aktueller GitHub-/Origins-Entwicklungsstand:** Basis-Commit mit dem
   Native-Noesis-/BepInEx-Bridge-Kandidaten, UI-Texturvertrag, 26 Demos,
   Spezialwerkzeugen, Portable-Builder und den bisherigen QA-Sperren.
2. **Offener gemeinsamer Mod-Projektworkflow:** alle 21 Quell-, Test- und
   Dokumentationsänderungen aus dem separaten lokalen Worktree;
   Projekt öffnen → Bilder/XAML bearbeiten → prüfen → überprüftes Mod-ZIP.
   Inbegriffen: kürzere portable Import-Baselines, Projektarchiv-Roundtrip,
   Noesis-Revisionshistorie, sichere Wechsel mit offenen Editoren,
   Prüfsummen und Schutz bei fehlerhaften Exportbelegen.
3. **Steam-Kompatibilität:** zehn bisher nicht versionierte Tool-/Test-/
   Dokumentationsdateien aus dem älteren Steam-Worktree. Die Diagnostik
   ist über die gemeinsame Projektansicht und die ältere Startseite
   erreichbar, läuft im Hintergrund und ist ausschließlich lesend.
   Nicht verfügbare Build-/ABI-/Script-Extender-Nachweise werden
   ausdrücklich nicht als Erfolg bewertet.
4. **Frühere Portable-Stände:** die Quellcommits `849ca1f`,
   `60e012d`, `a5ec598` und `1967129` sind Vorfahren des
   Basis-Commits und bereits im Quellstand enthalten. Ältere
   Portable-ZIPs werden *nicht* über eine neuere Version kopiert.

## Abgleich der älteren GitLab-Entwicklung

Die ältere, stark geänderte GitLab-Arbeitskopie wurde separat und
rein lesend mit diesem Stand abgeglichen:
- 213 abweichende/unversionierte Dateieinträge wurden inventarisiert.
- 169 davon haben bereits denselben SHA-256-Inhalt im integrierten Stand.
- 24 unterscheiden sich (vor allem ältere Test-/Dokumentations- und
  Werkzeugfassungen).
- 20 fehlende Gegenstücke sind temporäre `.hud-synch-editor-*.tmp`
  Dateien und gehören nicht in eine auslieferbare Anwendung.

Die 24 älteren Alternativen wurden nicht blind über neuere Dateien
gelegt. Mehrere alte Tests würden eine andere Sicherheits-/Freigabepolitik
als der aktuelle Stand voraussetzen. Diese Unterschiede müssen fachlich
geprüft werden, bevor eine Verhaltensänderung zulässig wäre.
Die frühere GitLab-Kopie und die lokale Steam-QA bleiben unverändert.
Das einzelne ältere HUD-Layout-UI-Experiment wird nicht über die
aktuelle, inzwischen anders organisierte Oberfläche kopiert.

## Aktueller regulärer Bedienablauf

1. `Suite starten.cmd` aus dem *vollständig entpackten* Windows-Portable-Ordner
   öffnen. Die Portablaufzeit enthält CPython 3.13 und GUI-Abhängigkeiten.
2. Unter **Mein Mod-Projekt** ein Projekt anlegen/öffnen.
3. Eigene PNGs und private Noesis-XAML-Quellen importieren; bearbeiten und
   Revisions- beziehungsweise Projekt-ZIP-Sicherungen erstellen.
4. `Änderungen & XAML prüfen` ausführen, dann
   `Geprüftes Mod-ZIP bauen`. SHA-/Manifest-Nachweise geben nur
   Dateiintegrität an, nicht Ingame-Funktion.
5. Bei Bedarf `Steam-Version prüfen` verwenden. Diese Diagnose
   liest den lokalen Steam-Build und Meldungen zur Zuordnung.
   Sie installiert weder BepInEx noch Mods oder andere DLLs.
6. Originalspielinstallationen bleiben gesondert; die Anwendung
   darf sie nicht automatisch durch ältere Mappings überschreiben.

## Abnahme- und Sicherheitsgrenzen

- Ein grüner automatisierter Test ist **kein** sichtbarer Spiel-/Noesis-
  Nachweis; statische Overlays sind keine belegten dynamischen Bindings.
- Eine saisonale Atlas-Routenkennung ohne vollständigen Restore ist
  kein echter reversibler Grafik-Hot-Swap.
- Ein lokal gebautes Windows-Portable-ZIP ist nicht gleich einer auf einem
  zweiten unabhängigen Windows-Rechner geprüften Verteilung.
- Hardware-DPI, NVDA/Narrator, lange GUI-/Runtime-Läufe, originale
  Game-/Unity-Assets und native Plugin-ABIs benötigen manuelle QA.
- Ohne erneuten Nachweis keine Spielinstallation, kein Merge nach `main`,
  kein Release und keine behauptete Veröffentlichung auf GitHub.
- Private Mapping-Kandidaten, Benutzerbilder, Spielbibliotheken und
  Arbeitsordner werden nicht in den Quellstand integriert.

## Tests und lokale Nachweise

- Steam-Regressionen (Python 3.13): 34 bestanden, 1 private QA
  übersprungen.
- Gemeinsamer Projektworkflow einschließlich Steam-GUI-Anbindung
  (Python 3.13): 75 bestanden, 2 versionsbezogene Skips.
- Der vollständige CI-ähnliche Pytest-Lauf und die frische Portable-
  Paketprüfung sind als gesonderte Prüf-Gates auszuführen.

**Keine öffentliche Freigabe** ohne dokumentierte unabhängige
Windows-CI- und manuelle Ingame-/Hardwareabnahme.

## Integrationsprüfung nach erstem Portable-Build

**Erster instrumentierter Windows/Python-3.13-Gesamtlauf (Junit und
Coverage-JSON in separater lokaler QA-Ablage):** 1.720 Tests bestanden,
36 übersprungen, 3 fehlgeschlagen (1.759 gesammelt, 1330,91 Sekunden,
gemessene aggregierte Quellzeilenabdeckung rund 51 %).
Die drei Fehler betrafen zwei historische Quellcode-Bytegleichheitstests,
die den absichtlich abgesicherten Tcl-Start nicht berücksichtigt hatten,
sowie einen Suchdialog-Test, der den inzwischen ausgeblendeten alten
Top-Bar-Knopf statt der sichtbaren linken Suche erwartete.
Diese Testverträge wurden auf die tatsächlich unverändert verfügbaren
Funktionen beziehungsweise genau die zulässigen Tk-Änderungen aktualisiert
und separat nachgetestet. **Der erste Gesamtlauf ist damit nicht
rückwirkend grün.** Eine unabhängige erneute vollständige CI-Prüfung
bleibt Voraussetzung für die spätere Release-Freigabe.

**Erster Paketbau:** vollständiges Windows-x64-Paket mit CPython 3.13.15,
12.525 Dateien, 333.490.565 ZIP-Bytes. Hashprüfung der ZIP-Datei,
ZIP-CRC, Git-Quellcommit-Metadaten, Ausschluss privater Spiel-/Arbeitsordner,
Portable-Selftest und realer Tk-Hauptfensterstart bestanden.
Ein synthetisches Projekt konnte mit dieser tatsächlichen gebündelten
Laufzeit ein geprüftes Mod-ZIP sowie ein übertragbares Projekt-ZIP
erstellen und wiederherstellen; Originalquellen wurden dabei nicht
geändert. Keine Ingame- oder Cross-PC-Zulassung ist damit verbunden.

Die letzte Quellstand-/Testkorrektur wird als nachfolgender lokaler Commit
in den finalen Integrationskandidaten übernommen. Alle ZIPs haben
versionierte Commit-Metadaten, keine automatische Aktualisierung oder
Veränderung alter Portable-Ausgaben.
