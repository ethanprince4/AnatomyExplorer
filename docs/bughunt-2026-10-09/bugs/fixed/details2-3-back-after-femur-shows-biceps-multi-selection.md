# Back after Biceps -> femur shows "4 structures selected" Details, not Biceps brachii muscle; search box stays "femur"
Severity: functional (wrong state after back)

Repro (seen in runs details2-2 and details2-3):
./aerun details2-x "search:Biceps brachii;activate;wait:2500;action:toggle_panels;wait:1500;search:femur;activate;wait:2500;action:back;wait:2000;shot:x"

What happened:
- Before: Details shows "Biceps brachii muscle" (Key facts, Structures 4, Clinical correlations (1)).
- After selecting femur and pressing action:back, Details shows "4 structures selected" with a "Selection (2)" group listing "Short head of biceps brachii (2)" and "Long head of biceps brachii (2)". The 3D view shows the biceps, but the Details is not the Biceps brachii muscle entry the user came from.
- The Systems search box still reads "femur" with the femur result list, so the left panel and the restored selection disagree.
- The Back button is enabled after the step, so the history is not blocked.

Expected: back restores the previous structure (Biceps brachii muscle) with its Details, and the search field matches the restored item (or is cleared).

Evidence:
- runs/details2-2/A1.jpg (Biceps Details), runs/details2-2/B1.jpg (femur Details)
- runs/details2-3/back2.jpg (after back: "4 structures selected"), runs/details2-3/back2d.txt (SearchLine 'femur')
- Forward after back was dumped only (runs/details2-3/fwd2d.txt); its Details content was not viewed.
