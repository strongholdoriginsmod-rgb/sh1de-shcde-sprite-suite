# SH1DE → SHCDE Universal Suite 2.0 (Stronghold Europe / ORIGINS)

Transfer graphics from **Stronghold: Definitive Edition** to **Stronghold Crusader: Definitive Edition**, then view, change, check and ship them as a mod – in one interface. Static GUI/sprite packages use **no fixed SE version and no C# DLL**; optional C# runtimes retain separate ABI safety checks. Interface **German / English** (switchable). Deutsch: [README.md](README.md)

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
4. Keep the **existing Script Extender**. Use **Editor & exchange** to build **DLL-free asset mods** from edited HUD/GUI assets. No standalone version checker or automatic extender changes. C# runtimes still need ABI checks.
5. *Setup* → enter game folders → *Save paths* → *Read games*.

Top right: **Sprache / Language** and **Strict**. The default is **lenient mode**: deviations (versions, reference hashes, placement proofs) are reported and logged and the workflow continues; *Adopt proofs* writes the measured values. *Strict* blocks as before.

**Ctrl+K — Find a workspace or tool:** Search all 14 workspaces, the
Sandbox game HUD, AtlasBuilder, pivot measurements, animations and pixel
comparison, even while the embedded Qt game map has keyboard focus.
Searching never runs a build, installs a mod, or changes files.
Press Enter to navigate and Esc to close. Both languages are supported.

**Whole-application usability:** Eight short, readable main tabs remain
visible; **Bereich öffnen / Go to** provides direct access to all 14
workspaces including legacy tools. **Alle Reiter** expands the complete tab
strip, while **Reiter bündeln** restores the compact view. The log can be
shown whenever needed and no longer permanently takes up workspace height.
Long action rows have named overflow menus and editor/build forms can scroll.
[Complete workspace usability notes](docs/WHOLE_SUITE_USABILITY_2026-10-13.md)
(German). [Additional bilingual UI, keyboard and accessibility audit](docs/SPRITESUITE_UI_GESAMTPRUEFUNG_2026-10-13.md) (German).

## Tabs

| Tab | Purpose |
|---|---|
| **Setup** | game and tool paths, environment check, read games |
| **Asset catalogue** | all graphics groups by theme (buildings, castle, units, animals, vegetation, landscape, effects …), four views per frame: delivered, Crusader, Stronghold 1, working copy. Replace (fitted at the foot point), take over, copy direction/damage blocks, redirect whole objects, own categories and new assets |
| **Diagnosis & repair** | checks known error classes: edge anchors (shifted battlements), partially redirected tile objects, donor identity, frame drift between game versions, canvases, bundle integrity |
| **Sandbox** | **Fully embedded Sandbox Studio in the existing Sprite Suite window** (Tk + Qt on Windows): real map-engine sprite frames, interactive placement, shared asset catalogue navigation, pixel editor, live refresh, minimap and HUD tools in the same tab. No separate GUI process. See `docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`. Full Unity shader/gameplay HUD parity remains work in progress. |
| **Editor & exchange** | HTML sprite editor out and back, SE atlas with the AtlasBuilder (`Override/Atlas`, PNG or BC7 DDS), buildings as layers (ORA) |
| **Targets and mods** | manage game targets and install own mods – each with a backup and restore |
| **Edit sprites / Build package** | Europe BC7 package via Unity, incremental group cache |

**Integrated sandbox:** The tab now has **Open map**, **Palette**,
**Inspector**, **Focus**, and **Reset layout** controls. **More tools** gives
access to the animation editor, game HUD, maps-folder picker, comparison
tool, and asset-catalogue shortcut. The embedded Qt tool picker exposes
every inspector/HUD without a row of truncated dock tabs. The map takes
most of the available workspace; a DPI-aware Win32 resize keeps the Qt
child clipped exactly to its Tk host. The selected maps directory is
remembered privately in `config/sandbox-maps.local.json`; original game
files are not changed. See `docs/SANDBOX_MAIN_SUITE_INTEGRATION.md`.

**Project-wide release preflight:** In **Diagnosis & repair**, select a BC7
profile and use **Verify entire build (SHA-256)**. This checks every delivered
file, the bundle index, profile/group identities and optional explicitly
selected pivot approvals without installing or changing any game files.
The results are an **offline integrity snapshot**, not proof of in-game
functional correctness. See `docs/RELEASE_PREFLIGHT.md` (German).

**New: Pivot-to-BC7 staging.** Diagnosis can cross-check an explicitly
approved Zinnenlineal measurement against the original measurement file,
current sprite/index, the published BC7 manifest, and the **exact
corresponding immutable BC7 group-cache atlas**. Pivots that are already
correct in the shipped atlas are excluded from rebuild proposals. The
measurement review window also provides **Check pivot in BC7 atlas**.
It writes only a source-pinned, **non-applicable change intent**: native
geometry proofs and BC7 bundles still require a separate reviewed rebuild.
See [Pivot/BC7 staging](docs/PIVOT_BC7_STUFENPLAN.md) (German).

**Synthetic BC7 V2 rehearsal:** In **Diagnosis & repair**, use
**Prepare synthetic BC7 pivot rehearsal** to construct two
isolated, fully validated V2 Unity input projects and compare
changed/unchanged group cache identities. This exercises the
real preparation code but **does not run Unity or produce an
encoded bundle**; the required pinned Unity 2021.3.45f2 editor
is currently unavailable. See [BC7 rehearsal](docs/PIVOT_BC7_REHEARSAL.md).

**Native battlement proof (new):** In **Diagnosis & repair**, choose
**Verify native battlement geometry proof**. The published BC7 cache atlas
and original SH1DE/Crusader mapping independently reconstruct all four
frozen anim_castle geometry/origin hashes for 95 SH1DE and 11 original
Crusader frames. This is read-only provenance, not an installer or
permission to change frozen game assets.
See [Native BC7 provenance](docs/PIVOT_NATIVE_PROVENANCE.md) (German).

**Flexible local setup:** Unity and .NET tool paths can now be saved
without selecting either game installation first. Partial configuration
updates preserve unrelated settings; changing saved game directories
requires confirmation in the GUI and keeps a backup. Invalid settings
are validated before replacing existing files. **Setup status** now
reports missing or malformed local settings without starting tools, while
a damaged toolchain JSON can be repaired only with explicit consent and
a backup of its original bytes. Invalid game-path TOML now produces
an actionable warning in setup rather than preventing the main window
from opening. Other Suite functions remain usable.
See [Setup instructions](docs/EINRICHTEN.md) (German).

**Build prerequisites (new):** Under **Build packages → Check build
prerequisites**, inspect the selected profile, original-game paths,
sprite mapping, exact pinned Unity editor, .NET SDK and any existing
output before building. Missing inputs remain **blockers** instead
of being suppressed by the lenient setup doctor. This does not start
Unity, modify project files or certify a release. The SDK can also
be found in portable work/toolchains folders, DOTNET_ROOT or system
locations when PATH is missing or points to a runtime-only installation.
The real builder still probes the SDK version before writing output.
The **Build package (preflight)** button always repeats this check,
asks for explicit consent (default **No**) and treats failed
post-build validation as an error, even in lenient setup mode. Unsaved
game/Unity selections and manual SDK overrides differing from the
actual SDK the builder will use do not count as valid build inputs.
See [Build readiness](docs/BUILD_READINESS.md) (German).

**Build completion feedback:** After an actual tracked Suite build,
the window separates the build/validator exit code from an independent
SHA-256 offline audit. **Show build result** displays verified files,
warnings, previous-manifest comparison and clearly pending in-game
approval. Failed or cancelled attempts never inherit a prior package's
success, and no installation is triggered.
See [Build completion](docs/BUILD_COMPLETION.md) (German).

**Persistent local build history:** **Build packages → Show build history**
checks a local SHA-256-linked journal of genuine Suite build attempts
across application restarts. Incomplete/cancelled sessions never
turn into a success; entries cannot install or approve a release.
See [Build history](docs/BUILD_HISTORY.md) (German).

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

See [Script Extender compatibility and unverified runtime ABI](docs/SCRIPT_EXTENDER.md).

## Stronghold Origins: full HUD/GUI graphics catalog

The **ORIGINS Grafiken** workspace indexes all **13,562** versioned entries from the [Stronghold Europe graphics repository](https://gitlab.com/strongholdoriginsmod/stronghold-europe-grafikdaten), including **4,086 HUD/GUI assets**, Noesis XAML, historic blue/silver color schemes and the GUI atlases. Start the Universal Suite, open **ORIGINS Grafiken**, search and filter every source path, and select an authorized local Git-LFS clone to verify SHA-256 provenance and create isolated editable copies. The native Stronghold 1 DE HUD Studio remains accessible.

Large and partly game-derived binary resources remain in the access-managed graphics repository. The Suite source contains the complete path/Git-ID catalog and processing tools. [Setup and limitations](docs/ORIGINS_GRAFIKDATEN_KATALOG.md).
