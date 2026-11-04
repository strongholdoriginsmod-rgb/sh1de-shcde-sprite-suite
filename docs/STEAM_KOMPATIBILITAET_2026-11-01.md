# SpriteSuite – Steam-Build-Kompatibilität und Grafikmapping (1. November 2026)

**Arbeitszweig:** `feature/steam-build-compatibility-20261101`.
**Basis:** `39d076826e9d06381c98d605528d3c66fae8404e`.
**Sicherheitsmodell:** Neues freies Projektverzeichnis; keine Änderungen am Steam-Spiel, an SH1DE, der alten Suite, an gespeicherten Modinstallationen oder an GitHub `main`.

## 1. Tatsächlich geprüfter aktueller Steam-Build

- Steam AppID **3024040**, Stronghold Crusader: Definitive Edition.
- Lokal installierter Steam-Build **24816905**; Steam-Appmanifest `buildid == TargetBuildID`, `StateFlags == 4`.
- Referenzordner: `lokale Steam-Bibliothek / steamapps / common / Stronghold Crusader Definitive Edition`.
- Fünf kanonische Spieldateien per SHA-256 attestiert, neu berechnete Zielkennung:
  `installed-target-ac847c12ce18463f69f018852d312824bd902ab8e46f8011380936ce34f46286`.
- Vorheriges Target 2.80 entspricht **nicht** dieser vollständigen Fünf-Datei-Kennung: vier Dateihashes unterschiedlich; die eigentliche Sprite-/Texture2D-/Audio-Geometrie wird dadurch jedoch nicht automatisch geändert.
- Aktuelle Steam-Installation besitzt **keinen Script Extender/BepInEx**; kein Ingame- oder Noesis-Interaktionsnachweis.
- „Neueste“ meint die zur Prüfung aktuell lokal installierte Steam-Version – nicht eine unabhängig über Steam-Server nachgewiesene weltweit neueste Build-Version.

## 2. Stärkster möglicher Beleg der Grafikgleichheit ohne Spielmodifikation

`tools/steam_reimport_target.py` hat `resources.assets` aus dem aktuellen Steam-Spiel innerhalb etwa 16 Sekunden neu katalogisiert:

| Objekte | Neu im Steam-Inventar |
|---|---:|
| Unity-Sprite-Records | 135.354 |
| Texture2D-Records | 41 |
| AudioClip-Records | 1.038 |

`tools/steam_sprite_compat_diff.py` hat danach **alle** diese Metadaten-Datensätze mit dem alten 2.80-Inventar verglichen: **0 hinzugefügt, 0 entfernt, 0 geändert**. Die externe Bild-/Audio-Ressourcendatei `resources.assets.resS` ist SHA-256-identisch.

`tools/steam_serialized_graphics_compare.py` hat darüber hinaus die **serialisierten Rohbytes aller 135.354 Sprite-, 41 Texture2D- und 1.038 AudioClip-Objekte** mit dem alten, separat als Original-2.80-Build nachgewiesenen Spiel verglichen. **Alle Objekt-Rohhashes sind identisch**, auch die drei inline gespeicherten Texturobjekte; die 38 externen Texturen liegen im identischen `.resS`-Strom.

Damit sind die Sprite- und Textur-Daten der untersuchten Unity-`resources.assets` zwischen diesen beiden Builds **bytegleich**. **Nicht** nachgewiesen ist, dass andere Unity-Assets, Script-Extender-Hooks, nativer Render-Code oder Noesis-ViewModel-Bindings gleich geblieben sind.

## 3. Wiederverwendetes Mapping mit unabhängiger Quell-/Zielprüfung

- Die alte, benutzerbearbeitete Mapping-Datei wurde unverändert und per SHA gesichert.
- Jeder der **135.354** alten Zielsprites wurde mit Name, PathID, Texture, Abmessungen, Position, Pivot und Pixel-Einheiten im Steam-Target verglichen: **keine Abweichung**.
- Die alte SH1DE-Quelle lag in einer privaten QA-Installation und wurde gegen die fünf originalen SH1DE-Referenzdateien gelesen. Alle fünf stimmen mit dem zugelassenen Build `local-sh1de-unity-2021.3.27f1-2025-01-20` überein.
- `tools/steam_mapping_rebase_preview.py` erzeugt erst nach vollständiger Grafikgleichheitsprüfung eine separate Kandidatendatei und einen unabhängigen Hash-Nachweis.
- `tools/steam_mapping_promote.py` prüft **beide Spiele erneut**, vergleicht die gesamte Kandidatendatei mit dem unveränderten alten Mapping (bis auf Build-ID und Zeitstempel), verifiziert Rohgrafiken nochmals und kopiert Kandidat samt Nachweis **nur** in den neuen QA-Arbeitsordner.
- In dieser Entwicklungsrunde war die Migration erfolgreich. Aktuelles getrenntes QA-Mapping:
  `work/mapping/proposals.json.gz`
  im Worktree `separaten, nicht ausgelieferten Steam-QA-Worktree`.
- Die regulären Prüfungen `target_selection_guard.verify_target` und `stronghold_europe_de.builds.verify_supported_builds` akzeptieren dort Quelle und Steam-Ziel **ohne Änderung historischer Referenz-IDs oder Abschaltung der SHA-Pins**.
- **Kein produktives Installationsziel wurde aktiviert.** Es gibt keine neue `installations.local.toml` oder `config/ziele.json` für Steam, keine Modinstallation und keine Änderungen in den vorhandenen Spielordnern.

## 4. Neue nutzerfreundliche versionsneutrale Diagnostik

**`tools/suite_steam_compatibility.py`** erkennt Steam unter Windows über die registrierte Steam-Bibliothek und `libraryfolders.vdf`. Anders als ältere fest codierte Spieleversionen wird bei jedem Lauf der aktuelle lokal installierte Build mit fünf Dateihashes bestimmt.

Unabhängig und einzeln angezeigt werden:

- Installation aktuell und vollständig / Steam-Update noch ausstehend;
- Originalkarten-/Unity-Kataloglesung möglich;
- SHA-gebundene Zielinventar-Prüfung;
- Sprite-Mapping exakt für diesen Build oder veraltet;
- originale native DLL/Managed-Assembly passen zu den bislang bestätigten ABI-Hashes oder nicht;
- Script Extender vorhanden oder fehlend;
- ausdrücklich offene Noesis-/Ingame-Freigabe und Modinstallation.

**Neue Schaltfläche in der Suite-Startseite:** `Steam-Version prüfen`. Die Diagnose läuft über den normalen Hintergrund-Runner, **nicht** im GUI-Thread; sie verändert weder Steam noch Projektdaten.

Beispiele nach dem Entpacken des Quellcodes aus einer neuen, sicheren Projektkopie:

```powershell
python tools/suite_steam_compatibility.py --project .
python tools/suite_steam_compatibility.py --project . --mapping work/mapping/proposals.json.gz
```

## 5. Grenzen: Grafikgleichheit ≠ nativer oder Ingame-Freibrief

Die Steam-`CrusaderDE.dll` besitzt weiter 77 alte Symbolnamen, aber **eine andere SHA-256-Summe** als die alte verifizierte Binärdatei. Die verwaltete `Assembly-CSharp.dll` ist ebenfalls verändert. Ohne unabhängige neue ABI-Attestierung dürfen diese DLLs nicht mit den alten Ctypes-Signaturen oder Puffern als „kompatibel“ aufgerufen werden.

Die Steam-Originalinstallation ist absichtlich modfrei; für Noesis und einen installierbaren StrongholdEuropeDE-Mod sind eine separate autorisierte **QA-Spielkopie**, eine zur aktuellen Steam-Version passende Script-Extender-Version und reale Spielabnahme nötig.

Die 152 auf den aktuellen Steam-Karten bestandenen Tests und fünf gezielten Steam-Basisprüfungen sind in der vorausgehenden **Steam-Referenz-QA vom 1. November** dokumentiert. Sechs native Engine-Snapshot-Tests wurden als tatsächlich unbestätigt erfasst; die Sperre bleibt bestehen.

## 6. Freigabestufen

| Funktion | Status |
|---|---|
| Aktuelle Steam-Build-ID erkennen | Verifiziert |
| Aktuelle Originalkarten lesen und in der Sandbox offline auswerten | Steam-QA bestanden |
| Aktuellen Unity-Sprite-Katalog importieren | Verifiziert |
| Grafik-Rohdatengleichheit zum alten 2.80-Build | Verifiziert für Sprite/Texture2D/Audio |
| Vorhandene 135.354 Sprite-Zuordnungen auf Steam-Build neu pinnen | Im isolierten QA-Arbeitsprojekt verifiziert |
| SH1DE-Spenderbuild mit Original-SHA prüfen | Verifiziert |
| Quell-/Ziel-Build-Verträge gemeinsam prüfen | Verifiziert |
| Nativen Engine-Snapshot auf geänderten DLLs ausführen | **Blockiert bis unabhängige ABI-Prüfung** |
| Noesis-Script-Extender/Mod im Spiel installieren und freigeben | **Nicht getestet / modfreie Steam-Installation** |
| Öffentliche GitHub-Stable-Freigabe, zweiter PC, Lizenzreview | Separate ausstehende Gate-Schritte |

Diese Untersuchung **maximiert die unterstützte Grafikdaten-Kompatibilität**, ohne eine falsch gepinnte native Spiel-Engine oder eine Installation in der persönlichen Steam-Bibliothek zu riskieren.
