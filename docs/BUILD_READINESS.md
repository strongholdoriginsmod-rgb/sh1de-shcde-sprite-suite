# Sprite Suite: Bauvoraussetzungen vor dem BC7-Paketbau

**Stand: 12. Oktober 2026.** Eigenständige, vor dem Bau nutzbare
und nicht installierende Projektprüfung.

## Warum die Funktion nötig ist

Die frühere Einrichtungskontrolle der Suite ist bewusst nachsichtig:
Im Standardmodus kann sie Fehler als Warnungen protokollieren und ihren
Ablauf ohne harten Abbruch beenden. Ein tatsächlicher BC7-Neubau
benötigt trotzdem das exakt festgeschriebene Unity 2021.3.45f2,
Originalspiel-Pfade, das Mapping und gegebenenfalls ein .NET-SDK.

Die neue Bauvoraussetzungsprüfung nennt deshalb klare **Blockaden**
und unterscheidet sie von unverbindlichen Hinweisen. Eine grüne
Anzeige bedeutet ausschließlich, dass ein **Bauversuch möglich**
erscheint. Sie ist keine Bestätigung eines tatsächlich ausgeführten
Builds, keiner vollständigen BC7-Qualitätsprüfung und keiner
Ingame- oder Releasefreigabe.

## Bedienung in der normalen Hauptanwendung

Unter **Paket bauen** zuerst das gewünschte Profil im globalen
Vorlagenwähler auswählen. Optional die Eingaben für Unity und
.NET-SDK unter **Einrichten** auswählen und speichern. Anschließend
**Bauvoraussetzungen prüfen** drücken.

Die Kontrolle läuft in einem Hintergrundthread. Eine Statuszeile
meldet Blockaden und Hinweise; ein lesbarer Detaildialog zeigt
zu jeder Bedingung die Feststellung und den **nächsten Schritt**.
Über **Zu Einrichten** gelangt man direkt zum Setup-Reiter.

Wird während der Prüfung die Profilauswahl, ein Spiel-, Unity- oder
SDK-Pfad oder die Option **Vorhandene Paketausgabe ersetzen** geändert,
wird das vorherige Resultat **als veraltet verworfen**.
Es kann niemals durch eine alte Prüfung ein Paket gestartet werden.

**Paket bauen (mit Vorprüfung)** startet nun ebenfalls zuerst einen
neuen Hintergrund-Prüflauf. Bei Blockaden öffnet er nur die
Handlungsempfehlungen. Bei blockadenfreiem Ergebnis fragt die Suite
ausdrücklich nach, ob der konkrete Bauversuch gestartet werden soll
(Standardauswahl **Nein**). Erst nach Zustimmung werden sämtliche
gebundenen Konfigurations-, Mapping- und Profilhashes sowie das
Vorhandensein der Paketausgabe nochmals überprüft. Ein geänderter
Ausgabeordner darf nicht unbeabsichtigt überschrieben werden.
Der reguläre Builder führt anschließend zusätzlich seine eigenen
vollen Verträge und Transaktionsschutzprüfungen aus.

## Was tatsächlich geprüft wird

| Kategorie | Verhalten |
| --- | --- |
| Profil | Existenz, Größe, SHA-256, tatsächliche Profil-ID, gültiger Atlas-/Gruppenvertrag |
| Originalspiele | Gültige lokale Installationskonfiguration, SH1DE- und SHCDE-resources.assets, Zielspielordner |
| Mapping | Sicherheitsbegrenzt entpackte Original-GZIP, strenges JSON, Quell-/Ziel-Build-IDs, SHA-256 |
| Unity-BC7 | Exakt festgeschriebener Unity-Editor 2021.3.45f2, Revision, tatsächlicher Executable-SHA |
| .NET-SDK | Bei Runtime-Profilen vorhandene SDK-Dateistruktur und stabile SDK-Version ab 8.0.100 |
| Paketausgabe | Schon existierender Ordner und bewusste Ersetzen-Wahl; Link-/Junction-Pfade werden blockiert |

Der .NET-SDK-Test liest nur die Ordner-/Versionsstruktur;
er **startet dotnet nicht**. Er sucht zuerst nach verwendbaren
stabilen SDKs in PATH, danach in portablen `work/toolchains/dotnet-*`-
Installationen, DOTNET_ROOT und üblichen Systemverzeichnissen. Ein
reines Runtime-Verzeichnis oder eine veraltete SDK-Version wird
übersprungen; ein passendes SDK kann daher ohne PATH-Änderung
automatisch gefunden werden. Ein explizit gewählter, aber ungültiger
Pfad wird **nicht stillschweigend umgedeutet**. Die GUI schlägt
ein automatisch gefundenes SDK im Einrichten-Feld vor.

Dieselben Suchregeln gelten für den tatsächlichen Runtime-Builder.
Vor dem Build führt er zusätzlich `dotnet --version` aus und prüft
die Mindestversion; ein bloßer Ordnerfund ersetzt diese Prüfung nicht.
Auch der Unity-Editor wird in der Vorprüfung nur auf seine
Originalidentität geprüft, nicht gestartet.
Der Inhalt der Originalspiel-resources.assets wird in diesem
schnellen Bereitschaftscheck **nicht** erneut inventarisiert;
ein tatsächlich gebautes Bundle wird hier nicht getestet.

## Kommandozeile

Im Projektverzeichnis:

~~~powershell
.\.venv\Scripts\python.exe tools\qa_suite_build_readiness.py --profile sprite-suite-world-bc7-v2
~~~

Optional mit den **zuvor unter Einrichten gespeicherten** Toolchain-Pfaden
(die CLI-Argumente prüfen die Übereinstimmung, speichern sie aber nicht):

~~~powershell
.\.venv\Scripts\python.exe tools\qa_suite_build_readiness.py --profile sprite-suite-world-bc7-v2 --unity "C:\Pfad\Editor\Unity.exe" --dotnet "C:\Program Files\dotnet"
~~~

Die lokale Toolchain-Konfiguration aus
config/toolchains.local.json wird dabei ebenfalls geprüft und mit ihrem
SHA-256 an den Bericht gebunden. Die neue **Einrichtungsstatus**-Anzeige
ist dagegen absichtlich nachsichtig: Beschädigtes JSON erscheint dort
als Warnung und verhindert nicht die Arbeit in anderen Suite-Bereichen.
Ein tatsächlicher BC7-Paketbau verwendet weiterhin die strenge
Konfigurations- und Hashvalidierung. Ein nur im Eingabefeld ausgewählter
Unity- oder SDK-Pfad, den der spätere Builder nicht tatsächlich verwendet,
ist **eine Blockade**, kein grüner Bereitschaftsstatus.
Entsprechendes gilt für nicht gespeicherte Originalspielpfade in der GUI.
Wer statt des kanonischen `*_Data`-Ordners den übergeordneten
Originalspiel-Installationsordner ausgewählt hat, wird dagegen
**nicht** fälschlich als unspeicherte Abweichung gemeldet: Beide
Auswahlformen entsprechen demselben geprüften Spielverzeichnis.
Unter **Einrichten → Pfade speichern** lassen sich Werkzeugpfade
auch ohne bereits konfigurierte Originalspiele sichern.

Die optionale Ersetzen-Auswahl der Hauptanwendung lässt sich über
--replace abbilden. Ohne Ersetzen sperrt eine bestehende Paketausgabe
den Neubauversuch; mit Ersetzen erscheint ein ausdrücklicher Hinweis.

**Exitcode 0:** keine sichtbaren Blockaden vor dem Bauversuch,
aber keine Releasefreigabe.

**Exitcode 2:** mindestens eine Blockade oder ein fehlerhafter Prüflauf.

Es werden keinerlei Build-, Installations-, Spiel-, Profil- oder
Cachedateien verändert und kein neuer Bericht geschrieben.
Eine Windows-Konsole mit älterer Zeichenkodierung gibt nicht
darstellbare Unicode-Zeichen sicher als Ersatzfolgen aus.

## Tatsächliche Projektkontrolle

Für das aktuelle Profil sprite-suite-world-bc7-v2 meldet der
Nur-Lesen-Check nach der kompatibleren SDK-Erkennung derzeit
**zwei** konkrete Hindernisse: fehlende lokale Spielpfadkonfiguration
und der nicht vorhandene **exakt gepinnte** Unity-2021.3.45f2-Editor.
Das portable **.NET SDK 10.0.401** unter `work/toolchains` wird
dagegen als vorhanden erkannt, selbst ohne PATH-Eintrag (reiner
Dateistrukturcheck; das Programm wird hierfür nicht gestartet).
Das Profil und das Mapping mit 135.354 Spritevorschlägen sind
lesbar und vertragsgemäß. Weil die lokale Spielkonfiguration fehlt,
ist auch das Ausgabeziel nicht zuverlässig bestimmbar.

Ein schon erfolgreich veröffentlichter Produktionsbau ist davon
zu unterscheiden. Dessen Hash-Integrität kann weiterhin mit dem
separaten SHA-256-Release-Preflight geprüft werden, selbst wenn
die zum vollständigen **Neubau** erforderlichen Installationen
lokal nicht mehr vorhanden sind.

## Nach dem Bau: Historie nach Neustart

**Bauverlauf anzeigen** liest die lokalen start-/abschlussgebundenen
Bauereignisse und verifiziert ihre SHA-256-Verkettung.
Ein vorzeitig beendeter Bau wird nach einem Neustart nicht
als Erfolg dargestellt. Ein beschädigter Verlauf blockiert
stattdessen den nächsten Start, bis die Ursache ausdrücklich
geklärt ist. [Dauerhafter Bauverlauf](BUILD_HISTORY.md).

## Regression und Sicherheit

- Tests mit synthetischen Profilen/Pfaden beweisen, dass ein
  gültiger Zustand nur den Bauversuch, nie die Freigabe signalisiert.
- Entfernte Bildressourcen, Mappingdateien, falsche Unity-Hashes,
  fehlende SDKs, fremde Profil-IDs, unerlaubte Linkziele sowie
  während der Prüfung veränderte Dateiprüfsummen blockieren.
- Vorhandene Pakete werden mit und ohne bewusste Ersetzen-Wahl
  ohne Schreibzugriff beurteilt. Neu entstandene Ausgabeordner,
  umbenannte oder manipulierte Eingangskonfigurationen und
  während der Bestätigung geänderte Einstellungen stoppen den Bau.
- Die CLI-Baufolge behandelt ihre abschließende Paketvalidierung
  jetzt auch im Nachsichtmodus **immer als verpflichtend**:
  ein fehlgeschlagener Validator ergibt einen Fehlercode, niemals
  einen fälschlichen Erfolg.
- tests/sandbox/test_suite_build_readiness.py prüft die
  Kernlogik, CLI-Zeichensatzsicherheit und echte Projektbeobachtung.
- tests/sandbox/test_suite_build_readiness_gui.py prüft
  die Bedienung in der realen Tk-Hauptanwendung, Hintergrundthread,
  veraltete Auswahlen, belegten Runner und Setup-Navigation.
- tools/qa_suite_embedded.py umfasst zusätzlich die native
  Tk-/Qt-Hauptfensterabnahme ohne Unity-Bau.

**Offene Grenzen:** Original-RGBA-Byteprüfung, vollständige
Geometrie-/Review-Proofs, Unity-Projektvorbereitung,
echte BC7-Komprimierung und Ingame-Funktion bleiben
Aufgaben des tatsächlichen Builders und der getrennten
Release-/Game-Qualitätsprüfung. Der neue Check darf
nicht als Ersatz für diese Prüfungen verwendet werden.


## Durchgängiger Bau-Startschutz und Abschlussabnahme

Der separate Nur-Lesen-Knopf ist weiterhin unabhängig verfügbar.
**Paket bauen (mit Vorprüfung)** durchläuft jetzt selbst dieselbe
vollständige, aktuelle Prüfung. Fehlende Voraussetzungen verhindern
den Start; bei blockadenfreier Prüfung ist eine weitere ausdrückliche
Bestätigung mit Standardantwort **Nein** nötig. Der Dialog nennt die
gewählte Profil-ID und ob eine vorhandene Ausgabe ersetzt würde.

Nach Zustimmung wird vor dem CLI-Aufruf erneut kontrolliert:

- Ausgewähltes Profil und Ersetzen-Wahl identisch zum geprüften Stand
- Aktuelle SHA-256 von Profil, Spielpfadkonfiguration, Mapping-GZIP,
  Unity-Vertragsdatei und gegebenenfalls gespeicherter Toolchainkonfiguration
- Vorhandensein und Typ des Ausgabeordners weiterhin wie bei der Prüfung
- Keine laufende andere Tool-/Buildaktion

Ein veralteter oder widersprüchlicher Prüfbericht ist keine
wiederverwendbare Freigabe. Die Spiel-, Unity- und SDK-Eingabefelder
werden jetzt mit den tatsächlich gespeicherten beziehungsweise
automatisch verwendeten Builderpfaden abgeglichen. Eingetippte,
aber nicht gespeicherte Spiel- oder Toolchain-Pfade erzeugen keinen
fälschlich grünen Zustand. Veränderungen an diesen Feldern während
des Prüflaufs machen das Ergebnis ebenfalls ungültig.

**Ergebnis nach dem Bau:** Der tatsächlich gestartete
CLI-Bau und sein verpflichtender Validator werden anschließend
von der Suite ausgewertet und durch eine zweite, unabhängige
SHA-256-Offline-Kontrolle ergänzt. Der neue Bereich
**Bauergebnis anzeigen** unterscheidet einen Baufehler von
vollständiger Offlineintegrität, Warnungen und einem zum vorherigen
Stand identischen Manifest. Selbst ein bestandener Offlinevergleich
ist ausdrücklich noch keine Ingame- oder Releasefreigabe.
[Einzelheiten zur Bau-Abschlussanzeige](BUILD_COMPLETION.md).

**Wichtig:** Der normale CLI-Workflow der Suite behandelt
die Build-Nachvalidierung jetzt unabhängig vom Nachsichtmodus
als **verpflichtend**. Ein von der Validierung abgelehntes Paket
führt zu einem nicht erfolgreichen Exitcode. Der bewusst
nachsichtige Einrichtungscheck bleibt davon unberührt.
Die Original-Pipeline führt alle tieferen Sicherheitsprüfungen,
Geometrie-, Unity- und BC7-Beweispflichten weiterhin selbst aus.

### Verifizierte Abschlussresultate

- **41 reine Bereitschafts-/Workflowtests bestanden**,
  inklusive Quelle/Pivot-Input-Drift, unerwarteter Ausgabe,
  manipulierter Reports, falscher bzw. nicht gespeicherter
  Spiele-/Unity-/SDK-Pfade und fest verpflichtender Validierung.
- **12 GUI-Tests bestanden** für Blockaden, Neustart nach
  geänderter Auswahl, Zustimmung/Ablehnung, Runner-Sperre,
  sichere Fehleranzeige und Fenstergröße 1020×680.
- **Gesamte Projekttestsuite: 445 passed in 359.84s**,
  Exitcode 0, keine übersprungenen oder fehlgeschlagenen Tests.
- Echter Windows-Tk-/Qt-Smoketest: **BC7_BUILD_BUTTON_GATED**
  und **QA_PASS**, Exitcode 0.
- Der bestehende Produktionsbau wurde separat lesend bestätigt:
  **154/154 Dateien**, **149 Gruppen**, **0 Fehler**, **0 Warnungen**.

Alle Schreibvorgänge für ein tatsächlich neues Bundle oder
eine Spielinstallation blieben während dieser Abnahme abgeschaltet.
