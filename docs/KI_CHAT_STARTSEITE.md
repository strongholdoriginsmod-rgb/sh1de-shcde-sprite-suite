# KI-Chat auf der Startseite

**Gilt für den neuen Main-Quellstand.** Die erweiterte Startseiten-Einbettung,
Arbeitsmodi und lokale Gesprächsauswahl sind in älteren RC4-Paketen noch nicht
enthalten.

Die Startseite im Hauptfenster enthält den Chat mit Eingabe, Verlauf und
Optionen. Der Einstieg **KI-Assistent** führt zum selben Assistenten. Das
Gespräch arbeitet mit dem aktuell ausgewählten SpriteSuite-Projekt und dessen
vorhandenen Werkzeugen.

Voraussetzung ist ein installierter **offizieller lokaler Codex-Client**, der
als `codex` im Windows-Suchpfad erreichbar ist. Die Suite verwendet entweder
`codex.exe` oder eine vorhandene npm-Installation mit `codex.cmd` und
erreichbarem `node.exe`. Installation und Anmeldung beschreibt die
[offizielle Codex-CLI-Anleitung](https://developers.openai.com/codex/cli).
Das Windows-Startpaket richtet Python-Abhängigkeiten ein; es installiert den
Codex-Client nicht automatisch. Ein API-Schlüssel wird nicht benötigt.

## Anmelden und eine Aufgabe beginnen

1. Das gewünschte Projekt öffnen und auf die Startseite wechseln.
2. **Mit ChatGPT anmelden** verwenden. Die Anmeldung läuft über den lokalen
   Codex-Client und das reguläre ChatGPT-Anmeldefenster; dort kann, soweit für
   das Konto angeboten, auch Google verwendet werden. Ein API-Schlüssel ist
   dafür nicht erforderlich. Verfügbarkeit und Kontolimits gelten weiterhin.
3. Die Voreinstellung **Aufträge (alle Werkzeuge)** kann direkt verwendet
   werden. Unter **Optionen ▸ → ChatGPT und Arbeitsmodus** bei Bedarf den
   Arbeitsmodus, das Kontomodell oder die Denkstufe ändern.
4. Eine Frage oder einen konkreten Auftrag mit gewünschtem Ergebnis eingeben
   und **Auftrag senden** anklicken.
   Die Antwort und der Werkzeugstatus erscheinen im Gespräch. Ergebnisse wie
   geänderte Bilder oder ein Paket anschließend in der Suite prüfen.

## Den passenden Modus verwenden

| Modus | Verwendung |
| --- | --- |
| **Fragen (nur lesen)** | Das aktuelle Projekt und vorhandene Funktionen erklären oder untersuchen lassen. Dieser Modus dient dem Lesen und Antworten. |
| **Aufträge (alle Werkzeuge)** – Voreinstellung | Alle vorhandenen Projekt-, Editor-, GUI-, Fach- und Codewerkzeuge verwenden, einschließlich eigener Projektdateien und lokaler Python-Läufe. |
| **Programmieren (Projektdateien)** | Eine eigene Arbeitsausrichtung für Quelltextaufgaben wählen. Die Codewerkzeuge sind bereits im normalen Auftragsmodus verfügbar. |

Eine passende erste Frage ist beispielsweise: „Welche Grafiken liegen in
diesem Projekt, und welcher Atlasweg passt zu meinem PNG und XAML?“
Ein konkreter Auftrag lautet: „Öffne den Atlas-Arbeitsbereich und zeige mir,
welche Angaben für die Übertragung des ausgewählten SH1-Ausschnitts fehlen.“
Für eine Änderung das betroffene Asset beziehungsweise die Projektdatei und
das gewünschte Ergebnis benennen.

Im Auftrags- und Programmiermodus lassen sich normale UTF-8-Quelldateien im
Projekt lesen und schreiben, etwa Python, Lua, C#, JSON oder XAML. Eine Schreiboperation
prüft den zuvor gelesenen Datei-Hash und sichert eine vorhandene Version.
Eine inzwischen anderweitig geänderte Datei muss zuerst neu gelesen werden.
Das Schreiben von C#-Quelltext ist noch kein erfolgreicher DLL-Bau; dafür
müssen die passenden vorhandenen Buildwerkzeuge und Bibliotheken verfügbar
sein.

Der Assistent muss fehlende Dateiauswahlen oder erforderliche Eingabedaten melden.
Ein solcher Hinweis ist noch keine erledigte Dateioperation. Er führt die
vorhandenen Suite-Funktionen aus; eine Textantwort allein belegt keinen
erfolgreichen Export oder Spieltest.

## Modelle, Denkstufen und Python-Ausführung

Die Modellauswahl stammt aus der aktuellen lokalen Codex-/Kontositzung.
Unter **Modell aus Konto** mit **Modelle laden** verfügbare Modelle abrufen;
**Denkstufe** zeigt die dazu angebotenen Stufen. Beim bloßen Start der Suite
wird noch keine Modellabfrage ausgeführt. Deshalb gibt es hier keine
festgeschriebene Liste von Modellnamen oder eine für alle Modelle zugesicherte
Denkstufe. **Kontostandard** und **Standard** können verwendet werden, ohne
einen Modellnamen oder eine Denkstufe selbst einzutragen.

**Lokalen Pythonlauf erlauben** ist zunächst eingeschaltet. Der Assistent kann
damit bereits im normalen Auftragsmodus einen lokalen Python-Projektlauf
starten; ein Wechsel in **Programmieren (Projektdateien)** ist dafür nicht
nötig. Wer solche Läufe begrenzen möchte, schaltet die Option aus. Lesen und
Schreiben von Projektquelltext bleiben im Auftragsmodus verfügbar. Der
frei wählbare Fragenmodus bleibt lesend. Ein Python-Prozess läuft mit den Rechten des
angemeldeten Windows-Benutzers. Der Projektordner als Arbeitsverzeichnis,
Dateiprüfungen, Zeitlimit und Stoppen bilden **keine Betriebssystem-Sandbox**.

## Gespräche wieder öffnen

Der Verlauf ist lokal und an das jeweilige Projekt gebunden. Über die
Auswahl **Lokaler Verlauf** ein bisheriges Gespräch öffnen oder mit **Gespräch neu**
ein weiteres beginnen. Es werden höchstens zwanzig Gesprächsdateien je Projekt
und höchstens achtzig begrenzte Nachrichten je Gespräch gehalten; außerdem
gilt eine Grenze von 160.000 Bytes je Gesprächsdatei. An der Grenze von
zwanzig Gesprächen ein vorhandenes Gespräch auswählen; alte Gespräche werden
für ein neues nicht automatisch gelöscht.

Beim Wiederöffnen zeigt die Suite die gespeicherten Nachrichten an. Für den
nächsten Auftrag wird ein begrenzter Ausschnitt des bisherigen Gesprächs als
Kontext an eine neue Sitzung übergeben. Das ist keine unbegrenzte Erinnerung
und keine Synchronisierung mit dem ChatGPT-Webverlauf. Kontotokens, rohe
Werkzeugantworten und entfernte Sitzungskennungen gehören nicht zur lokalen
Verlaufsdatei. Eigene Nachrichten und Antworten bleiben Gesprächsinhalte.

Bei einem Projektwechsel wird der Assistent an den Verlauf und die Sitzung des
neuen Projekts gebunden. Der Verlauf eines anderen Projekts wird nicht als
Fortsetzung des neuen Projekts ausgegeben.

## Einen Auftrag stoppen und das Ergebnis prüfen

**Stoppen** unterbricht den aktuellen Auftrag und dessen laufende Werkzeuge.
Wartende, zur gestoppten Runde gehörende GUI-Aufrufe dürfen danach nicht
nachgeholt werden. Bereits abgeschlossene Änderungen bleiben erhalten.
Zum Rücknehmen die vorhandene **Rückgängig**-Funktion des betroffenen Editors
oder eine Projektsicherung verwenden; Stoppen ist kein gemeinsames Undo aller
vorherigen Arbeitsschritte.

**Details ▸** zeigt die begrenzten technischen Werkzeugantworten zur aktuellen
Arbeit. Der gespeicherte Gesprächsverlauf enthält dagegen die Nachrichten und
kurzen Werkzeugstatusmeldungen.

## Welche Funktionen der Assistent verwendet

Die neun nativen Werkzeuge verbinden den Chat mit den vorhandenen Funktionen:

| Werkzeug | Zweck |
| --- | --- |
| `suite_context` | Projektbestand und Inhalts-Hashes lesen, optional prüfen. |
| `suite_tool_catalog` | Die vorhandenen lokalen Fachwerkzeuge suchen. |
| `suite_tool_describe` | Argumente und statische Hilfe eines Werkzeugs lesen. |
| `suite_tool_run` | Ein bestehendes Suite-Fachwerkzeug mit seinen Argumenten ausführen, soweit der gewählte Modus und die Wirkungsklasse es erlauben. |
| `suite_project_op` | Vorhandene Projekt-, Import-, Prüf-, Sicherungs- und Paketfunktionen aufrufen. |
| `suite_ui` | Tatsächliche freigegebene GUI-Felder, Menüs und Editoraktionen bedienen. |
| `suite_editor` | Den verbundenen lokalen HTML-Sprite-Editor über seine nativen Aktionen und seine Historie bedienen. |
| `suite_sandbox` | Die bereits geöffnete Qt-Sandbox über ihre Schnittstelle bedienen. |
| `suite_code` | Projektquelltext im Auftrags- und Programmiermodus lesen und schreiben; lokale Python-Helfer direkt starten, solange die standardmäßig eingeschaltete Option **Lokalen Pythonlauf erlauben** aktiv ist. |

Die fachlichen Werkzeuge behalten ihre eigenen Prüfungen und Grenzen. Für den
lokalen HTML-Editor muss der gewünschte Tab verbunden sein. Atlasquellen,
Dateipfade, Ressourcenschlüssel und benötigte native Werkzeuge müssen zum
Auftrag passen. Ein gebautes Paket oder eine Vorschau bestätigt noch keine
Darstellung im laufenden Spiel.

Weiterführend: [Aktuelle Arbeitsabläufe](WORKFLOWS.md),
[PNG/XAML-Atlas](UI_ATLAS_PNG_XAML.md) und
[native Assistentenwerkzeuge](SPRITESUITE_NATIVE_ASSISTANT_TOOLS.md).
