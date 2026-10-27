# Sprite Suite – UI-Verdrahtung und Schutz der Bedienwege

**Datum:** 22.10.2026  
**Arbeitsverzeichnis:** `E:\SpriteSuite` · Branch `feature/sandbox-studio`  
**Gegenstand:** Qt-Sandbox-Studio im Tk-Hauptfenster, funktionales HUD, XAML-Testbindungen, Spriteauswahl, Kartenwechsel, Radar-/Viewport-Export.  
**Abnahmestatus:** **NICHT FREIGEGEBEN** – dieser Bericht beschreibt nachgewiesene Teilreparaturen.

## Vorher reproduzierte Fehler und Korrekturen

1. **HUD-Pixeleditor / falscher Frame (P1):** Der HUD-Button benutzte die letzte Asset-Preview-Auswahl statt der im HUD sichtbaren Gruppe/Framezahl. Jetzt überträgt `NativeGameHUD.edit_sprite_requested(str, int)` die tatsächliche Auswahl an `SandboxStudio.open_hud_pixel_editor`, mit gesondertem Engine-Quellweg bei passender tatsächlicher Engine-Auswahl.
2. **HUD-/Inspector-Auswahl driftete auseinander (P1):** Die beiden Editoren synchronisieren Gruppe und Frame jetzt bidirektional, mit signalblockierter Kopplung und Preview-Invalidierung. Auswahl aus Native Engine oder Testfeld wird ebenfalls übertragen.
3. **Verlust durch stillschweigendes Frame-Clamping (P1):** Die Asset-Vorschau endete bei 100.000, das Szenenmodell/HUD bei 999.999. Beide Wege verwenden nun den gleichen zulässigen Framebereich.
4. **XAML-Testbinding ohne Spielkarte (P1):** Ein Bindungs-Klick konnte trotz abgelehnter Spielkartenansicht eine Platzierung anstoßen. Jetzt wird nur nach erfolgreich aufgerufener `show_native_map()` platziert; andernfalls deutliche Fehlermeldung und keine versteckte Aktion.
5. **Kartenordnerwechsel mit alter Karte im Fenster (P1):** Bei Wechsel zu einem leeren Originalkartenordner waren die alte Radaransicht und NativeMapCanvas weiterhin bedienbar. `NativeMapCanvas.clear_map` und `SandboxStudio._clear_open_map_views` entfernen alle kartenbezogenen Quelle-/History-/Cache-/Auswahl-/Tab-/Minimap-Zustände erst nach erfolgreich bestätigtem Ordnerwechsel. Ein realer, ausschließlich lesender Originalkarten-Test prüft den unveränderten SHA-256.
6. **Export in fremde Dateien / ungefangener IO-Fehler (P0-Schutz):** Vorher wurde jede gewählte Endung ungeprüft mit PNG-Pixeln beschrieben; beim Schreiben konnten unbehandelte OS-Fehler auftreten. Der neue `sandbox_png_export.py`-Schreibweg verlangt `.png`, schützt vorhandene Fremddateien außerhalb von `work/` sowie Originalspiel- und Maps-Verzeichnisse, lehnt Dateisymbolverknüpfungen ab und ersetzt nur nach vollständigem PNG-Schreib-/Signaturtest atomar. Radar- und Viewport-Export zeigen Fehler an und lassen alte Bytes intakt.
7. **Historischer HUD-Chrome-Versatz bei 1168px (P2):** Alle Aktionsschalter in einer horizontalen Reihe erzwangen eine zu große mittlere HUD-Spalte; die grüne Steuerleiste verfehlte die dokumentierten Bildproportionen. Die bestehenden Buttons liegen nun ohne abgehängte Signale in zwei schmalen Reihen. Zwei reale, Qt-offscreen HUD-Geometrieparameter und die Compact-Buttonprüfung wurden erneut bestanden.

## Testbelege

- Neue Dateien `tests/sandbox/test_studio_action_wiring.py` und `test_sandbox_png_export.py`: **12 bestanden, 0 Fehler**, inklusive Negativfälle, Fehler-Simulationen, Originalkarten-SHA und Fehlerbehandlung.
- Gezielter Nachtest für XAML-Varianten, grüne HUD-Leiste (1168×542 und 784×342) sowie kompakte HUD-Buttons: **4 bestanden, 0 Fehler**.
- Der erste breitere Qt-/Werkzeugtestlauf vor den zusätzlichen UI-Nachkorrekturen hatte **98 bestanden, 3 fehlgeschlagen, 1 übersprungen** in 215,54 s. Zwei Fehlfälle betrafen veraltete Testannahmen (XAML ohne geladene Karte und Team-Keyword der funktionalen Platzierung); die dritte Fehlstelle war der echte HUD-Geometrieversatz. Alle drei betroffenen Wege wurden im gezielten Nachtest überprüft.
- Der einzelne Skip ist die bekannte Tcl/Tk-Prozessinitialisierung und **nicht als bestanden gezählt**.
- Der neue vollständige 61-Modul-Headless-Systemlauf wird unabhängig beurteilt; seine Ergebnisse gehören erst nach vollständigem Prozessende in diesen Bericht.

## Unverändert offene Abnahmeblocker

- **Historische V1-Szenen:** Boden-Seeding, GM1-Komposite und Zeit-/Frameanimationen können im V2-Testfeld weiterhin nicht verlustfrei bearbeitet werden; der vorhandene Schutz verhindert Schreibverlust, ersetzt aber keine V1-Unterstützung.
- **Produktionsziel:** Fehlende bzw. nicht ausdrücklich ausgewählte, versionspassende Zielkonfiguration (`installations.local.toml`, `ziele.json`). Kein Build/Install gestartet.
- **Originalwerkzeug-Parität:** Nicht alle historischen Spezialprüfer und reale BC7-/Output-/Originalspiel-Zustände vollständig nachgewiesen.
- **Natives Langzeit-/Accessibility-QA:** Tk/Tcl-Skips, GDI-Handle-Messung, DPI-/Screenreader-Test und vollständige visuelle Gameplay-/Shaderparität aus der Gesamtabnahme bleiben offen.

## Schutz / Änderungspolitik

Originale `.map`-, GM-/Unity- und XAML-Dateien nicht bearbeitet, kein Produktionsziel geändert, kein Git-Commit oder Reset. Bereits vorhandene uncommittete Arbeitsänderungen bleiben erhalten. Neue Tests verwenden temporäre Pfade oder lesen die Originalkarte ausschließlich. Eine grüne Teilprüfung ist keine Freigabe der gesamten Sandbox.


## Fortsetzung am 22.10.2026 – vollständiger erweiterter UI-/Originaltool-Headless-Lauf

**Ausgangspunkt:** Der unmittelbar vorangegangene 61-Modul-Lauf war
**624 bestanden, 1 fehlgeschlagen, 0 übersprungen**.
Die einzige fehlgeschlagene Prüfung
`test_qt_language_accessibility.py::test_qt_file_menu_tabs_hud_combo_and_accessible_names_roundtrip`
nahm für F5 nach DE→EN→DE→EN eine konstante Beschriftung an.
Tatsächlich ist F5 nun absichtlich **arbeitsflächenabhängig**:
Radar zeigt `Kartenansicht neu laden` / `Reload original map`,
das Testfeld `Sprite-Grafiken neu laden` / `Reload test sprites`.
Der Test wurde auf unveränderliche QAction-Identität,
Shortcuts sowie fachlich richtige, reversible DE/EN-Beschriftungen
der sichtbaren Arbeitsfläche korrigiert. Es wurde nicht die
korrekte F5-Routenlogik zurückgenommen.

**Gezielter Kontrolllauf:** 26 bestanden, 0 Fehler.
Die drei neuen offscreen-sicheren Module
`test_original_gui_command_parity.py`,
`test_studio_action_wiring.py` und
`test_sandbox_png_export.py` sind dauerhaft in die
zusätzliche Headless-Liste aufgenommen.
Der Systemstarter erzwingt jetzt genau **64 eindeutig gelistete Module**
und schreibt in ein neues XML, sodass das frühere
Fehlerergebnis als Beleg erhalten bleibt.

**Vollständige Wiederholung:** **642 bestanden, 0 fehlgeschlagen,
0 Fehler, 0 übersprungen, Exit 0** in 356,59 Sekunden.
Keine Tk-/Win32-Fenster wurden gestartet; Qt lief offscreen.
Anschließend wurde die JUnit-Datei **unabhängig** überprüft:
642 einzelne `testcase`-Elemente, dieselben JUnit-Gesamtzahlen,
exakt dieselben 64 Modulnamen wie in den beiden Testlisten.
Erneut wurde Git-HEAD `00276ec` nachgewiesen.
Alle **drei** früher dokumentierten Spielquellen-Prüfsummen
(2 Originalkarten und `globalgamemanagers.assets`) stimmen
nach dem Lauf weiterhin bytegenau mit der Referenz überein.

**Maschinenlesbare Belege:**

- `work/reports/ui-audit/sandbox-headless-wiring-64modules-20261022.xml` – JUnit
- `work/reports/ui-audit/sandbox-headless-wiring-64modules-20261022.log` – Konsolenlauf
- `work/reports/ui-audit/sandbox-headless-wiring-proof-20261022.json` – unabhängige Zählung/64-Module- und 3-Quellhash-Prüfung
- `work/qa_verify_ui_wiring_20261022.py` – reproduzierbarer Verifizierer

**Einschränkung:** Die 642 Tests sind eine **reproduzierbar grüne
Modell-/Qt-Offscreen-Teilabnahme**. Sie ersetzen weder den vollständigen
Tk-/Windows-GUI-Langlauf noch die offenen P0-Blöcke:
verlustfreie V1-Szenenbearbeitung, freigegebenes versionsgebundenes
Produktionsziel, reale Original-/BC7-/Ingame-Buildparität,
Shader-/Gameplay-/HUD-Zustandsabgleich sowie DPI, Screenreader und
Tcl/Tk-/GDI-Ressourcenprüfung. **Gesamtfreigabe: weiterhin NEIN.**
