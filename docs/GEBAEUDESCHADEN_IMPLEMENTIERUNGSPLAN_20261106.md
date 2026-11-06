# Gebäudeschadens-Workflow – Implementierungsplan (06.11.2026)

## Umsetzung in überprüfbarer Reihenfolge
1. Arbeitsisolation: eigenes Git-Worktree ab dem geprüften 1px-Overlap-Commit; bestehende 162 Änderungen in `E:\SpriteSuite` nicht anfassen.
2. Pure Domain: `src/damage.js` mit strenger Profil- und Schwellenvalidierung, Auswahlfunktion, monotoner Reihenfolge, Prompterstellung und technischer PNG-Prüfung (ohne DOM).
3. Datenmodell: optionales `damageProfiles` im bestehenden Schema 2, rückwärtskompatibel mit Altprojekten; gespeicherte Kandidaten-Asset-IDs in History/SHSPRITE aufnehmen; Szenenreferenzen validieren; bestehende Projekte ohne neue Daten weiterhin vollständig lesbar.
4. Szenenworkflow: Gebäudescene auswählen und Schadensstufe aus unabhängigen Klonen der Basis-Tiles erzeugen; für die neue Stage keine automatischen SHCDE-Zielnamen übernehmen. Beim Wechsel zwischen Stufen keine Ausgangsbilder überschreiben.
5. UI: Inspector-Tab „Schaden“ mit Gebäudeauswahl, mechanisch/Feuer, HP-Testwert, sauber sortierten Schwellen, Szenenwechsel, Änderungstexten, Referenzexport, Kandidatenimport und Abnahme.
6. Codex-Austausch: ZIP mit Referenz-/optionalem Vorgängerbild, Modellwahl, sachlichem Prompt und ausführbarer Instruktion. Lokaler Python-Adapter validiert das Bundle, führt nur auf ausdrücklichen Aufruf die GPT-Image-2.6-Edit-Anfrage aus und legt PNG plus nicht geheime Metadaten separat ab.
7. Qualitätsgate: exakte Original-Canvas, echter Alphakanal, Validierung von Inhalt/Position und kontrollierte Zerlegung des generierten Kandidaten mit `core.partition/split` unter `{overlap:1,rearShare:true}`. Keine automatische Freigabe. Nach Änderung einer bereits freigegebenen Stage automatische Rückstufung auf Entwurf.
8. Ausgabe: separate deterministische `damage-manifest.json` plus Stufentiles; ausschließlich freigegebene Varianten, Schwellen und Ursache. Standard-Script-Extender-Modexport ignoriert Stage-Gruppen.
9. Regression: Node-Tests für HP-Grenzen, Feuer-Fallback, geordnete Stufen, ungültige/duplizierte Schwellen, Projektroundtrip mit Kandidat, 64px, Alpha, Masken, Abnahme und Nichtbeeinflussung des Standardexports; CLI-Python-Tests mit simuliertem API-Response.
10. Releasekontrolle: HTML neu bauen, DE/EN-Gleichheit nach existierendem Projektstandard prüfen, Tests/Browsertests laufen lassen, Git-Diff und Status dokumentieren. Keine Löschung oder Spielinstallation.

## Abbruch-/Rückrollregel
Jeder Fehler in der Validierung oder Split-Rekonstruktion führt zu vollständigem Abbruch ohne Commit. Originalscene und Arbeitsspeicher-Assets werden nicht mutiert. Neue Dateien im isolierten Worktree sind durch Git-Diff nachvollziehbar; Rücknahme ist nicht an Hauptrepository oder Spieldaten gekoppelt.
