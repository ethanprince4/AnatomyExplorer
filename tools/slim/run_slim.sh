#!/bin/bash
# Export, simplify and stage review copies of the candidate parts (see README.md in this folder).
# usage: tools/slim/run_slim.sh OUT_DIR [candidates.txt] [jobs]
# PYTHON: a Python 3.11 with bpy 5.0.1, numpy, scipy, moderngl, Pillow and PySide6 6.11.2 (default: python3).
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
OUT="$(mkdir -p "$1" && cd "$1" && pwd)"
CANDIDATES="${2:-$HERE/candidates.txt}"
JOBS="${3:-2}"
PY="${PYTHON:-python3}"
cd "$REPO"
rm -f "$OUT/manifest.jsonl" "$OUT/results.jsonl"

# 1. export: one call per model with all of its candidate parts ("model:part" per line)
"$PY" - "$CANDIDATES" > "$OUT/bymodel.txt" <<'PY'
import collections, sys
by = collections.OrderedDict()
for line in open(sys.argv[1], encoding="utf-8"):
    line = line.strip()
    if line:
        m, p = line.split(":", 1)
        by.setdefault(m, []).append(p)
for m, ps in by.items():
    print("\t".join([m] + ps))
PY
while IFS=$'\t' read -r -a row; do
  QT_QPA_PLATFORM=offscreen "$PY" "$HERE/slim_export.py" "$OUT" "${row[@]}" >> "$OUT/export.log" 2>&1
done < "$OUT/bymodel.txt"
git checkout -- data/anatomy/depth.npz data/anatomy/samples.npz 2>/dev/null || true   # app caches the export rewrites

# 2. decimate and score, the manifest split across JOBS processes (each can take several GB on the largest parts)
n=$(wc -l < "$OUT/manifest.jsonl")
step=$(( (n + JOBS - 1) / JOBS ))
for ((s = 0; s < n; s += step)); do
  "$PY" "$HERE/slim_decimate.py" "$OUT" "$s:$((s + step < n ? s + step : n))" >> "$OUT/decimate.log" 2>&1 &
done
wait

# 3. review copies of the model files (originals untouched), under OUT/staged/
"$PY" "$HERE/slim_stage.py" "$OUT" > "$OUT/stage.log" 2>&1
echo "done: $(wc -l < "$OUT/results.jsonl") parts scored; see $OUT/decimate.log and $OUT/stage.log"
