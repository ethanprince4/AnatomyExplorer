# Embed spike handoff
Code: R/tools/perf/spikes/embed/{common,bench,scene,run_bench.sh,summarize}.py. Logs: this folder.
DONE Q1+Q4 (bench_*.log, nodraw/). Monitor 2560x1440 logical DPR1.5 240Hz; RTX 3080 Vulkan; tooth = 33 parts 2.13M tris.
 screen: 1280x800 119fps(8.4ms), 2560x1600 60.6fps(16.6ms) GPU-bound (acquire blocks); nodraw 2370fps.
 bitmap: 1280x800 89fps(11.2), 2560x1600 40fps(24.6); nodraw 139fps (7ms readback+blit overhead).
 swapchain == widget physical always (2561x1601 from logical rounding).
 jitter: screen render timer ticks = frame rate (loop blocked in acquire); bitmap ~800-960 ticks/s.
TODO Q2 scene.py (not yet run), Q3 resize.py, Q5 hook inspect (hooks read: wgpu hook collect_dynamic_libs+resources; rendercanvas hook; spec unused() regexes to test).
DONE Q2: scene_{screen,bitmap}_{child,toolwin,after}.log (show_scene.py). card+opaque labels visible in both; screen+child overlay: partial alpha mis-blended (R 31 vs 128), toolwin correct.
DONE Q3: resize_{screen,bitmap}.log: 21 checked steps + 20 rapid each, 0 bad, 0 log records, max frame age 2.
DONE Q5: spec unused() drops none of wgpu/rendercanvas paths (spec_filter_check.py); wgpu/rendercanvas not in requirements.txt; PyInstaller not in venv; hooks via pyinstaller40 entry points.
Only remaining: final report.
