import sys, numpy as np
a, b = np.load(sys.argv[1]), np.load(sys.argv[2])
for k in sorted(set(a.files) & set(b.files)):
    x, y = a[k].astype(np.float64), b[k].astype(np.float64)
    d = np.abs(x - y)
    print(k, "shape", x.shape, "differing", int((d > 0).sum()), "max", float(d.max()), "mean", float(d.mean()))
print("only in one:", sorted(set(a.files) ^ set(b.files)))
