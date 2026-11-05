# SpriteSuite: dynamische Versionserkennung und Python 3.15.2

**Datum:** 5. November 2026. **Zweig:** `feature/python315-dynamic-compat-20261105`.

## Absicht und Grenzen

SpriteSuite soll möglichst viele *tatsächlich passende* neue Versionen erkennen.
Das bedeutet **keine pauschale Aufhebung von Dateischutz, Spielversions-Integrität
oder nativen ABI-/Installationssperren**. Der genaue Pfad, aktuelle DLL-Signaturen
und im laufenden Spiel sichtbare Pixel müssen weiterhin nachgewiesen werden.
Versionsstrings und ein erfolgreicher C#-Compilerlauf allein sind kein
Spieltest.

## Python-Unterstützung, getrennt nach Ebenen

| CPython | Quelle / Syntax | Tatsächliche Tcl-/Qt-Laufzeit | Auslieferung |
| --- | --- | --- | --- |
| 3.13.x | unterstützt | bewährte Tk 8.6 + PySide6 6.10.2 | **lokaler Windows-x64-Portable-Stand** |
| 3.14.x | unterstützt | Tcl/Tk 9 ZIPFS, aktualisierte Wheel-Umgebung nötig | Quellumgebung mit separatem Lock, kein öffentlicher 3.14-Release |
| 3.15.x | Quell-Paketmetadaten erweitert | Tk 9 aus Python-3.15-DLL-ZIPFS; PySide6 ab 6.12 | isolierte QA, nicht automatisch neu veröffentlicht |

Die originale Python-3.13-Portable-Ausgabe bleibt **unverändert**. Die
Quell-Metadaten erlauben jetzt `>=3.13,<3.16`. Bei Python 3.15 verwendet
`gui` PySide6 mindestens 6.12 und die Assets-Familie kompatible
Versionsbereiche; 3.13/3.14 behalten ihre bestehenden festgeschriebenen
Quellabhängigkeiten und SHA-gepinnten Windows-Lockdateien.

### Experimenteller, lokal reproduzierter CPython-3.15-Wheelstand

Die anfängliche Einschränkung „keine Python-3.15-Wheels“ wurde durch
separates Erstellen fehlender UnityPy-/lz4-/tpk_ar-Komponenten behoben.
Die vollständige QA-Wheelumgebung wurde in **27 Einzel-Wheels**
mit **SHA-256** erfasst und in
`requirements-py315-win_amd64.lock` versioniert. Der Quellbuild von
UnityPy 1.25.4 und lz4 4.4.5 ist der Grund, weshalb keine allgemeine
Binärkompatibilität auf fremden Geräten behauptet wird.

Die lokalen, bytegenau geprüften Wheels liegen außerhalb des Git-Baums unter
`E:/SpriteSuite_LiveGameQA_20261105/COMPAT_20261105/py315-wheelhouse`.
Eine **zweite, leere CPython-3.15.2-Venv** wurde ausschließlich daraus mit
`--no-index --require-hashes` aufgebaut; alle 27 Paketversionen
wurden installiert und `pip check` blieb fehlerfrei.

Im isolierten QA-Quellzweig lässt sich mit dem experimentellen Paketbauer ein
**separates** Windows-x64-Portable-Archiv erstellen:

```powershell
python tools/build_portable_windows.py --python-minor 15 --experimental `
    --python-home "E:/SpriteSuite_LiveGameQA_20261105/COMPAT_20261105/cpython315-full-isolated" `
    --venv "E:/SpriteSuite_LiveGameQA_20261105/COMPAT_20261105/venv-cp315-verified-from-lock" `
    --wheelhouse "E:/SpriteSuite_LiveGameQA_20261105/COMPAT_20261105/py315-wheelhouse" `
    --out "E:/SpriteSuite-Py315-Experiment"
```

Die Ausgabe erhält den Dateinamen-Zusatz **EXPERIMENTAL**.
Ohne `--experimental` oder ohne die vollständig SHA-geprüften Wheels
verweigert dieser Zweig die Python-3.15-Paketierung. **Die bisherige
Python-3.13-Ausgabe bleibt davon unberührt.** Die experimentelle Ausgabe
ist kein automatischer Stable-/Ingame-Release.

Der neue Laufzeitprüfer unterscheidet bewusst
`source_version_supported`, `full_gui_runtime_verified`,
`core_ui_ready` und `native_game_approved`. Ein fehlender oder nicht passender hashgesicherter Python-3.15-Wheel-Lock
bleibt als **Einschränkung** sichtbar,
auch wenn die lokale Entwicklungs-QA funktioniert.

### Isolierter Windows-Python-3.15-Test

- Offizielle Python-3.15.2-Windows-AMD64-Pakete unter `E:/SpriteSuite_LiveGameQA_20261105/COMPAT_20261105`, jeweils vor Entpackung SHA-256-geprüft.
- Vollständige CPython-3.15.2-Laufzeit mit Tcl/Tk 9.0.4 und separater Venv.
- PySide6 6.12.0, Pillow 13.0.0, NumPy 2.5.4, SciPy 1.18.1, pytest 9.2.0;
  UnityPy 1.25.4 und lz4 4.4.5 mussten mangels Python-3.15-Wheel **nur in
  dieser QA-Umgebung aus Quellpaketen** zu echten CPython-3.15-Wheels gebaut
  werden. Es wurden keine systemweiten Pakete und keine Spieldaten verändert.
- `pip check`, QtWidgets-Offscreen-Start, Tcl-/Tk-Start,
  `compileall` und getrennte GUI-/Workflow-Tests dienen als konkrete Gates.

**Hinweis:** Selbst ein erfolgreicher lokaler Quellbuild ist noch keine
reproduzierbare, öffentlich verteilbare Python-3.15-Portable-Laufzeit.
Vor einer öffentlichen 3.15-Distribution müssen Windows-Wheel-Hashes,
Tcl-/Tk-Laufzeit, Neu-Entpackung und echte GUIs auch auf einem unabhängigen
Windows-PC attestiert und die Drittanbieter-Lizenzen geprüft werden.

### Kompatibilitätsmatrix ausführen

```powershell
python tools/suite_multi_python_matrix.py --python "C:\Python314\python.exe" --json-out "E:\mein-qa\python-compat.json"
```

Mehrere `--python`-Argumente prüfen mehrere Interpreter. Es werden keinerlei
Pakete installiert oder Spiele modifiziert.

## Neue Tcl-9-DLL-Erkennung

Python 3.14 verwendet auf diesem Rechner Tcl/Tk 9 mit `libtcl9.0.*.zip` /
`libtk9.0.*.zip`. Die offizielle Windows-ZIP-Laufzeit Python **3.15.2**
verwendet dagegen `DLLs/tcl90.dll` und `DLLs/tcl9tk90.dll` mit
eingebetteten ZIPFS-Tcl-/Tk-Skripten. Die bisherige reine ZIP-Dateisuche
lehnte diese korrekt funktionierende Umgebung ab.

Die neue Quelle wird nur akzeptiert, wenn die DLL-Dateien zur **selben**
`sys.base_prefix`-Laufzeit gehören, beide Größen und SHA-256-Fingerprints
lesbar sind und Tcl **sowie Tk** die eigenen `init.tcl`-/`tk.tcl`-Quellen
aus `//zipfs:` tatsächlich öffnen können. Eine kaputte mitgelieferte
Laufzeit darf niemals durch ein anderes System-Python als funktionsfähig
zertifiziert werden.

## Native Spiele und Script Extender

`tools/suite_native_game_capabilities.py` nimmt unabhängig von der
Versionsnummer eine **nur lesende** Strukturinventur eines selbst ausgewählten
Game-/Script-Extender-Ordners vor. Sie prüft SHA-256 von Spiel- und
Noesis-Dateien, Extender-Info, vorhandene XAML-Dateien und eindeutig benannte
Grids. Optional werden 7 Cecil-Metadatensignaturen im getrennten QA-Ordner
validiert:

```powershell
python tools/suite_native_game_capabilities.py --game "E:\SSLiveGame_20261105" --metadata-qa-dir "E:\MeinQa\abi-einmalig" --json-out "E:\MeinQa\abi-strukturen.json"
```

Die in diesem Gespräch vorhandene, vollständig SHA-verifizierte
QA-Spielkopie (Steam-App 3024040, Build 24816905, Spielversion 2.8.2,
Script Extender 2.14.3) besitzt 70 eindeutige XAML-Grid-Kandidaten und
**7/7 erwartete Strukturmerkmale**. Ein natives SpriteSuite-C#-Plugin
wird deshalb trotzdem **nicht automatisch installiert**. Die alte native
Releasepipeline ist absichtlich für andere konkrete DLL-Hashes gepinnt,
und beim echten Spieltest wurde zwar ein statischer Mod registriert,
aber die erwartete Overlaygrafik zunächst **nicht** im Spiel gerendert.

Die Kompatibilitäts-GUI hat jetzt zusätzlich **»Spielstruktur prüfen«**.
Der Ordner wird nur gelesen; die Anzeige unterscheidet
`Game XAML/Noesis source structure` von
`Native game ABI: unverified`.

## Noch ausstehende öffentliche Stable-Gates

- Reproduzierbare, hashgesicherte Python-3.15-Windows-Distribution mit
  Neu-Entpackung und unabhängigen GUI-Tests.
- Sicher attestierte Native-C#-Events, tatsächliche Noesis-Pixel und
  Spiel-/Atlas-Rollback in einer autorisierten QA-Spielkopie.
- Unabhängiger zweiter PC, Hardware-DPI-/Screenreader-Prüfung und
  Original-Asset-Rechte.

Die Windows-Steam-Originalinstallation und die bestehende SpriteSuite-Portable-
Ausgabe wurden durch diese Kompatibilitätsarbeit **nicht** überschrieben.
