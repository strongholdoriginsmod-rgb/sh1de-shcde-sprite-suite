# Sprite Suite – gesamter Arbeitsbereich: Bedienbarkeitsrunde

Stand: 2026-10-13, Branch `feature/sandbox-studio`.

## Ausgangspunkt

Die frühe technische GUI-Abnahme bestätigte, dass sich alle Bereiche
öffnen lassen. Sie maß aber nicht ausreichend, ob man auf einem
gewöhnlichen Bildschirm tatsächlich die benötigten Inhalte sehen,
Bedienelemente erreichen und einen Ablauf ohne Suche nach versteckten
Schaltflächen abschließen kann. Deshalb werden jetzt zusätzlich
Fenstergeometrie, echte Tk-Steuerelemente, Katalogauswahl, sichere
Aktionsmenüs und direkt angesprungene Editor-Abschnitte geprüft.

## Übergreifendes Bedienkonzept

- **Arbeitsfläche vor Protokoll:** Das Protokoll bleibt in allen Bereichen
  per **Protokoll anzeigen / Protokoll ausblenden** erreichbar, beansprucht
  aber beim Start keine dauerhaft reservierte Höhe. Die vorherigen
  Meldungen bleiben erhalten. Ein Fehler wird am Protokollschalter
  sichtbar signalisiert. Eine explizite Nutzerentscheidung zum
  Einblenden bleibt auch bei einem Reiterwechsel erhalten.
- **Lesbare Hauptnavigation:** Acht Hauptreiter bleiben als kurze,
  verständliche Bezeichnungen sichtbar. Die Kombobox **Bereich öffnen**
  erreicht alle 14 vorhandenen Haupt-/Spezialbereiche. **Alle Reiter**
  kann die vollständige historische Reiterleiste wieder anzeigen;
  **Reiter bündeln** schaltet zurück. Keine alte Funktion wurde gelöscht.
- **Priorisierte Aktionsleisten:** Häufig benutzte Tätigkeiten bleiben
  sichtbar; weniger häufige Befehle liegen in eindeutig benannten
  Menüs. Der Klickpfad führt weiterhin in die unveränderten
  Original-Callbacks mit ihren Warnungen und Bestätigungen.

## Änderungen je Arbeitsbereich

| Bereich | Konkrete Bedienänderung |
|---|---|
| Einrichten | Bisherige unabhängige Speicherung und lesende Diagnose bleiben erhalten; mehr Formfläche durch einblendbares Protokoll |
| Sprite-Werkstatt | Vorschauen und **Rückweg** sind separate Arbeitsansichten statt übereinander liegender Formulare |
| Asset-Katalog | Nur Hauptaktion **Neu laden**, Gruppierung und Erweiterungen im Menü; Frameübersicht vor Bearbeitungsformular; Auswahl öffnet Vorschau/Bearbeitung automatisch; das Formular lässt sich wieder schließen |
| Diagnose & Reparatur | Häufige Prüfarten sichtbar, weitere im Menü; Pivot-Protokollwahl separat; längere Ergebnistabelle horizontal scrollbar; Eingaben füllen die verfügbare Breite |
| Sandbox | Kartenfokus, Palette und Inspector ein-/ausblenden, alle HUD-Werkzeuge über eine Auswahlliste und DPI-korrekte Qt-Einbettung (vorheriger geprüfter Commit) |
| Editor & Austausch | Direktwahl der Editor-, Atlas-/Pivot- und ORA-Abschnitte; gewählter Abschnitt wird **oben** im Scrollbereich positioniert |
| Ziel & SE 2.11 | Installieren/Deinstallieren und Sicherungen sind klar als sichere Spezialaktionen zusammengefasst; Ziele können jederzeit aktiviert und aktualisiert werden; breite Datenfelder horizontal scrollbar |
| Paket bauen | Gesamter Bauablauf und die UI-BC7-Spezialwerkzeuge lassen sich bei kleinen Fenstern scrollbar erreichen, ohne Build-Gates abzuschwächen |
| Alle Werkzeuge | Dynamische CLI-Formulare mit zuverlässigem Scroll-/Tastaturfokus; die Aktionen **CLI-Hilfe** und **Ausführen** stehen in einer eigenen festen Fußzeile statt unter einem zu hohen Formular zu verschwinden |
| Start & Anleitung | Die Schritte und die Projektbereitschaft sind getrennte, vollbreite Innenreiter (**Schritt für Schritt** / **Projektbereitschaft**); kein quetschendes Nebeneinander mehr |
| Sprite-Gruppen | Bleiben über die Bereichsauswahl erhalten, profitieren von mehr freiem Platz |
| Oberfläche | Atlasvorschau erhält mehr vertikale Fläche; die Einleitung bricht auch auf einem 1020px-Bildschirm vollständig um |
| Texte | Scan-/Regelfunktionen bleiben direkt erreichbar; längere Erklärtexte laufen nicht mehr rechts aus dem Fenster |
| Historisch Bauen/Installieren | Jeder Schritt der ursprünglichen Prozessfolge ist scrollbar; die Bestätigungs- und Installationssicherungen bleiben bestehen |

## Geometrie

Gemessen am tatsächlichen Hauptfenster:

| Fensterausmaß | Inhaltsfläche vorher | Inhaltsfläche nach Änderung |
|---|---|---|
| 1020 × 680 | 988 × 390 | **988 × 513** |
| 1320 × 800 | 1288 × 510 | **1288 × 633** |

Das sind **123 zusätzliche Pixel Höhe** je regulärem Arbeitsbereich.
Die Messung wird im lokalen, nicht ausgelieferten Test
`work/qa_all_views_layout.py` dokumentiert. Seine Screenshots und
der JSON-Kontrollbericht liegen ausschließlich unter
`work/reports/layout-all-views/`. Für **alle 14 Arbeitsbereiche** wurden
bei zwei Fenstergrößen insgesamt **28 Aufnahmen** und automatisch
kontrollierte Widget-Grenzen erstellt. Bei den geprüften sichtbaren
Kontrollen wurden **keine horizontal über den Reiter hinausragenden
Schaltflächen** gemeldet; dies allein ersetzt jedoch nicht die visuelle
Sichtprüfung oder das tatsächliche Betätigen der Aktionen.

## Prüfgrenzen

Ein sauberer Bildschirmaufbau ist keine Genehmigung, Spielordner zu
ändern. Ein echter BC7-Neubau verlangt weiter die vollständige
Bauvoraussetzungsprüfung, die gepinnte Unity-Version, ein gültiges SDK,
die ausdrückliche Bauentscheidung und die unabhängige
SHA-256-Abschlussprüfung. Installationen, Deinstallationen,
Profiländerungen und vorhandene Paketausgaben behalten ihre
bestehenden Bestätigungs- und Sicherungsprozesse.

## Abnahmeergebnis – 13. Oktober 2026

- **583 Tests bestanden, 0 fehlgeschlagen, 0 übersprungen** in
  612,52 Sekunden (10:12), Exitcode 0. Vollständiger Testbericht:
  `work/reports/whole-suite-final-regression-20261013.log`.
- **Echter Windows-Tk-/Qt-Hauptfenstertest: QA_PASS**, Exitcode 0.
  Das Protokoll bleibt beim Wechsel zwischen Sandbox und Katalog
  erhalten, und der Benutzer kann es bewusst ein- und ausblenden.
  Bericht: `work/reports/whole-suite-ux-native-20261013.log`.
- **23 gezielte Bedienungstests bestanden**. Sie kontrollieren unter
  anderem kompakte Reiter, bisher verborgene historische Bereiche,
  Arbeitsfläche/Protokoll, Katalog-Vorschau/Bearbeiten,
  Diagnose/Installationsmenüs, Editor-Sprünge und die tatsächlich
  sichtbare `CLI-Hilfe`/`Ausführen`-Leiste.
- **28 Windows-Aufnahmen** aller 14 Bereiche bei 1020 × 680 und
  1320 × 800. Keine über den sichtbaren Reiter seitlich hinausragenden
  Bedienelemente in den geprüften Widget-Grenzen. Der Werkzeugkatalog
  wurde außerdem anhand der Aufnahmen nachgebessert.
  Log: `work/reports/whole-suite-ux-all-views-20261013.log`.
- **Unabhängiger Produktions-SHA-256-Preflight:** 154/154 Dateien,
  149 BC7-Gruppen, 0 Fehler, 0 Warnungen, Exitcode 0. Die historischen
  1009 Prüfungen sind kein neuer Unity-/Ingame-Nachweis.

Es wurden keine Originalspiel-Dateien, Spielinstallationen oder
Produktionspakete verändert. Es erfolgte kein neuer Unity-Build und
keine Ingame-Freigabe.


## Fortsetzung: leere Ansichten und verlässliche Berichtsinterpretation

Die zweite Bedienbarkeitsrunde ergänzt in **Ziel & SE 2.11** und
**Diagnose & Reparatur** eine verständliche Statuszeile direkt bei der
Arbeitsliste:

- Bei **noch keinem Zielspiel** wird der Einstieg
  **Ziel hinzufügen …** erklärt. Das reine Hinzufügen ist
  **keine automatische Installation**. Sind Ziele vorhanden,
  werden ihre Anzahl und die aktive Auswahl angezeigt.
- Eine **beschädigte Ziel-Registry** legt nicht die ganze Oberfläche
  lahm; ungültige Einträge werden übersprungen und sichtbar
  beanstandet. Eine fehlerhafte Quelldatei wird beim Anzeigen nicht
  repariert oder überschrieben.
- Ohne Diagnosebericht erhält man **keine leere Tabelle ohne Kontext**,
  sondern den Hinweis auf **Alles prüfen** und die einzelnen Prüfarten.
  Ein vorhandener Bericht mit **0 Befunden** wird ausdrücklich
  von „noch nie geprüft“ und einer **Build-/Ingame-Freigabe** unterschieden.
- Die Diagnose verwendet für ihren on-disk-JSON-Bericht eine **strikte
  Leseauswertung** statt des sonst nachsichtigen allgemeinen
  Katalog-Lesers. Kaputtes JSON, ein falscher Wurzeltyp oder einzelne
  beschädigte Befunde werden als Fehler der **Berichtsdatei**
  benannt – **niemals** als Null-Befund-Bestätigung.
- Beim Wechsel von einem SHA-256-, Pivot- oder QA-Bericht zurück
  zum Grafikdiagnosebericht verschwinden überholte Vorschautexte
  und Detailbilder. Statuszeilen zu den separaten Prüfberichten
  benennen Herkunft und Anzahl der Befunde.

Die zugehörigen GUI-Tests verwenden ausschließlich synthetische
Daten und temporäre Diagnoseverzeichnisse. Kein Test installiert
oder baut einen Mod; die Ingame-Freigabe bleibt offen.

## Kritischer Zweit-Audit: Sprachkonsistenz und tatsächliche Bedienbarkeit

**Datum:** 13. Oktober 2026. Die bereits dokumentierte geometrische
Vollabnahme der 14 Arbeitsbereiche wurde um eine zweite, textbezogene
Prüfung mit echten Windows-/Tk-Steuerelementen ergänzt.

### Was zuvor nicht geprüft war

Die ursprünglichen DE-Screenshots und Widget-Grenzprüfungen konnten nicht
erkennen, dass ein als **Deutsch/English** ausgewiesenes Programm
bei `EN` an vielen Stellen weiterhin Deutsch anzeigte. Eine gesonderte
Bestandsaufnahme der *tatsächlich sichtbaren* Labels und Popup-Einträge
im vorhandenen Hauptfenster lieferte zunächst:

- **255 unterschiedliche sichtbare GUI-Beschriftungen/Menütexte** in der
  untersuchten Tk-Oberfläche.
- **84 davon ohne direkten Eintrag** in der englischen Übersetzungstabelle.
  Diese Zahl umfasst auch einige unveränderliche Eigennamen, technische
  IDs und von Nutzerdaten abhängige Statuszeilen, nicht 84 einzelne
  funktionslose Buttons.
- Menüeinträge in einem `tk.Menu` waren auch **mit**
  Wörterbucheintrag beim Umschalten häufig nicht übersetzt, weil
  Menüpunkte kein `winfo_children()` eines Tk-Widgets sind.
- Die dynamischen Schalter **Protokoll anzeigen/ausblenden**,
  **Alle Reiter/Reiter bündeln** und
  **Vorschau/Bearbeiten schließen** fielen nach Bedienung wieder
  in die deutsche Beschriftung zurück.

### Direkt umgesetzte Verbesserungen

- Fehlende zentrale Kurztexte wurden in
  `config/suite-sprachen.json` ergänzt. Der geprüfte EN-Katalog
  enthält jetzt **507 Übersetzungseinträge** statt zuvor 425.
- Die Tk-Sprachroutine übersetzt jetzt auch `tk.Menu`-Kommandos,
  Check-/Radiobutton-Einträge und Untermenüs; ein expliziter
  De-/En-/De-/En-Test überprüft bidirektionales Umschalten
  ohne Verlust der eigentlichen Aufrufaktionen.
- Dynamische Schaltflächen verwenden die aktive Sprache auch nach
  sichtbaren Statusänderungen, nicht nur direkt nach dem Locale-Wechsel.
- Erstmeldungen des integrierten Sandkastens und die Statusleiste der
  Zielspielverwaltung unterscheiden sich jetzt auch auf Englisch
  korrekt zwischen **kein Ziel vorhanden**, **gültiges Ziel** und
  **fehlgeschlagene Registrierungsdatei**. Bei Sprachwechsel bleibt
  die aktive Zielzeile in der Tabelle markiert.
- Im Asset-Katalog wurden die schwer deutbaren Icon-only-Elemente
  **✕**, **◀** und **▶** durch
  **Leeren**, **◀ Zurück** und **Weiter ▶** ersetzt.
  Die englischen Bezeichnungen sind ebenfalls in der Locale-Tabelle.
- Die erneute Inventur ergibt **255 sichtbare Einträge, 20 ohne direkten
  EN-Schlüssel**. Die meisten verbleibenden Kurztexte sind
  eigensprachliche Produktnamen (`Crusader DE`,
  `Unity 2021.3.45f2`), Quell-IDs (`dx`, `dy`, `directory`),
  Symbole oder dynamische Zahlen-/Statuswerte. Dies ist **keine**
  behauptete vollständige englische Übersetzung aller Programmmodule.

### Bildschirmabnahme / Belege

Die Windows-Screenshot-Prüfung nach dem Sprachwechsel erzeugte
**28 neue EN-Aufnahmen** aller 14 Arbeitsbereiche bei
`1020 × 680` und `1320 × 800` unter
`work/reports/layout-all-views-en/`.
Die geometrische Prüfung meldete
**0 seitlich außerhalb der Arbeitsfläche liegende sichtbare
Bedienelemente**. Darunter sind tatsächliche Screenshots von
Asset-Katalog, Diagnose, Zielspiele und Sandbox-Shell.

Das sind **Tk-Hauptfenster-Screenshots**: Im Sandbox-Reiter
ersetzt der QA-Lauf das Laden der echten Qt-Karte bewusst durch
einen Stub. Die wirkliche Win32-Tk-/Qt-Einbettung und die
`.map`-Engineansicht werden unabhängig mit
`tools/qa_suite_embedded.py` überprüft; ein leerer QA-Sandbox-Screenshot
ist **keine Darstellung der laufenden Spielkarte**.

### Ehrliche Restmängel, priorisiert

| Priorität | UI-Thema | Bewertung / Abnahmekriterium |
| --- | --- | --- |
| P1 | **Qt-Studio nicht voll bilingual** | Die Unteroberflächen des eingebetteten Qt-Editors sind überwiegend deutsch; die DE/EN-Umschaltung der Tk-Haupt-Suite übersetzt sie noch nicht systematisch. Erst abschließen, wenn Qt-Menüs, Inspektor, alle aktiven Dialoge, Tooltips und dynamische Texte auch rückwärts korrekt umgeschaltet werden. |
| P1 | **Tastatur und Screenreader** | Form-Scroll mit Fokusnavigation ist in Teilen getestet, eine vollständige Tab-Reihenfolge, Tastatur-Platzierung auf der Karte, Accessible Names für alle Qt-Icons und Screenreader-Nutzung sind noch nicht als fehlerfrei nachgewiesen. |
| P1 | **Hohe Windows-Skalierung** | 1020×680 und 1320×800 sind echte QA-Größen, aber die gesamte Anwendung wurde noch nicht vollständig bei 150 % und 200 % Windows-DPI, mit großen Systemschriften oder sehr schmalen Fenstern getestet. |
| P2 | **Visuelle Zweiteilung Tk/Qt** | Die Sandbox nutzt einen eigenen dunklen Qt-Toolbar-/Dockstil und eigene Menübegriffe. Funktional integriert, aber hinsichtlich Hierarchie, Schriftgröße und Aktionsnamen noch nicht vereinheitlicht. |
| P2 | **Dichte Kopfleiste** | Bei 1020×680 belegen globale Programmschalter, Bereichsauswahl und Notebook-Reiter mehrere Zeilen. Die erreichte Höhe von 513 px ist brauchbar; weitere Reduktion oder ein personalisierbarer Kompaktmodus wäre sinnvoll, ohne gefährliche Menüs zu verstecken. |
| P2 | **Ausgabestatus & Datenidentität** | Einige maschinell erzeugte CLI-Beschreibungen erscheinen auch im deutschen UI auf Englisch; technische Quellnamen (`geliefert`, Frame-IDs) werden als echte Identifikatoren beibehalten. Eine Trennung zwischen internen Werten und lokalisierter Beschriftung ist für die nächste Revision erforderlich. |
| P3 | **Interaktive Langzeittests** | Ein ganztägiger Einsatz mit wiederholtem Reiterwechsel, Pixeleditor und Auto-Speicher-Abbruch wurde noch nicht durchgeführt. Automatisierte Kurztests reichen dafür nicht aus. |

**Keine Freigabe einer 1:1-Stronghold-Spieloberfläche:** Diese
Bedienbarkeitsprüfung betrifft die *Sprite Suite*; die
eigenständigen technischen Aufgaben der Engine-Shader und
Gameplay-HUD-Parität bleiben unverändert offen.


### Abschluss der deutsch-englischen Tk-Oberflächenkorrektur

Die 13.-Oktober-Prüfung wurde nach dem ersten Audit erweitert und vollständig
mit den überarbeiteten Übersetzungsschlüsseln wiederholt:

- **507** englische Übersetzungsschlüssel statt ursprünglich **425**.
- **255** bei der konkreten Windows-Tk-Aufnahme sichtbare unterschiedliche
  GUI-Beschriftungen/Menütexte; nach der Ergänzung **20 ohne direkten
  Wörterbucheintrag**, darunter Produktnamen, Symbole, technische Feldnamen
  und Zahlen. Diese Zahlen beziehen sich auf diesen erfassten Tk-Zustand,
  **nicht** auf sämtliche dynamischen Texte, die das Programm je anzeigen kann.
- Menüpunkte der Tk-Kontext-/Overflow-Menüs werden jetzt unabhängig von
  Tk-Widget-Kindbeziehungen in beiden Richtungen übersetzt. Die
  originalen deutschen Menüeinträge bleiben für die Rückumschaltung erhalten.
- **Protokoll**, **Reiter**, **Vorschau**, Diagnose- und Zielspielstatus sowie
  das erstmalige Laden der Sandbox berücksichtigen die aktive Sprache
  auch bei späteren Zustandsänderungen. Der ausgewählte Zielspiel-Eintrag
  bleibt bei einem Sprachwechsel erhalten; der Diagnosebericht wird
  durch Umschalten **nicht** verworfen.
- Die Katalognavigation verwendet ausgeschriebene, tastatur- und
  lesefreundlichere Aktionen **Leeren**, **◀ Zurück**, **Weiter ▶**
  beziehungsweise **Clear**, **◀ Previous**, **Next ▶**.
  Die sichtbare Textbreite dieser Aktionsknöpfe wird im GUI-Test
  zusätzlich zur äußeren Widgetposition gemessen.
- **28 erneut aufgenommene englische Fensteransichten**, jeweils
  14 Bereiche bei 1020×680 und 1320×800, liegen nur lokal unter
  `work/reports/layout-all-views-en/`. Die überprüften sichtbaren
  Steuerelemente ragen bei keinem dieser Aufbauten horizontal aus
  der Arbeitsfläche (0 beanstandete Positionen).
- **589 vollständige verfügbare Projekt-Tests bestanden**:
  `589 passed in 639.88s`, Exitcode 0.
  Die gezielte Sprachumstellungs-/Menü-/Knopfbreitenprüfung wurde
  nach den letzten Ergänzungen ebenfalls einzeln erfolgreich
  wiederholt (`2 passed`).
- Echter Win32-Tk-/Qt-Test vor den reinen Lokalisierungsänderungen
  `QA_PASS`. Die EN-Layoutprüfung stützt sich auf echte Tk-Elemente;
  das Qt-Rendering wird durch die eingebaute, separate native GUI-QA
  geprüft.

**Noch nicht erledigt:** die Qt-Sandbox mit allen Menüs, Tooltips,
Dialogen und dynamischen Inspektortexten zweisprachig durchgängig
umzustellen; Hoch-DPI- und Screenreader-Abnahme über alle Komponenten;
vereinheitlichte visuelle Hierarchie und längere Benutzersitzungen.
Die 589 erfolgreichen Tests sind kein Beweis der vollständigen
Barrierefreiheit oder 1:1-Spiel-HUD-Parität.
