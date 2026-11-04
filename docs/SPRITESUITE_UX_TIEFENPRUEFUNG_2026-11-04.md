# SpriteSuite – minutiöse Workflow-/Interface-Prüfung, 04.11.2026

**Status: lokaler Windows-UX-Integrationskandidat, keine öffentliche Stable-/Ingame-Freigabe.**

## Grundlagen und Schutzgrenzen

- Isolierte Git-Quelle: audit/ux-meticulous-20261104, Ausgangscommit e94df766821569a85530ff88ba60562e25572c16.
- Alle GUI-Läufe verwenden synthetische PNG/XAML-Projekte sowie testkontrollierte Einstellungen und Locks. Originale, Spiele und ältere Portable-Ausgaben bleiben unverändert.
- Native Spiel-/Noesis-/C#-ABI, wirkliche Spielkarten und Atlas-Rollback sind durch diese synthetischen GUI-Tests nicht bestätigt.

## Tatsächliche Sichtprüfung

Alle **18 Arbeitsbereiche** der Universal-Suite wurden in einem realen Tk/Qt-Prozess jeweils bei **1020 × 680** und **1440 × 900** geöffnet und mit Windows PrintWindow fotografiert (**36 Fensteraufnahmen**). Die aktive Projektseite wurde in zwölf Kombinationen von Fenstergrößen und Tk-Skalierung (1.0, 1.25, 1.5, 2.0) vermessen. Im historischen Bereich „Editor & Austausch“ liegen bei 1020 × 680 fünf Bedienelemente unterhalb des sichtbaren Ausschnitts, die jedoch über die Abschnittsauswahl und den Scrollbereich erreichbar sind. Dies ist eine dokumentierte Bediengrenze; keine Fachwerkzeuge wurden versteckt oder entfernt.

Zusätzlich visuell geprüft wurden der Layout-Designer bei **880 × 570**, die Sandbox ohne private Originalkarte und die englische Hauptwerkbank bei 1020 × 680.

## Gefundene und korrigierte Fehler

1. **Deutsch/Englisch unvollständig.** Wichtige Titel, Schaltflächen, Kategorien und dynamische Statusmeldungen blieben in EN deutsch. Der Übersetzungskatalog wurde ergänzt und eine reversible Anzeige für dynamische Statuswerte implementiert. Persistierte Kategorien, Arbeitsdateien und Exportmetadaten bleiben unverändert.
2. **Sprachwechsel löste Projektreiter-Neuladen aus.** Das ersetzte die soeben angezeigte Export-Erfolgsmeldung. Reaktivierung erfolgt jetzt nur nach echtem Reiterwechsel; Sprache aktualisiert allein die sichtbare Anzeige.
3. **Abgeschnittene EN-Elemente bei 1020 × 680.** „More actions“, die Tabellenspalte „Status“ und ein Seitenleistenhinweis waren zu breit. Kürzere Beschriftungen, geringere Spaltenbreiten und angepasster Textumbruch beheben dies.
4. **Deaktivierter „Abbrechen“-Button im Leerlauf.** Der Knopf wird nur sichtbar, wenn tatsächlich ein CLI-Lauf akzeptiert wurde.
5. **Leere Spielvorschau ohne Erklärung.** Eine fehlende Originalkarte erhält eine verständliche Meldung und einen Weg zur Spieleinrichtung; der Hinweis verschwindet bei echter Karte.
6. **Mindestgröße des Layout-Designers.** Die Ebenenliste verdrängte Eigenschaften und der Status wurde abgeschnitten. Unter 700 px Fensterhöhe sind vier statt sieben Tabellenzeilen gleichzeitig sichtbar, die Werte lassen sich früher erreichen und der Status wird mehrzeilig umgebrochen.

## Nachweisbare Prüfungen und offene Gates

- Vor Korrektur: **178 GUI-/Navigation-/Workflow-/Sicherheitsregressionen bestanden**, 0 Fehler.
- Gezielt nach Korrektur: kombinierte 37-Tests-GUI-Suite bestanden und weitere Mindestfenster-, Sprach- und Zustandsprüfungen bestanden.
- Derselbe größere GUI-Testkatalog wird nach allen Änderungen erneut ausgeführt; Ergebnis wird getrennt protokolliert. Ein unterbrochener oder übersprungener Test zählt nicht als bestandener.
- Ein neu verpackter Windows-x64-Portable-Kandidat muss an einen sauberen Git-Commit gebunden sein, ZIP/CRC/SHA, neu entpackten Launcher, echte Tk-GUI und synthetische Projekt-/Mod-ZIP-E2E-Prüfungen bestehen.
- Offen vor **öffentlicher Stable-Freigabe**: unabhängiger Windows-PC, echte Ingame-/Noesis-/C#-ABI-/Atlas-Rollback-Abnahme, visuelle/dpi-/Screenreader-Nutzungsprüfung und Rechteprüfung privater Originalassets.

## Separat gesicherte QA-Belege

Alle Messdaten, Screenshots, Testprotokolle und Paketintegritätsnachweise liegen unter E:\SpriteSuite_UX_MinutiösQA_Results_20261104: geometry_matrix.json, navigation_audit.json, screens/, contact-sheet-1.png, contact-sheet-2.png, deep-gui-regression.xml, postfix-deep-gui-regression.xml und gezielte Regressionen. Es wurden keine privaten Originalspielgrafiken in Git eingebracht.
