# SpriteSuite Windows Portable – ohne separat installiertes Python

**Ausgabe:** 28. Oktober 2026. Für Windows 10/11, 64 Bit.

## Start in drei Schritten

1. Auf der [GitHub-Releases-Seite](https://github.com/strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite/releases)
   die Datei **SpriteSuite-Windows-Portable-2026-10-28.zip** herunterladen.
   **Nicht** die GitHub-Schaltfläche **Code → Download ZIP** nehmen:
   Dieser Download enthält nur Quellcode und keine Python-Laufzeit.
2. Die ZIP-Datei **vollständig entpacken**, z. B. nach `C:\\SpriteSuite`.
   Die Dateien `SpriteSuite\\python\\python.exe` und
   `SpriteSuite\\.venv\\Scripts\\python.exe` müssen vorhanden sein.
3. **SpriteSuite → Suite starten.cmd** doppelklicken.
   Es werden keine Python-Systeminstallation, Adminrechte, `pip`
   oder Ausführung von `setup.ps1` benötigt. Die Suite nutzt eine
   private, vollständig mitgelieferte CPython-3.13-Laufzeit.

Diagnose bei Startproblemen: Im entpackten Ordner in der Eingabeaufforderung
`Suite starten.cmd --self-test` ausführen. **PORTABLE_READY=1** und
**GUI_BACKENDS_READY=1** bedeuten, dass die Pakete einschließlich der
Tk-/Qt-Grafiklaufzeit lokal geladen und geöffnet werden konnten.
Auch `Sandbox Studio starten.cmd` richtet die entpackte Laufzeit
eigenständig auf ihren aktuellen Speicherort ein.

**Kompatibilität:** Ziel sind Windows 10 ab Version 1809 und Windows 11
auf x64-PCs. Das entspricht den dokumentierten Plattformen von Qt 6.10:
https://doc.qt.io/qtforpython-6.10/overviews/qtdoc-supported-platforms.html
Windows on ARM sowie ältere Windows-10-Versionen sind nicht freigegeben.
Ein
erfolgreicher Test nach Pfadwechsel und ohne System-Python ist ein
Portabilitätsnachweis, aber noch kein vollständiger Ersatz für einen
Test auf einem unabhängigen Windows-10-/11-Rechner. Einzelne optionale
Editoren, externe Encoder und native Werkzeuge können weitere
Voraussetzungen haben.

## Was in der ZIP steckt

- GitHub-Quellcode des geprüften Commits einschließlich HUD-/Menü-Designer.
- Portabler Windows-CPython-3.13-Interpreter, Standardbibliothek und Tk.
- Eigene virtuelle Laufzeit mit Pillow, UnityPy, PySide6 und übrigen
  zum Suite-Start benötigten Python-Paketen.
- Keine installierten Spiele, Benutzerdateien, kommerziellen Spielgrafiken
  oder Passwörter.

Die Laufzeit wird beim Start anhand ihres lokalen Ablageorts neu zugeordnet,
damit der entpackte Ordner verschoben werden kann. `work/` enthält künftig
die eigenen Arbeitsstände; Originaldateien der Spiele bleiben getrennt.

Für manche **optionalen** Bauvorgänge werden nach wie vor die originale
Spieleinstallation, Unity, .NET, Script Extender oder besondere Encoder
benötigt. Die Portabilität beseitigt ausschließlich die separate
Python-Installation und Paketinstallation.

## Für Entwickler: reproduzierbarer Paketbau

`tools/build_portable_windows.py` exportiert ausschließlich bereits
commitete Projektdateien über `git archive` und fügt eine vorhandene,
geprüfte CPython-3.13-Laufzeit mit kompatibler venv hinzu. Es kopiert keine
lokalen `work/`-Dateien oder Spielinstallationen. Bestehende Ausgabeordner
werden nicht überschrieben.

Auf einem **Windows-Buildrechner** mit vorhandenen Werkzeugen:

```powershell
python tools/build_portable_windows.py --python-home C:\\Pfad\\Python313 --venv C:\\Pfad\\Venv313 --out C:\\Paket-Ausgabe
```

Der Builder erzeugt einen entpackten Ordner für die lokale Funktionsprüfung,
ein ZIP und eine SHA-256-Prüfsummendatei. Vor der Veröffentlichung:
`Suite starten.cmd --self-test` im Ausgabeverzeichnis ausführen,
SHA-256 des ZIP prüfen und GUI-Start mit dem tatsächlichen Paket testen.
