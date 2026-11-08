# Native Schnittstelle des Sprite-Editors

`window.SuiteEditorAPI` bedient die vorhandenen Editorfunktionen. Die
Schnittstelle enthält keinen Modellzugang und benötigt keinen API-Schlüssel.
Ihre Installation öffnet keine Dateien, startet keine Bildgenerierung und
ändert kein Projekt. Die eigenständige HTML-Datei bleibt offline nutzbar.

`discover()` beschreibt Aktionen, Ansichten, Inspektorbereiche und die
JSON-Schemas der Operationen. `inspect()` liefert Projektzustand, Auswahl,
aktuelle native Steuerelemente, Formularzustand und einen `revision`-Token.
Jede Änderung muss diesen aktuellen Token als `expectedRevision` mitgeben.
Bei einer inzwischen geänderten Oberfläche oder Historie wird der Auftrag
mit `stale` abgelehnt. Animation und Zeichnen verändern den Token nicht.

```javascript
const current = SuiteEditorAPI.inspect();
const result = await SuiteEditorAPI.execute({
    operation: 'view.set', viewId: 'sprite', expectedRevision: current.revision
});
```

| Operation | Vorhandener nativer Weg |
| --- | --- |
| `action.invoke` / `actionId` | Registrierte Editoraktion, einschließlich Speichern, Exportdialog, Undo und Redo |
| `view.set` / `viewId` | Vorhandene Ansichtsumschaltung |
| `panel.set` / `panelId` | Vorhandener Inspektor und seine originalen Callback-Funktionen |
| `selection.set` / `frameIds` | Derselbe Auswahlhelfer wie die Spriteliste, einschließlich Strg-Mehrwahl; eine Gruppe pro Auswahl |
| `canvas.gesture` / `points`, `button` | Vorhandene Pointer-Handler und derselbe Stroke-Abschluss; Koordinaten aus `inspect().model`, optionale boolesche `ctrlKey`/`shiftKey` |
| `field.set` / `fieldId`, `value` | Aktuelles DOM-Feld mit seinen normalen `input`- und `change`-Ereignissen |
| `control.invoke` / `controlId` | Aktuell vorhandener nativer Button-Callback |
| `control.files` / `controlId`, `files` | Originaler dateibezogener Button-Callback; seine nächste Dateiauswahl erhält die ausdrücklich bereitgestellten Dateien |
| `form.read` / `formId` | Felder des gerade offenen nativen Formulars |
| `form.fill` / `formId`, `values` | Formularfelder nach ID; Typen/Optionen werden vor dem Füllen geprüft |
| `form.submit` / `formId` | Bestehender Formularhandler mit seiner Validierung und Historie |
| `project.open` / `files` | Bestehender Projektleser, mit ausdrücklich bereitgestellten Dateidaten |
| `files.import` / `files` | Bestehender Importdialog mit bereitgestellten Dateien; Übernahme über sein natives Formular |

Dateien haben das Format `[{name, base64}]`. Zulässig sind die bestehenden
Importformate PNG, JSON, ZIP, CSV und SHSPRITE mit portablen Dateinamen.
Die bestehenden Datei-, Import-, Archiv-, Bild- und Pixelbudgets bleiben
wirksam. Der Browser erhält keinen beliebigen Dateisystemzugriff. Ein nativer
Aufruf, der eine Dateiauswahl benötigen würde, liefert `input_required`.

Antworten sind `{ok:true, revision, result}` beziehungsweise
`{ok:false, revision, error:{code,message}}`. Zu den Fehlercodes gehören
`busy`, `unknown`, `disabled`, `stale`, `invalid`, `input_required`, `canceled`
und `native_error`. Die laufende Aktion wird durch einen parallel
abgelehnten Aufruf nicht freigegeben.

`canvas.gesture` nimmt 1–256 Modellpunkte `{x,y}` mit endlichen Koordinaten
zwischen −131072 und 131072 an. `button:0` ist die linke, `button:1` die
mittlere Taste. Ein Punkt ist ein Tap, mehrere Punkte bilden einen Stroke.
Für eine Messung werden wie in der Oberfläche zwei getrennte Taps gesendet.
`inspect().model.items` enthält Frame-IDs und Rechtecke; `model.transform`
beschreibt die aktuelle Ansicht. Der Adapter verwendet eine feste Transformation
für den gesamten Stroke und ruft die bestehenden Pointer-Handler direkt auf.
Pfadlänge und Pinselarbeit sind begrenzt. Ein echter laufender Benutzerdrag
blockiert native Aufträge mit `busy`. Abbruch vor dem Stroke-Abschluss verwirft
den unveröffentlichten Drag beziehungsweise die Pinselmaske. Ein Pivot-Tap kann
bereits beim Pointerdown eine Historienänderung erzeugen; ein danach eintretender
Abbruch meldet das mit `error.completedChanges:true`. Die vorhandene Undo-Historie
bleibt maßgeblich. Die Schnittstelle führt keine zweite Bildbearbeitungs- oder
Undo-Implementierung ein.

## Lokale Desktop-Verbindung

Nur die Loopback-Version aktiviert den Transport. Der gewünschte Tab wird
ausdrücklich über **Projekt → Assistent verbinden** oder über die Auswahl
seiner `pageId` im Desktopclient verbunden. Ein Heartbeat wählt keinen Tab.
Der verbundene Tab bleibt ausgewählt, wenn der Benutzer zum Suite-Chat
wechselt. Eine neue ausdrückliche Auswahl löst die alte Lease ab.

Die lokale Capability steht ausschließlich in der ignorierten Datei
`work/session-registry.json`: Schema `spritesuite.editor.session.v1`,
`serverPid`, `origin`, zufällige `sessionNonce`, `createdUtc`, `expiresUtc`
und `expiresAt`. Sie enthält keine Kontozugangsdaten. Die Nonce wird intern
gelesen und erscheint nicht in Modellantworten oder Zustandsberichten.
Desktopanfragen verwenden `X-SpriteSuite-Desktop-Session`; Browseranfragen
verwenden die vorhandene Browser-Session und den exakten eigenen Origin.
Host und Rollen werden auf allen Routen geprüft.

| POST-Route | Rolle und Verhalten |
| --- | --- |
| `/native/state` | Desktop: Seitenliste, aktive Seite, Zustand und Discovery; optional `activatePageId` |
| `/native/execute` | Desktop: `request`, optional `pageId`, `commandId` und `timeoutMs` |
| `/native/cancel` | Desktop: `commandId`; meldet `canceled`, `cancel_requested` oder `completed`, niemals eine erfundene Rücknahme |
| `/native/poll` | Browser: Zustand/Heartbeat und einmalige Auslieferung wartender Aufträge |
| `/native/result` | Browser: erneute Lease-/Fristprüfung vor Ausführung und danach das native Ergebnis |

Nach 30 Sekunden ohne Heartbeat ist eine Seitenlease ungültig. Ein Auftrag
hat eine eigene Frist und wird höchstens einmal ausgeliefert. Abgelaufene
oder gestoppte Aufträge verschwinden aus der Warteschlange. Abbruch vor
einem später eintreffenden Execute wird ebenfalls gespeichert. Laufende
Aufträge erhalten ein Abbruchsignal; vorhandene Import-/Exportabbrecher
und Prüfungen vor Commit, Projektwechsel und Download verwenden es.
Bereits abgeschlossene Änderungen werden durch einen Stopp nicht als
zurückgenommen ausgegeben.

## Reproduzierbare Prüfungen

`node --test tests/test_native_api.cjs` prüft native Weiterleitung, Fehler,
Feldereignisse, Formularfluss, Parallelität und Abbruch. Der echte
Chromium-Test `node tests/test_native_browser.cjs` prüft die gebaute HTML,
Undo, Dateirundlauf und kleine Browserhöhen: 1280×480, 1024×540, 800×500 und
640×360. Dabei müssen native Werkzeugaktionen, letzte Inspektorfelder und
Formularfooter über echte benutzbare Scrollbereiche erreichbar bleiben.
`node tests/test_native_gesture_browser.cjs` prüft beide Sprachfassungen mit
je acht echten Browserfällen: Drag, Pan/Fit, Messung, Pivot, Pinsel, Abbruch,
Schutz eines laufenden Benutzerdrags und ungültige Eingaben. Undo/Redo werden
gegen Projektzustand und Canvas-SHA geprüft; Pinselabbruch muss Zustand,
Assetstore und Historie erhalten.

Der Suite-Test `tests/sandbox/test_sprite_editor_native_broker.py` prüft
Leases, HTTP-Rollen, Fristen, Stopprennen und unveröffentlichte Capabilities.
Mit `SPRITESUITE_RUN_NATIVE_BROWSER=1` führt
`tests/sandbox/test_sprite_editor_native_browser.py` den echten
`EditorNativeClient` gegen den Server und einen frischen Browser aus.
Er pausiert den Renderer gezielt vor einem wartenden Löschauftrag, stoppt
über den Desktopclient und bestätigt nach Wiederaufnahme den unveränderten
synthetischen Projektzustand. Echte Spiele und Benutzerprofile werden
dabei nicht verwendet.
