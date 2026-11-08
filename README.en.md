# SpriteSuite 2.0 · Stronghold modding

Edit graphics, atlases, HUDs, Noesis pages, buildings, animations and custom mod files in a shared project, inspect the result and build a mod ZIP. Specialist tools cover Script Extender, Lua, C# and SHCDE content. The interface supports German and English. [Deutsch](README.md).

## Current version

**RC5** extends RC4 on `main` with a direct **PNG plus XAML atlas workspace** and a **ChatGPT conversation on the start page**. Mandatory explanations and quality approvals for SH1 transfers, AI candidates and custom damage/tile drafts are removed. The downloaded RC4 does not contain these changes. [RC5 changes and checks (German)](docs/SPRITESUITE_RC5_20261108.md).

**Real HP/fire game acceptance remains open.** The isolated Steam QA copy stops with `Application load error T:0000065432`. File, GUI and ZIP tests do not establish a sprite change in the running game. Historic branches and worktrees remain until complete acceptance. [Consolidation and acceptance report (German)](docs/SPRITESUITE_RELEASE_KONSOLIDIERUNG_20261108.md).

## Download and launch

Windows users should download the **Windows start package**. It includes Python and downloads hash-pinned dependencies into its own folder on first launch. That initial setup requires internet; a separate Python installation is unnecessary.

- [RC5 prerelease: Windows start package, full source and SHA-256 files](https://github.com/strongholdoriginsmod-rgb/sh1de-shcde-sprite-suite/releases/tag/v2.0.0-rc.5).
- **Source ZIP** is for development and custom builds; it has no configured Python runtime.
- The fully populated offline build, including Qt/FMOD components, is a locally verified development artifact, not a public release asset.

Fully extract into a short private path such as `C:/SpriteSuite`, then run `SpriteSuite/Suite starten.cmd`. Short paths avoid Windows extraction problems with long Qt filenames. Game installations and graphics are not distributed.

## Edit an atlas directly

From RC5, use **Ctrl+K → UI atlas · PNG + XAML**, **Project & Files → More → UI atlas (PNG + XAML)…**, or the **PNG + XAML öffnen…** button in the legacy UI workspace.

1. Select the atlas PNG and matching XAML. XAML supplies sprite names and rectangles; select the `BitmapImage` key when multiple sheets are declared.
2. Open the pair as a workspace and select an entry. A second atlas can supply the replacement sprite.
3. Replace the selection using `exact` for matching dimensions, or explicitly choose `contain` or `stretch`. Target rectangles stay fixed.
4. Persistent undo, redo and restore-original preserve the input files.
5. Publish into the active mod project to copy PNG and byte-identical XAML under `Override/Assets/GUI/Sprites/`. Inspect, back up and build the mod ZIP from that project. Export does not install into a game.

The workspace supports master atlases including 8192 × 8192 pixels and displays selected crops as Tk images. Extra sheets referenced by the same XAML need to remain available separately; warnings describe this limitation. [Detailed atlas guide (German)](docs/UI_ATLAS_PNG_XAML.md).

Crusader DE resources normally live under `<game>/BepInEx/plugins/000shcdese/Override/Assets/GUI/Sprites/UI-MasterAtlas.xaml`; original pixels may be embedded in `globalgamemanagers.assets` and can be extracted through the existing UI export. A mod's XAML, such as `Stronghold1Textures`, must match that mod's atlas. An atlas dictionary is distinct from a HUD layout page. The old **Stronghold 1 HUD → Crusader DE** bridge continues to map already exported SH1-DE crops. SH1 Classic uses the separate GM1 tools.

## Start-page ChatGPT

The conversation has input, local history, account-provided models, reasoning effort and work modes. The official local Codex client signs in with a ChatGPT account, without an API key. Google sign-in, when available, happens in the official login window. Availability and usage depend on the account's Codex allowance.

- **Questions** reads project and tool information.
- **Tasks** uses all native tools by default, including custom programming.
- **Programming** uses the same tools for focused source editing. Python execution is enabled in the work modes and can be disabled in the options.

Executed Python inherits the Suite process's OS permissions; there is no OS sandbox. The assistant cannot enable its own execution option. Stop uses cancellation and process termination paths. Local history does not synchronize with ChatGPT web conversations. [Conversation guide and limits (German)](docs/KI_CHAT_STARTSEITE.md).

The AI sprite workshop remains available for prompts using a selected original and requested variations or damage stages. A generated sprite does not prove a valid in-game SpriteSlot or gameplay binding.

## Projects and documentation

The shared project connects import, pixel/text editing, layouts, inspection, backups and mod ZIPs. Custom DLL, Lua, configuration, audio and other assets can be imported without converting their bytes. Unverified runtime archives remain identified as drafts. Project backups include editable metadata; restoration creates a new project.

Ctrl+K discovers workspaces and specialist forms. Scrolling, separate tool windows and the collapsible chat keep overflowing controls reachable. Native plugins still need matching API/ABI evidence and real game acceptance; a new game version is not a blanket modding prohibition.

- [Current quickstart (German)](docs/KURZANLEITUNG.md) and [current workflows (German)](docs/WORKFLOWS.md).
- [Project backup and transfer (German)](docs/PROJEKTARCHIVE_2026-10-29.md).
- [Archived English README through RC4](docs/README_HISTORISCH_BIS_RC4_EN.md) and [archived workflows](docs/WORKFLOWS_HISTORISCH_BIS_20261107.md).

The illustrated PDF dated November 4 is a historic partial guide. Use the current guides for the new atlas and chat features.

Source launch: `python tools/suite_start.py`. Requirements files define dependencies; the Windows start package installs from a hash lock. CI covers core and specialist tools on Python 3.13 and 3.14. Native game tests require a valid local Steam/game environment.
