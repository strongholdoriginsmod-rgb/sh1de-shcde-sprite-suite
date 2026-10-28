# Script Extender und versionsneutrale Grafikpakete

Die Sprite Suite arbeitet mit dem **bereits vorhandenen Script Extender**.
Die Oberfläche enthält keinen separaten Script-Extender-Versionschecker
und installiert oder aktualisiert den Extender nicht.

## HUD/GUI ohne versionsgebundene Runtime-DLL

Für statische Änderungen ist ein **Asset-Mod mit `Manifest: 0`**
vorgesehen. Die Paketstruktur ist in den Upstream-Leitfäden dokumentiert:

- `Override/Assets/GUI/Images/*.png` für UI-Bilder
- `Override/Assets/GUI/Sprites/*.png` für UI-Atlanten
- `Override/Sprites/*.png` für einzelne Sprites und `_m.png`-Masken
- `Override/Atlas/...` für unterstützte Sprite-Atlanten
- `Patches/Assets/GUI/.../*.xaml` für statische XPath-Operationen

Zunächst im **SH1 HUD-Studio** oder **ORIGINS Grafiken** die Originale
bearbeiten, dann Änderungen getrennt unter `work/` ablegen und in
`Override/` oder `Patches/` einordnen.

Der Builder **Editor & Austausch → DLL-freies Asset-Modpaket bauen**
führt keine SE-Versionserkennung durch, setzt weder eine Mindest-
noch eine Höchstversion in `info.json` und liefert Modverzeichnis plus ZIP:

```powershell
.venv/Scripts/python.exe tools/se_asset_package.py --source work/meine-hud-aenderungen --guid europehud --name "Europa-HUD"
```

Die Quelle enthält zum Beispiel
`work/meine-hud-aenderungen/Override/Assets/GUI/Images/HudBild.png`
oder `work/meine-hud-aenderungen/Patches/Assets/GUI/XAMLResources/HUD_Main.xaml`.
Die Ausgabe entsteht ausschließlich unter `work/se-asset-mods/`.
**Das Spiel und der vorhandene Script Extender bleiben unverändert.**

`Manifest: 0` vermeidet die Binärabhängigkeit einer eigenen C#-DLL,
garantiert aber **keine identische Asset-/XAML-API in jeder
historischen und zukünftigen SE-Version**. Sprite-Atlas-Unterstützung,
BC7, Shader und Noesis-Patching können sich unterscheiden.

## Optionale C#-Runtime

Die historische Stronghold-Europe-/Origins-C#-Runtime bleibt im
aktuellen Quellstand auf bestimmte SHCDE-SE-2.11-DLLs, MVIDs,
Game-Assembly-Identitäten und native API-Layouts ausgelegt.
Ein DLL-freies Asset-Mod braucht diese Komponenten **nicht**.
Eine C#-Runtime mit abweichendem SE darf erst nach Neubau und
nachgewiesener API-/ABI-Kompatibilität freigegeben werden.
Das Entfernen dieses internen Schutzes könnte Abstürze oder
beschädigte Spielstände verursachen.

Historische SE-Installationsskripte bleiben nur für dokumentierte
Altstände und Rücknahme im Quellcode, sind aber **nicht mehr in der
Universal-Suite-Oberfläche aufrufbar** und dürfen keine neuere
oder fremde SE-DLL überschreiben.

Quellen:
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/mod-types.html
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/asset-api.html
- https://rawra-stronghold-crusader.gitlab.io/shcde-script-extender/docs/guides/xaml-api.html
