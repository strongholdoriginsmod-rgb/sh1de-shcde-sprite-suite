# SH1DE → SHCDE Universal Suite 2.0 (Stronghold Europe / ORIGINS)

Transfer graphics from **Stronghold: Definitive Edition** to **Stronghold Crusader: Definitive Edition**, then view, change, check and ship them as a mod – in one interface. Targets **SHCDE Script Extender 2.11.0**. Interface **German / English** (switchable). Deutsch: [README.md](README.md)

## Download

| Variant | Contents | How |
|---|---|---|
| **Bare suite** (default) | source, all graphics tools, profiles, interface, editor – about 11 MB | branch `main` → *Code* → *Download source code (zip)* |
| **Complete (Windows)** | as above plus a ready Python 3.13 with all packages and the BC7 encoder for SE atlases – no setup needed | download branch `komplett` |
| Earlier versions 1.x | Sprite Suite 1.0–1.1.3 with installers | tag `v1.1.3` |

Game graphics are **not** distributed. They are created from your own installed games when reading and building.

## Setup

1. Extract to a **short path**, e.g. `D:\SU` (Unity creates deep paths).
2. Double-click **`Suite starten.cmd`**.
   - *Complete:* starts immediately.
   - *Bare suite:* on first start `setup.ps1` creates the Python environment from an installed **Python 3.13** (packages hash-checked from `requirements-py313-win_amd64.lock`).
3. For BC7 package builds: install **Unity 2021.3.45f2** via Unity Hub (`unityhub://2021.3.45f2/88f88f591b2e`) and a **.NET SDK 8 or newer** (10 recommended). Enter them in the *Setup* tab.
4. Download **SHCDE Script Extender 2.11.0** from its official release page and put it at `extras/shcdese/SHCDESE-2.11.0.zip` – the *Target & SE 2.11* tab then installs it with a backup and a way back.
5. *Setup* → enter game folders → *Save paths* → *Read games*.

Top right: **Sprache / Language** and **Strict**. The default is **lenient mode**: deviations (versions, reference hashes, placement proofs) are reported and logged and the workflow continues; *Adopt proofs* writes the measured values. *Strict* blocks as before.

## Tabs

| Tab | Purpose |
|---|---|
| **Setup** | game and tool paths, environment check, read games |
| **Asset catalogue** | all graphics groups by theme (buildings, castle, units, animals, vegetation, landscape, effects …), four views per frame: delivered, Crusader, Stronghold 1, working copy. Replace (fitted at the foot point), take over, copy direction/damage blocks, redirect whole objects, own categories and new assets |
| **Diagnosis & repair** | checks known error classes: edge anchors (shifted battlements), partially redirected tile objects, donor identity, frame drift between game versions, canvases, bundle integrity |
| **Sandbox** | **Fully embedded Sandbox Studio in the existing Sprite Suite window** (Tk + Qt on Windows): real map-engine sprite frames, interactive placement, shared asset catalogue navigation, pixel editor, live refresh, minimap and HUD tools in the same tab. No separate GUI process. See `docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`. Full Unity shader/gameplay HUD parity remains work in progress. |
| **Editor & exchange** | HTML sprite editor out and back, SE atlas with the AtlasBuilder (`Override/Atlas`, PNG or BC7 DDS), buildings as layers (ORA) |
| **Target & SE 2.11** | several game installations, install SE 2.11.0 and mods – each with a backup and restore |
| **Edit sprites / Build package** | Europe BC7 package via Unity, incremental group cache |

## Three delivery routes

1. **Europe BC7 package** – all groups as BC7 AssetBundles with a runtime DLL for SE 2.x.
2. **Single images** – `Override/Sprites/<name>.png`, override the atlas by name.
3. **SE atlas** – `Override/Atlas/<group>/atlas.dds|png`, loaded by the Script Extender itself.

## Limits

- The sandbox approximates team colour (red channel of the mask) and wind; lighting and fog are missing.
- Images the game never requests do not appear; new slots need runtime code.
- The UI texture list (128 entries) and the UI lane runtime check (114) are not unified yet; validating with UI BC7 therefore shows a warning.
- Log output of the command-line tools is German.

## Included

- **AtlasBuilder** by Serpens66 (`extras/atlasbuilder`, with permission); BC7 encoder `texconv` from Microsoft DirectXTex (in branch `komplett`, otherwise via `fetch_texconv.py`).
- **Stronghold Sprite Editor** 1.0 (`extras/sprite-editor`, MIT), with a bilingual version.
- Atlas contract (`extras/atlas-contract`).


### Find tools from any workspace

Press **Ctrl+K** or **Search (Ctrl+K)** to find all 14 workspaces and key
tool views such as pivot measurements, AtlasBuilder, the game HUD, animation
and pixel comparison. It also works while the embedded Qt game map has focus.
Type to filter, use arrow keys to choose, **Enter to navigate**, **Esc to close**.
Searching never runs builds, installs mods, or changes files. German and
English queries work regardless of the selected interface language.
