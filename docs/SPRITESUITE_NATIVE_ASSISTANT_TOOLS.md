# Gemeinsame native Werkzeuge des Suite-Assistenten

## In der Suite verwenden

Links **KI-Assistent** öffnen. **Anmelden** verwendet den vorhandenen lokalen
Codex-Client und dessen verwaltete ChatGPT-Anmeldung. Ein Google-Login erfolgt,
soweit vom Konto angeboten, im normalen Anmeldefenster. Die Suite benötigt
keinen API-Schlüssel und verspricht keine von den Kontolimits unabhängige Nutzung.
Das Gespräch erhält den aktiven Projektkontext. Beispiele für Aufgaben sind
„Prüfe die Assets und zeige beschädigte Masken“, „Erstelle eine transparente
Grafik und sichere das Projekt“ oder „Öffne die KI-Werkstatt für das ausgewählte
Original und bereite drei Schadensvarianten vor“.

Der Host `suite_ai_assistant.py` verbindet `suite_ai_session.py` mit den unten
beschriebenen Werkzeugen. Er streamt Antworttext und zeigt Werkzeugstatus,
Fehler und Abbruch an. **Abbrechen** unterbricht den aktuellen Turn und laufende
Werkzeuge. Wartende GUI-Aufrufe gehören zu genau dieser Runde; ein späterer
Start darf abgebrochene Aufrufe nicht nachholen. Die letzte normale
Benutzerentscheidung über Projektwechsel und ungespeicherte Editoren gilt
auch für den Assistenten.

| Weitere native Schnittstelle | Verwendung |
| --- | --- |
| `suite_ui` | Tatsächliche Tk-Controls und Menüeinträge lesen, suchen, fokussieren und bedienen; Texteditoren, Listen und Skalen bearbeiten sowie native Canvasgesten ausführen. Änderungen benötigen den aktuellen `state_token`. |
| `suite_editor` | Geöffneten lokalen HTML-Editor aktivieren und über seine vorhandenen Aktionen, Formulare und Importfunktionen bearbeiten; Änderungen benötigen die aktuelle Editorrevision. |
| `suite_sandbox` | Bereits geöffnete Qt-Sandbox und ihre Szenenhistorie lesen und bedienen; Änderungen benötigen deren aktuellen Token. |

Snapshots sind filterbar und paginiert. Ausgewählte lokale Dateien können dem
HTML-Editor direkt übergeben werden; Bilddaten müssen nicht als Text durch das
Modell laufen. Der lokale Browserkanal verwendet eine kurzlebige Capability
und akzeptiert ausschließlich Loopback. Kontotokens sind kein Teil des Kanals.
Die Browseroperationen sind in [NATIVE_API.md](../extras/sprite-editor/dokumentation/NATIVE_API.md)
beschrieben. Dialoge mit noch fehlender Auswahl melden `input_required` zurück.
Eine solche Rückgabe wird nicht als abgeschlossene Dateioperation dargestellt.

`suite_ui` mit `operation: "gesture"` benötigt die aktuelle `widget_id`,
`expected_state` und 1–128 lokale sichtbare Punkte als `[[x,y], ...]`.
Optionale `modifiers` sind `shift` und `control`. Vor dem ersten Ereignis werden
alle Punkte geprüft. Die vorhandenen Pixel-, HUD-Layout-, SH1-HUD- und
Origins-Editoren erhalten ihre ursprünglichen Press-/Motion-/Release-Ereignisse;
ihre eigene History bleibt für Undo zuständig. Modell-/Bild-SHA und Historie
gehören zum Zustandstoken. Ein laufender Benutzerdrag blockiert einen neuen
Auftrag. Beim Abbruch können bereits angewandte Änderungen bestehen bleiben;
der Host meldet dies und schließt die native Geste am letzten ausgeführten Punkt.
Eine Rücknahme wird nicht erfunden.

`set` auf einem nativen Texteditor ersetzt dessen Inhalt als eigenen Undo-Schritt
und löst die vorhandene Änderungsanzeige aus. Da der Snapshot lange Texte kürzt,
benötigt ein vollständiger Ersatz eines solchen Textes zusätzlich
`replace_full_text: true`. Dieses Argument bestätigt den beabsichtigten ganzen
Ersatz innerhalb des Werkzeugaufrufs. Deaktivierte Controls, Passwortfelder und
ungültige Auswahlwerte bleiben unverändert.

Die dynamischen Tools und das App-Server-Protokoll sind experimentelle
Codex-Schnittstellen. Ein verfügbarer kompatibler Codex-Client, eine angemeldete
ChatGPT-Sitzung und freie Kontokapazität sind Voraussetzungen. Der Assistent
kann Aufruffehler machen; strukturierte Fehler, Zustandskontrollen und Undo
erleichtern die Korrektur. Ein Testlauf ersetzt keine Prüfung jeder denkbaren
Aufgabe oder die offene echte HP-/Feuer-Abnahme im Spiel.

## Projekt- und Fachwerkzeuge

`tools/suite_native_tools.py` stellt die vorhandenen lokalen Fachwerkzeuge
und die zentrale Projektpipeline als strukturierte Funktionen bereit. Die
Konversationsschicht verwendet dafür `NativeToolService`. Diese Schicht
enthält keine Modell-Endpunkte und benötigt keinen API-Schlüssel. Anmeldung,
ChatGPT-/Codex-Konto, Konversation und GUI-Aktionen werden vom Host verwaltet.

```python
from pathlib import Path
from suite_native_tools import NativeToolService

service = NativeToolService(
    project=Path("work/mein-projekt"),
    approval=lambda request: host_approval(request),
)
dynamic_tools = service.specs()
answer = service.call("suite_context", {"limit": 100})
```

`specs()` liefert unabhängige JSON-Werte mit `type: "function"`, stabilem
`name`, `description` und typisiertem `inputSchema`. Der Host kann seine
GUI-Werkzeuge ergänzen. `call(name, args)` gibt entweder
`{"ok": true, "result": ...}` oder
`{"ok": false, "error": {"code": ..., "message": ...}}` zurück.
Fehler eines ausgeführten Werkzeugs enthalten begrenzte Ausgaben unter
`error.details`. Allgemeine interne Exceptions geben ihren Typ, jedoch
keinen möglicherweise vertraulichen Exceptiontext zurück.

| Werkzeugname | Funktion |
| --- | --- |
| `suite_context` | Aktuelles Projekt, Asset-IDs, Größe, Inhalts-SHA-256, Kategorien und optional vollständiges Pipeline-Audit |
| `suite_tool_catalog` | Alle lokalen Python-/PYW-Fachmodule mit statischen CLI-Deklarationen, Suche und Pagination |
| `suite_tool_describe` | Beschreibung, Quell-SHA und statische Argumenthilfe eines Moduls |
| `suite_tool_run` | Vorhandenes Fachwerkzeug mit unveränderter Argumentliste ausführen |
| `suite_project_op` | Echte Operationen der vorhandenen Projekt-, Paket- und Transferfunktionen |

Inventare verwenden `offset` und `limit`. Die Antwort enthält `total` und
gegebenenfalls `next_offset`. Asset-IDs haben die Form `asset:<relativer Pfad>`,
Werkzeug-IDs die Form `tool:<Dateiname>`. Der Katalog importiert keine
Fachmodule. Auch `suite_tool_run` mit `--help` oder `-h` liefert ausschließlich
statisch ausgewertete Hilfe und führt das gewählte Skript nicht aus.
Ein leerer Projektkontext bleibt erfolgreich lesbar. Bei `include_audit: true`
enthält er dann `audit.ok: false` und den Hinweiscode `no_assets`. Beschädigte
vorhandene Assets erzeugen weiterhin einen echten Fehler `asset_audit_failed`
mit dem bereits ermittelten Kontext unter `error.details.context`.

Ein Werkzeugaufruf erwartet `name`, `arguments: list[str]` und optional
`timeout_seconds` zwischen 1 und 300. Die Standardgrenze beträgt 120 Sekunden.
Die Ausführung verwendet direkt `[sys.executable, tool_path, *arguments]`
mit `shell=False`. Ein eigener temporärer Ordner hält Standardausgabe und
Fehlerausgabe. Die Rückgabe ist je Stream auf 32 KiB begrenzt. Anhaltende
Ausgaben über insgesamt 4 MiB beenden den eigenen Prozessbaum. Der Host
kann `cancel()` von einem anderen Thread aufrufen. Vor einer neuen Runde
ruft er `reset_cancel()` auf, bevor Login-, Netzwerk- oder Workerarbeit
beginnt. Ein früh eingetroffener Abbruch wird beim Prozessstart nicht gelöscht.

Eine optionale `runner(command, **subprocess_kwargs)`-Funktion kann für
kontrollierte Host-Ausführung eingesetzt werden. Sie übernimmt dann selbst
die Prozess- und Abbruchsteuerung. Die Ausgaben der injizierten Funktion
werden ebenfalls vor der Rückgabe begrenzt.

Der vorhandene `suite_tool_policy.classify` bestimmt die Wirkungsklasse.
`game` und `unknown` benötigen eine ausdrückliche Hostfreigabe. Dasselbe
gilt für als `destructive: true` deklarierte bestehende Operationen.
Normale `workspace`-Aktionen lösen keine zweite Rückfrage aus.
`approval(request)` erhält Werkzeug, Argumente, Kategorie, Beschreibung,
Projekt und Destruktivkennzeichen. Nur der boolesche Wert `True` gibt den
Aufruf frei. Ohne Callback lautet der Fehler `approval_required`.

`suite_project_op` verwendet diese Operationen:

| Operation | Benötigte Eingaben |
| --- | --- |
| `create_image` | `name`, `width`, `height`, optional `category` |
| `import_image` | `source`, optional `category` |
| `import_mod_file` | `source`, `relative_path` |
| `import_patch` | `source`, optional `game_document` |
| `inspect` | `relative_path` |
| `audit` | Keine weiteren Eingaben |
| `build` | `guid`, `name`, optional `author`, `version`, `output` |
| `backup` | `output` als neues Projekt-ZIP |
| `restore` | `source` als Projekt-ZIP, optional `project_name` |
| `new` | `name` als Projekt-ID der bestehenden Pipeline |
| `open` | `project` als vorhandener Projektordner |

Bildimport, Moddateien, Patches, Audit und Mod-ZIP stammen unmittelbar aus
`ProjectPipeline`. Sicherung und Wiederherstellung verwenden
`hud_menu_project_transfer`. Eigene DLL-, Lua- und andere Dateiformate und
eigene Versionsbezeichnungen bleiben durch die bestehenden Fachfunktionen
bearbeitbar. Die vorhandenen Pfad-, Inventar- und SHA-Prüfungen gelten weiter.
Originaldateien werden nicht als Bearbeitungsziel verwendet. Neue Ausgaben
ersetzen keine vorhandenen Sicherungen oder Pakete.

`new`, `open` und `restore` setzen `service.project` auf das erfolgreiche
Ziel und liefern `result.project`. Vor einem solchen Projektwechsel muss
der GUI-Host auf dem Mainthread ungespeicherte Editorzustände behandeln.
Danach kann er seine Ansichten mit dem zurückgegebenen Projekt synchronisieren.
Der native Service importiert keine GUI-Komponenten.

Bekannte Credential-Verzeichnisse und Credential-Dateien werden vor einem
Dateiimport oder Werkzeugaufruf abgewiesen. Projektkontext zeigt für solche
bereits vorhandenen Einträge weder Inhalt noch Inhalts-Hash. Ein vollständiges
Audit, Export oder Backup eines solchen Projekts wird abgewiesen. Der Service
liest keine Anmeldedateien und entfernt API-Schlüssel aus der Umgebung seiner
Python-Unterprozesse.

Die Tests in `tests/sandbox/test_suite_native_tools.py` verwenden synthetische
Projekte. Sie prüfen den echten Weg Import → Pixeländerung → ZIP → Sicherung
→ Wiederherstellung, Unicode-Argumente, Traversalabwehr, Wirkungsfreigaben,
Fehlercodes, Ausgabebegrenzung, Timeout, laufenden Abbruch und dessen Reset.
Sie starten kein Spiel und führen keine Konto- oder Netzwerkanmeldung aus.

## Bestehende Qt-Sandbox

`tools/suite_native_qt.py` ergänzt `NativeQtTools(provider)` mit dem Tool
`suite_sandbox`. Der Provider gibt das bereits vorhandene Sandbox-QWidget
zurück. Der Adapter besitzt den Marker `requires_gui_thread = True` und muss
vom Host auf dem tatsächlichen Qt-GUI-Thread aufgerufen werden. Er erzeugt
weder `QApplication` noch ein Fenster oder einen Thread. Ist Qt oder das
Fenster noch nicht verfügbar, liefert er einen erfolgreichen Kontext mit
`available: false` und `code: "not_available"`. Die Suite kann dann über ihren
vorhandenen UI-Aufruf die Sandbox öffnen und erneut einen Snapshot anfordern.

`operation: "snapshot"` liefert `items`, `token`, `window_title` und die
vorhandene Szenenhistorie unter `scene`. Die Controls haben stabile `qt:`-IDs,
Qt-Klasse, Objektname, Label, enabled/visible, zulässige Operationen und ihre
aktuellen Eingaben oder Auswahlwerte. Die Antwort ist mit `query`, `offset`
und `limit` filter- und paginierbar. Lange Texte werden für die Anzeige
gekürzt und zusätzlich vollständig gehasht. Passwortfelder werden weder
ausgelesen noch schreibbar angeboten.
`scene.placements` und `native_overlay.placements` enthalten die tatsächlichen
Objekt-IDs, Gruppen, Frames, Kachelpositionen und Teamfarben. Dieselben
Paginationseingaben gelten für diese Listen. Ein Zustands-Token berücksichtigt
die vollständigen Modell-SHA, auch wenn nur eine Seite angezeigt wird.

Jede Änderung benötigt `token` aus einem aktuellen Snapshot. Andernfalls
lautet der Fehler `stale_state`, bevor ein Callback ausgeführt wird. Die
Control-Operationen `activate`, `set_text`, `select`, `set_checked` und
`set_number` benötigen außerdem `id`. Sie bedienen ausschließlich konkrete
Qt-Klassen über `click`, `trigger`, `setText` mit `editingFinished`,
`setCurrentIndex`, `setChecked` oder `setValue`. Eine freie Methodenauswahl
oder Codeauswertung ist nicht vorgesehen. Die bestehenden Signalverbindungen
bleiben für Speicherung, Auswahl, Pivots und Undo zuständig.

`scene_load` und `scene_save` benötigen einen ausdrücklichen `path`. Sie rufen
die vorhandenen Methoden `load_test_scene` und `save_test_scene` auf.
`scene_save` verlangt eine neue Ausgabedatei. `undo`, `redo` und `zoom` nutzen
`undo_test`, `redo_test` und `zoom_active`. Zoom benötigt einen positiven
Faktor unter `number`. Szene, Auswahl und View-Transformation werden direkt
aus dem vorhandenen Modell beziehungsweise Qt-View ermittelt.

Die Operationen `scene_place`, `scene_move`, `scene_delete` und `scene_select`
bearbeiten ausdrücklich das isometrische Sprite-Testfeld. Sie benötigen einen
echten `SpriteTestBoard` und dessen vorhandene `SceneHistory`. `scene_place`
erwartet `group`, `frame`, `x`, `y` und optional `team`. Die Assetbezeichnung
wird durch den vorhandenen Suite-Katalog aufgelöst. Eigene Gruppen werden
wie in der bestehenden editierbaren Gruppenauswahl behandelt. `scene_move`
benötigt `object_id`, `x` und `y`. Löschen und Auswahl benötigen die aktuelle
`object_id`. Die Modellvalidierung erfolgt vor der Änderung. Anschließend
aktualisiert der vorhandene `board.rebuild` die Grafik und Inspector-Signale.
Undo und Redo arbeiten mit derselben Historie. Originalkarten und Quelldateien
werden durch diese Objektoperationen nicht verändert.

Dateidialoge, Nachrichten-, Eingabe- und modale Dialoge werden nur während
eines einzelnen nativen Aufrufs abgefangen und sicher abgebrochen. Die
Antwort `input_required` enthält Dialogbeschreibung und Zustand nach dem
Callback. Eine bereits erfolgte Änderung ist über `changed`, den neuen
Snapshot und `return_value` sichtbar. Die globalen Qt-Methoden werden im
`finally`-Pfad vollständig wiederhergestellt. Qt-Slotfehler werden als
`callback_failed` mit Exceptiontyp erfasst, ohne vertraulichen Exceptiontext
auszugeben. Native Projekt-/Dateioperationen bleiben für bereits bekannte
Dateipfade der direkte Weg.

`tests/sandbox/test_suite_native_qt.py` prüft reale Qt-Controls und eine echte
`SandboxStudio`-Instanz mit ausdrücklich synthetischer Szene, gemeinsamer
Undo-Historie, Zoom, Save-As, Tokenwechseln, Threadprüfung und Dialogabfang.
Es wird keine Ingame- oder Originalgrafikprüfung daraus abgeleitet.
