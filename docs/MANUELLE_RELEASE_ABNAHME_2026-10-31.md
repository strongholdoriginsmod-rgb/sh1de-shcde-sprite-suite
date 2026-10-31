# SpriteSuite – manuelle Freigabeprüfung (Nachweispflichten)

Dies ist eine Checkliste für eine spätere, **menschlich beobachtete** Abnahme. Ein grüner Offline- oder Unit-Test allein ist keine Windows-Portable- oder Noesis-Ingame-Freigabe.

## Vorbereitung

1. Auf dem für die QA ausdrücklich ausgewählten Windows-Testgerät eine frische Spielkopie und ein vollständig neu entpacktes SpriteSuite-Portable-Paket bereitstellen; eigene Originalspielinstallationen unverändert lassen.
2. Den Quell-Commit aus `PORTABLE-BUILD.json`, die Versionskennung, ZIP-SHA256 und Python-/Qt-/Tk-Selftest-Protokolle aufzeichnen.
3. Ein **zweites physisches** Windows-10/11-x64-Gerät ohne zuvor installiertes Python nutzen; Start, Projekt-ZIP übertragen, PNG laden, Layout speichern, Neustart und erneutes Öffnen prüfen.
4. QA-Spielkopie vor Mod-Installation sichern. Änderungen nur am autorisierten Kopieordner erlauben.

## Ingame / Noesis

- Die tatsächlich installierte Spiel-/Script-Extender-Version sowie die verwendeten XAML-Dateien mit SHA256 notieren.
- Menüs, HUD und Vordergrundgrafiken in einer echten Spielrunde bei mehreren Skalierungen öffnen.
- Statische Overlay-Positionen, Alpha, Bildausschnitt, Ausrichtung und Überdeckung prüfen.
- Mit Maus und Tastatur alle **ursprünglich existierenden** Schaltflächen bedienen; Fokus/Hover und Trefferbereiche dürfen durch Overlays nicht verändert werden.
- **Neue funktionale Buttons gelten nicht als implementiert.** Sie benötigen separate nachweisbare Controls/Bindings/Eventhandler – keine erfundene Funktion durch eine PNG-Datei.
- Nach der Probe den gesicherten eigenen Mod wieder entfernen; nachweisliche unveränderte Originale/andere Mods belegen.

## Grafische Referenzprüfung

- Die rechtmäßig vorhandenen Originalgrafiken nur auf dem QA-Gerät einlesen.
- Manuell annotierte Karten-/Button-Masken sowie erwartete Sprite-Offsets und Alphakanten erstellen, ohne Originalspielgrafiken mit dem Repository zu veröffentlichen.
- Pixelhash/IoU/Falschpositive für Gefechtsrouten, 49 Missionsbilder und andere Familien pro Spiel-Build erfassen.
- Den Effekt der tatsächlichen Unity-/Shader-Darstellung im Spiel gesondert prüfen.

## Ergonomie und Langzeitbetrieb

- 100 %, 150 %, 200 % DPI; Hochkontrast; größere Schrift; 1020×680 und große Displays.
- Narrator/NVDA für Hauptnavigation, Fehlermeldungen, Auswahl und Mod-Freigabe.
- Ausschließlich Tastatur, Tab-Reihenfolge, sichtbarer Fokus, Undo/Redo, Abbrechen und Wiederaufnehmen.
- 100–500 wiederholte Fensterzyklen und längere Builds; Peak-RAM, GDI-Handles und verwaiste Kindprozesse erfassen.
- Netzlaufwerks-/Antivirus-Blockade sowie Stromausfall-Fälle nur in vollständig simulierten QA-Daten testen.

## Maschinenlesbarer Nachweis

Das CLI `tools/suite_distribution_gate.py` akzeptiert `--junit`, `--version`, `--source-commit`, `--portable` und `--manual-evidence`. Die manuelle JSON-Datei benötigt das Schema `sprite-suite.release-acceptance.v1`, den vollen Source-Commit und die Checks `independent_windows_pc`, `real_ingame_hud`, `real_mod_install_rollback`, `visual_goldens`, `screenreader_and_200dpi`. Jeder Check enthält `passed: true`, den Dateinamen eines **lokal vorhandenen**, separat begutachteten Nachweises in `qa-evidence/` und dessen SHA256.

Die Prüfroutine vergleicht Datei-Existenz, Größe und SHA256. **Sie kann nicht feststellen, ob ein Screenshot echt ist oder eine menschliche Freigabe fachlich richtig war.** Leere oder unvollständige Belege blockieren. Erst ein zusätzliches menschliches Review darf die tatsächlich betroffene Version freigeben.

## Bekannte unvollständige Voraussetzungen

- Ohne berechtigte GitHub-Installation gibt es keinen verifizierten öffentlichen PR/CI/Release.
- Ohne bereitgestellte private Spielressourcen bleiben Test-Skips offen.
- Eine Win32-Portable-Ausgabe benötigt eine kompatible, separat gepackte Python-3.13-x64-Laufzeit und eine echte frische Startprüfung.
- Komplexe neue ViewModel-/Event-Handler werden durch die bestehenden statischen Overlay-Patches nicht erzeugt.
