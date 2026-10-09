# Search results panel stays open on top of the 3D view after opening a hit, with no clear way to dismiss it

- Severity: ux
- Workspace: Explore, top search

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun sweep1-07 "wait:1500;search:heart;wait:1500;activate;wait:2500;dump:b1;state:b1"
```
(Same as sweep1-03.)

## Expected / what the user would expect
After activating a search hit, the search results should close (or at least collapse), so the 3D view and the Details panel are the focus. Right now the results list, the "heart" search field and a "Close" button stay on the left, and the Details panel on the right is its own separate close control.

## Actual
- After activate, the "Systems" panel is still open on the left with the query "heart", "103 results · Enter to open", and 11+ rows.
- The panel has its own "Close" button (@0.287,0.198), and the Details panel has another "Close" button (@0.961,0.198). Two Close buttons close two different things, and nothing says so.
- The result count in the UI is "103 results", while the dump of the list reports rows=150. The two numbers do not agree (not sure which is right, so this is only noted here).

Suggested feature: after a search hit is opened, collapse the results to the open item (or add a "Back to results" control in Details) so there is one clear way to return to search, and label the two Close buttons by what they close.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-03/t1.txt (dump with both Close buttons)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-03/t1.jpg (screenshot: "103 results", Details panel beside the still-open list)
