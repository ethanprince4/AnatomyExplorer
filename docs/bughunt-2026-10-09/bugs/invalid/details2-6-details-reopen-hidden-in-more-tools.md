# Details panel can only be reopened from More tools (or by toggle_panels); no visible Details toggle
Severity: ux

Correction to details1-02: the reopen path does exist, but it is only in the "More tools" menu, not on the toolbar or the view controls.

Repro (confirmed in runs/details2-6):
./aerun details2-x "search:Biceps brachii;activate;wait:2500;press:More tools;wait:800;press:Details;wait:1500;dump:s2"
(s2.txt lists QPushButton 'Focus' and 'Close' for Details. Before the press (runs/details2-6/s1.txt) Details was not listed.)

Other reopen paths checked:
- Details Close (wclick 0.961,0.198) hides it. Systems stays open.
- action:toggle_panels hides Systems and Details together, and selecting a structure then reopens Details (runs/details2-3/sel1.txt).

Expected: a visible "Details" toggle next to Systems or in the toolbar, so a user who closed the panel can find it without knowing the More tools menu.

Suggested feature: a Details show/hide toggle in the toolbar or View menu, with its state reflecting whether the panel is open.
Evidence: runs/details2-6/s1.txt, s2.txt, runs/details2-3/cl1.txt (Details closed), more1.txt (menu list).
