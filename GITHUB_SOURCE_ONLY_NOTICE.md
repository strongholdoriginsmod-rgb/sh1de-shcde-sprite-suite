# GitHub: vollständiger Projektstand mit Beispieldateien

Dieser GitHub-Stand vereint die Sprite Suite mit Stronghold-1-HUD-Studio,
Stronghold-Origins-Anbindung, SHCDE-Noesis-/Atlas-Werkzeugen, Sandbox Studio
und der read-only-Kompatibilitätsprüfung für Script Extender v2.14.3.

**Nicht auf einen reinen Quellcode-Snapshot reduziert:**
Die neun synthetischen, im Sprite-Editor dokumentierten Beispielartefakte
(PNG, ORA, SHSprite und ZIP) sowie alle vier bisher im GitLab-Repository
versionierten Miliz-UI-PNGs sind enthalten. Diese Dateien wurden unverändert
aus dem vorhandenen GitLab-Projekt übernommen und per SHA-256 verglichen.
Die historisch vorbereitete reine Quellcodefassung hatte sie noch ausgelassen.

**Keine Veröffentlichung von Spielinstallationen:** Native Unity-Container,
extrahierte kommerzielle Spiel-Atlanten, lokale Savegames, Passwörter,
API-Schlüssel und gerätespezifische Konfigurationen sind keine
Repository-Projektdateien und werden nicht hochgeladen. Der komplette
Projektquellcode und die bereits öffentlich versionierten Projektassets
bleiben dagegen im Repository erhalten.

Die Datei ist **kein eigenständig spielbares Spiel**. Auch die
Stronghold-Europe-/Origins-Runtime auf Basis von SE 2.11.0 ist mit einer
bloßen Formatprüfung gegen SE 2.14.3 **noch nicht Ingame-/ABI-freigegeben**.
Für neue Script-Extender-Releases ist die Prüfung in
`tools/shcdese_compat_check.py` nur lesend. Der alte 2.11-Installer darf
kein neueres Script Extender automatisch zurückstufen.

Die README- und Kompatibilitätsdokumente erklären die Funktionen,
Sicherheitsgrenzen und offenen Runtime-Tests.

---
Historischer Dateiname: `GITHUB_SOURCE_ONLY_NOTICE.md`. Sein ursprünglicher
Ausschlussvermerk wurde durch diese vollständige Veröffentlichung ersetzt.
