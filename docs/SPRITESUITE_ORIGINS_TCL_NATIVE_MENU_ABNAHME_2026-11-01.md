# SpriteSuite: Noesis, Origins-ABI, Tcl/Tk und Demo-Abnahme

**Datum:** 1. November 2026
**Zweig:** feature/demo-coverage-noesis-tcl-runtime-20261101
**Arbeitskopie:** E:\SpriteSuite_Origins_Manuell_20261101

## Implementierte und wirklich getestete Fortschritte

### Tcl/Tk-Stabilisierung

Die Suite bereitet beim Programmstart die mitgelieferte Tcl/Tk-Laufzeit
in einem privaten, inhaltsadressierten Cache unter dem Windows-Benutzerprofil
vor. Erforderliche Skripte werden vor/nach dem Kopieren über SHA-256 geprüft.
Kein globaler System-Python-Pfad und keine Spielinstallation wird verändert.

Die vollständige Hauptanwendung wiederholt eine fehlgeschlagene native
Tk-Interpreterinitialisierung maximal fünfmal **nur** dann, wenn Tcl ausdrücklich
das Lesen von init.tcl/tk.tcl oder einen fehlenden Bootstrap-Befehl
tcl_findLibrary meldet. Andere Tk-Fehler werden weiter
als echte Fehler propagiert, nicht stillschweigend unterdrückt.

Belege: 40 sequenzielle Tk-Fensterinitialisierungen ohne Fehler,
Tcl-Kopier-/Korruptionsprüfungen, zwei gezielte Fehlersimulationen und
143 bestandene breit gefasste GUI-Regressionstests.

Das schließt den zuvor reproduzierbaren Problemfall in den geprüften
Umgebungen. Ein absoluter Ausschluss aller künftigen Windows-IO-Fehler
ist dadurch naturgemäß nicht beweisbar.

### Noesis-Vorschau und Pixelvergleich

Der bestehende XAML-Editor lädt echte XML-Hierarchie und Grafiken und erlaubt
frei bearbeitbare Positionen, Texte, Commands, Styles und Controls.

Neu im Noesis-Designer: „Pixelvergleich echter Noesis-Aufnahmen …“.

- Auswahl von zwei getrennten PNG-Aufnahmen.
- Kein automatisches Resampling, Dehnen oder Verschieben.
- Differenzmaske, Halbüberlagerung und numerischer Pixelbericht.
- Anzahl und Anteil abweichender Pixel, mittlere und größte Kanalabweichung.
- Negativtest: unterschiedliche Auflösungen werden zurückgewiesen.
- Kontrolltest: identische Bilder ergeben null Abweichung.

Damit lässt sich eine **tatsächlich im Spiel aufgenommene** Ansicht quantitativ
mit einer späteren Spielaufnahme vergleichen. Das Instrument ist kein
integrierter Noesis-Renderer. Ein Bericht setzt die Kennzeichen
native_noesis_renderer_invoked und game_render_parity_attested ausdrücklich
auf false, bis eine separat nachgewiesene Spiel-/Renderer-Abnahme vorliegt.

Die installierte Spielversion enthält die verwaltete
Noesis.NoesisGUI.dll und die native x86_64/Noesis.dll. Das Vorhandensein
dieser Komponenten allein liefert keinen isolierten Pixelrenderer mit
Spiel-Styles, ResourceProvider, CommandBindings und Unity-Grafikgerät.

### Origins-Menü-C#-Anbindung – tatsächlicher Status

Die separate Offline-ABI-Prüfung untersucht genau die bereits auf dem
Rechner vorhandenen Spielbibliotheken, ohne deren Code auszuführen:

- CrusaderDE.FrontendMenus als Noesis.UserControl
- ButtonClicked(System.String)
- Noesis.FrameworkElement.FindName
- BepInEx.BaseUnityPlugin und Harmony-Patching
- Mono.Cecil als reiner Metadatenleser

Der Menübridge-Quellcode wird inzwischen tatsächlich gegen
BepInEx.dll, 0Harmony.dll, Noesis.NoesisGUI.dll, UnityEngine.dll
und UnityEngine.CoreModule.dll kompiliert. Der zuvor fehlende
UnityEngine.dll-Referenzverweis ist behoben.

Anschließend prüft Mono.Cecil die erzeugte DLL auf:
Plugin-Basistyp, Plugin-Attribut, Harmony-Prefix-Signatur,
Awake-Einstiegspunkt und OnDestroy-Aufräummethode.
Diese Prüfungen *führen die DLL nicht aus*.

**Ergänzte dynamische Abnahme:** Die unveränderte C#-Menübridge wird
zusätzlich gegen kleine eigenständige Testklassen für Noesis, BepInEx
und Harmony kompiliert und als .NET-Testprogramm wirklich ausgeführt.
29 überprüfte Eigenschaften belegen unter anderem, dass Original-Befehle
(Roadmap, Multiplayer), unbekannte und Null-Commands an das Spiel
durchgereicht werden, während eigene CommandParameter das private
Kampagnenfenster öffnen/schließen, den Missionstext ändern und einen
nicht unterstützten Kartenstart ausschließlich protokollieren.
Der Harmony-Testhost sieht genau eine Registrierung und eine Aufräumaktion.
Dies ist ein **Offline-Fake-Host**, keine native Ingame-Sitzung.

**Behobene Windows-Compilerlücke:** csc.exe verwendet für C#-Quellcode,
Compiler-Zwischenablage und Metadatenleser einen kurzen, privaten
Ordner im Benutzerprofil. Damit funktionieren auch Demo-Projekte mit
sehr tiefem Temp-/Arbeitsverzeichnispfad. Nach dem Test werden die
erzeugten Dateien mit Hashvergleich in die normale private Arbeitskopie
übernommen; Compiler- und Testbibliotheken werden nicht als Mod ausgeliefert.

Die Kampagnen-XAML besitzt zusätzlich einen benannten
SpriteSuiteSelectedMission-Textblock, den die Menübridge beim
Missionswechsel ansprechen kann.

Eine private DLL und ein QA-Bericht liegen ausschließlich unter
work/.origins-native-menu-candidates/<Kampagnen-ID>/.
Der neue Button „BepInEx-Menübridge nur OFFLINE kompilieren“ in der
Kampagnenwerkstatt verlangt ausdrücklich die Auswahl des Spielordners,
der nur als Referenzquelle verwendet wird.

### Was weiterhin kein vollständiger Ingame-Nachweis ist

Es gibt **keine automatische Installation oder Aktivierung** dieser DLL.
Weder die tatsächliche Noesis-Klickweiterleitung noch die
Harmony-Hook-Registrierung im laufenden Spiel wurde als bestanden
nachgewiesen. Ein echter Missionsstart ist bewusst nicht programmiert,
sondern wird nur als LaunchRequested protokolliert. Auch MapSave/MapUnload,
Fortschrittspersistenz und Saisonatlaswechsel sind keine fertigen nativen
Spielaktionen.

Insbesondere die früher dokumentierte historische Origins-Runtime von
Spielversion 2.7.0 ist nicht allein durch C#-Kompilation für den aktuellen
Steam-Build freigegeben. Ohne versionspassenden Ingame-QA-Test bleibt diese
Grenze bestehen.

### Geführte Demos: 26 produktive Modulkategorien

Die ursprünglichen zehn Kategorien wurden um weitere sechzehn erweitert:

- Steinfarben
- Tier-Sprites / Keilerpalette
- historisches Origins Blau/Silber
- Teamfarben und Masken
- Sandkasten / Spielvorschau
- Button-Motivkatalog
- native Kachelmaterialdarstellung (als provisorisch gekennzeichnet)
- BC7-Texturen und Decoder
- Noesis-Pixelvergleich
- Noesis-Zusatzatlanten
- read-only Spiel-ABI und private C#-Menübridge
- polygonale Hintergrundauswahl und inneres Feathering
- vier originale UI-Buttonzustände
- Baum-/Strauch-Komposition mit echter Pivot-Geometrie
- Gold-/Silber-Relief über Kanten-/Distanz-Lookup-Tabellen
- tatsächlich ausgeführte C#-Menübefehle im isolierten Fake-Noesis-Host

Jede Kategorie führt Produktionsfunktionen tatsächlich aus und speichert
Prüfbelege. Die zusätzliche native Menü-Demo erfordert einen vom Benutzer
ausgewählten installierten SHCDE-Spielordner; die WebM-Demo erfordert
eine echte Videoquelle. Ohne diese Eingaben werden die Kategorien explizit
übersprungen statt mit erfundenen Daten als erfolgreich markiert.

Beispiele:

    python tools/suite_demo_cli.py --list
    python tools/suite_demo_cli.py --module native_menu --game "D:\Games\Stronghold Crusader Definitive Edition"
    python tools/suite_demo_cli.py --all --game "D:\Games\Stronghold Crusader Definitive Edition" --video "D:\Private\my.webm"

Die GUI bietet dieselbe Modulregistrierung und übernimmt die
Ergebnisse in die echten Fach-Editoren. Revisionsstände, Kompilat,
Vergleichsberichte, Quellen und Mod-ZIPs bleiben getrennt vom installierten
Spiel im Arbeitsordner gespeichert.

## Abnahme- und Freigabegrenzen

Die im Quellzweig nachgewiesenen Tests prüfen:

1. C#-Kompilierung und reproduzierbare ABI-Metadatensignaturen
2. Tatsächliche Dateiverarbeitung und erneutes Lesen des Ergebnisses
3. Auswahl und Betrieb aller Demo-Module
4. Tk-Initialisierung, Replay und Fehler-Injektion
5. Asset-Mod-ZIPs, CRC und SHA-256
6. Nachbearbeitung historischer XAML und Originalschutz

Trotz dieser Fortschritte ist **pixelgenaues natives Noesis-Live-Rendering
innerhalb der Suite** noch nicht nachgewiesen. Auch sämtliche
Spiel-DLL-Hooks, Engine-Versionen und jedes einzelne Spezialwerkzeug aus
dem gesamten Script-Bestand sind nicht pauschal freigegeben. Die
Produktionsfreigabe dieser Aufgaben benötigt eine isolierte, versionsgetreue
Ingame-Testumgebung und weitere Moduleinzelabnahmen.

Kein fehlender Ingame-Nachweis wird durch eine grüne Offlineprüfung ersetzt.


## Erweiterter Nachweis: C#-Menürouting und zuverlässige Compilerpfade

Nach den bisherigen statischen Compiler- und Cecil-Prüfungen existiert nun
ein **ausführbarer Verhaltenstest für die tatsächliche C#-Menübridge**:

- tests/sandbox/origins_menu_mock_harness.cs: echte Adapterquellen werden
  mit isolierten, kleinen Ersatzimplementierungen für Noesis, Harmony,
  BepInEx und CrusaderDE.FrontendMenus kompiliert.
- tools/origins_menu_mock_qa.py: das resultierende .NET-Testprogramm
  wird wirklich gestartet; mindestens 29 Assertions müssen bestehen.
- Originalbefehle wie Roadmap und Multiplayer werden durchgereicht;
  vorhandene eigene Legacy-Befehle blenden die Kampagnenansicht ein/aus,
  wählen Missionen und ändern den benannten Menütext.
- Unbekannte Parameter werden nicht vereinnahmt. LegacyStart fordert
  lediglich eine nicht unterstützte Startaktion an und protokolliert
  die Ablehnung; ein echter Kartenstart erfolgt ausdrücklich nicht.
- Aufräumen über OnDestroy muss im Test genau eine Harmony-Unpatch-
  Operation ausführen.

tools/origins_native_menu_compiler.py bindet den positiven Verhaltenstest
nun verpflichtend in den Build eines privaten Kandidaten ein. Der Bericht
enthält offline_fake_game_host_executed, die tatsächlich ausgeführte
Assertion-Anzahl und die eigenen Protokolldateien. Die provisorische
Mock-Executable und die zu Testzwecken kopierte Mono.Cecil.dll werden
**nicht** als installierbares Plugin übernommen.

### Fehlerbehebung: lange Arbeitsordner unter Windows

Der Windows-.NET-Framework-C#-Compiler kann bei tief verschachtelten
pytest-/Demo-Arbeitsordnern sein temporäres Ausgabefile nicht anlegen.
Die Fehlermeldung ist ein Systemaufruffehler und kein ungültiger C#-Code.

tools/suite_windows_csharp_scratch.py stellt deshalb ein kurzes,
eindeutiges, privates Compilerverzeichnis im LocalAppData-Ordner bereit.
Das operative Kompilieren und der Cecil-Metadatentest finden dort statt.
Die finalen .NET-Kompilate, Logs und Berichte werden bytegenau in das
eigentliche private work/-Projekt übernommen. Der Scratch-Ordner wird
nach jedem Compilerlauf entfernt. Ein vorher reproduzierbar fehlgeschlagener
Windows-GUI-Integrationstest besteht seit dieser Korrektur.

### Weitere fünf wirklich ausgeführte Spezialmodule

Zusätzlich zu den zuvor 21 Modulen:

- Hintergrund-/Polygonmaske: registrierte Bildausschnittmaske, echte
  Subtraktionsmaske, inneres Feathering; außerhalb der Maske bleiben
  alle Pixel und Alpha bitgenau erhalten.
- UI-Knopfzustände: echte wappenschild()-Renderformel für ruhend,
  überfahren, gedrückt und aus; der Hover-Zustand wird ins Projekt
  gespeichert und paketiert.
- Baum-/Strauch-Grafiken: transparente Donor-Grafiken werden über
  compose_on_canvas() mit Skalierung und Fußpunkten neu kombiniert.
- Gold-/Silberrelief: echte Distanztransformations-Merkmale,
  Sektortabellen und Einfärbungsfunktionen erzeugen zwei editierte
  Reliefzustände.
- Menübefehle / Fake-Host: zwei Missionsdaten als C# generieren,
  unveränderte Menübridge tatsächlich ausführen, 29 Verhaltenstests
  und Unpatch-Lebenszyklus prüfen.

Somit sind nun **26 Module einzeln auswählbar**. In einem vollständigen
lokalen CLI-Lauf mit echter Spiel-XAML, WebM und Originalbibliotheken wurden
26 erfolgreich ausgeführt; keines übersprungen. SHA-256-Vergleiche
bestätigten unveränderte Spieleingabedateien.

Alle Ingame-/Renderer-Vorbehalte aus den vorherigen Abschnitten gelten
unverändert. Der Mock-Test ist eine reproduzierbare, nützliche zusätzliche
Verhaltensprüfung, aber kein Ersatz für native Spieltests.


## Gemeinsame Tk-Initialisierung auch für eigenständige Werkzeuge

Nach einer breiten Regression mit 265 bestandenen und einem wegen
sporadischem init.tcl-Fehler übersprungenen Test wurde die bis dahin
nur in der Suite-Hauptklasse verwendete Tcl-Wiederholungslogik als
allgemeine Funktion bereitgestellt:

- suite_tcl_runtime.call_with_tcl_bootstrap_retries: Wiederholung
  ausschließlich beim fehlgeschlagenen Laden von init.tcl/tk.tcl
  beziehungsweise tcl_findLibrary; andere Tk-Fehler bleiben sichtbar
- suite_tcl_runtime.create_tk_root: derselbe überprüfte Weg für
  eigenständig gestartete Tk-Fenster
- suite.pyw, sandkasten.py und der Portable-Launcher-Selbsttest
  benutzen jetzt dieselbe Initialisierungslogik
- der normale native HUD-/Menü-GUI-Test startet seinen Tk-Interpreter
  ebenfalls über diese Produktionsfunktion; der zuvor übersprungene
  Fall wurde erfolgreich ausgeführt

Der isolierte Kombinationstest mit direktem Native-Tk und GUI-Werkstatt
erreichte danach 23 bestandene Tests ohne Skip.

Zusätzliche Windows-Regressionstests deckten die seltene Meldung
„invalid command name tcl_findLibrary“ während der Interpretererstellung
auf. Dieser Bootstrap-Fehler wird nun ebenso gezielt erneut versucht.
Ein Fehler in einem echten eigenen Widget oder einer beliebigen
Tcl-Aktion wird weiterhin **nicht** als Bootstrap-Fehler behandelt.

Dies adressiert die belegten, sporadischen Initialisierungsfehler durch
gezieltes Wiederholen. Andere GUI- oder I/O-Fehler bleiben weiterhin
echte Fehler und werden nicht als erfolgreich behandelt.
