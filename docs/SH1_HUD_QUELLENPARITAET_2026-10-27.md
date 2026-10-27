# Stronghold 1 DE: native HUD-Quellenparität und Regression (27.10.2026)

Status: **Native XAML- und Bildgrundlage im isolierten QA-Export nachgewiesen.**
**Keine 1:1-HUD-Konvertierung nach Crusader, kein Ingame- oder Release-Zertifikat.**

## Unveränderte Spielquelle und gesonderte QA-Arbeitskopie

- Originalquelle: `D:\Games\Stronghold Definitive Edition\Stronghold 1 Definitive Edition_Data\globalgamemanagers.assets`
- SHA-256 der Quelldatei: `5810367d1ce4e87d63f8993f49b48243b2f3808f973e18f5c5a76c134913261f`
- Neuer, gesonderter Export: `work/sh1-hud-original-crlf-qa-20261027-chat`
- Export: 1.391 XAML-benannte Ausschnitte in UI-MasterAtlas (1.323), UI-ROL (55) und UI-CandleAtlas (13); Exitcode 0.
- Erneute `check_workspace`-Prüfung: 1.391 validiert, 0 bearbeitet, Exitcode 0.
- Native Pixelabgleiche aus dem vorherigen Originalaudit: alle drei exportierten Basisatlanten entsprechen den Unity-Texturen pixelgenau.

## Fehlerursache und Korrektur

Vorher erzeugte `Path.write_text` unter Windows aus ursprünglichen
`CRLF`-Zeilenumbrüchen `CRCRLF`. Die drei alten XAML-Baselines waren damit
über ihre neu berechneten Exportmanifeste in sich konsistent, jedoch
**nicht byteidentisch zur nativen Unity-Ressource**. Identische Manifesthashes
allein beweisen keine Herkunft.

Die Extraktion bewahrt deshalb jetzt rohe XAML-Bytes und schreibt sie mit
`Path.write_bytes`, ohne Text-/Zeilenumbruchtransformation.
Eine unabhängige native Herkunftsprüfung im Unity-Kandidatenworkflow
vergleicht die Quell-XAML und alle drei Atlas-Pixelbilder; historische
doppelte CRLF-Exports werden ausschließlich nach strengem Abgleich mit
den nativen Bytes als Legacy erkannt.

| Native Ressource | XAML-Bytes | Native XAML = neuer Export | SHA-256 des neuen XAML |
| --- | ---: | :---: | --- |
| UI-MasterAtlas | 152.354 | ja | `791125944e58485a68763aa41bb2bf7eca2cfacc5bb6bfabc39b43509d36979a` |
| UI-ROL | 6.047 | ja | `0fb252190479d8211ff454bcd704ff35f7193daf292299f5cfd6c6e1931b92fe` |
| UI-CandleAtlas | 1.632 | ja | `8609dde62c771fae9d4defe32a957983279b9f90af65fc6a13d969a56e491392` |

## Tests und verbleibende Testinfrastruktur-Grenzen

- Im separaten Quellrepo: **29 Tests bestanden** über
  `test_sh1_source_provenance.py`, `test_sh1_hud_edit_roundtrip.py`
  und `test_sh1_unity_hud_patch.py`.
- Gesamtsuite vor den gezielten Korrekturen: 930 bestanden, fünf
  fehlgeschlagen und ein Setup-Fehler (22m57s am 26.10.2026).
- Wiederholung der elf vormals auffälligen/zugehörigen Fälle:
  **zehn bestanden; ein Tcl/Tk-Setup-Fehler** beim wiederholten Tk-Root
  in einem gemischten Windows-Qt/Tk-Pytest-Prozess.
- Der separate Readiness-GUI-Test bestand isoliert (1/1);
  Qt-Editor und beide SH1-Pixeleditor-Tests bestanden nach
  Korrektur des reinen Pfadschutztests gemeinsam (3/3).
- Das explizite Setzen von `TCL_LIBRARY` / `TK_LIBRARY` im gleichen
  gemischten Lauf beseitigte diesen Tcl-Setup-Fehler **nicht**.
  Daher wird die gesamte Suite **nicht** als fehlerfrei deklariert.

Laufprotokolle befinden sich unter `E:\SpriteSuite\work\reports\`
(`hud-sh1-full-regression-20261026.log`,
`hud-sh1-regression-followup-fixed-20261027.log`,
`hud-sh1-regression-tcl-explicit-20261027.log`).

**Sicherheitsgrenze:** Der Export-/Prüfprozess hat keine Spielinstallation
und kein Produktionspaket verändert. Die tatsächliche visuelle,
interaktive und spielzustandsabhängige Crusader-zu-SH1-Konvertierung
ist weiter offen; die 151 namensgleichen Elemente mit anderen
Abmessungen dürfen nicht pauschal übernommen werden.
