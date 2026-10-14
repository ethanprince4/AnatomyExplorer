"""Bundle plate metadata and every anchor file into assets/plates/plates.js, so pages work from file:// too."""
import json
import sys
from pathlib import Path
A = Path(sys.argv[1])
data = json.loads((A / "plates.json").read_text()) if (A / "plates.json").exists() else {"plates": {}, "anchors": {}}
for f in sorted(A.glob("*.anchors.json")):
    data["anchors"][f.name[:-len(".anchors.json")]] = json.loads(f.read_text())
(A / "plates.js").write_text("window.LH_PLATES = " + json.dumps(data, separators=(",", ":")) + ";\n")
print(len(data["anchors"]), "anchor sets")
