# Sonde 18: Festungsbau

Diese Quelle ist eine rein beobachtende Messsonde fuer SHCDE Script Extender
1.44.0. Sie misst, welche nativen logischen Zustaende die Mapper 25-27, 35, 46,
110, 140-147 und 181-186 beim manuellen Bauen wirklich erzeugen. Das automatische Urteil
deckt nur die logische Platzierung ab; Grafik, Pfad, Variantenkontext, getrennte
Schadensarten und Save-Persistenz bleiben ein manueller Teil des
Messprotokolls. Mapper 35 und die Treppen-Namensfamilie 181-186 bleiben
ausdruecklich nur Referenzwerte.

Die Sonde fuehrt keine Bauaktion aus, schaltet keine Mapper frei, veraendert
keine Kosten oder Trefferpunkte und registriert keine Save-Daten. In diesem
Repository wird sie nicht installiert. Das auslieferbare Ordnerpaket beginnt
bei `zzSonde18Festungsbau/`.

Die automatische Abdeckung zaehlt ausschliesslich Bauaktionen des lokalen
Spielers. Ereignisse anderer Spieler beziehungsweise der KI bleiben als
Rohdaten im Log, duerfen aber ein `URTEIL|` nicht vervollstaendigen.
Jede Ereignisart besitzt einen Ausgabedeckel. Auch die Deduplizierung und die
Menge spaeter fuer Damage-/Movement-Zuordnung beobachteter Kacheln sind hart
begrenzt; `WATCH_LIMIT|` und `watch_limit_reached=true` kennzeichnen das
Erreichen dieser Grenze.

## Start und Stopp

1. Fuer einen spaeteren, ausdruecklich freigegebenen Spiellauf den kompletten
   Ordner `zzSonde18Festungsbau` nach `BepInEx/plugins/` kopieren. Das hier
   erzeugte Quellpaket selbst bleibt unter `assets/lua/fortification-probe/`.
2. Exakt SHCDE-SE 1.44.0 verwenden. Die Sonde wartet bei einem neuen Spiel auf
   `Net_IsNetworkedEnvironmentAsync`. Nur das eindeutige Ergebnis `false`
   aktiviert sie; Mehrspieler und unbekannter Zustand bleiben inaktiv. Im
   Karteneditor aktiviert `mod_load(true)` die Sonde direkt.
3. Im Log auf folgende Zeile warten:

   ```text
   [SONDE18] CONTRACT|active=true|scope=singleplayer|...
   ```

   Im Editor steht `scope=editor`. Bei `active=false` darf der Lauf nicht als
   Messung gewertet werden.
4. Zum Stoppen die Karte verlassen oder neu laden. `mod_unload()` entfernt alle
   Abonnements und schreibt genau eine `SESSION_SUMMARY|`- und eine
   `URTEIL|`-Zeile. Die Sonde besitzt keine Taste.
5. Nach dem Lauf den Sondenordner wieder entfernen. Es gibt weder persistente
   Sondendaten noch eine Ruecknahme von Spielwerten, weil nie Spielwerte
   geschrieben werden.

## Verbindlicher Messablauf

Die gewuenschten Mapper muessen durch das Spiel, den Karteneditor oder einen
getrennten Menue-Prototyp erreichbar sein. Die Sonde selbst darf sie nicht
freischalten. Fuer jeden Mapper einzeln bauen und die Aktionsreihenfolge im
Testprotokoll notieren:

| Mapper | Name | Struct-Anker | Zweck |
|---:|---|---|---|
| 25 | `MAPPER_WALL` | - | normale Steinmauer |
| 26 | `MAPPER_CRENAL` | - | native Mauerzinnen; muessen erhalten bleiben |
| 27 | `MAPPER_STAIR` | `STRUCT_STAIRS` | native Treppe gegen fortifikationseigene Holztreppe `wooden_stairs` |
| 35 | `MAPPER_CRENAL2` | - | nur experimentelle Referenz |
| 46 | `MAPPER_WOODWALL` | - | nativer Holzwandweg |
| 110 | `MAPPER_TOWER1` | `STRUCT_TOWER1` | nativer Crusader-Wachturm gegen zusaetzliche Holzplattform `wooden_platform` |
| 140-143 | `MAPPER_GATE_WOOD1A` bis `1D` | - | vier Holztor-Ausrichtungen |
| 144-147 | `MAPPER_GATE_STONE1A` bis `2B` | - | Steintor-Gegenproben |
| 181-186 | `MAPPER_STAIR1` bis `MAPPER_STAIR6` | - | Treppen-Namensfamilie; nur Referenz, Orientierung und Bezug zu `wooden_stairs` ungeprueft |

### Pflichtvergleich fuer Treppe und Wachturm-Slot

Mapper 27 und 110 benennen jeweils nur den gemeinsamen nativen Bauweg. Die
EventArgs enthalten weder Varianten-ID noch Menueeintrag. Die Sonde kann daher
aus einem `BUILD|` allein nicht erkennen, ob der Tester den nativen Eintrag oder
die fortifikationseigene Variante gewaehlt hat. Variantenkontext, Auswahl und
Reihenfolge muessen im externen Testprotokoll stehen. `expected_struct=` ist nur
der am Dekompilat belegte Struct-Anker; `kind=wall` oder `kind=structure` ist der
tatsaechlich beobachtete Hookweg.

Zuerst einen Kontrolllauf **ohne Variantenkontext** ausfuehren: kein
Varianten-Menue, kein Menue-Prototyp und keine Variantenmechanik aktivieren. Auf
einer frischen Karte, ohne andere Zielbauten dazwischen, in genau dieser
Reihenfolge bauen und die `BUILD|op=`-Nummer notieren:

1. native Treppe (`MAPPER_STAIR`, `STRUCT_STAIRS`);
2. nativer Crusader-Wachturm (`MAPPER_TOWER1`, `STRUCT_TOWER1`).

Beide Ergebnisse muessen sichtbar und mechanisch nativ bleiben. Ohne
Variantenkontext duerfen weder die fortifikationseigene Holztreppe noch die
zusaetzliche Holzplattform erscheinen. Tritt doch eine Holzvariante auf, ist
der Kontrolllauf negativ und der Variantenvergleich darf nicht freigegeben
werden.

Danach einen getrennten Variantenlauf auf derselben Ausgangskarte mit dem
ausdruecklich dokumentierten Variantenkontext ausfuehren. Der Menue-Prototyp
muss native und fortifikationseigene Eintraege getrennt anbieten. Wieder ohne
andere Zielbauten dazwischen exakt diese Reihenfolge verwenden:

1. native Treppe;
2. fortifikationseigene Holztreppe `wooden_stairs` (`menu_order=80`, Basismapper 27);
3. nativer Crusader-Wachturm;
4. zusaetzliche Holzplattform `wooden_platform` (`menu_order=90`, Basismapper 110).

Fuer alle sechs Aktionen aus Kontroll- und Variantenlauf gehoeren gewaehlter
Menueeintrag, Variantenkontext, `BUILD|op=`, `kind=`, Tile-/Building-Diff,
Ressourcenwerte, Laufprobe und Screenshot in dieselbe Ergebnistabelle. Native
Treppe und nativer Wachturm muessen auch im Variantenlauf ihren Kontrollwerten
entsprechen. Fehlt der dokumentierte Kontext, ist die Reihenfolge unterbrochen
oder ist eine Auswahl nicht separat erreichbar, lautet das manuelle Urteil fuer
den betreffenden Vergleich `nicht_beobachtet`, nicht `negativ`.

Falls der Variantenlauf in `PLACEMENT_VALIDATION|` oder `BUILD|` einen Mapper
181-186 zeigt, muss der exakte Name als Referenzbefund erhalten bleiben; er darf
nicht automatisch in `wooden_stairs` umbenannt werden. Sind diese sechs Mapper
im Prototyp separat erreichbar, folgt erst nach den vier Pflichtaktionen ein
eigener Referenzblock in der Reihenfolge `MAPPER_STAIR1` bis `MAPPER_STAIR6`.
Diese Zusatzserie vervollstaendigt nur `observed_all`, nie das Primaerurteil.

Das externe Protokoll endet zwingend mit genau zwei Antwortzeilen:

```text
MANUELLES_URTEIL|vergleich=treppe|status=<bestaetigt/negativ/nicht_beobachtet>|kontrolllauf_nativ=<true/false>|variantenkontext=<dokumentiert/fehlend>
MANUELLES_URTEIL|vergleich=wachturm_slot|status=<bestaetigt/negativ/nicht_beobachtet>|kontrolllauf_nativ=<true/false>|variantenkontext=<dokumentiert/fehlend>
```

`bestaetigt` ist nur zulaessig, wenn beide Eintraege des Vergleichspaars in der
festen Reihenfolge separat gewaehlt und mit Log, Laufprobe und Screenshot
belegt wurden und der native Eintrag dem Kontrolllauf entspricht. `negativ`
bedeutet: beide Eintraege wurden gueltig beobachtet, aber die native Aktion
blieb nicht nativ oder die Holzvariante erzeugte nicht den vorgesehenen
unterscheidbaren Zustand. Bei fehlendem Kontext oder fehlender Beobachtung muss
`nicht_beobachtet` stehen.

Fuer die Linienmapper werden Laengen 1 bis 8, eine teilweise blockierte Linie
und ein Versuch ohne die benoetigte Ressource gebraucht. Dabei Stein und Holz
vor und nach jeder Aktion im HUD notieren. Die Sonde protokolliert
Ressourcenereignisse begrenzt auch ausserhalb eines Baufensters als
`mapper=unattributed`, ordnet aber nur jene `OnPlayerSubtractResource`-
Ereignisse fest zu, die synchron zwischen Pre und Post einer Ziel-Bauaktion
auftreten.

Danach fuer jeden tatsaechlich entstandenen Zustand:

- Enden, Ecke und T-Kreuzung bauen; bei Mapper 26 pruefen, dass die nativen
  Zinnen weiter als eigene Aktion funktionieren.
- Einheit ueber Mauer, Treppe und Tor schicken. `MOVEMENT_HIT|` ist ein
  positiver Beleg dafuer, dass eine Einheit nach einer lokalen Kachel- oder
  Unity-Z-Aenderung eine in dieser Sitzung veraenderte Kachel erreicht hat.
  Die Zeile nennt `local_coord`, `unity_coord`, `tile_changed` und `z_changed`.
  Die erste Position dient nur als Basis und wird nicht ausgegeben. Eine
  fehlende Zeile ist kein sicherer Negativbeleg. `unity_status=ok` ist fuer
  einen Z-Beleg erforderlich; der von der API bei fehlender Unity-Einheit
  gelieferte Nullvektor bleibt `zero_or_unavailable` und zaehlt nicht als
  Z-Aenderung. Der teurere Unity-Leser wird nur auf einer bereits beobachteten
  Zielkachel aufgerufen. `Tile_FindPath` wird bewusst nicht als Traversalbeleg
  verwendet.
- Holztore in allen vier Richtungen mit eigener und feindlicher Einheit testen.
  `GATE_QUERY|` belegt nur den nativen Torabfrageweg, nicht den sichtbaren
  Oeffnungszustand.
- Nahkampf, Pfeile, Feuer und Belagerung nacheinander und getrennt anwenden.
  Der jeweilige Angriff muss extern notiert werden, denn das EventArgs besitzt
  kein Feld fuer die Schadensart.
- Schaden reparieren, abreissen, speichern und neu laden. Der neue Lauf ist an
  `LIFECYCLE|entry=save_load` erkennbar. Vor und nach dem Laden die sichtbare
  Grafik, Laufebene, Schadensstufe, Besitzer und Trefferpunkte vergleichen.
- Vier Kamerarichtungen und abgeflachte Ansicht per Screenshot abnehmen. Diese
  Darstellung ist ueber die 1.44-Lua-API nicht lesbar.

## Auswertung

Alle Zeilen sind mit `[SONDE18] ` markiert und mit `|` maschinenlesbar:

- `BUILD|`: Phase, Spieler, Koordinaten, Mapper, `expected_struct` als
  Quellanker und native Zusatzfelder. Nur `kind=` belegt den Hookweg.
- `PLACEMENT_VALIDATION|`: begrenzte und deduplizierte Pre/Post-Eingaben des
  Platzierungs-Hooks. `custom_rules` und `force_block_override` sind nur rohe
  Override-Felder; `native_result=not_exposed` erfindet keine Entscheidung
  `erlaubt` oder `blockiert`.
- `TILE_DIFF|`: tatsaechliche Unterschiede aus den oeffentlichen Tile-Gettern;
  unter anderem Flags, Hoehe, Damage-State, Default-Hoehe beziehungsweise
  Tile-Gesundheit, Besitzer, Building-ID, Tile-Typ und die einfache
  Begehbarkeitsabfrage.
- `BUILDING_STATE|`: bei einem belegten Building-ID zusaetzlich Typ, Besitzer,
  aktuelle/maximale Gesundheit und belegte Kachelzahl.
- `RESOURCE_SUBTRACT|`: Pre/Post, Ware, Betrag und Lagerstand am Ereignis.
- `DAMAGE|`: Tile-Zustand rund um den Treffer; `damage_kind=not_exposed` ist
  absichtlich ehrlich.
- `MOVEMENT_HIT|`, `GATE_QUERY|`, `REPAIR|`, `REPAIR_COST|` und `BULLDOZE|`:
  Lauf-, Tor-, Reparatur- und Abrissbelege.
- `MAPPER_SUMMARY|`: feste Einzelbilanz fuer jeden der zwanzig Mapper.
- `SESSION_SUMMARY|`: Vollstaendigkeit der Sitzung. `observed_primary=13/13`
  schliesst Mapper 35 und 181-186 aus, `observed_all=20/20` schliesst sie ein.
  Beide Felder sowie `changed_primary` beziehen sich nur auf den lokalen Spieler;
  die Felder mit Suffix `_any_player` sind reine Diagnosewerte.
- `URTEIL|`: automatisches Urteil zur Datenvollstaendigkeit. Es setzt
  `mechanics_confirmed=false`, `variant_context=not_exposed`, beide
  Variantenvergleiche auf `manual_protocol_required` und
  `wood_gate_release=false`, bis Variantenkontext, Sichtpruefung, Laufweg,
  getrennte Schadensarten und Save/Load manuell bewertet wurden.

`placement_coverage_complete` bedeutet daher nur: alle dreizehn Zielmapper hatten
lokale Post-Ereignisse und vollstaendige logische Kacheldifferenzen. Es ist
keine Freigabe eines Holztors, keine Unterscheidung zwischen nativem und
fortifikationseigenem Menueeintrag und keine Aussage ueber die historische Grafik.
Die weiteren Statuswerte unterscheiden die fuer eine Messsitzung entscheidenden
Faelle:

- `inactive`: Die Sonde wurde nicht erfolgreich aktiviert; keine Messung.
- `nothing_observed`: Die Sonde war aktiv, sah aber keinen lokalen Bau eines
  der zwanzig beobachteten Mapper.
- `observed_inconclusive`: Ein lokaler Zielbau wurde gesehen, aber Pre/Post
  oder der Tile-Snapshot war unvollstaendig.
- `observed_negative`: Mindestens ein lokaler Zielbau hatte einen vollstaendigen
  Vorher/Nachher-Snapshot, aber keine logische Kachelaenderung.
- `partial`: Es gibt positive lokale Diffs, aber noch keine Vollabdeckung.

## Bewusste Abdeckungsgrenzen

- Der 1.44-Hook `OnBuildingTileTakeDamage` ist im Quellcode nur an einem
  Detour mit dem Namen `c_game_buildingtile_take_melee_damage` befestigt. Ob
  Pfeil-, Feuer- und Belagerungsschaden denselben nativen Weg erreichen, muss
  der Spiellauf zeigen.
- Das Damage-Event nennt keine Schadensart. `Unknown1`, `Unknown3` und
  `Unknown4` werden protokolliert, aber nicht geraten oder umbenannt.
- Die Tile-API nennt nach Save/Load keinen urspruenglichen Mapper. Darum ist
  die Mapperzuordnung nur fuer Kacheln und Gebaeude moeglich, die in derselben
  Sondensitzung als Diff beobachtet wurden. Spaetere Treffer bleiben korrekt
  als `unattributed` markiert.
- `Tile_IsWalkableAndUnoccupied` ist nicht identisch mit der Laufebene auf
  Mauern. Nur reale Bewegung plus Sichtpruefung kann Begehbarkeit und Hoehe
  bestaetigen.
- Sprite-Anschluss, Kamerarichtung, abgeflachte Darstellung, Toranimation und
  offener/geschlossener Torzustand besitzen keinen belegten Lua-Leser.
- Pre/Post-Snapshots sind synchron. Spaeter nachgelagerte reine
  Renderer-Aenderungen liegen ausserhalb der Messung.
- `OnPlacementValidation` liefert keinen nativen Rueckgabewert. Sein Post-Objekt
  wird aus den urspruenglichen Eingaben neu erzeugt. Die Sonde darf daraus kein
  `allowed`, `blocked` oder anderes Platzierungsurteil ableiten.
- Mapper 27 und 110 werden von nativer und fortifikationseigener Auswahl
  gemeinsam verwendet. Der Hook besitzt keinen Variantenkontext. Nur der oben
  festgelegte Kontroll-/Variantenlauf kann die beiden Auswahlen zuordnen; ein
  einzelnes Ereignis kann das nicht.
- `EngineInterface.StartMapperItem` und `PlaceMapperItem` sind nur C#-Methoden
  ohne Lua-Export. Der von der Engine zurueckgegebene beziehungsweise intern
  verwendete Mapper bleibt deshalb ein offener Messpunkt fuer einen spaeteren
  C#-Begleiter.
- Die Rohgrids fuer PillarGFX, ShowHi, MiscDisplay, PathConnection, Delay,
  Logic, WallOwner, Structure, Height, DefaultHeight, GFX, AlphaGFX,
  Construction, WallGFX, Noise, StructureWas und GatePath sind ebenfalls nur
  als C#-`Span` sichtbar. Die Lua-Sonde besitzt dafuer keinen belegten Leser und
  ruft auch keinen schreibenden Refresh als Ersatz auf.
- Ein geblockter Bauversuch darf ein Pre-Ereignis ohne Diff oder ohne Post
  auf einem Hook liefern, dessen 1.44-Detour `SkipOriginalFunction` wirklich
  auswertet. `OnBuildWall`, `OnBuildStructure` und
  `OnBuildingTileTakeDamage` werten dieses Feld dagegen nicht aus und liefern
  immer Post. Diese Unterschiede werden nicht vereinheitlicht oder geraten.

Die belegten 1.44-Namen und ihre Quellstellen stehen in
[`API-NACHWEIS-1.44.md`](API-NACHWEIS-1.44.md).

## Bedarf fuer den Lua-Pruefstand

Die bestehende Testwelt kennt Sonde 18 noch nicht. Fuer einen echten
Offline-Durchlauf braucht sie folgende ausschliesslich synthetische Attrappen:

- geboxte Enums `eEventHookPhase.Pre/Post`, alle zwanzig oben genannten
  `eMappers` und mindestens zwei `eGoods`;
- R3-Hooks fuer alle in `API-NACHWEIS-1.44.md` aufgezaehlten Namen, jeweils mit
  `Subscribe`/`Unsubscribe` und den dort genannten EventArgs-Feldern;
- der stark feuernde `OnPlacementValidation`-Hook mit wiederholten identischen
  Pre/Post-Eingaben, damit Deduplizierung und Deckel geprueft werden;
- eine Bauattrappe, die zwischen Build-Pre und Build-Post einen begrenzten
  Satz Tile-Werte aendert und innerhalb dieses Fensters Ressourcen-Pre/Post
  ausloest; Wall-, Structure- und Damage-Hooks muessen auch bei
  `SkipOriginalFunction=true` Post liefern, Ressourcen-, Repair- und
  Movement-Hooks dagegen nicht;
- Tile-Leser mit den Signaturen `(x, y)`, `(tileId)` sowie eine echte
  `int[]`-artige Sammlung mit `.Length` fuer
  `Building_GetOccupiedTileIds`;
- Building-Leser fuer Typ, Besitzer, Gesundheit, Startkachel, Rastergroesse
  und belegte Kacheln;
- Player-Leser `(playerId, good)`, `Player_GetLocalId()` und
  `Player_GetCurrentMapName()`;
- Unit-Leser, wobei `Unit_GetLocalPosition(unitId)` ein Objekt mit `.X` und
  `.Y` und `Unit_GetUnityPosition(unitId)` ein Objekt mit `.X`, `.Y`, `.Z`
  liefert; eine Sequenz muss Stillstand, Kachelwechsel und reine Z-Aenderung
  getrennt abdecken;
- `Net_IsNetworkedEnvironmentAsync(callback)` in drei Szenarien:
  `false`, `true` und kein Rueckruf. Nur das erste darf in Einzelspieler
  aktivieren; `mod_load(true)` deckt den Editor separat ab;
- mindestens je ein Damage-, Gate-Query-, Reparatur-, Bewegungs- und
  Abrissereignis, dazu ein absichtlich doppeltes Gate-/Movement-Ereignis fuer
  den Deduplizierungsnachweis und mehr als ein kleines Testlimit fuer den
  Protokolldeckel.

Der Pruefstand soll zusaetzlich vor und nach jedem Lauf alle synthetischen
Weltwerte vergleichen. Jede Differenz waere ein Vertragsbruch der
Nur-Lese-Sonde. Ein gruener Offline-Lauf darf weiterhin keine Aussage ueber
native Grafik, Pfadfindung oder Schadenstransport treffen.
