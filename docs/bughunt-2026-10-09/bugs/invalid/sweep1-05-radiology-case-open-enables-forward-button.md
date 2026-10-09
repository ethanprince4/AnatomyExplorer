# Opening a radiology case from Browse cases enables the Forward button with no prior Back

- Severity: functional
- Workspace: Radiology (top bar), Back/Forward history

## Reproduce
```
cd /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt
./aerun sweep1-05 "wait:1500;action:radiology;wait:1500;dump:v1;press:Browse cases;wait:1500;dump:v2;press:Chest;wait:2000;dump:v3"
```
Confirmed in two separate fresh launches (sweep1-04 and sweep1-05). Each time the Forward button is DISABLED before opening the case and ENABLED after it.

## Expected
Opening a new case is a new navigation. Forward history should stay empty (DISABLED), exactly as it is on the Radiology tab and in the Browse cases list (v1 and v2 both show Forward DISABLED).

## Actual
After clicking the "Chest — heart failure" row in Browse cases, the "Forward to the next place" button (@0.234,0.051) is enabled. The user never went Back, so there is nothing to go forward to. Pressing it changes the workspace unexpectedly.

## Evidence
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-05/v2.txt (Browse cases, Forward DISABLED)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-05/v3.txt (after opening case, Forward enabled)
- /Users/ethanprince/Desktop/MacTestingEnvironment/bughunt/runs/sweep1-04/u7.txt and u8.txt (same sequence, second run)

No traceback.
