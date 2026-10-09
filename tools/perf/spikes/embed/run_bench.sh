#!/bin/sh
# Q1/Q4 matrix. Usage: run_bench.sh <python> <log dir> <gpu_lock.py>
PY=$1; OUT=$2; LOCK=$3
D=$(dirname "$0")
for scale in "" 2; do
 for size in 1280x800 2560x1600; do
  for m in screen bitmap; do
   if [ -n "$scale" ]; then export QT_SCALE_FACTOR=$scale; else unset QT_SCALE_FACTOR; fi
   python "$LOCK" "$PY" "$D/bench.py" --method $m --phys $size --seconds 10 > "$OUT/bench_${m}_${size}_s${scale:-1}.log" 2>&1
  done
 done
done
unset QT_SCALE_FACTOR
for m in screen bitmap; do
 python "$LOCK" "$PY" "$D/bench.py" --method $m --phys 2560x1600 --vsync 1 --seconds 10 > "$OUT/bench_${m}_2560x1600_s1_vsync.log" 2>&1
done
echo done > "$OUT/bench_done.txt"
