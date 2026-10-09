# Toggle panels after closing the Systems panel hides Details and does not restore Systems

- **Severity:** functional (medium-low; confirmed twice)
- **Area:** Explore workspace, Anatomy tree ("Systems") panel, Close button, action:toggle_panels

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun tree1-03 "action:toggle_panels;wait:1200;press:Close;wait:900;action:toggle_panels;wait:1000;dump:x"
```
(Same sequence also seen in tree1-02, commands `toggle; ...; press:Close; toggle`.)

## Expected
Left "Systems" panel was closed with its Close button. Pressing toggle_panels should bring the Systems panel back (or at least the state should be consistent with what is shown).

## Actual
- Start: both panels hidden (dump has no Systems/Details widgets).
- After first toggle: Systems panel and right "Details" panel visible.
- After Close on Systems: Systems panel gone, Details still visible.
- After toggle_panels: BOTH panels disappear (only the top bar and bottom toolbar remain). Systems is still not visible.
- Only a second toggle_panels brings Systems and Details back.

So the toggle acts as a global hide/show of both panels, and after a single Close the user is left with an empty workspace after one toggle.

## Evidence
- runs/tree1-03/b1.txt (panels open), runs/tree1-03/b3.jpg (after Close), runs/tree1-03/b4.txt (after toggle: no panels, 16 lines), runs/tree1-03/b5.txt (after second toggle: panels back)
- runs/tree1-02/a11.txt and a12.txt show the same pattern.
- Note: in runs/tree1-06/f8 and f9, closing both panels and then toggling does restore both, so the problem is specific to closing only the Systems panel.
