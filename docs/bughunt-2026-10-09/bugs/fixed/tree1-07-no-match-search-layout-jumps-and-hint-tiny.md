# Systems panel with no-match query: layout jumps and "No matches" hint is tiny and far from the search box

- **Severity:** visual (low-medium)
- **Area:** Explore workspace, Anatomy tree "Systems" panel, filter box

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun tree1-07 "action:toggle_panels;wait:1200;press:Search anatomy, models;type:zzqxw;wait:1200;shot:x"
```

## Expected
A no-match message placed close to the search results area, with the filter box staying where it is, and the Systems/Regions/Tree tabs and Browse/View tabs kept in place or clearly hidden.

## Actual
- Typing a query with no matches removes the Browse/View and Systems/Regions/Tree tabs and the rows.
- The search box moves from the top of the panel (y≈0.255) to the middle (y≈0.47) leaving a large empty gap above it.
- The "All content" dropdown moves down to the bottom of the panel (y≈0.73).
- The only message is a very small grey "No matches. Try a shorter name, a Latin term, or All content." in the bottom-left corner, far from the search box, and hard to read.

## Evidence
- runs/tree1-07/g1.jpg (screenshot), runs/tree1-07/g1.txt (dump: SearchLine at @0.163,0.471, combo at @0.261,0.733)
- For comparison, the query "Skel" (runs/tree1-03/b2.txt) shows a normal 16-row "Search results" list with the search box in its usual place.
