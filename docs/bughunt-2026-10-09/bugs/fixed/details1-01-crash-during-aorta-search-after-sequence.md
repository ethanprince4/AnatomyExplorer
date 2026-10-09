# Crash (SIGSEGV, exit -11) while selecting "aorta" after a sequence of structure searches
Severity: crash (intermittent, NOT reproduced on retry)

Repro (run details1-01):
./aerun details1-01 "search:Biceps brachii;activate;wait:1500;dump:d1a;search:femur;activate;wait:1500;dump:d1b;search:median nerve;activate;wait:1500;dump:d1c;search:aorta;activate;wait:1500;dump:d1d;search:liver;activate;wait:1500;dump:d1e;search:nasion;activate;wait:1500;dump:d1f"

What happened: dumps d1a, d1b, d1c were written (median nerve selected). The process then died with exit -11 (SIGSEGV) during the "search:aorta;activate" step; d1d was never written. stderr only shows QAccessibleList "Invalid index at: -2" / "Invalid child in QAccessibleEvent: QListWidget studySearchResults" warnings before the death.

Expected: each search + activate opens the item, no crash.

Retry (details1-06, same first steps through aorta) died with exit -9 before the first dump, so the retry is inconclusive. Repeated activations of different items may be the trigger; a retry with the sequence above is needed.

Evidence: runs/details1-01/ (report.txt, stderr.txt, d1a.txt, d1c.txt), runs/details1-06/report.txt
