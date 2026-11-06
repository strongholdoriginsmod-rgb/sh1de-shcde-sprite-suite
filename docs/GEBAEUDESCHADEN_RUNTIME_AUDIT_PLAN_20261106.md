# SHCDE Gebäudeschaden – Runtime-Audit und Implementierungsplan (06.11.2026)

## 1. Verifizierte Grundlage
- Aktueller gemeinsamer Integrationsstand: `20bba53`, neuer isolierter Arbeitszweig `feature/building-damage-runtime-contract-20261106` auf `E:\SpriteSuite_DamageRuntime_20261106`.
- Die SHCDESE-API dokumentiert `GameBuildingManagerAPI.GetAllBuildings/GetAllAliveBuildings`, `GetType`, `GetCurrentHealth`, `GetMaxHealth`, `GetGlobalId`, `GetOnFireTicks`, `GetOccupiedTileIds` und `IsValid`. `BuildingR3EventHooks` bietet Damage, Repair, Spawn, Delete. Damit sind Gebäudezustand/Instanzidentität grundsätzlich abfragbar.
- `GetOnFireTicks` ist ein Indikator für derzeit aktive Feuerdauer, **kein historischer, absoluter Schadensursachenbeweis**. Mechanisch/Feuer muss daher konservativ als best-effort per Gebäude mit Zustandsprotokoll behandelt werden.
- Im bestehenden Runtime-Plugin gibt es `RuntimeTick`, einen persistenten Host sowie ausdrücklich fail-closed ausgelegte native Sprite-/Asset-Lanes. Die geteilten DLL-/SDK-Verweise werden per externem, versionsgeprüftem Bauvertrag vorgegeben, ein nackter `dotnet build` ist keine gültige Freigabe.
- Der Script-Extender-Asset-API-Index ist global und bei Modload vorindiziert; normale PNG-/Atlas-Overrides sind **keine** instanzspezifischen Zustandsübergänge.
- Vorhandene Runtime: `AssetStreamRuntimeLane` / `FortificationSpriteCatalog` und `FortificationFeature` können GM-Sprite-/Renderer-Operationen vornehmen, allerdings versions- und spielkontextspezifisch. Es gibt noch keine überprüfte generische Instanz-zu-Mehrtile-Spritezuordnung.
- Die neue SpriteSuite-Schadensbibliothek exportiert `damage-manifest.json` mit `runtimeHookInstalled:false`, optional `gameBuildingType`, pro Stufe `damageKind`, `hpAtOrBelow`, `tiles` samt SHA-256. Das ist der richtige sichere Übergabevertrag; eine direkte Installation darf daraus nicht vorgetäuscht werden.
- Der Zielrechner hat aktuell **keine dotnet-SDK-Installation** im PATH, aber .NET-Framework-C#-Compiler und Python/Node. Die rein algorithmische C#-Logik kann deshalb mit diesem Compiler separat geprüft werden; echte Plugin-Kompilation erfordert den freigegebenen Game-SDK-Baupfad und die korrekten DLL-Versionen.

## 2. Umsetzung – strikt in Etappen
1. **Quellstände sichern**: Git-Basis/Status notieren, keinerlei Änderungen an `E:\SpriteSuite`, anderen Worktrees oder Spielinstallationen.
2. **Reine C#-Entscheidungslogik**: expliziter eStructs-Gebäudetyp, Gesundheitsbruchvergleich ohne Float, geordnete getrennte mechanische/Feuer-Schwellen, Fallback, Persistenz aktiver Brandhistorie bis vollständig repariert, Slot-Reuse mittels Global-ID, invalid-state fail closed und begrenzte Zustandsliste.
3. **Python-Profilpreflight**: `damage-manifest.json` aus exportiertem ZIP strikt prüfen (Pfad-/ZIP-Sicherheit, Typ/HP-Eindeutigkeit, Tile-PNG, SHA, Geometrie, Reihenfolge, Dubletten). Ohne ausdrücklich geprüfte Zielgebäude-ID kein aktiver Runtime-Eintrag. Ausgabe als versionsgebundenen, zunächst nur lesenden Testvertrag, ohne Spielinstallation.
4. **Algorithmus-Tests**: C#-Compiler ohne Runtime/Game-Assembly starten, synthetische Szenarien prüfen: 100/75/40/0%, Brandanhalten/Erstauftreten/Ende, Reparatur, global ID Wechsel, ungültige oder unvollständige Daten. Python-/JS-Paritätsprüfungen für Manifest und HP-Grenzwerte. Keine wahren Spieler-ID-Mappings erfinden.
5. **In-Game-Leseprobe vorbereiten**: Bei allen benötigten realen API-Metadaten, aber ohne verifizierten SpriteRenderer-Pfad ausschließlich beobachtbare Leseadapter-/Klassifikationsschicht ausarbeiten; nur nach konkreter API- und Lebenszyklusvalidierung optional in Runtime-Host integrieren.
6. **Künftiger Renderer-Pfad**: In isolierter Spiel-/QA-Installation zunächst ein einzelnes Gebäude pro Typ, Referenz-Pivot/PPU/Material/Masken, unveränderte Vanilla-Sprites zurücksetzen, HP-Transitions, Feuer, Reparatur, Map-Reload, Multiplayer-/Replay-Abgleich, Fehlerfall und Speichersicherheit beweisen. Erst dann Instanz-Sprites erzeugen oder austauschen.
7. **Integration**: erst nach grünen lokalen Tests selektiven Commit auf bestehenden gemeinsamen Integrationszweig übertragen; Versions- und Diff-Bericht aktualisieren.

## 3. Sicherheitsvertrag
- Standardzustand bleibt inaktiv; keinerlei Spiel- oder Renderer-Manipulation durch Voranalyse.
- Kein Global-Override anhand einer dynamischen Schadensstufe.
- Referenzinfos/Modelle/Original-Tiles nicht verschieben oder überschreiben.
- Keine unbewiesene Querverwendung von TileId als BuildingId; eine eindeutige Zuordnung verlangt GameBuildingManagerAPI/GetOccupiedTileIds plus stabile GlobalId.
- Keine Race-sensitiven Unity-Operationen in R3-Hook-Callbacks (oft anderer Thread); falls benötigt, nur Daten zur späteren Main-Thread-Verarbeitung sammeln.
- Pro Gebäude einen begrenzten Zustand halten; bei Global-ID-Wechsel oder Löschung zurücksetzen; Fehler führen zu Vanilla-Bild.

## 4. Implementierter Read-only-Status

- `runtime/BuildingDamageOffline/BuildingDamageStageSelector.cs`: begrenzte, exakte Ganzzahl-HP-Auswahl; Feuerzustand hält bis zur vollständigen Reparatur; Global-ID-Wechsel leert veraltete Historie.
- `runtime/BuildingDamageOffline/BuildingDamageProfileTable.cs`: strikt geprüfte HP-/Gebäudetyp-Tabelle aus SHA-256-verifiziertem ZIP, keine Rendering-Aktion.
- `runtime/BuildingDamageOffline/BuildingDamageReadOnlyProbe.cs`: Main-Thread-Polling-Abstraktion mit vollständigem Snapshot vor Zustandscommit, ID-Duplikatsperre, endlicher Kapazität und Fail-closed-Stopp bis explizitem Reset.
- `runtime/BuildingDamageOffline/BuildingDamageGameBuildingSource.cs`: hochstufige `GameBuildingManagerAPI`-Lesezugriffe; prüft `IsValid` und `GetGlobalId` vor **und** nach der Abfrage. Kompiliert absichtlich nur, wenn `SHCDE_BUILDING_DAMAGE_READONLY_API` gesetzt wird. Der Standard-Runtime-Build und Spiel-Host verändern ihren Ablauf nicht.
- `tools/building_damage_runtime_preflight.py`: vollständiger PNG-Chunk-/IDAT-/Zeilenfiltertest, CRC, SHA-256, ZIP/JSON-Validierung, Materialmaskenprüfung, eindeutige Typen/HP-Stufen und normalisierte TSV-Tabelle. Nur `--prepare` schreibt Dateien, ausschließlich in einen neuen Ausgabeordner.
- `tools/qa_building_damage_runtime.py` erstellt und prüft das echte ZIP eines 5×5-Testgebäudes in einem temporären Verzeichnis: 16 Python-Regressionen, 56 C#-Selector/TSV-Assertions, 29 C#-API-Adapter-Assertions. Der Shader, Unity-Renderer und das Spiel werden nicht angesprochen.
- Strg+K-Werkzeugkatalog: Runtime-Preflight aufgenommen, Risikoetikett bei `--dry-run` lesend und bei `--prepare` Arbeitsdateien; Codex-Generierung mit `--execute` weiterhin separat als Netzwerkoperation.

## 5. Konkreter nächster Integrationsnachweis

Die öffentliche SHCDESE-Dokumentation bestätigt `GameBuildingManagerAPI.GetAllAliveBuildings`, `IsValid`, `GetGlobalId`, `GetType`, `GetCurrentHealth`, `GetMaxHealth` und `GetOnFireTicks`. Der lesende API-Adapter wurde gegen streng strukturierte Compile-Stubs und künstliche, während der Abfrage wechselnde GameBuildingManager-Zustände getestet. Das ist **kein** Test gegen die echten, zur aktuellen SHCDE-Spielinstallation gehörenden DLLs.

Vor der Renderer-Integration weiter nachweisen:

1. SDK-DLL- und Game-Build-Version passend zum gewählten installierten Script Extender; tatsächliche Main-Thread-Aufrufbarkeit, Map-Lifecycle und Abstimmung mit bestehenden Runtime-Features.
2. Eindeutige Zuordnung `GameBuildingManagerAPI.GetOccupiedTileIds` zur Reihenfolge der SpriteSuite-Tile-Slots, inklusive unterschiedlicher Footprintgrößen, Gebäuderotation, Ausrichtung, Höhe und zerstörten Rohdaten.
3. Nachweis des per-Gebäude **und per-Tile** ersetzbaren Sprite-Rendererpfads inklusive TeamColour-/Materialmasken, Sprite-Pivot, PPU und Renderer-Wiederherstellung.
4. Getrennte Original-/Runtime-Bilddaten und eigener Speicher-/Verfügbarkeitsvertrag, der bei Fehler automatisch Vanilla aktiviert. Keine globalen Overrides für dynamische Stufen.
5. Kleiner In-Game-QA-Test auf einer separaten Installation: Spawn, 75/40/0 %, aktives Feuer, Löschen, vollständiges Reparieren, Speichern/Laden, Map-Wechsel und parallele Gebäude.
6. Erst danach Makro und Runtime-Anbindung im Spiel aktivieren und unter kontrolliertem Feature-Schalter starten.

**Offline-QA-Aufruf:** `python tools/qa_building_damage_runtime.py` aus dem Projektverzeichnis. Alle Artefakte werden temporär erzeugt und nicht installiert.

## 6. Letzter vollständiger Offline-Abgleich (06.11.2026)

- `node --test ...` im Sprite Editor: **137/137** Tests bestanden.
- Vollständige ältere Edge-Browser-Workflows: **49/49**, keine Anwendungs-Netzwerkanfragen.
- Direkter `file://`-Edge-Browsertest für Gebäudeschäden, freie Ausgabe und KI-Übergabe: **16/16**, keine Anwendungs-Netzwerkanfragen.
- Vorhandene Suite-/Werkzeugkatalog-/Policy-Tests: **23/23** bestanden.
- Codex-/GPT-Image-Bridge Offline-Mocks: **10/10** bestanden.
- Runtime-Preflight inklusive manipuliertem PNG/ZIP/JSON und freier Ausgabe: **18/18** Python-Tests.
- C#-Schwellen-, Feuer-/Reparatur- und ZIP-/TSV-Abgleich: **56** erfolgreiche Assertions.
- C#-Leseadapter mit synthetischen SHCDESE-Signaturen und ID-Reuse-Fehlern: **29** erfolgreiche Assertions.
- `verify_release.py`: deterministische deutsche und englische HTML-Fassungen, beide Browserberichte und **162** SHA-256-Prüfsummen erfolgreich.
- `git -c core.whitespace=cr-at-eol diff --check`: keine Konflikte.

**Schnittstelle für die spätere Renderer-Arbeit:** Die öffentlich dokumentierten Gebäude-APIs sind [GameBuildingManagerAPI](https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/api/SHCDESE.API.GameBuildingManagerAPI.html) und die [Asset API](https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/asset-api.html). Die Asset API beschreibt globale bzw. namespace-lokale Overrides, nicht einen nachgewiesenen per-Gebäude- und per-Tile-Zustandsrenderer. Deshalb ist zunächst nur die Leseebene implementiert; die dynamische Spielrenderer-Anbindung ist weiterhin eine offene Entwicklungsaufgabe.

## Freier Runtime-Preflight und freiwillige Freigabekontrolle

Das neue `approvalDigest` wird beim SpriteSuite-Export neben den freigegebenen Tiles dokumentiert. Der Offline-Preflight prüft, dass es syntaktisch ein SHA-256-Wert ist; er kann die interne Projektdatei nicht auf Echtheit attestieren. Fehlt es in älteren oder bewusst frei exportierten Paketen, wird die Stufe in `unboundApprovedStages` dokumentiert. `--prepare` erzeugt standardmäßig auch für diese Stufen eine Testtabelle. Erst die ausdrücklich gewählte Option `--require-bound-approval` verlangt für jede Stufe einen gültigen Digest. Die Option `--dry-run` bleibt für reine Analysen verfügbar; es findet keine Spielinstallation statt.

Der synthetische Exporttest setzt den vorgesehenen Zielgebäudetyp jetzt **vor** der Modellfreigabe, damit die Änderung der Zuordnung keine bereits abgenommene Stufe unbemerkt ungültig macht.

## Abschluss der aktuellen Offline-Gates

Das vollständige Runtime-QA-Kommando `python tools/qa_building_damage_runtime.py` besteht nach der Aktualisierung des Freigabevertrags mit **18** Python-Preflight-Tests, **56** C#-Selector-/ZIP-Assertions und **29** schreibfreien API-Adapter-Assertions. Die gezielt synthetische Gebäude-ID wird vor der Modellfreigabe gesetzt, danach bleibt sie im SHA-256-gebundenen Zustand unverändert. Alte Datenpakete ohne eine solche Freigabehash-Bindung können diagnostiziert, aber nicht als angeblich geprüfte Runtime-Tabelle vorbereitet werden. Die aktive Renderer-Zuordnung bleibt bewusst deaktiviert.

## Erweiterung des Renderer-Vorabnachweises – Footprint-Audit

Die freigegebenen Gebäude-Datenpakete liefern jetzt eine versionsgeprüfte, **rückwärtskompatible** Raster-Schnittstelle: `runtime-table-v2` enthält `sprite_a` und `sprite_b`. Historische `v1`-Tabellen behalten ihre HP-Auswahl, dürfen aber mangels Rasterkoordinaten nicht zur Rendererzuordnung verwendet werden. Ein fehlerhaft gemischtes Raster wird bereits im Python-Preflight verweigert.

Die pure C#-Footprint-Analyse und der getrennte, nur auf expliziten Compiler-Schalter aktivierbare Gebäude-/Tile-Leseadapter stehen in `BuildingDamageFootprintAudit.cs` und `BuildingDamageFootprintGameSource.cs`. Es wurden zwei vorhandene SHCDESE-Assembly-Versionen (1.44.0 und 2.14.3) ohne Spielausführung erfolgreich **zur Compile-Zeit** geprüft. Der konkrete Bericht mit SHA-256, Quelldokumentation und noch offenen In-Game-Abnahmekriterien ist [GEBAEUDESCHADEN_FOOTPRINT_API_AUDIT_20261106.md](GEBAEUDESCHADEN_FOOTPRINT_API_AUDIT_20261106.md).

Die entscheidende Erkenntnis bleibt: Gameplay-belegte Tile-IDs und SpriteSuite-Grafikslots sind nicht automatisch dasselbe. Jede reale Modellumschaltung bleibt blockiert, bis ein gemessener per-Instanz-Spritepfad, Ausrichtung sowie Masken-/Renderer-Rollback existiert.

### Ergänzender historischer Converged-Zweig (früherer Stand)

Das vollständige Runtime-QA-Kommando `python tools/qa_building_damage_runtime.py` besteht nach der Aktualisierung des Freigabevertrags mit **18** Python-Preflight-Tests, **56** C#-Selector-/ZIP-Assertions und **29** schreibfreien API-Adapter-Assertions. Die gezielt synthetische Gebäude-ID wird vor der Modellfreigabe gesetzt, danach bleibt sie im SHA-256-gebundenen Zustand unverändert. Alte Datenpakete ohne Freigabehash können ebenfalls als ungebundene Runtime-Testkandidaten vorbereitet werden; der Freigabestatus bleibt transparent. Die aktive Renderer-Zuordnung bleibt bewusst deaktiviert.
