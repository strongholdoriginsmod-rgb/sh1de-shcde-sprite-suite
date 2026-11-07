# SpriteSuite: freie Individualisierung als Integrationsprinzip

Stand: 6. November 2026. Basis: `integration/spritesuite-converged-20261106`.

Die Suite ist eine Werkzeugbank zur möglichst vollständigen Bearbeitung von Stronghold-Spielen. Eine Funktion wird nicht allein wegen einer unbekannten Spielversion, eines ungewöhnlichen Dateityps, einer abweichenden Ordnerstruktur oder eines experimentellen Modding-Ablaufs ausgeschlossen.

## Umgesetzte Änderungen

- `suite_center.pyw`: Ein vom Benutzer ausgewählter Katalogbefehl wird unmittelbar ausgeführt. Der obligatorische zusätzliche Bestätigungsdialog entfällt.
- `suite_tool_policy.py`: Beschreibende Klassifizierung ohne globale Ausführungsfreigabe.
- `se_asset_package.py`: Standardmäßig werden beliebige bestehende Quellordner und selbst gewählte Zielordner akzeptiert. Der Mod-Bundle-Inhalt darf Lua, DLL, Sound, beliebige Dateiendungen, Noesis-Dateien und weitere Modding-Dateien enthalten; ein eigenes `info.json` bleibt erhalten. Versionstexte sind frei wählbar.
- Die frühere statische Asset-Prüfung ist mit `--strict-static` als optionaler Kompatibilitätstest aufrufbar, nicht mehr als universelle Sperre.
- `target_selection_guard.py`: Die tatsächliche Build-ID und die Mapping-Build-ID werden getrennt ermittelt. Eine abweichende Mapping-Herkunft blockiert die allgemeine Zielauswahl nicht mehr; `strict_mapping=True` steht nur als gezielter Diagnosevergleich zur Verfügung.
- `ziel_se211.py`: Bei Aktivierung eines bewusst ausgewählten Ziels wird dessen aktueller Fingerabdruck aktualisiert statt eine geänderte Spielversion zurückzuweisen.
- Sprite Editor: **Alle HP-Schadensmodelle exportieren…** schreibt auch Entwürfe, unveränderte Klone und verworfene Stufen mit sichtbaren Statusfeldern ins ZIP. Keine verpflichtende visuelle Abnahme oder Mindeständerung für diesen Export. Der frühere Export nur für freigegebene Zustände bleibt optional.
- `building_damage_runtime_preflight.py`: Testkandidaten können auch ohne Freigabedigest vorbereitet werden; `--require-bound-approval` erlaubt eine ausdrücklich gewählte strengere Kontrolle.

## Technische Grenzen und Funktionen

Die Editor-/Mod-Implementierungen müssen ihre jeweiligen Daten korrekt lesen und schreiben. Nicht vorhandene Eingabedateien, beschädigte ZIP-Strukturen, defekte Bytekopien oder ungültige Dateinamen sind keine Modding-Funktionen. Diagnostik darf den Export nicht ohne tatsächliche technische Notwendigkeit blockieren.

Eine exportierte DLL ist zunächst nur Bestandteil eines ZIPs; zur Aktivierung im Spiel ist weiterhin ein passender Plugin-/Runtime-Ladepfad zu implementieren und praktisch zu testen. Das Paketieren selbst installiert nichts automatisch und behauptet auch keine erfolgreiche In-Game-Ausführung.

## Geprüfte Entwicklungspfade

- Freier Paketexport aus beliebigem Verzeichnis einschließlich DLL, Lua und Sonderdateiendungen.
- Frei wählbarer Zielpfad und eigene Mod-Metadaten.
- Optionaler alter statischer Prüflauf als eigenständiger Testmodus.
- Direkt ausgeführte Werkzeugkommandos aus dem vorhandenen Suite-Katalog.
- Zielauswahl mit abweichender Build-/Mapping-ID und optionaler Paritätsdiagnose.

## Freie Mod-Dateien im gemeinsamen Projekt

**Dateien hinzufügen** übernimmt neben Grafik, Noesis-XAML und Menüvideo auch freie Dateitypen. Unter **Mehr → Mod-Dateien unverändert hinzufügen…** lässt sich für jede Auswahl der Paketordner angeben, etwa `Override/Audio`, `Scripts` oder `Plugins`. Die Dateien werden bytegenau in das aktive Projekt kopiert. Für eine Datei im Hauptverzeichnis bleibt das Ordnerfeld leer.

**Paketdetails** enthält Mod-ID, Paketname, Autor und Version. Eine eigene `info.json` im Projekthauptverzeichnis wird bytegenau übernommen. **Mehr → Mod-ZIP speichern unter…** legt das Ziel des geprüften Pakets fest. Der Export vergleicht die Paketdateien mit dem SHA-256 der Projektdateien.

**Projekt sichern (ZIP)** und **Projekt-ZIP öffnen** schließen diese Dateien zusammen mit den Grafik- und Noesis-Bearbeitungsdaten ein. Archive mit freien Paketpfaden verwenden die Schema-Version 2. Bestehende Projektarchive der Version 1 sind weiterhin lesbar.

## Weitere Integrationsarbeit

Historische Build-/Versionslimits in spezialisierten Installern, einzelne Werkzeug-Whitelists, vom Spiel selbst erzwungene Strukturformate und fehlende Laufzeit-Hooks sind separate Bearbeitungspunkte. Sie dürfen nicht allein wegen ihrer bisher restriktiven Implementierung als final erklärt werden. Zu prüfen sind alle offenen Funktionen aus HUD, Audio, Atlas, Gelände, Einheiten, Gebäuden, Diplomatie, Lua, Script Extender und Unity-/Noesis-Runtime auf sachliche Eignung und reale Funktion.
