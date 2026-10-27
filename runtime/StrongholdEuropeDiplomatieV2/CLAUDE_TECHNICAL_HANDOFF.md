# Technische Übergabe: Stronghold Crusader Diplomatie V2.1

> **Verbindlicher Codex-Nachtrag vom 2026-09-06:** Vor jeder öffentlichen
> Freigabe zuerst `CODEX_RELEASE_AUDIT_HANDOFF_2026-09-06.md` vollständig
> abarbeiten. Dort sind der exakt geprüfte Quell-/DLL-Stand, zwei konkrete
> P1-Blocker, weitere Kompatibilitäts- und Dauerlaufrisiken, alle
> Reproduktionsbefehle sowie die noch offene In-Game-Abnahme dokumentiert.

Stand: 2026-09-06  
Ziel: vollständiger Code- und Release-Review durch Claude  
Plugin-Version: `2.1.0`  
Wichtig: Diese Übergabe beschreibt den eigenständigen V2-Nachfolger. Er enthält die komplette V1-Funktionalität, verwendet aber weder den Europe- noch den Origins-Mod als Laufzeitabhängigkeit.

## 1. Ergebnis und Freigabestatus

Der Code, der reproduzierbare Build und der transaktionale Installer sind automatisiert geprüft. Der Build ist absichtlich **noch nicht als öffentlich freigegeben** markiert. Für eine öffentliche Veröffentlichung fehlt eine protokollierte In-Game-Abnahme auf der festgeschriebenen Spielversion.

Der Release-Gate steht sowohl im Builder als auch im ausgelieferten `build-manifest.json`:

- `engine_evidence = load_only`
- `in_game_acceptance_recorded = false`
- `public_release_ready = false`
- `status = in_game_acceptance_required`

Das ist keine bloße Dokumentationsnotiz. Claude soll eine Änderung auf `public_release_ready = true` nur akzeptieren, wenn die Abnahmematrix in Abschnitt 18 tatsächlich im Spiel protokolliert wurde.

## 2. Relevante Quell- und Artefaktpfade

### V2-eigener Code

- `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2Core.cs`
- `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2Feature.cs`
- `runtime/StrongholdEuropeDiplomatieV2/DiplomacyV2SaveCodec.cs`
- `runtime/StrongholdEuropeDiplomatieV2/HUD_AlliesPanel.V2.fragment.xml`
- `runtime/StrongholdEuropeDiplomatieV2/StrongholdEuropeDiplomatie.csproj`
- `runtime/StrongholdEuropeDiplomatieV2/bauen.py`

### Bewusst wiederverwendete V1-/Host-Basis

- `runtime/StrongholdEuropeDiplomatie/DiplomatiePlugin.cs`
- `runtime/StrongholdEuropeDiplomatie/DiplomatiePersistentHost.cs`
- `runtime/StrongholdEuropeDE.Runtime/DiplomacyCore.cs`
- `runtime/StrongholdEuropeDE.Runtime/DiplomacyFeature.cs`
- `runtime/StrongholdEuropeDE.Runtime/DiplomacyCombatSafety.cs`
- `runtime/StrongholdEuropeDE.Runtime/DiplomacySaveCodec.cs`
- `runtime/StrongholdEuropeDE.Runtime/ExtensionFeatureHost.cs`
- `runtime/StrongholdEuropeDE.Runtime/RuntimeSessionScopeDecision.cs`
- `runtime/StrongholdEuropeDE.Runtime/Hashing.cs`
- `runtime/StrongholdEuropeDE.Runtime/EuropeCapabilities.cs`
- `runtime/StrongholdEuropeDE.Runtime/RuntimeBuildGuard.cs`
- `runtime/StrongholdEuropeDE.Runtime/RuntimeDecision.cs`

### Tests

- `runtime/StrongholdEuropeDiplomatieV2.Tests/Program.cs`
- `runtime/StrongholdEuropeDiplomatieV1Compatibility.Tests/Program.cs`
- `runtime/StrongholdEuropeDiplomatieV1Compatibility.Tests/StrongholdEuropeDiplomatieV1Compatibility.Tests.csproj`
- `tests/test_diplomacy_v2_plugin.py`
- `tests/test_standalone_diplomacy_plugin.py`
- `tests/test_diplomacy_contract.py`

### Unveränderte V1-HUD-Basis

- `assets/xaml/HUD_AlliesPanel.xaml`

### Fertiges Paket

- `dist/StrongholdEuropeDiplomatieV2`

Der gesamte Arbeitsbaum enthält viele sachfremde, bereits vorhandene Änderungen. Claude soll den Review auf die oben genannten Diplomatiepfade begrenzen und keine fremden Änderungen zurücksetzen.

## 3. Identitäten und Abhängigkeiten

### Stabile Identitäten

- BepInEx-Plugin-ID: `strongholdeuropede.diplomatie.v2.private`
- Harmony-ID: `strongholdeuropede.diplomatie.v2.harmony`
- Feature-ID: `gameplay.diplomacy.v2`
- primärer Save-Identifier: `StrongholdEuropeDE.Diplomacy.v2`
- fortlaufender V1-Identifier: `StrongholdEuropeDE.Diplomacy.v1`
- Installationsordner: `BepInEx/plugins/StrongholdEuropeDiplomatieV2`
- Assembly: `StrongholdEuropeDiplomatieV2.dll`

Die bestehende V2.0-Identität bleibt absichtlich stabil. So ersetzt V2.1 die alte V2, und vorhandene Schema-2-Spielstände werden automatisch übernommen.

### BepInEx-Verträge

- harte Abhängigkeit: `000shcdese`, mindestens `1.44.0`
- Inkompatibilität: alter eigenständiger V1-Plugin-ID `strongholdeuropede.diplomatie.private`
- **keine** Abhängigkeit von `StrongholdEuropeDE`
- **keine** Abhängigkeit von `StrongholdOrigins`

Die fertige DLL referenziert folgende Assemblies und keine Europe-/Origins-Assembly:

| Assembly | Version |
|---|---:|
| `0Harmony` | `2.9.0.0` |
| `Assembly-CSharp` | `0.0.0.0` |
| `BepInEx` | `5.4.23.5` |
| `R3` | `1.3.1.0` |
| `SHCDESE` | `1.44.0.0` |
| `System` | `4.0.0.0` |
| `System.Core` | `4.0.0.0` |
| `System.Memory` | `4.0.5.0` |
| `UnityEngine.AssetBundleModule` | `0.0.0.0` |
| `UnityEngine.AudioModule` | `0.0.0.0` |
| `UnityEngine.CoreModule` | `0.0.0.0` |
| `Zhuqiaomon` | `1.0.0.0` |

## 4. Festgeschriebene Zielumgebung

- Spiel: Stronghold Crusader Definitive Edition
- angezeigte Version: `SHC:DE 2.80`
- Build-ID: `local-shcde-2.80-unity-2021.3.45f2`
- Script Extender: `SHCDESE 1.44.0`
- Engine-Datei: `Stronghold Crusader Definitive Edition_Data/Plugins/x86_64/CrusaderDE.dll`
- Engine-Größe: `3,450,880` Byte
- Engine-SHA-256: `1e6d4c2e10cc35a7b8082a7e2bcd8bb20680ebeda803d9b943257b948145cb2b`
- Engine-Nachweis: `load_only`, noch nicht `measured`

Der Builder kompiliert gegen eine saubere Referenz aus Crusader DE 2.80 + BepInEx + SHCDESE 1.44. Er passt die alte, geteilte Engine-Pin im isolierten Work-Verzeichnis an; deshalb enthält das Manifest `source_adjustments: ["engine-pin"]`. Die Quellbasis wird dafür nicht heimlich überschrieben.

## 5. Laufzeitarchitektur

`DiplomatiePlugin` ist ein dünner BepInEx-Host. Unter `DIPLOMACY_V2` erhält derselbe geprüfte Host die V2-ID, den V2-Logpräfix und keine weiche Europe-Abhängigkeit.

Wesentliche Abfolge:

1. `Awake()` prüft Fähigkeiten und die festgeschriebene Laufzeit.
2. `ExtensionFeatureHost` registriert genau einen Besitzer der Diplomatie-Hooks.
3. `DiplomacyFeature.Prepare()` bindet Save-, Karten-, Tages-, UI-, Transfer- und Kampfereignisse.
4. Karten werden nur für unterstützte Offline-Skirmish-Sitzungen aktiviert.
5. `CaptureRosterAndCoalitions()` bildet KI-Spieler nach ihrem positiven Vanilla-Team; Team 0 wird pro Spieler getrennt behandelt.
6. Preise, Karten-/Roster-Fingerprints und ursprüngliche Teamaufteilung werden eingefroren.
7. Ein passender V2-/V1-Spielstand wird wiederhergestellt oder neue Beziehungen werden erzeugt.
8. Tageswechsel verändern das politische Modell deterministisch; Simulationsticks erledigen Teamjournale, Transfernachweise und Invasionsscans.
9. Beim Kartenende oder Fehler werden eigene Teamänderungen transaktional zurückgenommen. Sicherheits-Hooks bleiben bei ungeklärter Rücknahme fail-closed gebunden.

Wichtige Alias-Entscheidung: Im V2-Build ist `DiplomacyPolicy` auf `DiplomacyV2StateMachine` gerichtet. Im V1-Build bleibt derselbe Host auf `DiplomacyStateMachine` gerichtet.

## 6. Koalitions- und Herrschermodell

Eine `CoalitionState` entspricht einem vorhandenen positiven Vanilla-KI-Team oder – bei Vanilla-Team 0 – genau einem KI-Spieler. Die politische Beziehung wird pro Koalition geführt, nicht pro Portrait. Dadurch bleiben bereits verbündete KI-Teams zusammen und werden nicht durch die Mod zerlegt.

Für jeden Verbund wird ein Primärherrscher deterministisch aus dem Mitglied mit der höchsten `send_goods_margin` gewählt. Bei Gleichstand gewinnt die kleinere Spieler-ID. Das Profil wird aus echten `InternalAIC`-Signalen abgeleitet:

- Handelsneigung: Kauf-/Handelsgrenzen für Nahrung, Rohstoffe, Mehl, Ale und Pech
- Militärneigung: Waffenbeschaffung und höchste Verteidigungs-/Belagerungs-/Störangriffsneigung
- Aggression: offensive Spitzenwerte und Harassment
- Vorsicht: defensive Wahrscheinlichkeiten plus Gütermarge

Es existieren genau sieben Profile:

| Profil | Geschenk-BP | Wiederholungsminimum | Material/Nahrung/Luxus/Waffen/Gold % | Bündnisschwelle / Mindestvertrauen / Maximalgroll | Waffenruhe / Handel / Verhandlungsfrist | Pflegeintervall / Hilfe / Ultimatum |
|---|---:|---:|---|---|---|---|
| Ehrenhaft | 9600 | 55 % | 105/100/85/105/90 | 76/58/30 | 75/180/42 Tage | 150/42/35 Tage |
| Händlerisch | 12400 | 42 % | 115/105/125/90/120 | 77/50/35 | 60/210/35 Tage | 120/35/30 Tage |
| Misstrauisch | 8500 | 62 % | 110/110/75/100/90 | 85/68/20 | 45/150/45 Tage | 135/42/35 Tage |
| Kriegerisch | 8800 | 48 % | 95/90/70/135/95 | 82/45/30 | 40/120/30 Tage | 90/30/24 Tage |
| Opportunistisch | 10500 | 42 % | 100/95/105/115/115 | 79/44/40 | 45/135/30 Tage | 80/28/21 Tage |
| Treu | 10000 | 58 % | 100/115/95/100/90 | 75/60/33 | 90/240/45 Tage | 180/49/42 Tage |
| Fordernd | 11400 | 38 % | 105/95/115/110/125 | 82/54/27 | 40/120/28 Tage | 75/28/21 Tage |

Die vollständigen Gewichte, Initialwerte, Reaktionskoeffizienten und Forderungsprozente stehen bewusst zentral in `DiplomacyV2PersonalityCatalog`.

## 7. Beziehungszustand und Invarianten

Jede `RelationState` besitzt unter V2 einen `DiplomacyV2RelationState`. Primäre sichtbare Dimensionen:

- Vertrauen
- Dankbarkeit
- Respekt
- Groll
- Verlässlichkeit
- Vertrauensobergrenze

Weitere dauerhaft gespeicherte Größen:

- positive/negative Dynamik
- strategische Drohung, Abhängigkeit, Koalitionswert und Machtvorteil
- erfüllte/verfehlte Forderungen und Unterstützungsserien
- manuelle Vertragsenden, heimtückische Angriffe, militärische Grenzverletzungen
- eigene und beobachtete Bündnisaufkündigungen
- Bruchpunkte und offene Wiedergutmachung
- Geschenkgedächtnis pro Ware
- Pflegeguthaben und Hilfe seit der letzten Pflege
- Verhandlungsdruck, Sperren und Ereignistage

Alle Prozentwerte werden auf 0–100 begrenzt. Historische Zähler sind auf 1.000.000 und historische Werte auf 1.000.000.000 begrenzt. Persistierte Fristen dürfen höchstens 365 logische Tage in der Zukunft liegen. Unmögliche Kombinationen – etwa `relation.Allied` ohne V2-Abkommen `Alliance` oder ein abgelaufener gespeicherter Pakt – werden verworfen.

Der Beziehungsscore ist das profilgewichtete Mittel aus Vertrauen, Dankbarkeit, Respekt und `100 - Groll`.

## 8. Verhandlungsleiter

Die beabsichtigte Reihenfolge ist strikt:

`Feindselig/Kontakt → Waffenruhebedingungen → Waffenruhe → Handelsbedingungen → Handelsabkommen → Bündnisbedingungen → bündnisbereit → Bündnis`

Wichtige Regeln:

- Kein Bündnis entsteht nur aus Goodwill oder freien Geschenken.
- Jede Stufe verlangt eine tatsächlich vollständig gelieferte Warenforderung.
- Ein Bündnis setzt mindestens drei erfüllte Stufen, ein aktives Handelsabkommen, erfüllte Abschlussbedingungen, keine offene Wiedergutmachung und die profilspezifischen Werte voraus.
- Mindestens ein feindlicher KI-Verbund muss übrig bleiben. Der letzte Gegner darf verhandeln und Pakte schließen, aber kein Bündnis bilden.
- Abschlussbedingungen bleiben historisch erfüllt, wenn ein Pakt friedlich ausläuft. Waffenruhe und Handel müssen erneut aufgebaut werden, das identische Abschlusspaket wird aber nicht doppelt verlangt.
- Ein Vertragsbruch löscht die frühere politische Zustimmung; nach Wiedergutmachung müssen die Bündnisbedingungen erneut erfüllt werden.
- Zu häufige Anfragen erhöhen Misstrauen und setzen profilspezifische Wartezeiten von 21–35 Tagen.
- Verhandlungsfristen liegen bei 28–45 Tagen; kein Kernschritt arbeitet mehr mit nur wenigen Tagen.

## 9. Situative Geschenke und abnehmender Nutzen

Sendbare Güter-IDs: `2,3,4,6,7,9..24`; ID 15 ist Gold.

Die Bewertung berücksichtigt gleichzeitig:

- eingefrorenen Vanilla-Verkaufswert pro Einheit
- Profilgrundwert
- Warenkategorie des Herrschers
- aktuell gemessenen AIC-Bedarf
- ob die Ware gerade gefordert wird
- aktives Handelsabkommen
- Wiederholungen derselben Ware
- kürzliche Rohwertsättigung derselben Ware
- abwechslungsreiche Kategorien
- weiche Obergrenze für sehr große Einzelgeschenke

Wesentliche Zahlen:

- jede direkte Wiederholung senkt den Faktor um 13 Prozentpunkte bis zum Profilminimum
- passende, konkret benötigte Ware: ungefähr 105–160 % Bedarfseinfluss
- nur kategoriell nützliche Ware: 88 %
- unpassende Ware: 70 %
- geforderte Ware: 125 %
- Geschenk unter Handelsabkommen: 112 %
- Sättigungsfaktor: 58–100 %
- Variation: bis +12 %
- jenseits 25 % des Beziehungsziels zählt zusätzlicher Rohwert nur noch zu 55 %
- maximal gutgeschriebener Einzelwert: 150 % des aktuellen Ziels

Das Warenbedarfsmodell liest alle im `InternalAIC` verfügbaren einschlägigen Felder. SHCDESE 1.44 besitzt kein `buy_meat_at`; Fleisch kann dennoch über laufende Produktion als Bedarf eingehen. Rekrutierungs- und Produktionsbedarf wird aus den AIC-Truppentypen, ihren Ausrüstungskosten und aktiven Produktionsgebäuden ergänzt.

## 10. Strategische Macht- und Koalitionsbewertung

Ökonomie und Militär werden aus dem tatsächlichen Vanilla-Zustand berechnet:

- Gold und alle sendbaren Lagergüter
- aktive Produktionsgebäude anteilig nach Materialwert
- lebende Kampfeinheiten nach Gold-/Ausrüstungswert und aktueller Gesundheit
- Lord mit festem Militärwert

Grundmacht: `Ökonomie × 0,8 + Militär × 1,4`.

Bewertet werden:

- Machtverhältnis Spielerblock zu Zielkoalition
- gemeinsame feindliche Koalitionen
- gesamte feindliche Wirtschaft und Militärmacht
- Zahl vorhandener Spielerbündnisse
- ob der Zielverbund strategisch unter Druck steht
- profilspezifische Drohungs- und Abhängigkeitsgewichte

Strategische Werte werden täglich geglättet (`65 %` vorheriger + `35 %` neuer Wert); Respekt bewegt sich mit `70/30`-Glättung. Misstrauische Herrscher reagieren skeptischer auf viele Bündnisse, Opportunisten stärker auf Abhängigkeit.

## 11. Bündnispflege, Hilfe und Ultimaten

Nach Bündnisschluss wird das nächste Pflegefenster profilspezifisch geplant. Das effektive Intervall ist mindestens 60 Tage und wird durch hohe Verlässlichkeit, erfüllte Hilfsserien und strategischen Druck verändert.

Vorab gesendete, nicht gerade geforderte Hilfe sammelt `MaintenanceCredit`. Reicht dieses Guthaben beim Pflegetermin, wird es anerkannt und die nächste Forderung entfällt.

Ohne ausreichendes Guthaben folgt:

1. Unterstützungsforderung mit 28–49 Tagen Frist.
2. Bei Versäumnis Vertrauens-/Groll-/Verlässlichkeitsfolge und ein Ultimatum mit 21–42 Tagen Frist.
3. Bei erneutem Versäumnis transaktionale Auflösung durch den KI-Verbündeten.

Erfüllung geschieht bei Einzel- wie Mehrfachforderungen über dieselbe direkte Schaltfläche. Die Waren/Goldmengen werden automatisch vollständig abgezogen und gutgeschrieben.

## 12. Vertragsbruch und dauerhafte Folgen

Unterschieden werden:

- manuelles Ende von Waffenruhe/Handel
- ausdrücklicher Angriff während eines Pakts
- substanzielle militärische Grenzverletzung
- aktive Aufkündigung eines Bündnisses
- Auflösung nach nicht erfülltem Ultimatum

Brüche verändern sofort Vertrauen, Dankbarkeit, Groll und Verlässlichkeit, erhöhen permanente Zähler und erzeugen Wiedergutmachungsschulden.

Die Vertrauensobergrenze ist `100 - Bruchpunkte × 0,52`, mindestens 65. Der dauerhafte Grollboden wird aus gewichteten historischen Taten gebildet:

- manuelles Vertragsende × 5
- heimtückischer Angriff × 14
- militärische Grenzverletzung × 10
- eigene Bündnisaufkündigung × 20
- beobachtete Bündnisaufkündigung × 4

Der resultierende Bruchboden ist auf 250 begrenzt; der Grollboden beträgt 35 % davon, maximal 60. Wenn Vertrauensobergrenze oder Grollboden die Profilanforderungen dauerhaft unerreichbar machen, bleibt ein erneutes Bündnis ausgeschlossen. Wiedergutmachung beseitigt die aktuelle Schuld, nicht das historische Gedächtnis.

Bei aktiver Bündnisaufkündigung durch den Spieler erhalten alle anderen lebenden, nicht verbündeten Fürsten einen beobachteten Verrat. Mehrere gleichzeitig aufgekündigte Bündnisse skalieren diesen Malus.

## 13. Waffenruhe-, Kampf- und Intimzonenschutz

### Vollständiger Spielerblock

Eine Waffenruhe bzw. ein Handelsabkommen gilt zwischen dem gesamten Spielerblock und dem Zielverbund:

- menschlicher Spieler
- alle bereits mit ihm verbündeten KI-Koalitionen
- alle Mitglieder des Vertragspartners

Vanilla-Team 0 wird dabei nie als positives Bündnis missverstanden. Beim Vertragsabschluss wird eine synthetische positive Schutzpartition gebaut und vorhandene feindliche Altzustände werden bereinigt:

- angreifende Tribes stoppen
- gefährliche Projektile löschen
- vom neuen Vertragspartner verursachte Gebäudebrände löschen
- AI-Siegeziele zwischen geschützten Seiten leeren

### Laufende Schutz-Hooks

Geschützt werden unter anderem:

- Tribe-Angriffsaufträge
- Projektilerzeugung
- Flächenerzeugung von Feuer
- Nahkampfschaden
- normaler und erweiterter Projektilschaden
- Gebäudekachelschaden
- KI-Angriffsbewertung

Feuerprüfung umfasst nicht nur die exakte Zielkachel, sondern auch Einheiten und belegte Vanilla-Kacheln im gesamten Wirkungsradius. Dadurch kann Feuer auf neutralem oder drittem Boden nicht automatisch in einen geschützten Vertragspartner übergreifen.

### Bewusster Angriff

Autonome Zielwahl, Vergeltung und veraltete Angriffe werden blockiert. Ein unmittelbar durch den lokalen Spieler ausgewählter und per Maus erteilter Angriff wird anhand ausgewähltem Tribe, Hover-Ziel, Kachelkoordinaten und engem Tickfenster erkannt. Vor Freigabe dieses Befehls wird der Pakt genau einmal als heimtückischer Angriff beendet. `Unknown33` gilt ausdrücklich nicht als menschliche Autorisierung.

### Intimzone

Alle 32 Simulationsticks werden ausschließlich menschliche Kampfeinheiten geprüft. Zentrum ist die feste Vanilla-Burgtorposition jedes lebenden Mitglieds des Vertragspartners, nicht der bewegliche Lord.

- Radius: 18 lokale Kacheln
- substanziell: mindestens 8 Einheiten und Militärwert 250
- alternativ 12 Einheiten unabhängig vom Wert
- alternativ mindestens 4 schwere Einheiten zusammen mit Wert 600
- der Lord selbst wird nicht als Invasionsverband gezählt

Das Eindringen beendet Waffenruhe/Handel und alle offenen Gespräche sofort, auch ohne Schaden.

## 14. Gütertransaktionen

### Gegnerische Geschenke

Der ausgelieferte Vertrag hat `GeneratedDiplomacyContract.IsolatedCanary = false`. Deshalb wird für Gegner **nie** auf Crusaders unsicheren nativen `Ally_SendGoods`-Pfad zurückgefallen. Gegnerische Sendungen verwenden einen direkten, zweiseitig geprüften Transfer.

### Verbündete Geschenke

Bei Verbündeten wird zunächst der Vanilla-Pfad verwendet, damit Bedienung und Rückmeldungen Vanilla bleiben. Der mutable native Rückgabewert ist nicht die Commit-Autorität; maßgeblich ist die exakte Lagerbilanz vorher/nachher. Schlägt dieser Pfad nachweisbar fehl, rollt V2 zurück und verwendet den direkten atomaren Ersatzpfad.

### Ein-Klick-Forderungspaket

`FulfillV2DemandPackage()`:

1. liest alle offenen Zeilen und beide Lagerseiten vorab,
2. lehnt bei fehlender Menge oder Überlauf ab, ohne etwas zu verändern,
3. erzeugt Memento und stabilen Save-Snapshot,
4. bucht jede Ware bzw. Gold zweiseitig mit exaktem Readback,
5. verbucht erst danach die politischen Lieferungen,
6. rollt bei jedem Fehler alle Inventare rückwärts und den vollständigen verwalteten Zustand zurück,
7. sperrt weitere Transfers für die Partie, wenn eine Inventarrücknahme nicht bewiesen werden kann.

Die UI zeigt bis zu drei Warenzeilen mit Soll, geliefert, offen und eigenem Lagerbestand. Dieselbe Primärschaltfläche erfüllt Einzel- und Mehrfachforderungen vollständig.

## 15. Teamtransaktionen und Crash-Journale

Native Teamänderungen sind keine einfachen Einzelwrites. Unterstützte Journale:

- `FormAlliance`
- `AiBreak`
- `PlayerBreakAll`
- V2-only `PlayerBreakOne`

Jede Änderung besitzt erwartete und Zielpartition, Session-Generation, Fingerprint und persistierbares Journal. Die Partie wird während kritischer Teamwrites lokal pausiert. Erst nach vollständigem Write- und Readback-Erfolg wird der politische Zustand committet. Danach bleibt eine zusätzliche Verifikationspartition aktiv, bis die Native-Seite stabil bestätigt ist.

Während Übergängen schützt eine Vereinigungsmenge aus alter und neuer Allianzbeziehung vor Friendly Fire und falschem Game-over. Beim Fehler wird ausschließlich eigener, exakt nachweisbarer Teambesitz zurückgerollt. Fremde gleichzeitige Änderungen werden nicht überschrieben.

`PlayerBreakOne` trennt nur die ausgewählte Koalition. V1 kennt diesen Journaltyp nicht; die fortlaufende V1-Projektion hält während dieses kurzen Fensters deshalb den letzten vollständig committeten Bündnisstand.

## 16. Save/Load, Migration und Rückfall

### Primärer V2-Stand

- Identifier: `StrongholdEuropeDE.Diplomacy.v2`
- Magic: `SEDE-DIP-V2\0`
- aktuelles Envelope-Schema: 3
- minimal lesbares Envelope-Schema: 2
- maximale Größe: 128 KiB
- Integrität: SHA-256 über den kanonischen Inhalt, Trailer-Magic `SHA2`

Das Envelope enthält den unveränderten, bereits validierten V1-Basispayload plus die nach Koalitions-ID gebundene V2-Erweiterung. Team- und Transferjournale behalten dadurch die getestete V1-Recovery-Semantik.

Schema 2 wird beim Lesen deterministisch auf Schema 3 ergänzt. Dabei werden Mindesthistorie, Verlässlichkeit, Bruchpunkte, Vertrauensobergrenze, strategische Werte, Geschenkgedächtnis und erfüllte Abschlussbedingungen aus den vorhandenen Schema-2-Fakten rekonstruiert.

### Automatische V1-Übernahme

V2 registriert gleichzeitig den alten Identifier `StrongholdEuropeDE.Diplomacy.v1`. Existiert kein primärer V2-Stand, wird der echte V1-Payload validiert, migriert, an die heute geladenen AIC-Persönlichkeitssignale gebunden und als V2-Zustand fortgeführt.

### Korruptionsrückfall

Existieren primärer V2- und V1-Rückfallstand, wird V2 zuerst rein lesend vorvalidiert. Ist dessen Format, Checksumme oder Semantik beschädigt, wird vor jeder nativen Teamrestauration der V1-Stand validiert, migriert und nochmals als V2 gelesen. Sind beide beschädigt, wird nichts halb restauriert.

### Fortlaufende V1-Projektion

Bei jedem Save schreibt V2 zusätzlich einen echten, von einer separat ohne `DIPLOMACY_V2` kompilierten V1-Assembly lesbaren Rückfallstand. Er bewahrt:

- Koalitionen und Lagerpreisvertrag
- aktuelle Teamaufteilung und unterstützte Journale
- laufenden Einzel-/Mehrfachfortschritt für Abschluss- und Bündnishilfeforderungen
- Allianzstatus und V1-repräsentierbare Sperren

Bewusst semantisch verlustbehaftet:

- Waffenruhe und Handelsabkommen besitzen in V1 keinen eigenen Zustand.
- V2-Persönlichkeiten, strategische Größen und permanente Historie existieren in V1 nicht.
- Ein dauerhaft ausgeschlossenes Bündnis wird beim Downgrade konservativ als höchstens 25 % Goodwill plus maximaler V1-Sperre projiziert. Nach längerem Weiterbetrieb ausschließlich unter V1 kann diese dauerhafte V2-Semantik nicht erhalten bleiben.
- `PlayerBreakOne` kann V1 nicht fortsetzen und wird wie oben beschrieben auf den letzten committeten Stand projiziert.

Der V2-Stand bleibt daher die autoritative Sicherung. Der V1-Slot ist ein echter Notfall-/Downgradepfad, aber kein verlustfreier Ersatz für V2.

## 17. Vanilla-HUD und Crusader-Kompatibilität

Das V1-Basispatch bleibt byteidentisch:

- V1-Patch SHA-256: `96407537a90b430a68bdf0eaa54a3e50414fdb6602ea4d9212ef75bd777e8203`

Der Builder fügt nur das V2-Fragment hinzu. Das fertige HUD:

- Größe: 24.546 Byte
- SHA-256: `e44abdbba2eac81fd39299736c223490a4a5cb574d3478cf5d38a0a0f222ef4c`
- Wurzelhöhe: 450
- Detailpanel: links 20, oben 150, Breite 660, Höhe 286, Unterkante 436
- vier Vanilla-Schaltflächen: Primäraktion, Senden, Befehle, Beenden
- 29 zwingend benötigte V2-Steuerelemente
- graceful fallback: Fehlt eines, bleibt das native Detail sichtbar und V2 protokolliert einmalig die unvollständige UI, statt eine halbe Oberfläche zu erzwingen.

Verwendet werden ausschließlich bestätigte Vanilla-Ressourcen:

- `BDR_SH1DEe`
- `BTN_SH_Plain`
- `Panel_Divider`
- `UI-Buttons C001` bis `C004`
- `booleanToVisibilityConverter`

Keine externen Texturen oder Europe-/Origins-Ressourcen werden geladen.

Bestätigte Crusader-DE-/SHCDESE-Dateien:

| Datei | Größe | SHA-256 |
|---|---:|---|
| `000shcdese/Override/.../HUD_AlliesPanel.xaml` | 84.163 | `6c927ac4a28fa181b06ef2327c7a084de5c828cc0e4f4a4de46a42dbb40ed0d6` |
| `000shcdese/Override/.../UI-MasterAtlas.xaml` | 258.119 | `b4092a81bdef00449f65b37d3988c432c1862f409d085ff84c039a71007cfb88` |
| `000shcdese/Override/.../BTN_SH_Plain.xaml` | 4.827 | `b2b074a8c4cb4c0f6e69e48f067bcecab50860e6aa3b66298c0f27555f7c51e0` |

Der Installer prüft diese drei Dateien in der konkreten Zielinstallation vor dem Austausch und lehnt außerdem jeden fremden `Patches/.../HUD_AlliesPanel.xaml` ab. Das vorhandene V2-Ziel ist dabei als zu ersetzende Version ausgenommen.

### Sprachumfang

Die neuen qualitativen Texte sind vollständig auf Deutsch und Englisch gepflegt. In anderen Vanilla-Sprachen fällt neuer V2-Text derzeit auf Englisch zurück; originale Waren- und Herrschernamen kommen weiterhin aus Vanillas Übersetzungssystem. Vor einer breiten Multi20-Veröffentlichung ist zu entscheiden, ob 18 zusätzliche Übersetzungen geliefert werden sollen.

## 18. Zwingende In-Game-Abnahme vor öffentlicher Freigabe

Jeden Punkt mit Spielstand, Uhrzeit, Build-Hash und relevantem Logausschnitt protokollieren:

1. Kaltstart auf exakt SHC:DE 2.80 / SHCDESE 1.44; genau ein V2-Plugin und V2-Capability-Log, kein fälschliches V1-Loaded-Log.
2. Neue Vanilla-Skirmish-Partie ohne Europe und ohne Origins.
3. Dieselbe Prüfung mit aktivem Europe-Grafikmod (`diplomacy: false`) und mit Origins.
4. Laden eines echten V1-Spielstands; Werte, Forderungsfortschritt, Teams und anschließendes erneutes Speichern prüfen.
5. Laden eines V2.0-/Schema-2-Spielstands.
6. V2 speichern/laden in jeder Stufe: ohne Pakt, Waffenruhe, Handel, offene Mehrfachforderung, bündnisbereit, Bündnis, Hilfe, Ultimatum, Wiedergutmachung.
7. Primären V2-Payload kontrolliert beschädigen und nachweisen, dass der fortlaufende V1-Slot übernimmt; niemals an einem einzigen ungesicherten Nutzersave testen.
8. Einzelforderung per Primärschaltfläche; exakter Abzug/Gutschrift und nur einmalige politische Verbuchung.
9. Drei-Waren-Forderung inklusive Gold per Primärschaltfläche; vollständige Atomizität.
10. Fehlende Ware in einem Mehrfachpaket; keinerlei Teilabbuchung.
11. Verbündetengeschenk über Vanilla-Pfad und – mit kontrolliert provoziertem Native-Fehler – direkter Fallback.
12. Waffenruhe: beide Seiten stellen automatische Angriffe, Beschuss, Vergeltung und Belagerungsziele ein.
13. Dieselbe Waffenruhe mit mindestens einem bestehenden KI-Verbündeten: Schutz muss in allen Richtungen für den vollständigen Spielerblock gelten.
14. Flächenfeuer auf neutraler und dritter Kachel neben geschützter Einheit sowie neben geschütztem Gebäude/Grundstück; kein Brand-/Schadensübergriff.
15. Bewusst erteilter direkter Angriff: Pakt endet genau einmal, Angriff wird danach ausgeführt, dauerhafte Historie steigt genau einmal.
16. Acht leichte bzw. vier schwere Truppen in 18-Kachel-Burgtorzone; Pakt/Gespräche enden ohne vorherigen Schaden. Kleine Eskorte darf den Pakt nicht brechen.
17. Friedliches Auslaufen von Waffenruhe und Handel nach den langen Profilfristen.
18. Vollständige Leiter bis zum Bündnis; letzter feindlicher Verbund darf nicht verbündet werden.
19. Pflegeguthaben durch proaktive Hilfe, spätere Unterstützungsforderung, Ultimatum und KI-Auflösung bei zweitem Versäumnis.
20. Gezielte aktive Aufkündigung genau eines Bündnisses; andere Bündnisse bleiben, alle gegnerischen Beobachter werden misstrauischer.
21. Save/Load unmittelbar vor, während und nach Teamänderungen und Gütertransfers; hierzu Kopien verwenden und keinen Prozess hart beenden, solange kein gesonderter Crash-Test vorgesehen ist.
22. UI bei jeder vom Spiel angebotenen UI-Skalierung/Auflösung sowie Deutsch, Englisch und mindestens einer Fallback-Sprache prüfen: keine Überlagerung, abgeschnittene Bedienaktion oder unsichtbare native Rückfalloberfläche.
23. Kartenende, Zurück ins Menü und neue Partie: saubere Teamrücknahme, keine falsche `fail_closed`-Meldung beim normalen Teardown.

## 19. Automatisierter Prüfstand

### Python-Verträge

Aktueller Stand:

- 23/23 fokussierte V2-/Standalone-Prüfungen bestanden.
- 66/66 kombinierte Diplomatieprüfungen bestanden, wenn der sachfremde bekannte Fortifikations-Rollout-Test abgewählt wird.

Bekannter, nicht von diesem Plugin verursachter Testfehler:

- `test_diplomacy_rules_and_rollout_are_pinned_to_declared_canaries_and_bc7_production`
- Ursache: `europe-bc7-fort-diplomacy-canary` fehlt in der sachfremden `_DIPLOMACY_ROLLOUT_PROFILE_IDS`-Konfiguration.
- Für diese Arbeit bewusst nicht geändert.

### C#-Modelltests

44 aufgerufene Tests decken unter anderem ab:

- alle sieben Persönlichkeitssignale
- situative und abnehmende Geschenkbewertung
- komplette Leiter und Sperrzeiten
- letzter feindlicher Verbund
- alle Vertragsbrucharten
- globale Verratsbeobachtung
- Pflege/Hilfe/Ultimatum
- persistente und dauerhafte Historie
- Schema-3-Roundtrip/Checksumme
- Schema-2-Upgrade
- V1-Migrationsvarianten
- beschädigter V2-Primärstand mit V1-Rückfall
- V1-Projektion einschließlich permanenter Bündnissperre
- 1.500 Tage Stress für jedes der sieben Profile mit mindestens 40 Save-Roundtrips je Profil, also mindestens 280 Roundtrips insgesamt

### Echte V1-Leserprüfung

Der V2-Test erzeugt per `--emit-v1-fallback` einen Binärpayload. Ein separates Projekt wird **ohne** `DIPLOMACY_V2` kompiliert und lädt/validiert diesen Payload mit der echten V1-Codec-Semantik. Die finale Prüfung akzeptierte den 493-Byte-Payload mit SHA-256 `7d272e3dfd5c2e8bbd72dd44bc5134cebf6dbc5832c07e6423a7277932ec491f`.

### Reproduzierbarkeit

Zwei unmittelbar aufeinanderfolgende Builds ergaben byteidentische DLL-, HUD-, Info- und Manifestdateien.

## 20. Reproduzierbare Befehle

Arbeitsverzeichnis:

`E:\Stronghold Crusader Definitive Edition Baldwin and Bullseye MULTi20\SE144`

Python:

`..\StrongholdEuropeDE\.venv\Scripts\python.exe`

.NET SDK:

`work\toolchains\dotnet-10.0.301\dotnet.exe`

### Fokussierte Tests

```powershell
& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' -m pytest `
  tests/test_diplomacy_v2_plugin.py `
  tests/test_standalone_diplomacy_plugin.py -q
```

### Erweiterter Diplomatievertrag ohne bekannten Fremdfehler

```powershell
& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' -m pytest `
  tests/test_diplomacy_v2_plugin.py `
  tests/test_standalone_diplomacy_plugin.py `
  tests/test_diplomacy_contract.py -q `
  -k 'not diplomacy_rules_and_rollout_are_pinned_to_declared_canaries_and_bc7_production'
```

### C#-Build und Lauf

```powershell
$env:DOTNET_ROLL_FORWARD='Major'
& 'work/toolchains/dotnet-10.0.301/dotnet.exe' build `
  'runtime/StrongholdEuropeDiplomatieV2.Tests/StrongholdEuropeDiplomatieV2.Tests.csproj' `
  -c Release -warnaserror
& 'work/toolchains/dotnet-10.0.301/dotnet.exe' run `
  --project 'runtime/StrongholdEuropeDiplomatieV2.Tests/StrongholdEuropeDiplomatieV2.Tests.csproj' `
  -c Release --no-build
```

### Echter V1-Fallback-Leser

```powershell
$fixture = (Resolve-Path 'work/runtime-tests').Path + '\diplomacy-v1-fallback.fixture.bin'
& 'work/toolchains/dotnet-10.0.301/dotnet.exe' run `
  --project 'runtime/StrongholdEuropeDiplomatieV2.Tests/StrongholdEuropeDiplomatieV2.Tests.csproj' `
  -c Release --no-build -- --emit-v1-fallback $fixture
& 'work/toolchains/dotnet-10.0.301/dotnet.exe' build `
  'runtime/StrongholdEuropeDiplomatieV1Compatibility.Tests/StrongholdEuropeDiplomatieV1Compatibility.Tests.csproj' `
  -c Release -warnaserror
& 'work/toolchains/dotnet-10.0.301/dotnet.exe' run `
  --project 'runtime/StrongholdEuropeDiplomatieV1Compatibility.Tests/StrongholdEuropeDiplomatieV1Compatibility.Tests.csproj' `
  -c Release --no-build -- $fixture
```

### Paketbau

```powershell
$sdk = (Resolve-Path 'work/toolchains/dotnet-10.0.301').Path
$env:Path = $sdk + ';' + $env:Path
$env:DOTNET_ROLL_FORWARD='Major'
& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' `
  'runtime/StrongholdEuropeDiplomatieV2/bauen.py'
```

### Gesicherte Installation

```powershell
& '..\StrongholdEuropeDE\.venv\Scripts\python.exe' `
  'runtime/StrongholdEuropeDiplomatieV2/bauen.py' `
  --install 'D:\Games\Stronghold Crusader Definitive Edition COPY'
```

Der Installer:

1. verweigert Koexistenz mit dem alten V1-Ordner,
2. verweigert jeden fremden Allies-HUD-Patch,
3. prüft Engine und drei Vanilla-UI-Dateien,
4. prüft Paketidentität und alle Nutzdateihashes,
5. kopiert in einen Stagingordner,
6. verschiebt eine vorhandene V2 atomar nach `BepInEx/plugin-backups`, also außerhalb des aktiven Pluginbaums,
7. benennt Staging atomar in den Zielordner um,
8. restauriert bei einem Fehler vor Abschluss die alte V2.

## 21. Finaler Build vor Installation

| Datei | Größe | SHA-256 |
|---|---:|---|
| `build-manifest.json` | 5.090 | `a78223f579175167b4a08ca2409f9b0a6fca0a0ad2601cc38f2aae469b9556af` |
| `info.json` | 401 | `d90e68483045d7344302a9cc6e2276b5be4e401323b8b266ebbf0064af97c0a7` |
| `Patches/Assets/GUI/XAMLResources/HUD_AlliesPanel.xaml` | 24.546 | `e44abdbba2eac81fd39299736c223490a4a5cb574d3478cf5d38a0a0f222ef4c` |
| `StrongholdEuropeDiplomatieV2.dll` | 280.576 | `9d970e120bdb33b101e93a0a89fa255565ea871691d2d2ce73004116c5e7785f` |

Diese vier Dateien wurden beim transaktionalen Austausch bytegleich installiert; die Nachprüfung ist in Abschnitt 22 protokolliert.

## 22. COPY-Installation

Status: transaktionaler Austausch am 2026-09-06 erfolgreich abgeschlossen und anschließend byteweise verifiziert.

Vorprüfung der COPY-Installation:

- Spielprozess lief nicht.
- Engine-Hash und -Größe stimmen exakt.
- alle drei Vanilla-UI-Hashes stimmen exakt.
- kein alter V1-Pluginordner vorhanden.
- kein fremder `HUD_AlliesPanel`-Patch vorhanden; nur SHCDESE-Basis und die zu ersetzende alte V2.
- `StrongholdEuropeDE/build-manifest.json` enthält `diplomacy: false` und `diplomacy_rules: null`.
- weder Europe noch Origins enthalten den aktiven V1-Save-Identifier.

Installationsergebnis:

- Installationsziel: `D:\Games\Stronghold Crusader Definitive Edition COPY\BepInEx\plugins\StrongholdEuropeDiplomatieV2`
- Backup der vorherigen V2: `D:\Games\Stronghold Crusader Definitive Edition COPY\BepInEx\plugin-backups\StrongholdEuropeDiplomatieV2-pre-2.1.0-20260906T105519Z`
- Das Backup liegt außerhalb von `BepInEx/plugins` und wird daher nicht von BepInEx geladen.
- Alle vier installierten Dateien (`build-manifest.json`, `info.json`, DLL und HUD-XAML) stimmen in Größe und SHA-256 exakt mit Abschnitt 21 überein.
- Das Installationsverzeichnis enthält genau diese vier Paketdateien; `.StrongholdEuropeDiplomatieV2.install` blieb nicht zurück.
- Im aktiven Plugin-Baum existieren genau zwei `HUD_AlliesPanel.xaml`: die SHCDESE-Basis und die neue V2-Ersetzung. Kein dritter/fremder Patch wurde gefunden.
- Nach dem Austausch lief weiterhin kein Stronghold-/Crusader-Prozess; eine Laufzeitbehauptung wird deshalb ausdrücklich erst nach Neustart und In-Game-Abnahme getroffen.

Beleg für die gesicherte vorherige V2:

| Datei | Größe | SHA-256 |
|---|---:|---|
| `build-manifest.json` | 1.682 | `986dfd10db9c1ed8bdef06e43820dd07da50093507849c7e3f4bda748525c1b6` |
| `info.json` | 360 | `54a954b21d17e20581b7f28dfe053e8f70f367e7b6e1f2736d3912147c74cbf8` |
| `Patches/Assets/GUI/XAMLResources/HUD_AlliesPanel.xaml` | 13.072 | `96407537a90b430a68bdf0eaa54a3e50414fdb6602ea4d9212ef75bd777e8203` |
| `StrongholdEuropeDiplomatieV2.dll` | 218.112 | `5f97d96e72bd5b11749125b024d8e73576ce5ab9fdd9800d17cdc7293044b573` |

## 23. Bekannte Grenzen und noch offene Release-Aufgaben

1. **Zwingend:** reale In-Game-Abnahme aus Abschnitt 18.
2. Die Engine ist nur `load_only`, nicht formal `measured` belegt.
3. Multiplayer/Koop und mehrere echte Menschen sind absichtlich nicht unterstützt; die Funktion bleibt dort inaktiv. Das muss in einer öffentlichen Beschreibung ausdrücklich stehen.
4. Neue Texte sind Deutsch/Englisch; weitere Multi20-Sprachen fallen auf Englisch zurück.
5. V1-Rückfall ist technisch echt und fortlaufend, kann V2-only Dauerhistorie aber prinzipbedingt nicht verlustfrei ausdrücken.
6. Plugin-Metadaten enthalten noch `Author: Private` und eine leere Website. Vor öffentlicher Veröffentlichung muss der Eigentümer die gewünschten Angaben festlegen.
7. Das enge Eingabe-/Tick-Matching für bewusstes Angreifen ist absichtlich konservativ und muss im Spiel für Einheit, Gebäude, Mauer und Bodenziel getestet werden.
8. UI muss auf allen tatsächlich angebotenen Skalierungen visuell abgenommen werden; XML- und Ressourcenverträge ersetzen keine Pixelprüfung in Noesis.

## 24. Priorisierte Review-Anweisung für Claude

### Priorität 0: keine Daten-/Spielzustandskorruption

1. `FulfillV2DemandPackage`, `TryAtomicTransfer`, `CompleteVerifiedNativeTransfer`, `RestoreTransferAmounts`:
   - niemals politische Doppelverbuchung,
   - niemals einseitige Inventaränderung,
   - Gold und Waren gleich streng,
   - Memento und stabiler Save-Snapshot in richtiger Reihenfolge.
2. `ProcessPendingTeamTransition`, `CommitTransitionState`, `CommitV2PlayerBreakOne`, `DiplomacyTeamTransaction`:
   - Commit erst nach vollständigem Readback,
   - Rollback überschreibt keine fremde Änderung,
   - Game-over- und Kampfguard decken alte und neue Partition.
3. `DiplomacySaveV2Codec`:
   - alle Längen vor Allokation begrenzt,
   - Checksumme vor Semantik-/Native-Restore,
   - Koalitionsbindung eindeutig,
   - Schema-2-Upgrade erzeugt nur gültige Schema-3-Zustände,
   - V1-Projektion wird wirklich vom V1-Build akzeptiert.
4. Fehler-/Unloadpfad `DisableMap(..., expectedTeardown)`:
   - normaler Kartenabbau darf kein falsches Fail-Closed-Latch setzen,
   - ungeklärte Recovery darf Sicherheits-Hooks nicht freigeben.

### Priorität 1: Vertrags- und Kampflogik

1. `V2TreatyProtectsPlayers` und `V2IsLocalDiplomaticBlocPlayer` auf alle Richtungen und mehrere Verbündete prüfen.
2. Projektil-/Feuerpfade einschließlich neutraler/dritter Kacheln und belegter Kacheln im Radius prüfen.
3. `V2AuthorizeExplicitPlayerAttack` darf nur echte lokale Eingabe autorisieren und den Bruch genau einmal buchen.
4. Intimzoneneinheiten verwenden Weltkoordinaten; Burgtor kommt als lokale Kachel und wird exakt mit `×8 + 4` umgerechnet.
5. AI-Verbündete dürfen den Spieler nicht durch autonome Angriffe als Verräter markieren.

### Priorität 2: politische Erreichbarkeit und Balance

1. Für jedes Profil beweisen, dass eine unbeschädigte Beziehung jede Stufe erreichen kann.
2. Dauerhafte Sperren dürfen nur aus der dokumentierten Bruchhistorie entstehen, nicht versehentlich aus normalem Verfall.
3. Nach Paktablauf mit bereits erfüllten Abschlussbedingungen muss ein erneuter Weg möglich bleiben.
4. Der letzte feindliche Verbund darf nicht zum Bündnis werden, aber auch nicht in einer unbedienbaren Forderung hängen.
5. Unterstützungsfrequenz und Fristen gegen reale Spielgeschwindigkeit prüfen.

### Priorität 3: Vanilla-UI und Distribution

1. XAML gegen die drei gepinnten Crusader-/SHCDESE-Dateien und echte UI-Skalierungen prüfen.
2. Sicherstellen, dass kein Europe-/Origins-Schlüssel, keine externe Textur und kein zweiter Save-Handler benötigt wird.
3. Installer-Abbruch muss vor dem Verschieben der alten V2 erfolgen, wenn Engine/UI/Kollision/Manifest nicht stimmen.
4. Nach Austausch installierte Dateien byteweise mit `dist` vergleichen und sicherstellen, dass `.StrongholdEuropeDiplomatieV2.install` nicht zurückbleibt.

### Review-Ausgabe

Claude soll Findings nach Schweregrad mit Datei, Methode, konkretem reproduzierbarem Szenario und vorgeschlagener minimaler Korrektur ausgeben. Hypothetische Stilpräferenzen bitte von echten Zustands-, Kompatibilitäts- oder Release-Risiken trennen. Wenn kein Fehler gefunden wird, ausdrücklich die noch fehlende In-Game-Abnahme und die prinzipbedingte V1-Semantikreduktion nennen.
