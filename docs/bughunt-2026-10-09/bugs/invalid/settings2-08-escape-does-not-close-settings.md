# Escape does not close the Settings dialog

- **Severity:** functional
- **Area:** Settings dialog (all pages)

## Reproduce
```
./aerun settings2-04 "settings:0;wait:800;dump:a;esc;wait:800;state:x"
```
(settings2-04 ran the same `esc` after the Mouse page; the minimal re-run was not done, budget used up.)

## Expected
Escape closes the Settings dialog, as it does for other dialogs.

## Actual
After `esc` and after `key:escape`, the state JSON still lists `SettingsDialog:Settings` among the top windows.
Seen after `esc` on Mouse page (settings2-04), after `key:escape` on Display page (settings2-02, settings2-05),
and after `key:escape` on the Keyboard page (settings2-08, where focus was in a shortcut field, which may consume Escape).
Caveat: the harness routes some keys to MainWindow, so `esc` (the app command) is the cleaner test.

## Evidence
- runs/settings2-04/m4_esc_mouse.json
- runs/settings2-02/d2_outline_esc1.json
- runs/settings2-05/m5_esc_a.json
- runs/settings2-08/f_esc.json
