# Sprite Suite – Gesamtüberarbeitung der Anwendung

**Stand:** 14.10.2026  
**Projekt:** `E:\SpriteSuite`, Branch `feature/sandbox-studio`  
**Auftrag:** Nicht einzelne Symptome übermalen, sondern Bedienkonzept,
Werkzeugausführung, Navigation, Datenintegrität, Diagnose, Sandbox und
Paket-/Freigabeprozess als **eine** konsistente Anwendung überarbeiten.

## Qualitätsmaßstab

Die Überarbeitung ist nicht daran gemessen, ob jede alte Schaltfläche noch
irgendwo existiert, sondern ob ein Anwender ein vollständiges Ziel **ohne
Raten** erreicht, jede Aktion nachvollziehbar ist und ein fehlgeschlagener
Schritt niemals einen späteren Vorgang legitimiert.

Ein abgeschlossener Hauptablauf ist:

1. Spiel/Projekt auswählen und Voraussetzungen sehen.
2. Vorhandenes Sprite suchen und alle verfügbaren Quellen unterscheiden.
3. Arbeitskopie bearbeiten, Rückgängig und Originalschutz prüfen.
4. Sprite inklusive Teilobjekten in der **integrierten** Sandbox testen.
5. Anker, Framezahl, Abmessungen, Bildmasken und Buildquellen validieren.
6. Paket aus dem gewählten Profil erzeugen, unabhängige Prüfergebnisse sehen.
7. Installation nur mit benanntem Ziel, Sicherung und Zustimmung durchführen.
8. Fehler, Unterbrechungen und die zuletzt ausgewählte Arbeitsaufgabe
   nachvollziehbar wiederfinden.

## Architektur, die erhalten bleibt

- **Ein Hauptfenster:** Tk Universal-Suite mit eingebettetem Qt Sandbox Studio.
  Qt- und Tk-Events müssen sauber zusammenlaufen; kein zweites Sandbox-Programm.
- **Eine Ausführungssteuerung:** Tk startet die bestehenden CLI-/Python-Tools
  statt deren Schutzlogik ein zweites Mal in Widgets zu implementieren.
- **Originalschutz:** Installierte `.map`-/GM-/Unity-Dateien werden nicht
  bearbeitet. Überlagerungen, gemessene Pivots und Arbeits-Sprites liegen
  in getrennten Datenständen und benötigen kontrollierte Speicherung.
- **DE/EN:** Sichtbare Bedienbegriffe wechseln reversibel, IDs und
  technische Quelldaten nicht.
- **Profil- und Releasesicherheit:** Fehlernde Validatoren können keine
  Build-/Installationsfreigabe erzeugen.

## Stufen und Abnahmekriterien

### Stufe 1 – Ausführungs- und Zustandsintegrität [in dieser Runde]

- [x] **Unberechtigt gestartete Folgeaktion verhindern:** Ein bloßes
  `run()`-Aufrufen gilt nicht mehr als erfolgreicher Start. Ein von
  `Runner.start()` abgelehnter Auftrag entfernt seinen Completion-Hook.
- [x] **Abschlussereignisse eindeutig zuordnen:** Solange ein beendeter
  Worker noch ein ungeprüftes `done`-Ereignis im Tk-Eventqueue hat, darf
  kein anderer Auftrag starten.
- [x] **Abbruch des Suite-Schließens respektieren:** Wenn Qt bei
  ungespeicherten Sandbox-Änderungen das Schließen ablehnt, läuft ein
  noch aktiver Bauprozess weiter und die Single-Instance-Sperre bleibt
  erhalten. Erst die tatsächlich erlaubte Zerstörung räumt beides ab.
- [x] **Ausnahmefestes Event-Drain:** Ein defekter Abschluss-Callback
  meldet seinen Fehler, ohne den Tk-Eventloop zu stoppen oder eine
  fremde Folgereaktion auszulösen.
- [x] **Katalogzustand erhalten:** Beim Neuladen, Filtern, Sprachwechsel
  und verzögerten Tk-Treeview-Selektionsevents bleibt die gewählte
  Gruppe/Frame-Auswahl konsistent.
- [ ] Langzeittest mit zahlreichen unmittelbar aufeinanderfolgenden
  GUI-/Worker-/Speichern-/Undo-Aktionen und simulierten Abstürzen.

### Stufe 2 – Aufgabenorientierte statt historisch gewachsene Navigation

- [x] **Startseite als primärer Einstieg:** Nicht versteckt als
  Spezialreiter. Sieben nachvollziehbare Ziele: Einrichten, Sprite finden,
  auf Karte testen, bearbeiten, diagnostizieren, bauen, installieren.
- [x] Jeder Einstieg **navigiert nur**, er startet niemals heimlich
  Konverter, Builds, Dateischreibbefehle oder Spielinstallationen.
- [x] Neue Hauptbegriffe und Anleitungen in Deutsch und Englisch
  hinterlegt; Strg+K bleibt der direkte Weg zu Spezialwerkzeugen.
- [ ] Alle alten Bearbeitungsdialoge hinsichtlich Fokus, eindeutiger
  Primäraktion, Eingabevalidierung und gut sichtbarem Fehlerzustand
  vereinheitlichen.
- [ ] Fortgeschrittene Optionen durch nachvollziehbare Arbeitsphasen
  statt Reiterduplikate ordnen; Einstellungen persistent und reversibel.

### Stufe 3 – Einheitlicher Bearbeitungsworkflow

- [ ] Alle Arbeitskopie-/Import-/Exportaktionen benötigen deutlich sichtbare
  Quelle, Ziel, Änderungsumfang, Vorschau, Abbrechen und Rückweg.
- [ ] Ein ausgewählter Frame bleibt konsistent zwischen Tk-Katalog,
  Qt-Sandbox, Animation, Pixeleditor, OpenRaster und Quellvergleich.
- [ ] Unterschiede zwischen Original, abgeleitetem Sprite, manuell
  bearbeitetem Arbeitsbild und ausgeliefertem Frame in jedem Schritt
  eindeutig markieren.
- [ ] Pivot-/Masken-/Richtungs- und Schadensblöcke über ein gemeinsames
  Prüfergebnis erklären statt unterschiedlicher Fehlermeldungstypen.

### Stufe 4 – Diagnose, Paketbau und Freigabe

- [ ] Eine Diagnoseübersicht unterscheidet tatsächlich getestete
  Ressourcen, Warnungen, blockierende Fehler und nicht durchgeführte
  Prüfungen. Ein alter Bericht ist kein aktueller Freigabenachweis.
- [ ] Build-Kette mit Echtzeitzustand, Abbruchregel, unabhängiger
  Ausgabesummenprüfung und klarer Nicht-Freigabe bei Unsicherheiten.
- [ ] Installationsschritte nur mit Backupliste, Zielauswahl, sicherem
  Rückweg und konkretem Bestätigungstext.
- [ ] Historische QA-Werkzeuge als ausdrücklich versionsgebundene
  lesende Prüfer; keine ungeprüften alten DLL-/Profileingriffe.

### Stufe 5 – Sandbox und Originalspielnähe

- [x] Integrierter Qt-Editor mit echten Engine-Grafikkommandos und
  Originalkarten bleibt Teil der Hauptanwendung.
- [ ] Eingaben und Layerwahl unter mehreren DPI-/Zoom-/Kamerawechseln
  langzeitprüfen.
- [ ] Original-HUD-, Unity-Spezialshader-, Wasser-, Wind- und
  Simulationstreue ausdrücklich separat nachweisen, nicht aus
  einem statischen Screenshot ableiten.
- [ ] Grafikspeicher, Task-/Texture-Caching und Dialoglebenszyklus
  mit längeren Sitzungen überprüfen.

### Stufe 6 – Gesamtabnahme und Ausgabe

- [ ] **Reproduzierbarer kompletter Testlauf** des gesamten,
  derzeit großen Testbestands (bisher 609+ Fälle), mit Ergebnis und
  reproduzierbarem Bericht, nicht als grün markieren wenn abgebrochen.
- [ ] Echte Windows-UI-QA bei 1020×680, 1320×800, größerer
  DPI-Skalierung, DE/EN, Tastatur sowie Screenreader-/Hochkontrastprüfung.
- [ ] Negative Pfade: defekte Quellen, fehlendes SDK/Unity/Spiel,
  ängstlich abgelehnte Dialoge, falsche Profile und
  Unterbrechungen müssen zu einem sicheren Zustand zurückführen.
- [ ] Release nur nach unabhängiger Dateiintegritätsprüfung und
  dokumentierter, zur Spielversion passender Abnahme.

## Nachweisprotokoll

In der aktuellen Runde sind die **Systemkorrekturen** (Runner,
Katalogzustand, Schließfolge und Startnavigation) implementiert. Gezielt
bestanden zunächst **33 Core/UI-Tests** sowie zusätzliche Tests der
Runner-Completion- und Callback-Fehlerfälle. Der neue Startseiten-Klicktest
wird separat unter realem Tk geprüft.

Die bisherige UI-Dokumentation meldete einen zeitweiligen
`g:anim_castle`-Selektionsverlust im kombinierten 60er Lauf, der in
Einzeltests nicht stabil reproduzierbar war. Der neue Treeview-Aufbau
adressiert dessen wahrscheinlichen Mechanismus (Rebuild + verspätetes
`<<TreeviewSelect>>`). Das ersetzt **keinen** erneuten kombinierten Test.

**Wichtig:** Die hier dokumentierten Stufen 3–6 sind noch nicht als
implementiert oder vollständig abgenommen zu betrachten. Diese
Reihenfolge verhindert, dass eine rein optische Neugestaltung dieselben
sicherheitsrelevanten Fehler in einer neuen Oberfläche versteckt.
