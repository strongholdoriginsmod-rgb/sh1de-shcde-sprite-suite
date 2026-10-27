# Review Diplomatie V2.1 — Claude, 2026-09-06

Antwort auf `CLAUDE_TECHNICAL_HANDOFF.md`. Gelesen: `DiplomacyV2Core.cs`,
`DiplomacyV2Feature.cs`, `DiplomacyV2SaveCodec.cs`, `bauen.py`, der komplette
Diff an den geteilten `Diplomacy*.cs` (1370 Zeilen), `Program.cs` der
Modelltests. Nachgefahren: pytest, C#-Modelltests, V1-Kompatibilitätsleser,
V2- und V1-Bau. Dazu ein echter Spiellauf auf der festgeschriebenen 2.80.

Befunde nach Schweregrad. „Bewiesen" = im Protokoll oder Dekompilat belegt,
„hergeleitet" = aus dem Quelltext, „vermutet" = nicht geprüft.

## P0 — Zustandskorruption / Partie-Ende

### 1. `RefreshV2DetailPanel` schreibt `Opacity` als Double — **behoben**

- Datei: `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2Feature.cs`,
  Methode `RefreshV2DetailPanel`, Aufruf `SetProperty(primaryLabel, "Opacity", …)`.
- Szenario (bewiesen, Protokoll 13:26): Kartenstart, Verbündetentafel öffnen,
  einen Fürsten wählen → `fail_closed|stage=ui_refresh|reason=ArgumentException:
  Object of type 'System.Double' cannot be converted to type 'System.Single'`.
- Ursache: `SetProperty` ruft `PropertyInfo.SetValue` ohne Umwandlung;
  `Noesis.UIElement.Opacity` ist `float` (Dekompilat). `1.0`/`0.48` sind
  Double-Literale.
- Korrektur: `SetNumericProperty` verwenden (vorhanden, wandelt per
  `Convert.ChangeType` in den Zieltyp). Einziger Gleitkomma-`SetProperty` im
  V2-Code (mechanisch gesucht).

### 2. `ui_refresh` eskaliert zu `DisableMap` — **behoben**

- Datei: `runtime/StrongholdEuropeDE.Runtime/DiplomacyFeature.cs`,
  `AlliesUpdatePostfix`.
- Szenario (bewiesen): jede Ausnahme in `RefreshVanillaDiplomacyUi` —
  reine Anzeige, keine Lager-/Teamschreibung — beendete die Diplomatie für die
  ganze Partie und hielt die Haken.
- Widerspruch zur Übergabe §17 (graceful fallback bei unvollständiger
  Oberfläche) und zu `CLAUDE.md` („ein normales Ereignis darf niemals dauerhaft
  abschalten").
- Korrektur: `DegradeUiRefresh(panel, exception)` — V2-Tafel verstecken,
  natives Detail zeigen, einmal je Karte `ui_integration|status=refresh_degraded`.
  `ui_roster` bleibt fail-closed (halb aufgebaute Aufstellung könnte eine
  Sendung fehlleiten).

## P1 — Vertrags- und Kampflogik

Keine Befunde mit reproduzierbarem Szenario. Hergeleitet geprüft:

- `V2TreatyProtectsPlayers` ist symmetrisch (Block-Zugehörigkeit beider Seiten,
  Fremdseite muss nicht verbündet sein, aktiver Pakt mit `AgreementUntilDay >
  day`). `V2IsLocalDiplomaticBlocPlayer` deckt Mensch + alle verbündeten
  Koalitionen.
- `V2AuthorizeExplicitPlayerAttack` verlangt Quelle = Mensch, lokal
  ausgewählten Tribe, Eingabefenster ≤ 1 Tick und exakte Zielübereinstimmung je
  Befehlsart; `Unknown33` fällt in `default → false`. Der Bruch wird über
  `_v2DeferredBreachCoalition` genau einmal gemeldet.
- Intimzone: Zentrum ist `GetPlayerKeepDoorPosition × 8 + 4`, `(0,0)` gilt als
  fehlend; Lord zählt nicht; Schwellen 8/250, 12, 4/600.
- `OnDiplomacyReceivedGoods`: Lagerbeleg ist Commit-Autorität, `ReturnValue`
  wird nur nach exaktem Beleg repariert. Das erklärt die Beobachtung vom
  05.09. (Sendung über 40 exakt bewegt, trotzdem „failed").

**Nicht geprüft (vermutet, nur im Spiel messbar):** ob das Eingabefenster von
einem Tick auf 2.80 für Mauer-/Bodenziele reicht; Übergabe §23 Punkt 7.

## P2 — Erreichbarkeit / Balance

- `CanFormAlliance` verlangt `FulfilledDemands >= 3`, aktiven Handelspakt,
  `AllianceTermsFulfilled`, keine Wiedergutmachung, Profilwerte. Die Leiter
  Courtship → TradeProof → AllianceTerms liefert genau drei erfüllte
  Forderungen; `PrepareAllianceReadiness` hebt Werte auf die Profilschwelle.
  Hergeleitet erreichbar; `TestEveryPersonalityCanCompleteFinalTerms` und der
  1500-Tage-Stress decken es modellseitig.
- Dauerhafte Sperre nur über `PermanentBreachFloor` (aus Bruchzählern), nicht
  aus Verfall: `ProcessEnemyDay` senkt Groll nie unter den Boden und hebt keine
  Zähler. Hergeleitet korrekt.
- `V2DurationText` meldet „noch 1 Monat" ab 60 Tagen — für Spieler ohne
  Kalender-Vorwissen unauffällig; kein Fehler.

## P3 — UI / Distribution

- Installer: Engine + drei Vanilla-UI-Dateien geprüft, Fremdpatch abgelehnt,
  Staging → atomares Umbenennen, Backup außerhalb von `plugins/`. Nach dem
  Austausch: installiert = `dist` byteweise (4/4), kein Staging-Rest.
- `build-manifest.json` trägt `release_readiness.status =
  in_game_acceptance_required`; nichts daran geändert.
- Anmerkung (klein): `StrongholdEuropeDiplomatieV2.Tests/Program.cs` schreibt
  bei Erfolg **nichts**. Exit 0 ist korrekt, aber ein nie laufender Test wäre
  unsichtbar. Eine Zeile „N Tests bestanden" je Lauf wäre der Gegenprüfung
  wert.

## Prüfstand-Ergebnisse

| Prüfung | Ergebnis |
|---|---|
| pytest fokussiert | 23/23 |
| pytest erweitert (Fremdfehler abgewählt) | 66/66 |
| C#-Modelltests | Exit 0 (44 Aufrufe, stumm) |
| V1-Kompatibilitätsleser | Exit 0, 493-B-Fixture |
| V2-Bau nach Korrektur | 281.088 B |
| V1-Bau nach Korrektur (ohne `DIPLOMACY_V2`) | 187.392 B |

## Was weiter fehlt

1. Die In-Game-Abnahme aus Übergabe §18 — der nächste Start prüft zuerst,
   ob die Detailtafel steht (`ui_integration|status=vanilla_portraits_extended`
   ohne folgendes `refresh_degraded`).
2. Engine-Nachweis bleibt `load_only`.
3. Die prinzipbedingte V1-Semantikreduktion des Rückfallstands (Übergabe §16)
   ist dokumentiert und unverändert.

---

# Nachtrag 2026-09-06 nachmittags — Kompatibilitätsvertrag und Dauerlauf-Audit

Anlass: Anforderung des Benutzers — maximale Kompatibilität zu anderen
Spielversionen, Zuverlässigkeit des kontinuierlichen Laufs zumindest auf
Codebasis geprüft.

## A. Kompatibilitätsvertrag, mechanisch aus der DLL extrahiert

Quelle: `ilspycmd -il` über `StrongholdEuropeDiplomatieV2.dll`, alle
`[Assembly]Typ::Mitglied`-Verweise; dazu alle Reflexionsziele per Name aus dem
Quelltext (`GetMethod/GetField/GetProperty/GetType/GetNestedType`) und die
Harmony-Ansprüche. Prüfung gegen vollständige Projekt-Dekompilate.

| Assembly | Typen | Mitglieder | 2.7 | 2.80 | SE 1.39 | SE 1.44 |
|---|---:|---:|---|---|---|---|
| Assembly-CSharp | 21 | 84 | 0 fehlend | 0 fehlend | — | — |
| SHCDESE | 41 | 202 | — | — | 0 fehlend | 0 fehlend |

(Der einzige Roh-Treffer `GameTimeManagerAPI::remove_OnTick` war ein
Prüfartefakt; das Ereignis `OnTick` existiert in beiden Extender-Fassungen.)

**Schluss (bewiesen für die vier lokal vorhandenen Fassungen):** kein vom
Plugin gebundenes Mitglied unterscheidet sich zwischen 2.7 und 2.80 bzw.
SE 1.39 und 1.44. Die Kompatibilitätsgrenze zieht heute ausschließlich die
Hash-Anmeldung: exakte SHA-256/MVID auf acht Voraussetzungs-Assemblies
(`RuntimeBuildGuard.VerifyCore`), auf `CrusaderDE.dll` (Engine-Pin) und auf
drei Vanilla-XAML-Dateien (Installer). Jede davon macht aus einer
Patch-Version, die nichts Benutztes ändert, einen Totalausfall.

Rohlisten: `scratchpad/v2-refs-assemblycsharp.txt`, `v2-refs-shcdese.txt`
(Sitzungs-Scratch; bei Bedarf in `runtime/StrongholdEuropeDiplomatieV2/`
ablegen).

## B. Dauerlauf-Audit (Codeebene, vollständig ausgezählt)

| Prüfung | Ergebnis |
|---|---|
| Ereignis-Abos ↔ Freigaben (`IDisposable`-Felder) | 15 ↔ 15, alle mit `Dispose(ref)` |
| V2-Kartenzustandsfelder ↔ `ResetV2RuntimeMapState` | 17 Felder; 13 im Reset, 4 mit eigenem Lebenszyklus (Legacy-Save-Staging, Handler-Registrierung) — korrekt |
| Zähler | `_featureTicks`/`_simulationTicks` `int`, ungeprüft inkrementiert → Wrap nach 2³¹ Takten ≈ 414 Tage Dauerlauf; `_logSequence` `long`. Informativ. |
| Protokollflut | `RecordBlockedCombat` ≤ 8 Zeilen je Übergang, `event=value` nur bei Signaturänderung, `CaptureCombatSafetyFault` latcht die erste Ausnahme. In Ordnung. |
| Ausnahmen in Haken | jede Hook-Methode fängt; kein Wurf durch native Rahmen. In Ordnung. |
| Abschaltstufen (`DisableMap`) | 11 Stufen ausgezählt: `day_change, feature_rollback, map_bootstrap_*, map_unload(expected), runtime_frame, save_load_pause, simulation_tick, transfer_postfix, ui_command, ui_rollover, ui_roster` |

### Befund 3 (P1, behoben) — Vollscans je Kampfereignis

`OnDiplomacySpawnFire` und `OnDiplomacyProjectileSpawn` riefen je Ereignis
`TryFindAlliedUnitNearWorldTarget` (alle lebenden Einheiten aufzählen + sortieren),
`TryFindAlliedOwnedTileNearWorldTarget` (Kachelraster) und unter V2 zusätzlich
`V2TryFindDiplomaticCounterpartNearWorldTarget` (nochmals alle Einheiten +
Raster) — **auch ohne Bündnis, Pakt oder KI-Team**, also im Normalzustand.
Kein Leck, aber O(N log N) je Brandpfeil/Pechfeuer; bei Belagerungen Dutzende
je Sekunde.

Korrektur, ergebnisneutral:
- `AnyProtectedPairPossible()` (CombatSafety): Bündnisschutz-Suchen nur, wenn
  eine Rückroll-/Übergangspartition aktiv ist, eine Beziehung `Allied` ist,
  ein V2-Pakt aktiv ist oder eine Koalition mehr als ein Mitglied hat
  (natives KI-Team). Genau die Quellen, aus denen `NativePlayersAreAllied`
  urteilt; im Zweifel wird gesucht.
- `V2TryFindDiplomaticCounterpartNearWorldTarget`: Schutzsuche nur bei
  aktivem Pakt (`V2AnyActiveTreaty`); Feindakt-Zuordnung höchstens einmal je
  32 Simulationstakte (`RecordHostileAct` ist je Tag idempotent).

### Befund 4 (P0, behoben) — `ui_rollover` eskalierte zu `DisableMap`

`AlliesRolloverPrefix` fing Ausnahmen aus `HandleRollover` (setzt
ausschließlich `AlliesCommandsRolloverText`, schreibt keinen Zustand —
mechanisch geprüft) und beendete die Diplomatie für die Partie. Jetzt
`DegradeUiRefresh("ui_rollover", …)` wie bei `ui_refresh`; die Warnung trägt
nun `stage=`.

## C. Empfehlung zur Kompatibilität (Entscheidung, nicht Fehlerbehebung)

Die Hash-Anmeldung durch eine **Mitgliederprüfung** ersetzen: der Vertrag aus A
wird beim Bau aus der IL erzeugt und einkompiliert; beim Start prüft das Plugin
jedes Mitglied per Reflexion und schaltet nur ab, wenn ein *benutztes*
Mitglied fehlt — mit dessen Namen im Protokoll. Hash-Abweichung und
unbekannte Engine werden zur Warnung (`unverified_build`), nicht zum Ausfall.
Der Diplomatie-Wächter wird dafür eigenständig (`DiplomatieCompatibilityGuard`
im V2-Projekt), damit `RuntimeBuildGuard` des Europa-Mods unverändert bleibt.
XAML: der Laufzeit-Rückfall (29 Pflichtelemente → natives Detail) bleibt; der
Installer-Hash der drei Vanilla-Dateien wird zur Warnung, weil der Patch
XPath-verankert ist.

---

# Nachtrag 2026-09-06 abends — Mitgliederprüfung statt Hash (umgesetzt)

Entscheidung des Benutzers: „Mitgliederprüfung statt Hash". Umgesetzt im
V2-Projekt; `RuntimeBuildGuard`/`EuropeCapabilities` des Europa-Mods sind
unverändert (der V1-Host benutzt sie weiter unter `#if !DIPLOMACY_V2`).

## Bauart

1. **Vertrag aus der IL** (`kompatibilitaet.py`): `ilspycmd -il` über die
   fertige DLL, jede Bindung an eine Vertragsassembly wird ausgezählt — Typen
   (auch `ldtoken`/`box`/generische Argumente), Methoden mit Parameterzahl,
   Felder. Keine gepflegte Liste.
2. **Zweistufiger Bau** (`bauen.py`): erst mit leerem Vertrag übersetzen, IL
   auszählen, `GeneratedCompatibilityContract.g.cs` schreiben, erneut
   übersetzen, erneut auszählen — der zweite Durchgang muss dieselbe Menge
   ergeben, sonst bricht der Bau ab.
3. **Wächter** (`DiplomatieCompatibilityGuard.cs`): beim Start wird jede
   Bindung per Reflexion geprüft (Assembly geladen? Typ vorhanden? Methode mit
   passender Parameterzahl / Feld vorhanden?). Fehlt eines → Abschaltung mit
   Namen (`missing_member=…`). Pruefsummen der 15 Voraussetzungen und die
   Engine werden nur noch **beglaubigt** (`attested=n/15`, `engine=attested`
   bzw. `unverified:<digest>`), nie verweigert. Wirft nie.
4. **`DiplomacyFeature.Prepare()`**: unter `DIPLOMACY_V2` wird eine fremde
   Engine als `unverified_engine` gemeldet statt `Prepare` scheitern zu lassen.
5. **Installer**: fremde Engine und abweichende Vanilla-XAML sind Warnungen
   (der HUD-Patch ist XPath-verankert, die Laufzeit fällt bei fehlenden
   Elementen auf das native Detail zurück). Verweigert bleibt: V1-Ordner
   daneben, fremder `HUD_AlliesPanel`-Patch.

## Gemessener Vertrag (Bau 12:25)

395 Bindungen: Assembly-CSharp 18 Typen / 33 Methoden / 33 Felder,
SHCDESE 58 / 130 / 72, 0Harmony 3/6/0, BepInEx 6/9/0, R3 3/0/1,
UnityEngine.CoreModule 8/9/1, AssetBundleModule 1, AudioModule 1,
Zhuqiaomon 2, System.Memory 1. Signatur im Manifest
(`compatibility_contract.sha256`) und im Startprotokoll (`contract=…`).

Offline gegen die Dekompilate geprüft: siehe Protokoll des Laufs (Ergebnis
dieses Nachtrags im Koordinationsdokument).

## Abnahme im Spiel

Startzeile: `event=compatibility|status=ok|bindings=395/395|attested=15/15|engine=attested|contract=…`.
Auf einer fremden Fassung erwartet: `bindings=395/395`, `attested=k/15`
mit `unattested_prerequisite`-Warnungen, `engine=unverified:…` — und die
Diplomatie läuft. Erst `missing_member` schaltet ab.

## Grenzen (ehrlich)

- Die Mitgliederprüfung sieht **Namen und Parameterzahl**, keine Semantik.
  Ändert eine Fassung das *Verhalten* eines gleichnamigen Mitglieds, merkt
  das erst das Spiel. Deshalb bleibt `engine-pins.json` mit Beleggrad die
  Aussage darüber, wo gemessen wurde.
- Nur vier Fassungen lagen lokal vor (2.7, 2.80, SE 1.39, SE 1.44). Für
  jede weitere gilt: Vertrag prüfen ist mechanisch möglich, Verhalten messen
  nicht.
- `BepInDependency("000shcdese", "1.44.0")` bleibt als Mindestversion; sie
  zu senken wäre eine eigene Entscheidung, obwohl der Vertrag auf 1.39 passt.

---

# Abnahmeprotokoll 2026-09-06, 15:17 — Spiellauf mit Mitgliederwächter (Build 12:39, DLL 317.952 B, Vertrag `f02ff21b8fc1`)

Zwei Karten (Crater Lake, Solo gegen 7; die zweite per Spielstand geladen),
Ende per Alt+F4. **Keine Warnung, kein Fehler, kein `fail_closed` aus V2.**
Zuordnung zur Matrix aus `CLAUDE_TECHNICAL_HANDOFF.md` §18, mit `seq`:

| § | Punkt | Beleg | Stand |
|---|---|---|---|
| 1 | Kaltstart 2.80/1.44, genau ein V2-Plugin, Startprotokoll | `compatibility\|status=ok\|bindings=402/402\|attested=15/15\|engine=attested` → `feature\|status=active` | **belegt** |
| 3 | mit aktivem Europa-Grafikmod (`diplomacy: false`) | Europa-Runtime meldet `lane=diplomacy\|status=inactive`; V2 läuft daneben | **belegt** (Origins geladen, verweigert sich selbst wegen SE-1.39-Pin) |
| 6 | V2 speichern/laden | `saving\|saved\|4985 B` + `v1_compat_saved\|1381 B` (seq 253/254, Stand mit zwei Bündnissen + Pakten); Karte 2 `trigger=save_load` → `restore_paused` → `map_active` (seq 258–269), Forderung läuft weiter (seq 278) | **teilweise** — geladen wurde ein anderer V2-Stand (Aufstellung `88ff…`), nicht der mit Bündnissen |
| 9 | Drei-Waren-Forderung per Primärschaltfläche, atomar | 7× `demand_package\|status=complete\|items=3` (seq 72, 91, 118, 162, 197, 226, 286); 21 `transfer\|confirmed\|transport=demand_package` = 7×3 | **belegt** |
| 11 | Verbündetengeschenk über Vanilla-Pfad | `native_allied_started\|target=8\|good=15\|amount=8000` → `native_allied_confirmed\|proof=post_inventory\|return_hint=false` (seq 142/143) — der native Rückgabewert ist falsch, der Lagerbeleg exakt: genau Codex' V1.1-Befund | **belegt**; provozierter Native-Fehler + direkter Rückfall offen |
| 12/13 | Waffenruhe/Bündnis: automatische Angriffe unterbunden, ganzer Spielerblock | `combat_guard\|blocked\|path=ai_attack_evaluation\|source=1\|target=8` (×4) und `target=2` (×2) bei zwei gleichzeitigen Bündnissen (Partition `2:1, 8:1`) | **teilweise** — nur der KI-Bewertungspfad ausgelöst; Beschuss/Nahkampf/Belagerungsziele nicht provoziert |
| 18 | Vollständige Leiter bis zum Bündnis | team:8: Waffenruhe (71) → Handel (90) → Bündnisbedingungen (118) → `FormAlliance` queued/native_commit/committed (119); team:2: 161 → 196 → 226 → 227; team:7: Waffenruhe (285) | **belegt**, zweimal |
| 19 | Pflegeguthaben durch proaktive Hilfe | `support\|coalition=team:8\|status=proactive_credit_accepted` (seq 215) | **teilweise** — Unterstützungsforderung, Ultimatum, KI-Auflösung offen |
| 21 | Save/Load nach Teamänderungen | Speichern nach beiden Bündnissen (253) sauber; Laden dieses Standes nicht versucht | **teilweise** |
| 23 | Kartenende / Zurück ins Menü | `map_teardown_rollback_complete\|stage=map_unload\|team_stable=true` (255); Alt+F4: `shutdown\|reason=application quit` → `process_exit\|rollback=not_required` | **belegt** |

Nebenbefunde: 26 bestätigte Sendungen (4 atomar, 21 Paket, 1 nativ
verbündet), 20 Sprachausgaben, 3 `agreement_safety`-Bereinigungen mit je
einem gelöschten KI-Angriffsziel. Kein `transfers_disabled`, kein
`refresh_degraded`, kein `unattested_prerequisite`.

**Offen bleiben:** 2 (Vanilla ohne Europe/Origins), 4 (echter V1-Stand),
5 (Schema-2-Stand), 7 (Korruptionsrückfall), 8 (Einzelforderung), 10
(fehlende Ware im Paket), 11b (provozierter Native-Fehler), 14 (Flächenfeuer),
15 (bewusster Angriff), 16 (Intimzone), 17 (friedliches Auslaufen), 20
(gezielte Aufkündigung), 22 (UI-Skalierungen/Sprachen), sowie die Reste von
6/12/13/19/21.

---

# Abnahmeprotokoll 2026-09-06, Lauf bis 19:00 — DLL 393.728 B (`4f24f8d4…`), Absturz

Eine Karte, 3 Verbünde (team:2, team:3, team:4), Spielstand geladen (Epoche 2).
Ende: **nativer Absturz 19:00:35** in Noesis `View.Update` (Renderer). Zur
selben Sekunde Windows-Ereignis 2004: „virtueller Speicher unzureichend“ —
Spiel 10,4 GB, codex.exe 5,7 GB, brave.exe 4,9 GB. Keine Ausnahme, kein
`fail_closed` aus V2; die letzten Diplomatiezeilen sind gewöhnlich. **Der
Absturz ist Speichererschöpfung der Maschine, kein Diplomatie-Befund.**

| § | Punkt | Beleg (`seq`) | Stand |
|---|---|---|---|
| 12 | Waffenruhe sperrt Angriffe | `combat_guard\|blocked\|path=projectile_spawn\|source=1\|target=4` ×8 (45–52), `…\|source=1\|target=2` ×7 (236–244), `tribe_order\|source=3\|target=2` (241, KI-Verbündeter gegen Waffenruhe-Partner) | belegt — **aber** die KI belagert weiter (Befund 5) |
| 15 | bewusster Angriff bricht den Pakt | `agreement\|team:4\|status=broken\|actor=player_attack` (54) | **belegt**, Auslöser unbekannt → Logdetails ergänzt |
| 17 | friedliches Auslaufen | `agreement\|team:2\|status=expired` (459) | **belegt** |
| 18 | Leiter Waffenruhe → Handel → Bündnis | team:3: 164 → 198 → 230–240 (FormAlliance, Partition `1:1,2:2,3:1,4:4`) | **belegt** (drittes Mal) |
| 19 | proaktives Pflegeguthaben | `support\|team:3\|status=proactive_credit_accepted` (396) | belegt |
| 20 | gezielte Aufkündigung | `agreement\|team:2\|status=broken\|actor=player` (301, Abkommen, nicht Bündnis) | teilweise |
| — | Wiedergutmachung | `restitution\|accepted` team:4 (123), team:2 (341) | belegt |
| — | Paketlieferung 3 Waren | 4× team:2, 3× team:3, 9× team:4 `demand_package\|complete\|items=3` | belegt |
| — | Transfer-Abbruch | `transfer\|failed_closed\|reason=recipient_credit_readback_mismatch` ×2 (107, 148) | Befund 7 |

## Befund 5 (P1, behoben) — Waffenruhe ohne Abstandsgebot

Beim Paktbeginn mit team:4 (417) wurden **203 Geschosse** gelöscht: der Pakt
kam mitten in einer Belagerung. Der Wächter sperrt Angriffsbefehle, Geschosse,
Feuer und Schaden — aber nichts beendet die native Belagerung. Das
Belagerungsziel (`r_AISiegePlayerIdTarget`) wurde nur einmal geleert; die KI
wählt neu, das Heer steht vor den Mauern, Pfeile fliegen keine. Genau das
Bild, das der Benutzer beschrieb. `OnPlayerAIEvaluateAttackOrder` hilft hier
nicht: es ist `c_game_ai_request_eval_attack_order`, die Bewertung einer
Angriffsbitte eines Verbündeten.

Maßnahme: Abstandsgebot (`treaty_standoff`) — periodisches Leeren der
Belagerungsziele, Rückruf von KI-Stämmen aus der fremden Kernzone,
Abweisen von Marschbefehlen in die fremde Kernzone, Sammelpunktabstand ≥ 22
Kacheln bei Vertragsgegnern. Symmetrisch, nie für den Menschen, Fehler
schalten nur das Gebot ab. Grenze: der native Belagerungsautomat ist nicht
vermessen; `ai_siege|status=rallypoint` ist die Messsonde dafür.

## Befund 6 (P1, behoben) — Drossel der Feindakt-Zuordnung lief über (Codex-Audit P1-A)

`_simulationTicks - int.MinValue` wickelt ins Negative; die Zuordnung von
Boden- und Feuerzielen zu einer Gegenpartei war seit Takt 0 gedrosselt. Jetzt
`DiplomacyV2CombatRules.ScanDue` (Sentinel −1, `long`-Differenz, Rollover =
fällig), Prüfung vor Drossel, alle Treffer im Umkreis. Tests im C#-Prüfstand
und als Struktur-Test.

## Befund 7 (P2, behoben) — Transferabbruch ohne Namen

Zwei `recipient_credit_readback_mismatch` ohne Ware und Menge. Ein Teilzugang
(Lager des Empfängers voll) heißt jetzt `recipient_capacity_clamped`, die
Zeile trägt `expected/observed/target/good/amount`, der Spieler liest „Der
Empfänger kann diese Menge nicht lagern. Die Sendung wurde vollständig
zurückgenommen.“ (5 Sprachen). Die Rückabwicklung war schon vorher exakt.

## Befund 8 (P3, ergänzt) — `actor=player_attack` ohne Befehl

Seq 54 folgte auf acht gesperrte Turmschüsse. Ob ein Klick auf eine Einheit
oder ein Bodenangriff den Bruch auslöste, stand nicht im Protokoll. Jetzt:
`command=|value1=|value2=|tribe=|target_player=|tick=`.

**Stand:** DLL 403.968 B (`faf02703d5a9…`), 420 Bindungen, 207 Texte × 5
Sprachen (Umfang laut Benutzer: DE EN FR ES PT PL IT), installiert 19:28.
`release_readiness` unverändert `in_game_acceptance_required`.
