# Details panel does not open when a structure is selected from search; only toggle_panels shows it
Severity: ux (possibly functional)

Repro:
./aerun details1-02 "search:Biceps brachii;wait:1000;activate;wait:2500;dump:k1;shot:k1shot"
(k1.txt contains no "Anatomy details" QTextBrowser and no Details Close button; the 3D view shows the biceps highlighted.)
Then: ./aerun details1-03 "search:Biceps brachii;activate;wait:2000;action:toggle_panels;wait:1200;dump:m1"
(m1.txt now lists QPushButton 'Close' @0.961,0.198 and QTextBrowser 'Anatomy details' @0.854,0.569 with Focus/X-ray others/Isolate/Hide/Show.)

What happened: after selecting a structure the Details panel stays hidden. The panel appears only after action:toggle_panels, and it did so in every run. Pressing Details' Close (wclick 0.961,0.198) hides it, and then there is no visible control to bring it back. The only way seen to reopen it was toggle_panels.

Expected: selecting a structure shows its Details, and a visible control (toolbar button or menu item such as "Show details") reopens the panel after Close.

Evidence: runs/details1-08/k1.txt, runs/details1-08/k1shot.jpg, runs/details1-09/m1.txt, m2.txt (closed), m3.txt (reopened via toggle_panels)
Suggested feature: auto-open Details on selection, and a "Details" toggle button in the toolbar or View menu next to Systems.
