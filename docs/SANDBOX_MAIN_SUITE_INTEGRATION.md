# Sandbox Studio als echter Reiter der Universal-Sprite-Suite

**Stand:** 2026-10-11. Integration für die bestehende Windows-Anwendung
`tools/suite_universal.pyw` mit ihrer Tkinter-Hauptoberfläche.

## Nutzerablauf

1. **`Suite starten.cmd`** (wie bisher) doppelklicken.
2. Im selben Sprite-Suite-Fenster den vorhandenen Reiter **Sandkasten**
   auswählen. Beim ersten Besuch wird dort **das vollständige Qt Sandbox
   Studio** geladen, ohne zweiten Startknopf oder unabhängiges Hauptfenster.
   Alle späteren Reiterwechsel verwenden dieselbe offene Instanz.
3. Native `.map`-Kartenansicht, Testfeld, Sprite-Palette, Original-XAML-HUD,
   Grafikvergleich, interaktives Platzieren und Pixeleditor sind direkt im
   Reiter zugänglich. Werkzeugleisten, Qt-Menüs und native Kartenkameras
   gehören **zur eingebetteten Studio-Ansicht**.
4. Im **Asset-Katalog** die Spritegruppe und den Frame auswählen und
   **„Im Sandkasten zeigen“** drücken: Die Sprite Suite wechselt zu
   Sandkasten, wählt die richtige Arbeitsgrafik aus und aktiviert
   die Platzierung auf der Originalkarte. Klick auf die Zielkachel.
   Falls keine Originalkarte geladen ist, steht das isometrische Testfeld
   stattdessen bereit. Vorhandene Karte/Overlays bleiben erhalten.
5. Im Sandkasten **„Originalgrafik im Katalog“** drücken, um den
   aktuell ausgewählten Engine-/Atlasframe im Haupt-Asset-Katalog zu öffnen.
   Kein manuelles erneutes Eintippen der Frame-Nummer.
6. Über **Karte öffnen** lädt man eine Originalkarte. **Palette** und
   **Inspector** zeigen die jeweils benötigten Bedienelemente; **Fokus**
   blendet die Seitenleisten für eine große Kartenansicht aus.
   **Layout zurück** stellt die Standardansicht wieder her. Über
   **Weitere Werkzeuge** sind Kartenordner, Speichern, Katalogsprung,
   Animation, Spiel-HUD und Pixelvergleich jederzeit erreichbar.
   Innerhalb von Qt gibt es zusätzlich eine benannte
   **Werkzeugauswahl** mit allen rechten Inspectoren und HUDs.
7. Beim Verlassen des Reiters kehrt das Suite-Protokoll automatisch mit
   allen bisherigen Nachrichten zurück. Beim Schließen der
   Universal-Suite fragt das Studio bei noch ungespeicherten Änderungen
   wie zuvor nach und kann den Schließvorgang abbrechen.

## Architektur / warum nicht zwei Fenster?

Die alte Universal-Suite verwendet **Tkinter/ttk**, der moderne
Originalkarteneditor **PySide6/Qt6**. Diese beiden GUI-Welten können nicht
direkt als dieselben Widgets ineinander gezeichnet werden.

`tools/sandbox_suite_embed.py` nutzt deshalb auf Windows das native
Qt-Fensterhandle (`winId`) und hängt es mit `SetParent` und
`WS_CHILD` an das tatsächliche **HWND des Tkinter-Sandkasten-Reiters**.
Es erscheint dadurch kein separates top-level Sandbox-Fenster und kein
zweiter Qt- oder Python-Hauptprozess.

- **Ein Prozess, ein Hauptfenster, ein Reiter:** Der bereits bestehende
  Tk-Event-Loop pumpt die Qt-Ereignisse in derselben UI-Thread-Instanz
  (`QApplication.processEvents` alle 25 ms).
- **Gemeinsame Arbeitsdaten:** Beide Werkzeuge nutzen die gleichen
  `work/katalog/arbeit`- und `sandbox/overlays`-Dateien und haben
  getrennte, atomisch geschützte Speicheraktionen.
- **Dynamische Größe und DPI:** `<Configure>` des Tk-Frames passt das native
  Qt-Kindfenster mit `SetWindowPos` an. Auf Windows sind dies
  **physische Win32-Pixel**; die Qt-Widget-Größe wird intern in
  **DPI-unabhängigen Punkten** geführt und darf nicht nochmals mit
  derselben Pixelzahl über `QWidget.resize()` gesetzt werden.
  Die Windows-QA vergleicht deshalb die wirklichen **HWND-Client-Rechtecke**
  und berücksichtigt den Qt-Skalierungsfaktor.
- **Platzoptimierung:** Das historisch unten stehende, siebenzeilige
  Suite-Protokoll wird ausschließlich im Sandkasten eingeklappt und
  bei Reiterwechseln wiederhergestellt. Die langen Qt-Werkzeug-Tabs
  werden durch **eine beschriftete Werkzeugauswahl** ersetzt; nur der
  aktuell gewählte Inspector ist sichtbar. Die breite Sprite-Palette
  wird bei Bedarf über **Palette** oder **F6** eingeblendet. **Fokus / F9**
  zeigt eine reine Kartenfläche. **Inspector / F7** blendet die rechten
  Tools ein und aus. Animation, Spiel-HUD und lokale Original-XAML-HUDs
  bleiben über die Werkzeugauswahl bzw. **Weitere Werkzeuge** erreichbar.
- **Lesbarer Inspector:** Auf der rechten Seite werden die
  Bedienbeschriftungen gekürzt (vollständige Hilfetexte als Tooltip)
  und die tatsächlich lesbaren Formularbreiten auch bei 1020 × 680
  geprüft. Vertikal gibt es Scrollleisten bis zu den unteren Funktionen,
  horizontal wird der wichtige Karten-Inspector nicht abgeschnitten.
- **Lebensdauer:** Das Qt-Studio wird beim ersten Sandkasten-Besuch
  erzeugt und nach Reiterwechseln wiederverwendet. Die normale
  Suite-Schließen-Aktion beachtet Qt-`closeEvent`, einschließlich
  sicherer Speichern-/Abbrechen-Dialoge; `QApplication` beendet
  nicht heimlich das Tk-Fenster.
- **Kompatibilität:** Der unabhängige `sandbox_studio.py`-Start bleibt
  für Entwicklungs-/Diagnosezwecke verfügbar; er ist **nicht** länger
  der Standardweg innerhalb der Universal-Anwendung. Die historische
  Tk-PIL-Vorschau bleibt aus Kompatibilitätsgründen im Quellcode,
  wird aber nicht mehr als Standardfunktion des Sandbox-Reiters angeboten.
- **Plattform:** Das native Kindfenster erfordert **Windows**.
  Fehlende Qt-Abhängigkeiten und nicht unterstützte Plattformen
  werden im Hauptreiter angezeigt, nicht durch einen still gestarteten
  Zweitprozess kaschiert.

## Installation / Abhängigkeiten

`PySide6==6.10.2` und alle drei unmittelbaren Qt6-Wheelabhängigkeiten
(`PySide6_Addons`, `PySide6_Essentials`, `shiboken6`, jeweils 6.10.2)
sind nun für die normale Windows-Python-3.13-Ersteinrichtung
**versions- und SHA-256-fixiert** in
`requirements-py313-win_amd64.lock`. Die Hashes wurden für die
offiziellen passenden `cp39-abi3-win_amd64`-Wheels abgeglichen.
Der bestehende Hash-Sicherheitsmodus des Setup-Skripts bleibt aktiv.
Auch `pyproject.toml` benennt `gui` als optionales Paket-Extra.

Das vollständige Windows-Paket muss die passenden Qt-Wheels
enthalten, falls es ausschließlich aus einem Offline-Wheelhouse
installiert werden soll.

## Verifizierte Abnahme

`tests/sandbox/test_suite_integration.py` prüft ohne eine zweite
GUI-Anwendung die Routen **Katalog→Sandkasten→Katalog**,
die Reiterwechsel und die gemeinsame Schließlogik.

Ein zusätzlicher **Echt-Windows-Smoke-Test** mit der aktuellen Suite
läuft über:

```powershell
.\.venv\Scripts\python.exe tools\qa_suite_embedded.py
```

Er prüft auf dem Windows-Desktop das wirkliche Win32-`GetParent` des
Qt-Sandbox-HWNDs, das Notebook-Host-HWND und die **physischen Client-Größen**
unter Windows-Skalierung; ferner Fokusmodus, Palette, Inspector,
Werkzeugauswahl, HUDs und Layout-Zurücksetzen bei
**1500 × 930** sowie **1020 × 680**. Die QA kontrolliert auch die
Szenenbreite und das Fehlen eines horizontal abgeschnittenen Inspectors.
Sprite-Auswahl, Reiterwechsel und wiederhergestellte Protokollfläche
bleiben Teil der Abnahme.
Ein privater QA-Screenshot liegt unter
`work/suite_embedded_sandbox_qa.png`.

**Die Shader-, Simulations- und komplette Spiel-HUD-Parität der eigentlichen
Stronghold-Engine bleibt eine eigenständige technische Restaufgabe.**
Die Integration löst jetzt das bisherige Problem „separates Fenster /
separater Prozess“, behauptet aber keine bislang nicht bewiesene
Spielrender-Identität.

## Qualitätsrunde 2026-10-11: reale Bedienfehler behoben

Nach der ersten 204-Tests-Abnahme wurden die tatsächlichen Abläufe in der
Universal-Suite und im eingebetteten Qt-Sandbox-Studio nochmals überprüft.

1. **Animationswerkzeug:** Die erste Tk/Qt-Einbettung verschob nur das
   Spiel-HUD und das Original-XAML-HUD nach rechts, versteckte jedoch den
   **Animation-/Frame-Test**-Dock vollständig. Das ist korrigiert:
   Animation, echtes Spiel-HUD und Original-XAML-HUD werden als erreichbare
   Qt-Werkzeug-Reiter eingebettet, wobei fehlende lokale XAML-Crops
   weiterhin toleriert werden. Neue Suite-Schaltflächen
   **Animation / Frames** und **Spiel-HUD** öffnen die jeweils passende
   Studio-Ansicht und aktivieren ihr Werkzeugfenster.
2. **Aktuelle Auswahl statt altem Engine-Treffer:** Beim Zurückwechseln in
   den Asset-Katalog konnte ein früheres `last_engine_pick` die inzwischen
   gewählte Spritegruppe oder Framenummer übersteuern. Die Rückroute
   verwendet nun die aktuelle Auswahl der zentralen Grafikvorschau.
   Die Übergabe `Asset-Katalog → Sandkasten` setzt alte Treffer zurück.
3. **Schließen ohne leeren Reiter:** Das direkte Qt-Schließen (z. B.
   Alt+F4) wird im eingebetteten Modus **nicht mehr isoliert ausgeführt**.
   Es löst über einen ereignisgesteuerten, nicht-reentranten Rückruf das
   reguläre Schließen der Universal-Suite aus. Dabei bleiben die
   existierenden Speichern-/Abbrechen-Dialoge für nicht gespeicherte
   Karten- und Szenenänderungen wirksam. Der normale eigenständige
   Qt-Diagnosestart bleibt unverändert.
4. **Keine versteckte Entwicklerinstallation:** Wenn
   `config/installations.local.toml` keinen gültigen Zielspielordner mit
   Originalkarten benennt, öffnet sich ein **leerer Kartenkatalog**. Der
   bisherige fest eingebaute QA-Pfad `E:/SSGameQA` darf in einer
   anderen Windows-Installation niemals als vermeintliches Zielspiel
   dienen. Über **Kartenordner wählen** im Sandkasten lässt sich der
   echte Spielordner direkt festlegen. Gültige konfigurierte
   Installationen werden automatisch gefunden.
5. **Installation bleibt reproduzierbar:** Die zuvor hinterlegten
   SHA-256-fixierten Qt6-Wheels bleiben unverändert. Für Qt- und
   Tk-Funktionen wird weiterhin ein einziger Prozess und derselbe
   Hauptthread verwendet; Originalspiel-Assets werden nicht geändert.

### Prüfbarkeit

- `tests/sandbox/test_suite_integration.py`: Interaktionsrouting,
  wieder sichtbare Animation, Auswahlaktualität,
  eingebettete Qt-Schließlogik und Abbruch eines unsicheren Schließens.
- `tests/sandbox/test_maps_configuration.py`: gültiger Spielpfad,
  fehlende/ungültige TOML-Konfiguration, expliziter Kartenordner,
  keine versteckte QA-Installation und unveränderte Karten-Bytes.
- `tools/qa_suite_embedded.py`: kompletter GUI-Test auf dem echten Windows
  mit Originalkarte, Tk-Hauptfenster, Qt-Kindfenster, Katalog-Rückroute,
  sichtbaren HUD- und Animationsdocks und Qt-Schließen über die Suite.
- `pytest -q tests`: vollständiger verfügbarer Testbestand.

Die Laufzeit-Sprites und der isolierte Original-Engine-Snapshot bleiben
derselbe; die oben genannten Punkte betreffen vor allem die **tatsächliche
Brauchbarkeit, Datenintegrität und das Ein-Fenster-Erlebnis**. Die fehlenden
Unity-Spezialshader und die vollständige Gameplay-HUD-Parität sind weiterhin
offene technische Aufgaben.

## Zweite Prüfung am 11.10.2026: tägliche Benutzbarkeit und Kartenpersistenz

Die Hauptfenster-Integration wurde bei echten Tk/Qt-Reiterwechseln und
Code-Regressionen erneut untersucht. Zusätzlich sind folgende Probleme
korrigiert:

- **Animation / Frame-Test** wird nicht mehr als unsichtbarer Bottom-Dock
  zurückgelassen. Die äußere Suite-Oberfläche enthält direkt anwählbare
  **Animation / Frames**- und **Spiel-HUD**-Knöpfe.
- Das Rückspringen zum Asset-Katalog nimmt die **aktuell ausgewählte**
  Frame-ID der Vorschau, statt den veralteten Treffer des letzten
  Engine-Mausklicks zu bevorzugen.
- **Alt+F4 / Qt-Schließen** aus dem eingebetteten Fenster veranlasst
  über einen entkoppelten Qt→Tk-Rückruf das kontrollierte Schließen des
  gemeinsamen Hauptfensters einschließlich etwaiger Rückfragen zu
  ungespeicherten Änderungen. Ein einsamer, leerer Sandbox-Reiter
  soll dadurch nicht zurückbleiben.
- Beim ersten Start wird kein Entwicklerpfad mehr geraten. Die Quelle
  der Originalkarten stammt bevorzugt aus dem **zuletzt explizit
  gewählten** und atomisch gespeicherten
  `config/sandbox-maps.local.json`. Fehlt dieser, gilt ein gültiger
  `[target].game_dir` in `config/installations.local.toml`, andernfalls
  ein leerer Kartenkatalog mit **Kartenordner wählen**.
- Eine manuelle Wahl funktioniert auch in einem beliebig benannten
  Verzeichnis mit `.map`-Dateien. Die Wahl wird beim Folgestart
  wiederhergestellt. Das lokale Konfigurationsfile ist Git-ignoriert;
  Originalkarten bleiben unverändert.

Die Details, Prioritäten, Tests und offenen Langzeitthemen stehen im
`docs/SPRITESUITE_QUALITAETSPRUEFUNG_2026-10-11.md`.


## Bedienbarkeitskorrektur 2026-10-13: Arbeitsfläche vor Werkzeug-Chaos

Die vorherige technische Einbettungsabnahme konnte erfolgreich sein,
obwohl die Sandbox im Alltag schlecht nutzbar war: Der schmale
Karten-Ausschnitt lag zwischen einer breiten Sprite-Palette und
überlangen rechten Dock-Reitern. Die doppelt ausgeführte Größenanpassung
in Win32-Pixeln und Qt-Logikpunkten führte bei Windows-Skalierung
außerdem dazu, dass Teile des Qt-Fensters aus dem sichtbaren
Tk-Host herausragen konnten.

Das eingebettete Studio (nicht die eigenständige Diagnose-Anwendung)
nutzt nun `tools/sandbox_compact_layout.py`:

- **Karte im Vordergrund:** Die linke Palette startet eingeklappt,
  der wichtigste Karten-Inspector bleibt sichtbar. Die Arbeitsfläche
  ist in den gemessenen Testfenstern mindestens 55 % der Qt-Breite.
- **Kürzere und sichtbare Schalter:** Der äußere Tk-Reiter zeigt
  **Karte öffnen**, **Palette**, **Inspector**, **Fokus** und
  **Layout zurück**. **Weitere Werkzeuge** gruppiert die übrigen
  Funktionen, ohne sie aus der Anwendung zu entfernen.
- **Alle Werkzeuge erreichbar:** Rechts wird nur das aktuell
  gewünschte Werkzeug angezeigt. Eine explizit beschriftete
  Qt-Auswahlliste öffnet Karten-/Objekt-Inspector, Animation, Spiel-HUD
  sowie optionales Original-XAML-HUD. Nicht verfügbare lokale
  XAML-Dateien erzeugen weiterhin keinen falschen Freigabestatus.
- **Fokus und Rückweg:** `F9` blendet beide Seitenleisten aus;
  `F6` öffnet die Palette und `F7` den Inspector. Die
  Toolbar-Aktionen und der sichtbare Tk-Reiter bieten denselben
  Funktionszugriff auch ohne funktionierende Qt-Tastenkürzel.
  `Layout zurück` stellt ein vorhersehbares Standardlayout wieder her.
- **Rechte Formulare ohne horizontales Abschneiden:** Die langen
  Qt-Schaltflächentexte werden ausschließlich eingebettet verkürzt,
  ihre Erklärungen bleiben als Tooltips verfügbar. Der
  Karten-Inspector bleibt vertikal scrollbar, aber sein
  horizontaler Scroll-Überlauf beträgt bei den beiden geprüften
  Fenstergrößen null.
- **DPI- und Resize-Korrektur:** Nur Win32 `SetWindowPos`
  dimensioniert das tatsächliche eingebettete Kindfenster in
  *physischen* Pixeln. Das redundante `QWidget.resize()` mit
  denselben Zahlen ist entfernt. Nach dem Verarbeiten der
  `WM_SIZE`-Ereignisse werden die Docks passend zur echten
  *logischen* Qt-Fensterbreite verteilt.
- **Keine schwebenden Drittfenster:** Die eingebetteten
  Werkzeug-Docks sind nicht floatbar. Der eigenständige
  `sandbox_studio.py`-Diagnosestart behält unverändert seine
  Standalone-Aufteilung.

**Echte Windows-DPI- und Interaktionsmessung:**

| Suite-Fenster | Tk-Host (physische Pixel) | Qt-Ansicht (logisch) | Kartenansicht (logisch) | Inspector horizontal |
|---|---|---|---|---|
| 1500 × 930 | 1460 × 687 | 1168 × 550 | 872 × 459 | 0 Überlauf |
| 1020 × 680 | 980 × 437 | 784 × 350 | 505 × 259 | 0 Überlauf |

Die native QA kontrolliert außerdem Palette, Fokus, Inspector,
Werkzeugauswahl (inklusive wiederholter Wahl desselben HUD-Werkzeugs),
Layout-Rücksetzung, sichtbare Tk-Schaltflächen, Win32-Parent/Client-
Rechtecke, Katalogwechsel, Animation, Spiel-HUD und Schließlogik.
Die Qt-Interaktionsregression enthält getrennte kleine und große
Fenster, den horizontalen Inspector-Überlauf und das Unterbinden
unabhängiger schwebender Dock-Fenster.

Diese Abnahme betrifft **Benutzbarkeit und Einbettung**, nicht
den Beweis identischer Original-Shader oder vollständiger
Gameplay-HUD-Funktion im Spiel.
