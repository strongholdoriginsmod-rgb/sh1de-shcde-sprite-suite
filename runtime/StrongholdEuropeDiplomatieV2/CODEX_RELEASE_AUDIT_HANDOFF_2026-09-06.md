# Codex-Release-Audit: eigenständige Diplomatie-Mod V2.1

Stand: 2026-09-06, nach Build 16:16:30  
Adressat: Claude Code  
Scope: ausschließlich das eigenständige BepInEx-Plugin `StrongholdEuropeDiplomatieV2`  
Arbeitsverzeichnis: `E:\Stronghold Crusader Definitive Edition Baldwin and Bullseye MULTi20\SE144`

## 0. Verbindliche Kurzfassung

Die Diplomatie-Mod ist auf Codebasis bereits ungewöhnlich umfassend abgesichert, aber **noch nicht öffentlich release-fertig**. Es wurde kein P0-Befund gefunden, der aktuell einen reproduzierten Absturz oder eine Savegame-Beschädigung belegt. Vor einer separaten Veröffentlichung sind jedoch mindestens diese Punkte zu erledigen:

1. **P1-A – fehlerhafte feindliche Nahbereichszuordnung:** Der Initialwert `int.MinValue` läuft bei der Differenzbildung über. Dadurch bleibt die nicht vertraglich geschützte Nahbereichszuordnung für sehr lange Zeit wirkungslos. Zusätzlich ist der 32-Tick-Throttle global statt beziehungsbezogen und wird vor vollständiger Validierung verbraucht.
2. **P1-B – unvollständige Lokalisierung:** Der Nutzer verlangt alle Sprachen, die Stronghold Crusader: Definitive Edition nativ anbietet. Implementiert sind momentan nur 7 von 21 Sprachen; 14 native Sprachen fehlen.
3. **Release-Gate – aktuelles Artefakt noch nicht im Spiel abgenommen:** Die installierte DLL entspricht zwar bytegenau dem aktuellen Dist-Build, aber das letzte Spiellog ist älter als diese DLL. Die aktuelle Revision besitzt deshalb noch keinen belastbaren In-Game-Nachweis.
4. **Öffentliche Produktidentität und Distribution:** GUID, Anzeigename und Metadaten sind weiterhin als `private` markiert; README, Lizenz und Changelog fehlen im Paket.

Die Punkte in den Abschnitten 4 bis 9 sind ebenfalls vor einer belastbaren öffentlichen Freigabe zu prüfen beziehungsweise zu härten. `public_release_ready` und `in_game_acceptance_recorded` dürfen erst nach vollständiger In-Game-Abnahme umgestellt werden.

## 1. Genaue Abgrenzung

Dieser Audit betrifft nur:

- `runtime/StrongholdEuropeDiplomatie/` als gemeinsam verwendete Diplomatie-/Host-Basis,
- `runtime/StrongholdEuropeDiplomatieV2/`,
- `runtime/StrongholdEuropeDiplomatieV2.Tests/`,
- `runtime/StrongholdEuropeDiplomatieV1Compatibility.Tests/`,
- die vier gemeinsam eingebundenen Diplomatie-Dateien unter `runtime/StrongholdEuropeDE.Runtime/`,
- die Diplomatie-Tests unter `tests/test_diplomacy*.py`, `tests/test_diplomatie*.py` und `tests/test_standalone_diplomacy_plugin.py`,
- das Paket `dist/StrongholdEuropeDiplomatieV2/`,
- die dedizierte Installation `D:\Games\Stronghold Crusader Definitive Edition COPY\BepInEx\plugins\StrongholdEuropeDiplomatieV2`.

Nicht Teil dieses Release-Audits sind Europe-Landschaft, Terrain, Festungen, Miliz, allgemeine UI-Asset-Bundles und andere Bestandteile des Gesamtprojekts. Fehler aus diesen Bereichen dürfen nicht als Fehler der eigenständigen Diplomatie-Mod verbucht werden.

Spielinstallationen auf `D:` und `E:` sind nur Referenz- beziehungsweise Installationsziele. Dort keine Quellbearbeitung vornehmen. Installation ausschließlich in den dedizierten Plugin-Ordner und nur bei beendetem Spiel.

## 2. Exakt geprüfter Revisionsstand

Die folgenden SHA-256-Werte binden alle Befunde dieses Dokuments an den tatsächlich geprüften Quellstand. Wenn einer dieser Werte abweicht, die betroffene Prüfung wiederholen.

| Datei | SHA-256 |
|---|---|
| `runtime/StrongholdEuropeDE.Runtime/DiplomacyFeature.cs` | `A43AF449661B4077249A82BCE23B5FDEB427193DA9FB6203C555464AF1467E9B` |
| `runtime/StrongholdEuropeDE.Runtime/DiplomacyCombatSafety.cs` | `7314855BDBEB1C80214DF33B9149333AA406EFFFCA35FA238141713E7ACD9766` |
| `runtime/StrongholdEuropeDE.Runtime/DiplomacyCore.cs` | `D76D1524540FB5C176F3FA481C6774403D35A9961A4D2B4DF9D35B2EFB84CD4A` |
| `runtime/StrongholdEuropeDE.Runtime/DiplomacySaveCodec.cs` | `1B0C4976D87BDF144342C47285EF8188B39CF85220373E050ACED336CB5D415D` |
| `runtime/StrongholdEuropeDiplomatie/DiplomatiePlugin.cs` | `FE49944CF8C78402F57D57A4AB8E087D76094D2FC8EFDEE2AF28F0789173AA5F` |
| `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2Core.cs` | `B05B68C7249DA71023E29E1C39EDC660E22DB452D2088FA9EC9997FA1012ED24` |
| `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2Feature.cs` | `D707E09B9194AD85C9BB8D0B2A0D595DE5C3BBEEEC077FB65B764125104834D8` |
| `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2SaveCodec.cs` | `AA466FA70CF5263299BF507B7A56630573EABAC4E5E367B143273F726808F881` |
| `runtime/StrongholdEuropeDiplomatieV2/DiplomatieCompatibilityGuard.cs` | `33ADF4B33ADAA97CBF1A7B08FCF6F0DAE861C4A53535ACEAB99B8312907EE787` |
| `runtime/StrongholdEuropeDiplomatieV2/StrongholdEuropeDiplomatie.csproj` | `18DB1B45E1E76558696C803E62607EEC889ED9E869780E3CF51F7C11AEFABFB1` |
| `runtime/StrongholdEuropeDiplomatieV2/bauen.py` | `1DFC72D6008863A7A070392CF0BD6E27EAD7E1223AAE86F79BD353669DBDA731` |
| `runtime/StrongholdEuropeDiplomatieV2/kompatibilitaet.py` | `E8C867C9ECFEEA27BA069CB6AFBBA604F8B6ABBD7FF1A8D5328F884A2D9CE9DE` |
| `runtime/StrongholdEuropeDiplomatieV2/texte.py` | `0A129256175B507DD1553A99810FB50C5E81FD6B03324CAD215744D2FDC10FBC` |
| `runtime/StrongholdEuropeDiplomatieV2.Tests/Program.cs` | `0C5BBA50C336288FA7AF7CBFA6248690BB0C06A30FE15C07BA390F9EEF960A70` |

Audit-Artefakt:

- DLL: `dist/StrongholdEuropeDiplomatieV2/StrongholdEuropeDiplomatieV2.dll`
- Größe: `393728` Byte
- Build-Zeit: `2026-09-06 16:16:30`
- SHA-256: `4F24F8D4FEA0EC61435DD9F6D59CB69C744559B908DCE0602F92EF6BF9335108`

Alle oben genannten Quellen waren beim Audit älter als die DLL. Die installierte DLL auf `D:` hat denselben SHA-256-Wert.

## 3. Automatisierte Nachweise und ihr Geltungsbereich

### 3.1 Fokussierte Python-Suite

Ausgeführt wurde:

```powershell
Set-Location 'E:\Stronghold Crusader Definitive Edition Baldwin and Bullseye MULTi20\SE144'
& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' -m pytest -q -k 'diplomacy or diplomatie'
```

Ergebnis des geprüften Stands:

```text
96 passed, 2148 deselected in 4.58s
```

### 3.2 C#-Modelltests

`runtime/StrongholdEuropeDiplomatieV2.Tests/Program.cs` ruft 52 Tests mit insgesamt 125 Assertions auf. Erfolgreicher Lauf:

```powershell
$env:DOTNET_ROLL_FORWARD = 'Major'
& 'work\toolchains\dotnet-10.0.301\dotnet.exe' run `
  --project 'runtime\StrongholdEuropeDiplomatieV2.Tests\StrongholdEuropeDiplomatieV2.Tests.csproj' `
  -c Release --no-build
```

Ergebnis: Exitcode 0; Auditmarker `CSHARP_MODEL_52_OK`.

Abgedeckt sind unter anderem:

- alle sieben Persönlichkeitsprofile,
- Geschenke, Forderungen und die Pflicht zu Waren für Bündnisse,
- Fristen und friedlicher Ablauf,
- explizite Angriffserkennung und Ein-Tick-Eingabefenster,
- Burg-Intimzone und militärische Schwellen,
- Waffenruhe, Handelspakt, Bündnis und gezielte Aufkündigung,
- Save/Load mehrerer Bündnisse und Verträge,
- V2-Schema 3, Schema-2-Migration, V1-Import und V1-Rückprojektion,
- beschädigte V2-Daten mit V1-Fallback,
- Unterstützung, Ultimatum, Auflösung und Erholung,
- Langzeitsimulation über 1500 Spieltage für alle sieben Profile.

Die Langzeitsimulation fordert pro Profil mindestens zwei Bündnisse, drei Unterstützungsforderungen, zwei Ultimaten, einen Vertragsbruch und mindestens 40 Save/Load-Rundreisen. Das ist ein starker Nachweis für das reine Zustandsmodell, aber kein Ersatz für native Eventlast, Unity-Laufzeit oder UI-Rendering.

### 3.3 V1-Kompatibilitätsleser

Der V1-Build akzeptiert die erzeugte V1-Rückprojektion:

```powershell
& 'work\toolchains\dotnet-10.0.301\dotnet.exe' run `
  --project 'runtime\StrongholdEuropeDiplomatieV1Compatibility.Tests\StrongholdEuropeDiplomatieV1Compatibility.Tests.csproj' `
  -c Release --no-build -- 'work\runtime-tests\diplomacy-v1-fallback.audit.bin'
```

Ergebnis: Exitcode 0; `V1_FALLBACK_READER_OK`.

### 3.4 Paketintegrität

Die interne Paketprüfung `_verify_package` war erfolgreich (`PACKAGE_INTEGRITY_OK`). Dist und COPY-Installation sind bytegleich:

| Relative Datei | Byte | SHA-256 |
|---|---:|---|
| `build-manifest.json` | 7040 | `2B3F1BBA6D3BE4216D69B839B42A01D4181698D1B5F57B2C12BB9FFA65629D10` |
| `info.json` | 401 | `D90E68483045D7344302A9CC6E2276B5BE4E401323B8B266EBBF0064AF97C0A7` |
| `StrongholdEuropeDiplomatieV2.dll` | 393728 | `4F24F8D4FEA0EC61435DD9F6D59CB69C744559B908DCE0602F92EF6BF9335108` |
| `Patches/Assets/GUI/XAMLResources/HUD_AlliesPanel.xaml` | 24546 | `E44ABDBBA2EAC81FD39299736C223490A4A5CB574D3478CF5D38A0A0F222EF4C` |

### 3.5 Gesamtsuite ist kein Diplomatie-Gate

Die zuletzt vom Claude-Hintergrundtask gemeldete äußere Prozessmeldung lautete zwar Exitcode 0, die eigentliche gespeicherte pytest-Ausgabe beginnt jedoch mit `exit=1` und endet mit:

```text
46 failed, 2190 passed, 4 skipped, 1 deselected, 3 errors in 192.85s
```

Die angezeigten Fehler betreffen Terrain-Europe und allgemeine UI-/Asset-Bundle-Provenienz, nicht das eigenständige Diplomatie-Plugin. Für den Diplomatie-Release weder ignorieren noch fälschlich als Diplomatiefehler behandeln: fokussierte Diplomatie-Suite separat ausführen und dokumentieren. Der Wrapper-Exitcode darf nicht als Beleg für eine grüne Gesamtsuite verwendet werden.

### 3.6 Mechanische Audits

Im geprüften Diplomatie-Scope wurden keine `TODO`, `FIXME`, `HACK`, `NotImplemented`, Merge-Konfliktmarker oder Whitespace-Fehler gefunden. Es gibt 15 dauerhaft gehaltene Event-Abonnements und dazu 15 symmetrische `Dispose(ref ...)`-Aufrufe. Dieser Zähltest ersetzt nicht die Laufzeitprüfung, stützt aber die Unload-/Restart-Sicherheit.

## 4. P1-A – Initialer Integer-Überlauf und globaler Hostile-Attribution-Throttle

### 4.1 Betroffener Code

Datei `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2Feature.cs`, geprüfter Stand:

- Zeile 35: `V2IncursionScanIntervalTicks = 32`
- Zeile 48: `_v2LastHostileAttributionTick = int.MinValue`
- Zeilen 1135–1175: `V2TryFindDiplomaticCounterpartNearWorldTarget(...)`
- Zeilen 1159–1164: Differenztest und sofortiges Setzen des globalen Ticks
- Zeile 2557: Reset zurück auf `int.MinValue`

Sinngemäß:

```csharp
if (_simulationTicks - _v2LastHostileAttributionTick
    < V2IncursionScanIntervalTicks)
{
    return false;
}

_v2LastHostileAttributionTick = _simulationTicks;
```

### 4.2 Reproduktion

C# verwendet hier standardmäßig ungeprüfte `int`-Arithmetik. Mit dem Initialwert `int.MinValue` ergeben sich:

```text
tick=0       delta=-2147483648  throttled=True
tick=1       delta=-2147483647  throttled=True
tick=1000000 delta=-2146483648  throttled=True
```

Die nicht vertraglich geschützte Nahbereichszuordnung bleibt damit bis in die Nähe von 2,147 Milliarden Simulationsticks unterdrückt.

### 4.3 Konkrete Wirkung

Direkte Angriffe mit bereits aufgelöstem Zielobjekt funktionieren weiterhin, weil Tribe-, Nahkampf-, Projektil- und Gebäudepfade `V2RecordUnprotectedHostileAct(...)` direkt aufrufen. Auch die Schutzsuche eines aktiven Vertrags läuft mit `requireActiveTreaty=true` und umgeht diesen Throttle.

Defekt ist insbesondere die Zuordnung von neutralem Bodenfeuer, Flächenfeuer oder anderen Weltziel-Ereignissen zu einer nahegelegenen diplomatischen Gegenpartei, wenn kein aktiver Vertrag vorausgesetzt wird. Dadurch können Feindseligkeitshistorie und politische Reaktion beziehungsweise Gesprächsöffnung fehlen.

### 4.4 Zweiter Fehler im selben Mechanismus

Der Throttle ist ein einzelnes Feld für alle Koalitionen. Zudem wird `_v2LastHostileAttributionTick` gesetzt, bevor Quelle und Koordinaten vollständig validiert und eine Gegenpartei gefunden wurden. Damit gilt:

- ein ungültiger Scan kann das Zeitfenster verbrauchen;
- Relation A kann Relation B im selben 32-Tick-Fenster unterdrücken;
- ein Event ohne Treffer kann ein nachfolgendes valides Event ausblenden.

`DiplomacyV2Core.RecordHostileAct` ist bereits pro Relation und Spieltag idempotent. Es rechtfertigt keinen globalen beziehungsübergreifenden Throttle.

### 4.5 Verbindliche Korrekturanforderungen

Nicht nur den Initialwert auf `-32` ändern. Das würde weder die globale Kopplung noch Langzeitüberläufe beheben.

Erforderlich:

1. Keine Differenzbildung gegen einen ungekennzeichneten `int.MinValue`-Sentinel.
2. Quelle und Koordinaten validieren, bevor irgendein Throttle verbraucht wird.
3. Throttle beziehungs-/koalitionsbezogen führen oder pro Simulationstick einen deterministischen Lookup cachen, ohne andere Relationen zu unterdrücken.
4. Überlaufsichere Zeitmessung verwenden, vorzugsweise monotone `long`-Ticks oder einen expliziten Initialisierungszustand mit sicherem Elapsed-Helfer.
5. Die reine Zulassungsentscheidung nach `DiplomacyV2Core.cs` extrahieren, damit sie ohne Unity getestet werden kann.

Mindestens folgende Tests hinzufügen:

- erster valider Scan bei Tick 0 und Tick 1 wird nicht unterdrückt;
- ungültige Quelle oder ungültige Koordinate verbraucht kein Fenster;
- Relation A und Relation B können innerhalb von 32 Ticks beide zugeordnet werden;
- dieselbe Relation wird deterministisch gedrosselt beziehungsweise bleibt durch Core-Idempotenz einmalig;
- Verhalten nahe `int.MaxValue`/Rollover;
- `requireActiveTreaty=true` bleibt unbeeinträchtigt und schützt weiterhin fail-closed.

## 5. P1-B – nur 7 von 21 nativen Spielsprachen

### 5.1 Nutzeranforderung

Der Nutzer hat ausdrücklich präzisiert: Übersetzungen nur für die Sprachen, die Stronghold selbst nativ anbietet – damit sind **alle** nativen Stronghold-Lokalisierungen gemeint, nicht nur eine kleine westliche Auswahl.

### 5.2 Native Locale-Matrix

Direkt aus den 2.80-Klassen `CrusaderDE.Translate` und `FatControler` der COPY-Installation bestätigt:

```text
enus, dede, frfr, eses, itit, plpl, ruru, ptbr, jajp, kokr,
zhcn, zhhk, cscz, trtr, huhu, thth, ukua, elgr, ar, nlnl, svse
```

Das sind 21 Sprachen/Locales.

### 5.3 Ist-Zustand

`runtime/StrongholdEuropeDiplomatieV2/texte.py:41` enthält nur:

```python
LOCALES = ("eses", "frfr", "itit", "plpl", "ptbr")
```

Deutsch und Englisch kommen aus den `Text(de, en)`-Aufrufen. Zusammen sind daher nur 7 von 21 nativen Locales abgedeckt.

Fehlend sind 14:

```text
ruru, jajp, kokr, zhcn, zhhk, cscz, trtr,
huhu, thth, ukua, elgr, ar, nlnl, svse
```

Es gibt 206 eindeutige Diplomatie-Textschlüssel. Die fünf vorhandenen JSON-Kataloge enthalten jeweils vollständig 206 Schlüssel und die vorhandenen Tests prüfen Quellaktualität, exakte Schlüsselmenge, Nichtleere, Rand-Whitespace, Steuerzeichen, deterministische C#-Generierung und Einbindung.

`tests/test_diplomacy_texts.py` enthält noch eine sachlich falsche Festlegung, wonach der Nutzer nur DE/EN/FR/ES/PT/PL/IT gewählt habe. Diese Annahme muss entfernt und durch die vollständige native Locale-Matrix ersetzt werden.

### 5.4 Erforderliche Umsetzung

1. `LOCALES` auf alle 19 nicht direkt aus `Text(de,en)` gespeisten nativen Locales erweitern.
2. Für jede der 14 fehlenden Locales einen vollständigen JSON-Katalog mit genau allen 206 Schlüsseln erstellen.
3. Tests müssen exakt die 21 nativen Spielsprachen festschreiben und für jede Katalogsprache Vollständigkeit erzwingen.
4. Unbekannte Locale oder unbekannter Schlüssel darf auf Englisch zurückfallen; eine bekannte native Locale darf nicht still vollständig Englisch anzeigen.
5. Build-Manifest und Release-Dokumentation müssen die vollständige Matrix nennen.

Automatische Vollständigkeit reicht visuell nicht aus. Vor Freigabe im Spiel prüfen:

- CJK-Glyphen und Font-Fallback für `jajp`, `kokr`, `zhcn`, `zhhk`;
- kyrillische Glyphen für `ruru` und `ukua`;
- Arabisch `ar`, insbesondere RTL, Interpunktion und Zahlen;
- lange niederländische, schwedische, türkische und griechische Texte;
- Abschneiden durch feste XAML-Breiten und `TextTrimming` bei allen UI-Skalierungen.

Vanilla-Warennamen und Sprachsamples sind bereits spielseitig lokalisiert und müssen nicht doppelt in den Diplomatie-Katalog aufgenommen werden.

## 6. P1 – aktueller Build besitzt noch keinen In-Game-Nachweis

Die COPY-Installation enthält bytegenau die aktuelle DLL `4F24...5108`. Das letzte `BepInEx/LogOutput.log` hat jedoch Zeitstempel `2026-09-06 15:17:32`; die aktuelle DLL wurde erst um `16:16:30` gebaut. Der erfolgreiche Lauf um 15:17 belegt daher einen älteren Build, nicht das aktuelle Audit-Artefakt.

Der ältere Lauf war wertvoll und zeigte unter anderem:

- `compatibility|status=ok|bindings=402/402|attested=15/15|engine=attested`,
- zwei vollständige Bündnisleitern,
- eine Waffenruhe,
- sieben Drei-Waren-Pakete,
- native Verbündetensendung mit exaktem Bestandsbeleg,
- sechs blockierte KI-Angriffsbewertungen gegen Verbündete,
- V2-Speichern und -Laden,
- sauberen Kartenabbau,
- sauberes Alt+F4 mit `process_exit|rollback=not_required`.

Diese Evidenz darf nicht als vollständige Abnahme des neuen Builds umetikettiert werden. Nach allen Korrekturen neu bauen, installieren, Hash notieren und den kompletten Abschnitt 12 mit genau diesem Hash im Spiel abnehmen.

## 7. P1/P2 – öffentliche Identität, Metadaten und Paketinhalt

Der aktuelle Stand ist absichtlich privat:

- `runtime/StrongholdEuropeDiplomatieV2/bauen.py:49`: GUID `strongholdeuropede.diplomatie.v2.private`
- `bauen.py:51`: Anzeigename `Stronghold Crusader Diplomatie V2 (Private)`
- `runtime/StrongholdEuropeDiplomatie/DiplomatiePlugin.cs:31–35`: gleiche private Identität
- `dist/StrongholdEuropeDiplomatieV2/info.json`: Autor `Private`, Website leer
- Manifest: `public_release_ready=false`, `in_game_acceptance_recorded=false`, Status `in_game_acceptance_required`
- Tests pinnen derzeit ausdrücklich die private Identität und den falschen Releasezustand.

Das Dist-Paket enthält nur DLL, `info.json`, Build-Manifest und HUD-XAML. Eine separate Veröffentlichung braucht mindestens eine aktuelle V2-README, Lizenz und Changelog beziehungsweise Release Notes. Die V1-README ist fachlich veraltet und darf nicht unverändert als V2-Dokumentation ausgeliefert werden.

Vor der ersten öffentlichen Version eine dauerhafte öffentliche GUID festlegen. Eine spätere GUID-Änderung erzeugt leicht Doppelinstallationen oder getrennte Konfigurationen. Die Save-IDs sind davon getrennt:

- primär: `StrongholdEuropeDE.Diplomacy.v2`
- Legacy: `StrongholdEuropeDE.Diplomacy.v1`

Eine öffentliche GUID-Änderung zerstört deshalb nicht automatisch Spielstände, braucht aber eine klare Konflikt-/Migrationsbehandlung für die private V2-GUID, die V1-GUID und alte Plugin-Ordner.

Die Dokumentation muss die reale Laufzeitgrenze nennen: Das Plugin aktiviert sich absichtlich nur im Offline-Solo-Gefecht. Kampagne, Multiplayer und Mensch-gegen-Mensch werden in `DiplomacyFeature.cs:1283–1328` abgelehnt.

Wichtig für Reproduzierbarkeit: Die neuen Standalone-Verzeichnisse und mehrere Tests waren beim Audit im Git-Status noch untracked. Vor öffentlicher Veröffentlichung muss der komplette Release-Quellstand versioniert und eindeutig tagbar sein.

## 8. P2 – maximale Versionskompatibilität ist noch nicht vollständig eingelöst

### 8.1 Harte SHCDESE-Mindestversion

`runtime/StrongholdEuropeDiplomatie/DiplomatiePlugin.cs:42` verlangt hart:

```csharp
[BepInDependency("000shcdese", "1.44.0")]
```

BepInEx verweigert auf SHCDESE 1.39 das Laden, bevor der neue Mitgliederwächter überhaupt laufen kann. Gleichzeitig ergab der vorhandene Offline-Vergleich der lokalen Dekompilate für Spiel 2.7/2.80 und SHCDESE 1.39/1.44 null fehlende gebundene Mitglieder; die bestehende Review notiert, dass der Vertrag strukturell zu 1.39 passt.

Da der Nutzer maximale Spielversionskompatibilität verlangt, gibt es vor Release nur zwei ehrliche Optionen:

1. Mindestversion nach einem echten 1.39-Load-/Runtime-Test absenken; oder
2. 1.44 ausdrücklich als einzige unterstützte Extender-Version dokumentieren und keine maximale 1.39-Kompatibilität behaupten.

Die nativen HUD-Ausgangsdateien der lokalen 2.7- und 2.80-Installationen sind bytegleich (SHA-256 `6C927AC4...`, Größe 84163 Byte), was die UI-Kompatibilität dieser beiden lokalen Versionen positiv stützt. Es ersetzt keinen Laufzeittest.

### 8.2 Mitgliederwächter prüft noch keine vollständigen CLR-Signaturen

`DiplomatieCompatibilityGuard.cs:193–245` prüft derzeit:

- Felder nur nach Name,
- Methoden nur nach Name und Parameteranzahl.

`kompatibilitaet.py:107–113` und `274–305` speichern entsprechend keine Parametertypen, keinen Rückgabetyp, keine statisch/Instanz-Kennzeichnung, keine generische Arität, keinen Feldtyp und keine Layoutinformation.

Die CLR löst MemberRefs über vollständige Signaturen auf. Der Wächter kann deshalb `402/402` melden, obwohl der JIT später bei einem gleichnamigen, gleichstelligen, aber typinkompatiblen Mitglied scheitert. Das ist bei verwendeten nativen Pointer-Strukturen wie `GameTribe`, `GameProjectile`, `GameBuilding` und `GamePlayerResources` besonders relevant; Name allein belegt weder Feldtyp noch Layout/Offset.

Vertrag auf normalisierte vollständige Signaturen erweitern. Für kritische explizit gelayoutete Native-Strukturen, wo sicher möglich, zusätzlich erwarteten Feldtyp, Offset und `Marshal.SizeOf` prüfen. Datei-Hashes weiterhin nur als Attestierung/Warnsignal verwenden, nicht als alleinige Kompatibilitätssperre.

### 8.3 Tote V2-Abhängigkeiten verkleinern

Das V2-Projekt kompiliert derzeit unter anderem:

- `EuropeCapabilities.cs`,
- `RuntimeBuildGuard.cs`,
- `RuntimeDecision.cs`.

Die Host-Verwendung dieser Klassen liegt für V2 hinter `#if !DIPLOMACY_V2`; sie sind im eigenständigen V2-Plugin tot, erscheinen aber weiter in der DLL. `RuntimeBuildGuard` zieht unter anderem `GameAssetManagerAPI`, `System.Memory`, `Material`, `AssetBundle` und `AudioClip` herein. Deshalb referenziert die finale DLL unnötig `System.Memory`, `UnityEngine.AssetBundleModule` und `UnityEngine.AudioModule`.

Das reduziert reale Versionskompatibilität und lässt den Mitgliedervertrag tote Typen prüfen, die Diplomatie selbst gar nicht benötigt. V2-Compile-Items und Buildvoraussetzungen auf tatsächlich live erreichbaren Diplomatie-Code reduzieren. Danach:

- Assembly-Referenzen erneut auslesen,
- Europe-/Origins-Verbot erneut prüfen,
- neuen kleineren Bindungsvertrag erzeugen,
- alle Builds und Laufzeittests wiederholen.

## 9. P2/P3 – Zuverlässigkeits- und Dauerlaufhärtung

### 9.1 Globaler Ressourcen-Hook ist reentranzgefährdet

`DiplomacyFeature.cs:5108–5185`, Methoden `AddGoodWithExactHookArguments` und `RemoveGoodWithExactHookArguments`, abonnieren kurzzeitig einen **globalen** Ressourcen-Pre-Observable und überschreiben dessen Spieler-, Waren- und Mengenargumente, bis der native Aufruf zurückkehrt.

Der normale gleichthreadige Pfad ist durch exakte Bestandsprüfung und Rollback stark abgesichert. Wenn jedoch ein anderer Mod-Observer synchron innerhalb dieses Fensters eine verschachtelte Ressourcenoperation auslöst, kann der Guard auch die fremde Transaktion umschreiben. Der äußere Readback kann den äußeren Vorgang erkennen und zurückrollen; die verschachtelte Nebenwirkung kann zu diesem Zeitpunkt bereits falsch sein.

Erforderliche Härtung:

- Operation eindeutig korrelieren, mindestens erwartete Originalargumente und nur das erste passende Event akzeptieren;
- per-Thread/per-Operation-Reentranzzustand verwenden;
- fremde oder verschachtelte Events niemals umschreiben;
- synthetische Tests mit einem Observer ergänzen, der synchron eine zweite Ressourcenoperation auslöst.

### 9.2 Feuer-/Projektilpfade können unter großer Eventlast teuer werden

`DiplomacyCombatSafety.cs:1413–1492` kann bei jedem relevanten Feuerereignis, sobald irgendein schützenswertes Paar existiert:

- eine Liste anlegen,
- alle lebenden Einheiten enumerieren,
- sortieren,
- nahe Kacheln rasterisieren.

`DiplomacyV2Feature.cs:1135–1320` kann zusätzlich nochmals alle Einheiten durchsuchen/sortieren und Kacheln rasterisieren. Der Vertragsschutzpfad umgeht den Hostile-Throttle absichtlich und kann damit jedes Event scannen. Bei spätem Belagerungsspiel mit tausenden Einheiten und dichtem Feuerpfeil-/Flächenfeueraufkommen entsteht potenziell `O(Ereignisse × U log U)` auf dem Hauptthread.

Die 1500-Tage-Modellsimulation misst diese native Last nicht. Empfohlene Härtung:

- deterministischen Alive-Unit-Snapshot oder räumlichen Index einmal pro Simulationstick cachen;
- für einen deterministischen nächsten Treffer nicht vollständig sortieren, sondern beim Scan nach Distanz und stabiler ID vergleichen;
- Benchmark/Harness mit tausenden Einheiten und dichter Feuerereignisfolge;
- dabei Schutzkorrektheit für mehrere Verbündete und neutrale Drittkacheln bewahren.

### 9.3 Signierte Tickzähler laufen bei sehr langem Prozess über

`DiplomacyFeature.cs:554` erhöht `_featureTicks`, Zeile 1504 `_simulationTicks`; beide sind `int`. Bei 60 Hz entsprechen `2^31` Ticks ungefähr 414 Tagen ununterbrochener Laufzeit. Die tatsächliche Tickfrequenz kann abweichen, aber der Code besitzt keinen expliziten Rolloververtrag.

Risiken:

- Eingabefenster in `DiplomacyV2Core.cs:2828–2839` kann nach Wraparound logisch offen bleiben;
- Transfer-/Cooldown-Differenzen können ihr Vorzeichen wechseln;
- eine `checked`-Subtraktion im Kampfschutz kann werfen.

Für maximale kontinuierliche Zuverlässigkeit monotone `long`-Zähler oder zentralisierte überlaufsichere Elapsed-Helfer verwenden und Grenztests um `int.MaxValue`/`int.MinValue` ergänzen.

## 10. Positive Befunde, die bei Umbauten erhalten bleiben müssen

### 10.1 Transaktionen

Der V2-Paketversand in `DiplomacyV2Feature.cs:631–803` liest alle Sender- und Empfängerbestände und erkennt jede fehlende Ware **vor der ersten Mutation**. Danach erfolgen exakte beidseitige Readbacks jeder Abbuchung/Gutschrift, Rückwärts-Rollback, Managed-State-Memento und Save-stabile Ausführung. Wenn Rollback nicht beweisbar ist, wird nur der Transferteil degradiert, nicht die gesamte Karte.

Der Basistransfer arbeitet analog mit Bounds-/Bestands-Preflight, exaktem Readback und Rollback. Diese Vorabprüfung darf beim Refactoring nicht aufgeweicht werden.

### 10.2 Savegames

- V2-Basis maximal 64 KiB, Envelope maximal 128 KiB;
- SHA-256-Trailer wird vor Parse und Native-Restore geprüft;
- Text- und Collection-Längen sind begrenzt;
- semantische Validierung ist umfangreich;
- Schema 3, Schema-2-Migration, V1-Import und laufende verlustbehaftete V1-Rückprojektion sind getestet.

### 10.3 Teamwechsel und Recovery

Teamänderungen besitzen erwartete und gewünschte Partitionen, nativen Apply/Readback, Kampfquarantäne, Memento/Rollback, persistentes Recovery-Journal und Schutz vor vorzeitigem Sieg. Ungeklärte Zustände bleiben fail-closed. Diese Reihenfolge nicht vereinfachen.

### 10.4 Kampfsicherheit

Abgedeckte native Angriffsflächen umfassen Tribe-Befehle, Projektil-/Feuerspawn, Nahkampf-, Projektil- und Gebäudeschaden sowie KI-Angriffsbewertung. Exception-Pfade blockieren Schaden/Befehl und markieren den Stage-Fehler. Die Sicherheitsbarriere darf durch Performanceoptimierungen nicht fail-open werden.

### 10.5 Lebenszyklus

Der Host ist persistent (`DontDestroyOnLoad`), Kartenepochen schützen gegen alte Events, Unload rollt laufende Zustände zurück, Prozessende/Alt+F4 wird behandelt. UI-Refresh- und Rollover-Fehler degradieren inzwischen nur die UI statt dauerhaft die Karte abzuschalten.

### 10.6 Eigenständigkeit und Build

Die finale DLL referenziert aktuell:

```text
0Harmony, Assembly-CSharp, BepInEx, mscorlib, R3, SHCDESE,
System, System.Core, System.Memory, UnityEngine.AssetBundleModule,
UnityEngine.AudioModule, UnityEngine.CoreModule, Zhuqiaomon
```

Es gibt keine externe Europe- oder Origins-Assemblyreferenz. Der Manifestvertrag umfasst 402 Bindungen und findet keine verbotenen Europe-/Origins-Präfixe. Das Paket besitzt nur seinen dedizierten Plugin-Ordner und den eigenen HUD-Patch. Der Installer erkennt den alten V1-Ordner sowie konkurrierende Plugins mit demselben HUD-Ziel und führt den Austausch transaktional mit Rücklage aus.

Der Build nutzt `net481`, `Deterministic=true`, keine PDB, `PathMap` und einen stabilitätsgeprüften Zwei-Pass-IL-Vertrag.

## 11. Empfohlene Implementierungsreihenfolge

1. Diesen SHA-gebundenen Auditstand sichern und P1-A mit einem kleinen C#-Grenztest reproduzieren.
2. Hostile-Attribution-Throttle korrigieren und die sechs geforderten Tests ergänzen.
3. Alle 14 fehlenden nativen Übersetzungskataloge erstellen; Locale-Matrix und Vollständigkeitstests korrigieren.
4. Tote V2-Abhängigkeiten und Referenzen entfernen.
5. Kompatibilitätsvertrag auf vollständige CLR-Signaturen und kritische Layoutdaten härten.
6. SHCDESE-1.39-Unterstützung real testen und Mindestversion fundiert festlegen.
7. Ressourcen-Hook reentranzfest machen und native Feuerpfade cachen/benchmarken.
8. Tickzähler auf `long` oder sicher definiertes Rollover umstellen.
9. Öffentliche GUID/Metadaten festlegen; README, Lizenz, Changelog und Upgrade-/Konflikthinweise erstellen; Quellen versionieren.
10. Deterministisch neu bauen, alle fokussierten Tests, V1-Leser und Paketprüfung ausführen.
11. Bei beendetem Spiel ausschließlich den dedizierten COPY-Plugin-Ordner installieren und Dist/Install byteweise vergleichen.
12. Komplette In-Game-Abnahmematrix mit genau dem finalen DLL-Hash durchlaufen. Erst danach Release-Gates umstellen.

## 12. Noch erforderliche In-Game-Abnahmematrix

Mindestens folgende Szenarien mit Logzeilen, Save und finalem DLL-Hash protokollieren:

1. Kaltstart auf Spiel 2.80/SHCDESE 1.44: genau ein Diplomatie-Plugin, vollständiger neuer Mitgliedervertrag, Feature aktiv.
2. Vanilla-Installation ohne Europe- oder Origins-Mod.
3. Migration eines echten V1-Saves.
4. Migration eines echten Schema-2-Saves.
5. Beschädigter V2-Block fällt kontrolliert auf die laufende V1-Rückprojektion zurück.
6. Dasselbe Save mit mehreren Bündnissen, Waffenruhe/Handelspakt und gezielter Aufkündigung speichern und laden.
7. Ein-Waren- und Drei-Waren-Paket; bei einer fehlenden Ware keinerlei Bestandsmutation auf beiden Seiten.
8. Native Verbündetensendung sowie erzwungenes natives Versagen mit direktem Fallback.
9. Waffenruhe-/Bündnisschutz für lokalen Spieler und alle vorhandenen KI-Verbündeten über Befehl, Projektil, Feuer, Nahkampf, Gebäudeschaden und KI-Zielauswahl.
10. Boden-/Flächenfeuer exakt an Vertragsgrenzen und auf neutraler Drittkachel.
11. Bewusster Angriff auf exakt gewähltes Vertragsziel bricht genau einmal; Vergeltung oder anderer Befehl nicht.
12. Militärische Burg-Intimzone; Keep-Door-Tile muss exakt mit `×8 + 4` in Weltkoordinaten umgerechnet werden.
13. Friedlicher Ablauf einer Waffenruhe.
14. Gezielte Bündnisaufkündigung trennt nur die ausgewählte Koalition.
15. Unterstützungsforderung → Ultimatum → KI-Auflösung → später mögliche Erholung.
16. Alle UI-Skalierungen und alle 21 nativen Locales, besonders CJK, Arabisch und lange Texte.
17. Karten-Unload, Rückkehr ins Menü, Neustart einer Karte und Alt+F4 ohne verbleibende Hooks oder unvollständigen Rollback.

Bis alle Punkte auf dem finalen Artefakt belegt sind, bleiben korrekt:

```text
engine_evidence = load_only
in_game_acceptance_recorded = false
public_release_ready = false
status = in_game_acceptance_required
```

## 13. Reproduktions- und Abschlussbefehle

```powershell
Set-Location 'E:\Stronghold Crusader Definitive Edition Baldwin and Bullseye MULTi20\SE144'

& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' -m pytest -q -k 'diplomacy or diplomatie'

$env:DOTNET_ROLL_FORWARD = 'Major'
& 'work\toolchains\dotnet-10.0.301\dotnet.exe' build `
  'runtime\StrongholdEuropeDiplomatieV2.Tests\StrongholdEuropeDiplomatieV2.Tests.csproj' `
  -c Release -warnaserror

& 'work\toolchains\dotnet-10.0.301\dotnet.exe' run `
  --project 'runtime\StrongholdEuropeDiplomatieV2.Tests\StrongholdEuropeDiplomatieV2.Tests.csproj' `
  -c Release --no-build

& 'work\toolchains\dotnet-10.0.301\dotnet.exe' run `
  --project 'runtime\StrongholdEuropeDiplomatieV1Compatibility.Tests\StrongholdEuropeDiplomatieV1Compatibility.Tests.csproj' `
  -c Release --no-build -- 'work\runtime-tests\diplomacy-v1-fallback.audit.bin'

& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' `
  'runtime\StrongholdEuropeDiplomatieV2\bauen.py'
```

Der V2-Builder benötigt wegen der zwei ILSpy-Pässe deutlich länger als ein gewöhnlicher Build. Nicht abbrechen, solange Fortschritt beziehungsweise der Prozess weiterläuft.

Installation erst nach erfolgreichem Build und bei geschlossenem Spiel:

```powershell
& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' `
  'runtime\StrongholdEuropeDiplomatieV2\bauen.py' `
  --install 'D:\Games\Stronghold Crusader Definitive Edition COPY'
```

Danach alle vier Dateien zwischen `dist/StrongholdEuropeDiplomatieV2` und dem dedizierten Plugin-Ordner byteweise vergleichen. Keine anderen Plugin-Ordner, Europe-Dateien oder Origins-Dateien verändern.

## 14. Abschlussdefinition

Claude darf die eigenständige Diplomatie-Mod erst als release-fertig kennzeichnen, wenn:

- P1-A nachweislich behoben und mit Grenz-/Mehrrelations-/Rollovertests abgedeckt ist;
- alle 21 nativen Stronghold-Locales vollständig eingebunden und visuell plausibilisiert sind;
- die öffentliche Identität, Dokumentation und Lizenz feststehen;
- die behauptete SHCDESE-/Spielversionsmatrix tatsächlich geladen und getestet wurde;
- fokussierte Python- und C#-Tests, V1-Leser, Zwei-Pass-Build und Paketprüfung grün sind;
- Dist und Installation bytegleich sind;
- die vollständige In-Game-Matrix mit dem finalen DLL-Hash dokumentiert wurde;
- keine Europe-/Origins-Laufzeitabhängigkeit hinzugekommen ist.

Ein bloß fehlerfreier Start, `bindings=N/N` oder eine grüne Modelltestsuite allein genügt ausdrücklich nicht für die öffentliche Freigabe.
