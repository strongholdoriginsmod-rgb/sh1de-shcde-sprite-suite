# SpriteSuite · aktuelle Kurzanleitung

RC5 erweitert RC4 um den direkten PNG-plus-XAML-Atlas, den Startseiten-Chat und freie Grafikabläufe ohne Pflichtbegründung oder Qualitätsfreigabe. Ein älterer Download erhält die Änderungen erst durch die neue Ausgabe. [Download und aktueller Stand](../README.md).

1. **Windows starten:** Windows-Startpaket vollständig in einen kurzen eigenen Ordner entpacken, `SpriteSuite/Suite starten.cmd` öffnen. Python ist enthalten. Der erste Start benötigt Internet für die hashgeprüften Zusatzpakete.
2. **Projekt wählen:** Auf **Projekt & Dateien** ein Projekt öffnen oder neu anlegen. Dort stehen Import, Bearbeiten, Prüfen, Projektsicherung und Mod-ZIP zusammen.
3. **Atlas öffnen:** **Strg+K → UI-Atlas · PNG + XAML**, passende PNG und XAML wählen, **PNG + XAML als Arbeitsstand öffnen**. Sprite-Schlüssel auswählen und einzeln ersetzen; ein weiterer Atlas kann die Quelle liefern. [Atlas-Anleitung](UI_ATLAS_PNG_XAML.md).
4. **Atlas übernehmen:** **Ins Mod-Projekt übernehmen** schreibt das bearbeitete Atlaspaar in das aktive Mod-Projekt. PNG-Einzelexport dient beispielsweise externer Weiterbearbeitung. Originalquellen bleiben erhalten.
5. **Chat verwenden:** Im Startseiten-Chat anmelden, angebotene Modelle laden, Frage oder Auftrag eingeben. Die Voreinstellung **Aufträge** nutzt alle Werkzeuge und kann selbst programmieren. Optionen erlauben unter anderem einen nur lesenden Fragenmodus und das Abschalten lokaler Python-Ausführung. [Chat-Anleitung](KI_CHAT_STARTSEITE.md).
6. **Sichern und ausgeben:** **Projekt sichern (ZIP)** bewahrt bearbeitbare Dateien und Metadaten. **Änderungen prüfen** liefert Befunde; **Geprüftes Mod-ZIP bauen** erstellt das Paket. Die Ausgabe installiert nichts in ein Spiel.
7. **Weitere Werkzeuge:** **Strg+K** durchsucht Arbeitsbereiche und Fachwerkzeuge. Bei wenig Platz den Chat einklappen, Scrollleisten verwenden oder ein Werkzeug im eigenen Fenster öffnen.

Für den alten exportbasierten SH1-DE→Crusader-Ablauf und weitere Aufgaben gelten die [aktuellen Workflows](WORKFLOWS.md). Das PDF vom 4. November und die [archivierten Workflows](WORKFLOWS_HISTORISCH_BIS_20261107.md) dokumentieren ältere Teilstände.

Die echte HP-/Feuer-Spielabnahme ist offen, weil die isolierte Steam-QA-Kopie mit `T:0000065432` endet. Automatisierte Datei- und Projekttests ersetzen keinen beobachteten Ingame-Lauf. Alte Entwicklungszweige bleiben bis zur vollständigen Abnahme erhalten.
