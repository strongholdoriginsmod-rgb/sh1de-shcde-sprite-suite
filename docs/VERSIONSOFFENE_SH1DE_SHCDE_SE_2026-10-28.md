# Versionsoffene SH1DE-/SHCDE- und Script-Extender-Verarbeitung

**Stand:** 28. Oktober 2026  
**Entwicklungszweig:** `feature/version-neutral-sh1-shcde-20261028`

## Ziel

Keine bekannte, unbekannte, ältere oder neuere **Spiel- bzw.
Script-Extender-Versionsnummer** ist eine pauschale Zugangssperre für
SpriteSuite, Originaldaten-Inventur, HUD-/Sprite-Bearbeitung,
Versionsdiagnose oder DLL-freie Asset-Modpakete.

Eine Versionsnummer allein beweist jedoch **keine** native
ABI-, Speicherlayout-, Shader-, Noesis-, Lua- oder Gameplay-Kompatibilität.
Alle originalen Spieldateien bleiben während Inventur und Tests
schreibgeschützt durch das Arbeitsverfahren; Mod-Ausgaben liegen
in eigenen Arbeits-/Ausgabeordnern.

## Verbindliche Regeln

| Aufgabe | Verhalten bei unbekannter/abweichender Version |
|---|---|
| SHCDE-Ziel registrieren | Zulassen, wenn die fünf erforderlichen Spieldateien normal lesbar sind. Content-basierte Build-ID statt Versions-Whitelist |
| SH1DE als Datenquelle | Zulassen bei lesbaren fünf Quelldateien, unabhängig von historischem Release-Pin |
| SHCDE-Ziel aktivieren | Zulassen, sobald der aktuelle fünf-Dateien-Fingerprint exakt mit dem neu eingelesenen Mapping übereinstimmt und das Ziel ausdrücklich gewählt wurde |
| Mapping für anderes Spiel | Nicht automatisch anwenden; aktuelle Grafikquelle neu einlesen. Diese Schranke schützt vor falschen Sprite-IDs und beschädigten Arbeitsständen |
| Community-Plugin-Versionen | Jede Versionsbezeichnung lesbar; API-Mindestversionsangaben, Fremdplugins und unbestätigte Kombinationskonfiguration als **Review** statt pauschalem Versionsblock |
| DLL-freies SE-Asset-Mod | Unabhängig von der verwendeten SE-Versionsnummer vorbereiten; statische Bild-, Atlas-, XAML- und Pfadsicherheit weiter prüfen |
| Optionale C#-Runtime | Keine pauschale SE-Major-/Minor-/Patch-Sperre. Compiler-Referenzen, Hashes, MVIDs und das native Feldlayout müssen tatsächliche ABI-Kompatibilität belegen |
| Historischer SE-2.11-Installer | Bereits vorhandene unbekannte oder neuere SE nicht ersetzen, sondern behalten und ohne Dateiveränderung melden. Eine höhere deklarierte APIShared-Mindestversion führt ebenso zu einer unberührten Installation statt zu einer Rückstufung |

**Technische Schranken, die nicht abgeschafft wurden:** fehlende
Dateien, beschädigte Formate, symlinkbasierte Pfadumleitung,
nicht zusammenpassende Build-/Mapping-Daten, unbekannte native
Feldlayouts, ausgetauschte DLL-Bytes, doppelte Plugin-GUIDs und
Überschreiben fremder Plugins. Das sind Integritäts- oder
Schnittstellenkonflikte, **keine Versions-Whitelist**.

## Prüfen statt ungeprüft freigeben

Eine neuere oder ältere Version kann zur vollständigen Bestandsaufnahme
gewählt werden. Die Suite muss unbekannte Versionen diagnostizieren und
mit passenden Originaldaten arbeiten können, darf jedoch keine
inkompatiblen nativen Hooks als getestet ausgeben. DLL-freie
Grafikpakete sind der allgemeine versionsunabhängige Weg; für eigene
C#-Laufzeitpakete muss die konkrete API/ABI im Zielspiel separat geprüft werden.

### Rückbau und Freigabestatus

Vor einem schreibenden Modinstallationsversuch werden Zielidentität,
Mapping und Dateizustand verifiziert. Vorhandene Original-Spiele
werden niemals für einen Versionswechsel ersetzt. Bei Ingame-, Save/Load-
und Cross-SE-Kombinationen ohne Nachweis gilt weiterhin
**Funktion nicht vollständig verifiziert**.

Qualitätssicherung: Tests für synthetische SH1DE-/SHCDE-Versionen,
Aktivierung mit neuen Fingerprints, falsche Mappings, SE 1.x/2.x/3.x,
APIShared-Hinweise, Fremdplugin-Koexistenz, Versionstext ohne PE-Metadaten,
und den nicht überschreibenden historischen Installer. Siehe
`tests/sandbox/test_target_selection_version_guard.py`,
`test_community_mod_compat.py`,
`test_shcdese_legacy_installer_guard.py` und
`test_runtime_adaptive_references.py`.
