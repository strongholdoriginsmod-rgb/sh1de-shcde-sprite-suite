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
Tk-Interpreterinitialisierung maximal dreimal **nur** dann, wenn Tcl ausdrücklich
das Lesen von init.tcl oder tk.tcl meldet. Andere Tk-Fehler werden weiter
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

### Geführte Demos: 21 produktive Modulkategorien

Die vorhandenen zehn Kategorien wurden um weitere elf erweitert:

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
