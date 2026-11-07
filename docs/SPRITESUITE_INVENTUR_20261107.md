# SpriteSuite – Chronologische Bestandsaufnahme und Übernahmeprüfung

Prüfstand vom 7. November 2026. Die Inventur hat 7 Git-Repositories, 43 lokale Zweige und 36 registrierte Worktrees in den unmittelbar relevanten SpriteSuite-, Grafikdaten- und Spielfamilien erfasst. Davon gehören 30 Zweige und 27 Worktrees zum kanonischen Git-Repository. Die drei während der Arbeit angelegten Worktrees sind im Zensus enthalten. Eigenständige Upstream-Abhängigkeiten, automatisch angelegte Test-Repositories und zusätzliche Spielprojektkopien wurden bei diesen Zahlen ausgesondert.

Die Reproduktion, aktuellen Statuscodes, SHA-256-Vergleiche, Remotes, Branch- und Commit-Daten liegen in der kompakten JSON-Inventur. Commit-Divergenzen beziehen sich auf 8d7eac4. Die Datei-SHA-256 vergleicht Arbeitsdateien mit dem Ziel-Checkout während der Inventur. Der Kandidatenzensus und die Archivprüfung erfassten HEAD und Arbeitsstand anschließend erneut.

## Chronologie

| Commit bzw. Zeitraum | Befund |
| --- | --- |
| 30. September 2026, 66dd212 | Ausgangskatalog der Grafikdaten. Zwei separate GitLab-Quellen liegen auf demselben Commit. Der Audit-Checkout meldet 13.562 staged Löschungen. Der Import-Checkout enthält den Stand vollständig. |
| 14. Oktober 2026, 00276ec | Ältere eigenständige SpriteSuite-Git-Familie mit Sandbox-, HUD- und UI-Entwicklung. Ihre beiden weiteren Worktrees liegen auf f6aa498 und 6e635a0. |
| 27.–31. Oktober 2026, f305d38 bis 39d0768 | Source-only-Stamm, SHCDESE-Kompatibilitätsverifikation, HUD-/Noesis-Arbeiten, UIs, Projektmetadaten, Portabilität und erste v2-Kandidaten. Der separate GitHub-Publish-Checkout eade2dd ist Vorfahr des Zielstands. |
| 1.–2. November 2026, 60e012d, 849ca1f, 1967129, 45789b3 | Origins-Menüs, interaktive Werkzeug-Demos, Tcl-/Noesis-Prüfungen und native Noesis-Anbindung. Diese Spitzen sind im Zielverlauf enthalten. |
| 4.–5. November 2026, 2284a86, 3ebd7a0, 6c635f9, dffce3f | UI-Feinprüfung, geführte Workflows, Spiel-QA und getestete Windows-Laufzeitpakete einschließlich experimenteller Python-3.15-Kompatibilität. |
| 6. November 2026, 10c79be, 7672835, b50e8ea, 20bba53 | Kachelüberlappung und Alpha-Kanten, Gebäudeschaden-Szenen, gemeinsame Workstreams und zentrale Werkzeugübersicht. |
| 6. November 2026, 7bdd125, d4dd387, aaa0702, 5296208 | Bibliotheks-Preflight, HP-Beobachtung, Stufenprüfung, Gameplay-Footprints und isolierte Renderer-QA. Für vier parallele Zweige ist der Git-Dateibaum mit den enthaltenen Pendants exakt identisch. |
| 6. November 2026, 275d766, 0dd2458 | Zusammenführung freier Bearbeitungsabläufe und Runtime-QA, statischer Lebenszyklus der Probe und IL-Nachweis für TileData. |
| 6.–7. November 2026, f78b39f und d09397d | Zwei Nachfolger von 0dd2458. Tilemap-Beobachtung auf f78b39f, Grafiklayer und isolierter Sprite-Kanarientest auf d09397d. Merge 9bf262c kombiniert beide Beweisketten und löst die drei überlappenden Pfade auf. |
| 7. November 2026, 8d7eac4 und ce24864 | Native Originalsprite-Extraktion und acht unabhängig verwendbare Kornkammer-Anfragen. Separat integrierte HP-/Feuer-Runtime aus der uncommitteten Arbeitskopie. |
| 7. November 2026, b14b46f | Freie Mod-Dateien sind im bearbeitbaren Projekt verknüpft. Der Projekt-Asset-Worktree befindet sich weiterhin im selben Git-Verlauf. |

## Uncommittete Änderungen und Übernahme

| Quelle | Vergleich und Klassifikation |
| --- | --- |
| E:\SpriteSuite_HPFireIntegration_20261107 | 2 geänderte und 15 untracked Pfade. A/B. Live-Mod, Stufenauswahl, Bindings, Paketprüfung, HP-/Feuer-Logprüfer und QA-Quellen waren nur im Worktree vorhanden und wurden über adf424a und ce24864 eingebracht. |
| E:\SpriteSuite_DamageVisualProof_20261107 | 10 geänderte und 7 untracked Pfade. A/B. Sieben neue Dateien für Quellenextraktion, Typenkatalog, native SHSPRITE-/ORA-Erstellung, acht Schadensentwürfe und Tests wurden in 8d7eac4 übernommen. E. Der entworfene API-Pfad und die Reihenfolgesperre sind durch den Kontoworkflow und unabhängige Anfragen abgelöst. Die übrigen geänderten Registrierungs-, Prompt- und Dokumentationspfade betreffen die parallele Integration. |
| E:\SpriteSuite_ToolConsolidation_20261106 | 10 lokale Pfade. D. Beide Konsolidierungsdokumente, zwei Tests und das Inventarwerkzeug sind bytegleich in 20bba53. E. Fünf verbleibende Pfade enthalten frühere README-Texte und die Vorgänger der Suche, Richtlinien und Registry. Die Zielversion ergänzt Suchbegriffe und Werkzeuge sowie eine differenzierte Einordnung ausführbarer Aktionen. |
| E:\SpriteSuite_GameLiveIntegration_20261105 | D. Die einzige untracked Datei tools/suite_live_noesis_log_audit.py liegt SHA-256-identisch im Ziel. SHA-256 a036f853106b7ba00abbbe026d050ad0179f8d89e432a2dd14c98cf03842e46d. |
| E:\SpriteSuite | D. 168 der 213 lokalen Pfade sind bytegleich, weitere 2 unterscheiden sich nur in Zeilenenden. Die 20 am Zielpfad fehlenden Dateien sind leere HUD-Zwischendateien. E. In den 23 verbleibenden Pfaden betreffen ältere Tests unter anderem frühere Versionssperren und starre GUI-Paketregeln. Der AST-Vergleich fand in den abweichenden Produktions-Python-Dateien keine zusätzliche Funktion oder Klasse. Verhaltens- und Datenunterschiede der separaten Familie bleiben im Inventar einzeln erkennbar. |
| StrongholdEuropeDE und SE144 | Separate gemeinsame Git-Familie mit Spiel-Runtime, Diplomatie und Upstream-Tests. Ihre Worktrees haben 2.370 bzw. 477 lokale Einträge. Der Zensus hält sie getrennt von SpriteSuite fest. |
| Detached QA und Grafikdaten-Audit | Detached QA 39d0768 liegt im Verlauf, enthält aber 22.813 ignorierte Dateien. Der separate Grafikdaten-Audit-Checkout enthält staged Löschungen; das GitLab-Import-Repository erhält den gleichen Quellcommit. Beide sind keine Bereinigungskandidaten in dieser Runde. |

Exakte Commit-Paare aus jeweils leerem Dateibaumvergleich

| Parallelzweig | Im Zielverlauf enthaltenes, dateigleiches Pendant |
| --- | --- |
| 37eb85a | 7bdd125 |
| 9161cae | d4dd387 |
| 4bd7354 | aaa0702 |
| b791fa7 | 5296208 |

## Lokale Sicherungen

Der ältere Bereinigungsbericht protokolliert 21 bereits am 6. November entfernte Worktrees bzw. Zweige. Die 16 vorhandenen historischen Archiv-ZIPs wurden in dieser Runde unabhängig per ZIP-CRC geprüft und neu per SHA-256 gehasht. Die drei Nov.-6-Portable-Kandidaten stimmen mit ihren bestehenden SHA-256-Beipackdateien überein.

| Alter Portable-Kandidat | SHA-256 |
| --- | --- |
| SpriteSuite_Shared_RC_Portable_20261106 | 7af91d9aeb5c4379809e338ef87eab369799fe125de88ac1ac7a0a216da06191 |
| SpriteSuite_Converged_RC_Portable_20261106 | fd9c2b169b244a85b80694d65937d849c593f4fee6410c4e00c839f0dcf8334d |
| SpriteSuite_RenderEvidence_RC_Portable_20261106 | e108a4306ddaf1f7b0999c2a63d23d771c1a669b05908a851ee334921fd9877b |

Für neun saubere, im Ziel enthaltene Worktrees liegen 415 ignorierte Dateien in verifizierten ZIP-Archiven. Jedes Archiv enthält den exakten Ursprungspfad, Zweig, HEAD, Commit-Datum und SHA-256 jeder Datei. CRC, Manifest, archivierte Bytes und Quelldateien wurden gegengeprüft. Diese Vorprüfung ist von einer abschließenden Live-Prüfung unmittelbar vor einer Entfernung getrennt.

| Worktree | HEAD | Archivierte Dateien | ZIP SHA-256 |
| --- | --- | ---: | --- |
| E:\SpriteSuite_TileOverlap_20261106 | 10c79be | 1 | 068d6ce4d846b881d43611cfe60483699378efeb3b20104f0060f070b825981e |
| E:\SpriteSuite_BuildingDamage_20261106 | 7672835 | 2 | b3cf25a5091d40196c176cf601943ed5d5f0c25220b2d0a6b4b4a33a8a6c0f55 |
| E:\SpriteSuite_Integrated_Final_20261106 | aaa0702 | 58 | f1a361745d2fd59ffad5bd98a2827029110ddc605f93258bcd8a88e26b11d2ca |
| E:\SpriteSuite_ConvergedMergeQA_20261106 | 275d766 | 63 | 5aafe5a62df9b38387ea05340ec1e9d34ba6c2e7c9b2c0a766e97f2de550b6e5 |
| E:\SpriteSuite_DamageRunnerFix_20261106 | 0dd2458 | 21 | 5682ca7b216a435ce48a741c1df50743e107a29576bf1c8b149afb77012c9d5c |
| E:\SpriteSuite_Converged_20261106 | f78b39f | 100 | a9560203d180c4b6d545cf984bf181bd0baf47838c1ea507b9366a53d819d6d5 |
| E:\SpriteSuite_RenderEvidence_20261106 | f78b39f | 24 | f53d6eccc3757f343c8523e0cb42ea6d6cc4a41bed64bddaf93c1df38fbdf51f |
| E:\SpriteSuite_DamageGameMapQA_20261106 | d09397d | 68 | c4d248f977de1a078542d0f1039ef444634a5b4ca44abe4dba2c813355150fed |
| E:\SpriteSuite_FinalCandidate_20261106 | d09397d | 78 | 420436d6a5e38b4f77cb1c47b2565a6cb6b26d3b385966e78ff9b1f7d19765eb |

Die vier bytegleichen, per Commit-Ancestry divergierenden Zweige erfordern zusätzlich eine eindeutige Sicherung ihrer Git-Referenzen. Private QA, die externe Git-Familie und aktive Arbeitskopien haben eigenen Bestand.

Entfernte Worktrees und Zweige in dieser Runde jeweils 0. Die verifizierten Archive bereiten die spätere Bereinigung nach der ausstehenden End-to-End-Spielabnahme vor.

## Nachweis für Originalsprites und Renderer-QA

- 41 zielgerichtete Python-Tests zum vereinten Renderer-Audit, Logparser, Tilemap-Korrelation und Werkzeuginventar bestanden. Die Standardprobe und die SHA-gebundene AutoMap-/Kanarien-Variante kompilierten jeweils gegen die DLLs der isolierten SHCDE-QA-Kopien.
- 10 Python-Tests zur Originalsprite-Extraktion und 5 Node-Tests zur nativen Autorenausgabe und Stufenplanung bestanden.
- Die tatsächliche UnityPy-Extraktion aus der SHA-geprüften QA-Datei resources.assets erzeugte 16 Original-PNGs. Alle 16 stimmen bytegenau mit der bestehenden Extraktion überein. Acht Ausrichtungen wurden visualisiert. Das SHSPRITE-Projekt, OpenRaster, PNG-Vorschau und acht Anfrage-ZIPs wurden mit den vorhandenen echten Kornkammer-Referenzen erzeugt. Die PNG-Anfragen dokumentieren unveränderte Originalreferenzen und individuelle Prompts.
- Diese Probe misst Dateiintegrität und Kompilierbarkeit. Die Verifizierung der gewählten Spielausrichtung und der dynamischen visuellen Übergänge verlangt die separaten Spieltests.

## Reproduktion

Die folgenden Befehle werden im Arbeitsordner ausgeführt.

    python spritesuite_inventory.py spritesuite_inventory.json
    python summarize_sprite_inventory.py spritesuite_inventory.json
    python spritesuite_cleanup_census.py
    python verify_sprite_archives.py spritesuite_archive_audit.json

Die kompakte Inventur fasst ignorierte Dateien nach Stammordner zusammen. Quellnahe ignorierte Dateien behalten Einzelpfade und Prüfsummen. Vor jeder Entfernung ist der aktuelle Worktree erneut gegen das vorliegende Archiv zu prüfen.
