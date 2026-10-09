# "Read more" / Clinical correlations expansion from one structure carries over to the next structure's Details
Severity: functional (stale state after switching items)

Repro:
./aerun details2-x "search:Biceps brachii;activate;wait:2500;action:toggle_panels;wait:1500;wclick:0.760,0.490;wait:800;search:femur;activate;wait:2500;shot:x"
(0.760,0.490 is "Read more..." under the Biceps description; I clicked the Clinical correlations header first at 0.779,0.714.)

What happened: after expanding "Read more..." on Biceps brachii muscle, selecting Femur shows the Femur description already expanded: the paragraph runs to "...forming the knee joint. By most measures the two (left and right) femurs are the strongest bones..." with a "Show less" link. The expansion was not reset for the new structure.

Expected: each structure's Details starts collapsed (or each keeps its own state), so the expansion of one item does not change another.

Evidence: runs/details2-3/leak1.jpg (Femur with expanded text, "Show less"), runs/details2-3/helper.log (clicks). Compare runs/details2-2/B1.jpg, where the same Femur Details shows the collapsed "Read more...".
Note: a re-run (runs/details2-6) was not visually checked because the image budget was used up. The leak was seen in one visual run only.

> Coordinator triage: by design — ui/info_panel.py keeps one `_open` dict of expanded sections (clinical, attachments, … and 'lead-more' for Read more) that deliberately carries across selections as a reading preference. If Read more should reset per structure, drop 'lead-more' from `_open` when the selection changes.
