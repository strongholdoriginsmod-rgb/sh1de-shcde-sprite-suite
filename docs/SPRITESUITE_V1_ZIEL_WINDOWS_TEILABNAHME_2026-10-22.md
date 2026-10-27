# Sprite Suite – V1-Szenen, Zielversionierung und native Windows-QA
**Stand:** 22.10.2026 · **Arbeitsprojekt:** E:\SpriteSuite · **Git HEAD:** 00276ec

## Implementiert und gezielt geprüft
- Historische V1-Szenen werden im eigenen Schema erhalten: prozeduraler Boden mit Saat, GM1-Kompositaufbau, Frameanimationen, Titel, Teamfarbe und HUD-Metadaten. Der ursprüngliche Sandkasten-Renderer bleibt Pixelreferenz. Ein Qt-Dialog bietet Änderung der genannten Eigenschaften, Undo/Redo und Zeitvorschau; Speichern erfolgt im gesicherten Arbeitsordner.
- Zielauswahl: `target_selection_guard.py` prüft 5 vollständige SHCDE-Dateien gegen `supported-builds.json` und die Ziel-Build-ID von `work/mapping/proposals.json.gz`, zusätzlich die 5 SH1DE-Dateien. Registrierung aktiviert kein Ziel. Der bestehende Zielmanager und Tk-Dialog fordern ausdrückliche Auswahl, die Build-Ausführung verweigert fehlende oder inkompatible aktive Ziele. Kein produktives Ziel wurde geschrieben.
- Tcl/Tk: die Bibliothekspfade werden vor Python-Start gesetzt. Reine Tk-Zyklen und komplette Suite-Zyklen laufen nativ. Die Ursache der GDI-Wachstumsrate waren zurückgebliebene Tk-Variablentraces, die alte Universal-Roots hielten; sie werden beim bestätigten Schließen abgemeldet.

## Belastbare Zahlen
- V1-/Szenenmodell-/Zielverwaltung: **22 bestandene Tests** im abschließenden gezielten Lauf, 0 Fehlschläge.
- Native Lebenszyklus-Prüfung `work/reports/ui-audit/native-windows-lifecycle-20261022.json`: Status **PASS**, 20 reine Tk-Zyklen und 25 komplette Suite-Zyklen; GDI-Differenz reine Tk **+1**, Suite **0**, USER-Differenz Suite **0**. Tatsächlich beobachtete DPI **96**.
- Reale 2.80-QA-Zielkopie: **5/5** Zielpins stimmen; lediglich lesend geprüft.
- Git-HEAD unverändert, kein Build, keine Modinstallation, kein Commit.

## Nicht als abgeschlossen beansprucht
- **DPI:** Nur 96 DPI wirklich gemessen; 120/144/192 DPI, Monitorwechsel und Screenreader noch nicht validiert.
- **Volle Windows-Dauerabnahme:** 25 native Suite-Neustarts sind bestanden, nicht jedoch ein mehrstündiger echter Tk+Qt-Bedienlauf. Vor dem Fix war der native 60er-Suite-Lauf wegen +177 GDI-Handles fehlgeschlagen.
- **V1:** Die historischen zwei Szenen werden im Modell und Qt-Bedienpfad bearbeitet; umfassende Pixel- und Performanceparität aller Szenentypen sowie alter Tool-Spezialfälle bleibt weiter abzugleichen.
- **Zielwahl:** E:\SSGameQA ist versionsgleich, aber **nicht** als Produktionsinstallation benannt. Registrierung/aktive Konfiguration fehlen bewusst bis zu einer ausdrücklichen Benutzerwahl.
- **Gesamtsuite:** Es gab in dieser Entwicklungsrunde neue Module und Anpassungen; der zuvor grüne 642-Test-Headless-Lauf wurde **nicht vollständig erneut** ausgeführt. Die Gesamtfreigabe bleibt **NEIN**.
