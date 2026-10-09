# Aorta Details header repeats the name (bold title plus italic subtitle "Aorta")
Severity: visual

Repro: ./aerun details1-04 "search:aorta;wait:1000;activate;wait:2500;action:toggle_panels;wait:1200;shot:x" (toggle_panels is needed to show Details; see details1-02)

What happened: the Details header reads "Aorta" in bold, and directly below it an italic "Aorta" subtitle, then the breadcrumb "Cardiovascular system › Arterial system › Systemic arteries". The second line adds no information.

Expected: the subtitle shows the alternate or Latin name, or is omitted when it equals the title.

Also (minor, to check): the Histology section header says "(7)" while its only visible row says "Elastic artery (aorta) · 7 images", so the count is ambiguous.

Evidence: runs/details1-09/m4shot.jpg, runs/details1-10/n2shot.jpg
