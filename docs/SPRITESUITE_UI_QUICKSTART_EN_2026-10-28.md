# SpriteSuite – Updated interface quick guide

**Version: 28 October 2026.** The main navigation has been simplified
without removing specialist tools or changing saved project formats.

## Main navigation

Use the left rail to switch between **Start**, **HUD & menus**, **Edit
sprites**, **SH1 HUD Studio**, **ORIGINS graphics**, **Game preview**,
**Check**, **Build package**, and **Targets & mods**. Other pages are
available under **More workspaces** or with **Ctrl+K**. The tabs can
still be expanded via **Show all tabs**. Program logs are under **Show log**.

## Resume a project

The HUD/menu workshop automatically reopens the last existing
workspace folder, selects the previous image and restores the last
**saved layout name** when the files are available.
The current project is shown above the image list. Imported files
are copied into the workspace without changing the original.
After importing multiple images, the last successful import becomes
the selected image.

The preference is stored as a **relative** path in
`SpriteSuite/work/.hud-menu-last-session.json`. It does not include
external paths or modify installed games. To switch projects, choose
**Show workspace folder → Folder …**. **4 Prepare export** now
opens the designer's next-step guidance directly without another popup.

## Transfer an editable project

Choose **Back up project…** in **HUD & menus** to export an editable
project archive with image sources, all saved layouts and their metadata.
Choose **Open project ZIP…** on the target computer. A new, unused
project name is suggested; existing projects are never replaced.
The archive excludes installed game files and QA installation receipts.

[Complete German guide](PROJEKTARCHIVE_2026-10-29.md).

## Edit a menu image

1. Open **HUD & menus**. Select a listed PNG or click **1 Open image**
   to import an existing PNG, JPG or WebP image. Imports create local copies.
2. Use **2 Edit pixels** for brush, eraser, filling, opacity and colors.
   Save the edited PNG with **Ctrl+S**.
3. Use **3 Arrange layout** to open the layout editor. Select the image
   from the right-side list, click **Insert image**, then drag it directly
   on the canvas. Yellow handles resize; the green handle rotates.
4. The banner at the top always shows the next necessary action:
   **1 Place an image**, **2 Save layout**, **3 Export PNG** or
   **4 PNG ready**. The button beside it performs the indicated step.
5. **Save · Ctrl+S** retains editable layers and positions, while
   **Layout → PNG + positions** exports the composited PNG and position
   manifest. After moving a layer, save again. After editing an input
   PNG, export again.
6. Use **More actions** (or right-click the canvas/layer list) for
   copy, paste, duplicate, delete, layer order and export verification.
   The source-image dropdown shows the filename before its category.
7. For a static in-game overlay use **Bind game UI (Noesis)** and
   select a verified XAML container. Visibility and interactions
   must still be checked in-game.

## Know the difference

**Pixel editor:** changes pixels in an image copy.

**Layout editor:** places multiple images independently and stores
coordinates, dimensions, rotation, anchors and layer order.

**Export:** bakes the layout into one PNG. Re-export after any change
to the layout or its image sources.

**Noesis:** can add a static, click-through overlay into a verified
game UI container. It does not automatically move existing buttons
or their click targets. User assets remain under `SpriteSuite/work/`;
original game installations are not modified by the editor.

The technical workspace folder and specialist actions are collapsed by
default in the HUD and menu workshop. Use **Show workspace folder** or
**Show more graphics tools** to reveal them.

For detailed German instructions see
[SpriteSuite – Die neue Oberfläche](SPRITESUITE_NEUE_OBERFLAECHE_2026-10-28.md).
