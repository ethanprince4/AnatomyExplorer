# Checkpoint 2, question B: the depth gauge

This copy of the Specimen mockup changes only the dissection gauge on the atlas and peel screens (and, for option 3,
the title above them). Everything else is the same as `app/specimen/index.html` was when it was copied on 15 October.

Open `index.html?screen=atlas&variant=1|2|3` (or `screen=peel`). Without `variant`, option 2 shows. Extra states:
`&gauge=drag` (the knob held), `&gauge=only` ("Show only this layer" on). In a browser the gauge also works: drag the
knob or the track, Tab to the knob and use the arrow keys, Page Up and Page Down, Home and End, `[` and `]`.

Renders: `renders/checkpoint-2/gauge/`.

## What is fixed in all three (critique 2b, item 8)

- **Real levels.** Every stop sits at its level from the app's `DISSECTION_STOPS` (`app/ui/view_panel.py`): 0, 8, 16, 26,
  40, 55, 70 and 85 %. The track is 700 px tall, 7 px per 1 %, so every level lands on a whole pixel. The current stop
  doesn't move: only its size and weight change (20 px, weight 460).
- **End captions.** "Dissection" stays as the column head. "Superficial" and "Deep" are the two ends of the track,
  in 11 px capitals with 0.1 em tracking, centred on the track. The bundled Fira Sans has no small caps, so these are
  spaced capitals; in Qt use the same, not `QFont.SmallCaps` (that makes fake small caps).
- **Contrast** against the wall behind the gauge, at its lightest point (y = 232). The lowest value in any of the six
  schemes is given here, worked out by `contrast.py` in this folder and checked against the rendered pixels:
  - lines and major marks use `--leader`: 4.58:1 (it was `--line-2`, 2.2:1);
  - fine marks, past band lines and option 3's rail use `--text-3` at 70 %: 3.45:1;
  - the brass fill and knob are 6.97:1, and the knob on the lit band is 4.80:1;
  - past stop names use full `--text-3` (5.43:1), stops still to come use `--text-2` (8.05:1), and the current stop uses `--text`;
  - the percentage (`--accent-2`) is 8.67:1, and "Show only this layer" (`--text-2`) is 8.05:1.

  The pool of light ends about 140 px left of the gauge, so the wall behind it is the plain gradient.
- **Show only this layer** is on screen in every option, next to the stop it acts on. In the app this is the
  `depth_band` checkbox: it keeps a window 0.13 deep below the cut (`band = 0.13` in `_depth`). Options 1 and 3 draw that
  window as a hairline bracket beside the rule when it is on.
- **Keyboard.** The knob is `role="slider"`, `aria-orientation="vertical"`, with a value from 0 to 100 and a value text
  such as "40% deep, Deep muscles". Down and Right go 1 % deeper, Page Down 10 %, Home and End go to the ends, and `[` and `]` step
  between stops, as the app's Shallower and Deeper do. The focus state is a 2 px `--text` ring 5 px outside the knob
  (`1_peel`, `2_peel`, `3_peel_focus`). The knob's halo is the wall colour at the knob's own height, not `--stage-bottom`,
  so it never shows as a dark ring.

## The three options

**1. Rule.** A measuring rule hung beside the specimen: a fine scale with the eight stops named in italic at their real levels.
- 1 px `--leader` rule, with a 5 px mark every 2 % and a 9 px mark every 10 % in `--text-3` 70 %.
- 14 px major marks and italic Literata names at the eight levels.
- A 3 px brass fill from 0 down to the knob, a 15 px brass knob, and the percentage beside the knob.
- "Show only this layer" is a small checkbox under the current stop's name. It moves with the stop.

**2. Strata (recommended).** A core sample: eight stacked bands, each as tall as its depth range, the current band lit.
- A 40 px column. Each band is drawn from its level to the next (8, 8, 10, 14, 15, 15, 15, 15 %) with `--leader` edges.
- Bands still to come have a 5 % `--text` fill. Peeled bands are empty, with `--text-3` 70 % edges and `--text-3` names.
- The current band is lit with `--spot` from the knob down, and its sides are drawn in `--text-2`.
- Names hang just under their level. The current name is upright 20 px Literata, with "Show only this layer" under it.
- The knob is a brass cut line across the column with a 13 px brass handle on its right edge.
- Clicking any band moves the cut to that band's level and turns on "Show only this layer". With it on, the bands
  below the lit one empty too, so only one layer is left lit (`2_peel_only_crop`).

**3. Title.** The page title carries the depth, and the gauge shrinks to a slim rule that shows names only while you use it.
- A 3 px rule in `--text-3` 70 % with a brass fill, small marks at the eight levels, a 17 px knob and the percentage.
- No names at rest. They fade in (120 ms) while the knob is dragged or has keyboard focus (`3_atlas_drag`, `3_peel_focus`).
  While dragging, the knob gets a 1 px brass ring.
- The title is the current stop ("Superficial muscles" on the atlas, "Deep muscles" on the peel) and updates live. The
  caption puts depth first: "26% deep · 2,231 of 3,922 shown".
- "Show only this layer" is a checkbox on the caption line, beside the layer's name.

## Carrying the chosen option into `app/specimen/index.html`

All three share one markup, built by JS, so most of the port is the same whichever option is chosen.

1. **CSS.** Replace the old `/* dissection gauge */` block (`.gauge .line` … `.gauge .end`) with this copy's block. It
   starts at the `dissection gauge` comment and ends at `[data-variant="3"] .v12`. Keep the shared rules (`.gauge` to
   `.x-only { display: none; }`) and the chosen option's rules. Then remove the `[data-variant="n"]` prefix from those rules and
   delete the other two options' rules.
   - For option 2, the `.gauge` custom properties `--cw` and `--gc` move into the plain `.gauge` rule.
   - For option 3, keep `.x-only` visible (`display: inline-flex` with option 3's margin and size) and drop the `.v12`/`.v3` spans
     (next step).
2. **Markup.**
   - Options 1 and 2: no change outside the gauge. The two `<div class="gauge" data-depth="…">` stay as they are.
   - Option 3: on the atlas, set the `<h1>` to `<span data-stop-name>Superficial muscles</span>` and the caption to
     `<span data-pct>26%</span> deep · 2,231 of 3,922 shown` followed by the `<button class="x-only">` from this copy. Do the same
     on the peel with "Deep muscles", 40 % and 1,526. Use this copy's exhibit markup without the `v12` spans.
3. **JS.** Replace the old `STOPS` / `.gauge` block with this copy's block, from the `// The app's DISSECTION_STOPS` comment
   down to the `.x-only` click handler. It contains `drawGauge`, `setDepth`, `setOnly` and the pointer and key handlers.
   Remove the `data-variant` line from the first script block, or set it to the chosen number if you keep the
   prefixed CSS. The `?gauge=drag|only` lines are only for renders and can go.
4. **Assets:** none. Scheme tokens only (`--leader`, `--text*`, `--accent*`, `--spot`, `--stage-top/bottom`), so every
   option recolours with the scheme. `2_atlas_umber` shows it with Umber's steel-blue accent.

## What the Qt app needs

Today the gauge is a plain `QSlider` (0 to 1000), Shallower and Deeper buttons, the `depth_band` checkbox and a text
line, all in the Dissection group of `ViewPanel`. In every option the gauge becomes one custom widget beside the 3D view,
drawn with `QPainter`. Call it `DepthGauge(QWidget)`.

- **Shared.**
  - Read the levels and names from `DISSECTION_STOPS`, and draw at the device pixel ratio so the 1 px lines stay crisp.
  - `keyPressEvent` handles the keys above, and `Qt.StrongFocus` gives it Tab focus. Draw the focus ring yourself in `paintEvent`.
  - Expose it as a slider: `setAccessibleName("Dissection depth")`, plus a `QAccessibleInterface` with a value, or keep a hidden
    `QSlider` as the accessible proxy.
  - Emit the existing `depthChanged(cut, band)` so the renderer side is unchanged.
  - Fonts: Literata italic for names, Fira Sans for the percentage and checkbox. Both are bundled under the OFL.
  - Colours: `theme.MUTED` and `theme.TEXT_2`, the accent tokens, and a new `LEADER` constant from the scheme's `leader` token.
  - "Show only this layer" stays a real checkbox (`depth_band`), placed by the widget next to the current stop.
- **Option 1:** only the painter. Every part is lines, marks and text.
- **Option 2:**
  - Band rectangles need hit testing: `mousePressEvent` finds the band and calls `set_depth(level, True)`. Add a hover state.
  - **Decision needed:** the app's window is a fixed 0.13, but the bands are 8 to 15 % deep. For the lit band to be exactly what
    "Show only this layer" keeps, `_depth` would emit `band = next_level - cut` instead of 0.13. That is a one-line
    change to app behaviour and needs the owner's yes. At the two rendered depths the window and the band nearly agree
    (26 to 39 % against 26 to 40 %, and 40 to 53 % against 40 to 55 %).
- **Option 3:**
  - The workspace title has to follow the depth, so the atlas header (outside `ViewPanel`) listens to `depthChanged`.
  - Names show on `mousePress` and `focusIn`, and hide on `mouseRelease` and `focusOut`, with a short opacity animation (`QVariantAnimation`).
  - The "Show only this layer" checkbox moves into the title caption row.

## Not drawn here

- The "preparing" and "unavailable" states, and the intact state ("Intact – nothing removed yet") at 0 %.
- The app's "Reset dissection" button.
- Hover previews of a stop's name and count in the caption (critique section 3): the mockup has counts only for 26 % and 40 %.
- With "Show only this layer" on, the shown count would change. So the on state is rendered only as gauge crops, and the full-screen
  captions are never shown with wrong numbers.
