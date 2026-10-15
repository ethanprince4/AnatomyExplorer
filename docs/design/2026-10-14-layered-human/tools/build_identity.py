import sys
print(sys.version)
for m in ("PIL", "numpy", "fontTools", "uharfbuzz", "scipy", "skimage"):
    try:
        __import__(m)
        print(m, "ok")
    except Exception as e:
        print(m, "missing", e)
