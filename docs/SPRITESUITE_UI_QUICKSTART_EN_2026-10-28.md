# SpriteSuite – Updated interface quick guide

**Version: 28 October 2026.** The main navigation has been simplified
without removing specialist tools or changing saved project formats.

## Main navigation

Use the left rail to switch between **Start**, **HUD & menus**, **Edit
sprites**, **SH1 HUD Studio**, **ORIGINS graphics**, **Game preview**,
**Check**, **Build package**, and **Targets & mods**. Other pages are
available under **More workspaces** or with **Ctrl+K**. The tabs can
still be expanded via **Show all tabs**. Program logs are under **Show log**.

## Edit a menu image

1. Open **HUD & menus**. Select a listed PNG or click **1 Open image**
   to import an existing PNG, JPG or WebP image. Imports create local copies.
2. Use **2 Edit pixels** for brush, eraser, filling, opacity and colors.
   Save the edited PNG with **Ctrl+S**.
3. Use **3 Arrange layout** to open the layout editor. Select the image
   from the right-side list, click **Insert image**, then drag it directly
   on the canvas. Yellow handles resize; the green handle rotates.
4. Click **Save · Ctrl+S** to retain editable layers and positions,
   then **Layout → PNG + positions** to export a composited PNG plus
   an exact position manifest.
5. For a verified, static in-game overlay use **Bind game UI (Noesis)**
   and select an existing XAML Grid from the installed game.
   Visibility and interactions must still be checked in-game.

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
