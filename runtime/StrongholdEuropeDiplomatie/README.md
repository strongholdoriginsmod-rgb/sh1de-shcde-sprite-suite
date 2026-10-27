# Diplomatie als eigenständiges Plugin

Die Diplomatie V1.1 liegt seit dem 05.09.2026 als eigenes BepInEx-Plugin vor,
getrennt vom Europa-Mod.

## Stand V1.1

V1.1 härtet zuerst das vorhandene Grundgerüst, ohne seine Spielregeln zu
verändern:

* Eine Gütersendung gilt nur dann als erfolgt, wenn Absender und Empfänger noch
  im synchronen Ereignisrahmen exakt um die angeforderte Menge verändert wurden.
  Der unter Script Extender 1.44 falsche native Rückgabewert ist nur noch ein
  Diagnosehinweis und löst keinen falschen Rollback mehr aus.
* Ein mehrdeutiger oder fehlgeschlagener Gütertransport sperrt ausschließlich
  weitere Transporte. Beziehungen, Forderungen, Angebote und Bündnisse bleiben
  aktiv.
* Ungültige Sentinel-IDs werden vor Einheiten-, Gebäude-, Stamm- und
  Projektilzugriffen abgefangen.
* Besiegte Koalitionen werden nicht weiter täglich berechnet; unveränderte
  Koalitionswerte werden nicht mehr tausendfach protokolliert.
* Ein reguläres Beenden des Spiels wird als `shutdown` protokolliert und nicht
  mehr fälschlich als `failed_closed`.

Neue Beziehungsmodelle, Persönlichkeiten und Vertragsarten gehören in eine
separate Spielfunktionsfassung. So lässt sich erst die technische Korrektur und
danach jede neue Regel einzeln im Spiel abnehmen.

## Warum

Sie war in `StrongholdEuropeDE.Runtime.dll` **einkompiliert**
(`GeneratedDiplomacyContract.Enabled`, erzeugt aus dem Profilschlüssel
`runtime.diplomacy`). Am 05.09.2026 hat ein Neubau des Europa-Pakets — es ging
um die Zinnen-Verankerung, nicht um die Diplomatie — die diplomatiefähige DLL
mit einem Bau aus dem Profil `europe-bc7-fort-canary` (`"diplomacy": false`)
überschrieben. Die Diplomatie war damit weg, ohne dass an ihr etwas geändert
worden wäre, und ohne dass es jemandem auffiel: der HUD-Patch blieb liegen, nur
der Code dahinter fehlte.

Solange Code und Grafikpaket dasselbe Erzeugnis sind, kann das jederzeit wieder
passieren. Als eigenes Plugin hängt die Diplomatie an ihrem eigenen Ordner:
liegt er unter `BepInEx/plugins`, ist sie an.

## Wie herausgelöst

**Nicht durch Kopieren des Quelltexts.** Eine Kopie wäre ein Fork — zwei Stände
derselben 404 KB, die still auseinanderlaufen. Das Projekt hier verlinkt die
Quellen aus `runtime/StrongholdEuropeDE.Runtime` (`<Compile Include="..." />`)
und erzeugt daraus nur ein **zweites Erzeugnis**. Codex' Baum bleibt die
einzige Quelle; jede Korrektur dort landet beim nächsten Bau im Plugin.

Herausgelöst wird also auf der **Auslieferungsebene**:

| | Europa-Mod | Diplomatie-Plugin |
|---|---|---|
| Profil | `"diplomacy": false` | — |
| Diplomatie-Code | nein | ja |
| `HUD_AlliesPanel.xaml` | nein | ja |
| `HUD_Main.xaml` | ja | nein |

Genau eine Seite besitzt die Ansprüche. Das ist Bedingung, nicht Geschmack: der
Erweiterungswirt lässt je Haken und je Oberflächenelement genau einen
Eigentümer zu, und zwei Harmony-Wirte auf denselben Haken wären ein Doppelgriff.

## Was mitübersetzt wird

Gemessene transitive Hülle der vier `Diplomacy*.cs`: sie greifen aus dem
übrigen Laufzeitbaum auf **drei** Dinge zu — `ExtensionFeatureHost`,
`RuntimeSessionScopeDecision`, `Hashing`. Kein Asset-Stream, keine
UI-Textur-Bahn, kein Audio, keine Miliz, keine Festungen.

Dazu kommt die Fähigkeitsprüfung (`EuropeCapabilities`, `RuntimeBuildGuard`,
`RuntimeDecision`), damit ein fehlendes R3 die Diplomatie abschaltet statt das
Spiel zu zerlegen — dieselbe Fehler-zu-Bahn-Trennung wie im Europa-Plugin.

Ergebnis: 180 KB gegen 1,18 MB der Europa-Laufzeit.

## Bauen

```
python runtime/StrongholdEuropeDiplomatie/bauen.py
python runtime/StrongholdEuropeDiplomatie/bauen.py --install "D:/Games/…"
```

Voraussetzungen wie beim Europa-Bau: venv-Python und **genau** dotnet SDK
10.0.301 auf dem PATH. Das Skript

1. rechnet die V1-Regelwerte aus `profiles/diplomacy-v1-canary.json` gegen
   `runtime_build._DIPLOMACY_RULES_V1` gegen (zwei Quellen, ein Vergleich),
2. prüft deklariert-gegen-benutzt: jedes `GeneratedDiplomacyContract.X`, das
   der geteilte Quelltext benutzt, muss der erzeugte Vertrag führen,
3. übersetzt gegen die festgeschriebenen Voraussetzungen der Zielinstallation,
4. prüft den HUD-Patch gegen seinen festgeschriebenen Abzug,
5. weigert sich zu installieren, solange der Europa-Mod `HUD_AlliesPanel.xaml`
   noch selbst führt.

## Engine-Anmeldung — der eigentliche Blocker

`DiplomacyFeature.Prepare()` beglaubigt genau eine `CrusaderDE.dll`. Die
Konstante im geteilten Quelltext steht auf **2.7** (3.446.272 B), weil die
Funktion dort entwickelt wurde. Gemessen am 05.09.2026:

| Installation | Spielversion | CrusaderDE.dll |
|---|---|---|
| E:-Baum | 2.7 (5/5 Dateien passend) | 3.446.272 — die einkompilierte Zahl |
| COPY (D:) | **2.80** (5/5 passend) | 3.450.880 |
| Shadow (D:) | 2.80 | — |

Die vier `Diplomacy*.cs` wurden **byte-gleich** aus dem 2.7-Baum nach SE144
übernommen, samt 2.7-Anmeldung; beim Umzug auf 2.80 wurde sie nie nachgezogen.
Folge: die Diplomatie konnte mit der damaligen Europa-Runtime in der
COPY-Installation nicht aktiv werden — alle fünf damaligen Protokolle sagen
`status=inactive`, und ein Wiedereinspielen der alten DLL wäre an derselben
Prüfung gescheitert.

`engine-pins.json` führt deshalb die zugelassenen Engines mit Abzug und
Beleggrad. Der Bau nimmt den Eintrag zum Zielbau aus `supported-builds.json`,
schreibt Codex' Quelle **in `work/`** um (zwei Zeilen, Zeilenenden erhalten) und
übersetzt die Kopie. Codex' Datei bleibt unberührt. Eine nicht gelistete Engine
bricht den Bau ab — fail closed bleibt fail closed, die Entscheidung ist nur
nachlesbar geworden statt einer einzelnen Zahl im Quelltext.

`verification` sagt, worauf ein Eintrag sich stützt:

* `measured` — das Verhalten wurde auf dieser Engine gemessen (2.7).
* `load_only` — die formale Freigabe bleibt bis zur Abnahme des jeweils letzten
  korrigierten Baus eingeschränkt. Auf 2.80 sind inzwischen Start,
  Koalitionsbildung, Angebote, Bündnisse und native Lagerbewegungen beobachtet;
  die V1.1-Korrektur der Rückgabesemantik muss nach dem letzten Neubau noch im
  Spiel bestätigt werden. Grundlage: im Diplomatie-Code steht keine einzige
  rohe Engine-Adresse, jeder native Zugriff läuft über die typisierten
  Strukturen des Script Extenders 1.44.

`--install` prüft zusätzlich die Engine der Zielinstallation gegen das, was die
DLL beglaubigt, und verweigert bei Abweichung — sonst fiele der Unterschied
erst beim Spielstart auf.

## Spielstände

`SaveDataIdentifier` bleibt `StrongholdEuropeDE.Diplomacy.v1` — unverändert
gegenüber dem Europa-Bau. Ein neuer Name würde vorhandene Stände ihre
Diplomatie verlieren lassen, ohne dass jemand einen Fehler sieht.

## Abnahme im Spiel

Im BepInEx-Protokoll steht genau eine abschließende Zeile:

```
SEDE_RUNTIME_V1|lane=diplomacy|event=feature|status=active
```

`status=failed` nennt den Grund (`r3_unavailable`, `claim_registration:…`,
`startup_failure`, …). Bricht die Funktion später im Spiel ab, kommt einmalig
`status=failed_closed|reason=…`.

Für die V1.1-Transportabnahme wird zuerst einem Gegner ein Geschenk bis zum
Bündnis gemacht und danach dem tatsächlichen Verbündeten eine weitere Sendung
geschickt. Der Erfolgsbeleg lautet:

```
event=native_allied_confirmed|proof=post_inventory
event=transfer|status=confirmed|transport=native_allied
```

Dabei dürfen weder `native_allied_failed` noch Zugriffe auf die Sentinel-ID
`65534` auftreten. Beim normalen Beenden muss `event=shutdown` statt eines
`failed_closed` folgen.
