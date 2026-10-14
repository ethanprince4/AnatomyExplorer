"""Colour schemes for the three Layered Human directions, with a WCAG contrast check.

Run: python schemes.py  -> writes schemes.json and schemes.css next to this file and prints the contrast report.
Every scheme sets the 3D stage (the renderer's bg_top/bg_bottom and the selection colour) as well as the chrome.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lum(h):
    r, g, b = (lin(c) for c in hex_rgb(h))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def over(fg_hex, alpha, bg_hex):
    """Flatten a translucent colour over a background (for the Overlay films)."""
    f, b = hex_rgb(fg_hex), hex_rgb(bg_hex)
    return "#" + "".join(f"{round((alpha * x + (1 - alpha) * y) * 255):02x}" for x, y in zip(f, b))


# ------------------------------------------------------------------------------------------------ schemes
# Field meanings (all designs):
#   stage_top / stage_bottom  renderer background gradient (app: Settings > Display > background)
#   spot                      the lighter pool behind the subject (Specimen); Overlay/Plate keep it near the stage
#   surface, surface_2, surface_3, sunken   panels, raised/hover, selected, inputs
#   line, line_2              hairline and strong rule
#   text, text_2, text_3      primary, secondary, muted
#   accent, accent_2, accent_soft, on_accent   active state, links, selected background
#   select                    3D selection outline colour (renderer setting selection_color)
#   card, card_text, card_text_2   Specimen's wall label card (others mirror their surface)
#   film_alpha                Overlay only: panel opacity over the stage
SCHEMES = {
    "overlay": {
        "label": "Overlay",
        "fonts": {"ui": "Archivo", "display": "Archivo", "reading": "Archivo"},
        "schemes": {
            "graphite": dict(name="Graphite", mode="dark", stage_top="#24272b", stage_bottom="#151719", spot="#2c3035",
                             surface="#30343a", surface_2="#3a3f46", surface_3="#283e45", sunken="#1d2024",
                             line="#454b53", line_2="#5c636c", text="#eef0f2", text_2="#bcc3cb", text_3="#959da7",
                             accent="#7cc8da", accent_2="#a2dbe8", accent_soft="#24434b", on_accent="#0a1c21",
                             select="#7cc8da", film_alpha=0.90),
            "slate": dict(name="Slate blue", mode="dark", stage_top="#1f2733", stage_bottom="#121821", spot="#27303d",
                          surface="#2a3442", surface_2="#344052", surface_3="#2e3a5c", sunken="#18202a",
                          line="#3e4a5c", line_2="#56647a", text="#edf1f7", text_2="#bcc6d4", text_3="#93a0b2",
                          accent="#a3b8ff", accent_2="#c2cfff", accent_soft="#303c66", on_accent="#121c3d",
                          select="#a3b8ff", film_alpha=0.90),
            "moss": dict(name="Moss", mode="dark", stage_top="#202825", stage_bottom="#131917", spot="#28312d",
                         surface="#2b3531", surface_2="#35413c", surface_3="#26453a", sunken="#19201d",
                         line="#3f4c46", line_2="#57665f", text="#eef3f0", text_2="#bccac3", text_3="#94a59d",
                         accent="#8fd6b4", accent_2="#b0e5cb", accent_soft="#23463a", on_accent="#0b2219",
                         select="#8fd6b4", film_alpha=0.90),
            "plum": dict(name="Plum", mode="dark", stage_top="#27222c", stage_bottom="#17141b", spot="#302a36",
                         surface="#352e3c", surface_2="#403848", surface_3="#3b3359", sunken="#1d1922",
                         line="#4b4256", line_2="#635972", text="#f3f0f6", text_2="#cbc3d4", text_3="#a69db1",
                         accent="#c6b5ff", accent_2="#dacfff", accent_soft="#3d345e", on_accent="#1d1640",
                         select="#c6b5ff", film_alpha=0.90),
            "smoke": dict(name="Smoke", mode="dark", stage_top="#4a4d50", stage_bottom="#37393c", spot="#525558",
                          surface="#3b3e42", surface_2="#45494d", surface_3="#36505a", sunken="#2c2e31",
                          line="#55595e", line_2="#6d7278", text="#f3f4f5", text_2="#cfd3d7", text_3="#adb2b8",
                          accent="#9fe0ee", accent_2="#c0ebf4", accent_soft="#2f525c", on_accent="#0b2228",
                          select="#ffffff", film_alpha=0.92),
            "clear": dict(name="Clear", mode="light", stage_top="#eef0f2", stage_bottom="#d9dde1", spot="#f6f7f8",
                          surface="#ffffff", surface_2="#f0f2f4", surface_3="#dbeaf0", sunken="#f5f6f7",
                          line="#d3d8dd", line_2="#aeb6bf", text="#151a20", text_2="#3a434d", text_3="#5b6570",
                          accent="#21697f", accent_2="#185567", accent_soft="#dcedf2", on_accent="#ffffff",
                          select="#1f6b82", film_alpha=0.86),
            "fog": dict(name="Fog blue", mode="light", stage_top="#e6ebf1", stage_bottom="#cdd6e0", spot="#f0f3f7",
                        surface="#fbfcfe", surface_2="#eef2f7", surface_3="#dfe6f8", sunken="#f3f6fa",
                        line="#cfd8e3", line_2="#a7b4c4", text="#141b24", text_2="#36414f", text_3="#566273",
                        accent="#3450a6", accent_2="#283f86", accent_soft="#e1e7f8", on_accent="#ffffff",
                        select="#3450a6", film_alpha=0.86),
            "sand": dict(name="Sand", mode="light", stage_top="#ebe8e3", stage_bottom="#d5d0c8", spot="#f3f1ed",
                         surface="#fffdfa", surface_2="#f2efea", surface_3="#e7e2f1", sunken="#f7f5f1",
                         line="#dcd6cd", line_2="#b5ada2", text="#1d1a17", text_2="#47413a", text_3="#686057",
                         accent="#58468c", accent_2="#463772", accent_soft="#e9e4f5", on_accent="#ffffff",
                         select="#58468c", film_alpha=0.88),
        },
    },
    "specimen": {
        "label": "Specimen",
        "fonts": {"ui": "Fira Sans", "display": "Literata", "reading": "Literata"},
        "schemes": {
            "slate": dict(name="Gallery slate", mode="dark", stage_top="#2a3138", stage_bottom="#1d2227", spot="#3d4750",
                          surface="#2c333a", surface_2="#353d45", surface_3="#3a4550", sunken="#22282e",
                          line="#3e4851", line_2="#56626d", text="#efece6", text_2="#c7c6c1", text_3="#a2a39f",
                          accent="#d4b47e", accent_2="#e3caa0", accent_soft="#3d3a33", on_accent="#231b0d",
                          select="#ffffff", card="#ece8e0", card_text="#1d2024", card_text_2="#4c5056"),
            "green": dict(name="Museum green", mode="dark", stage_top="#24302b", stage_bottom="#18211d", spot="#384a42",
                          surface="#26322d", surface_2="#2f3c36", surface_3="#36473f", sunken="#1c2521",
                          line="#3a4a42", line_2="#53665c", text="#eef0ea", text_2="#c5cbc3", text_3="#9faa9f",
                          accent="#d6b67e", accent_2="#e5cca0", accent_soft="#3b3a2c", on_accent="#231b0d",
                          select="#ffffff", card="#ebe9e1", card_text="#1b211e", card_text_2="#4a524d"),
            "prussian": dict(name="Prussian", mode="dark", stage_top="#1e2637", stage_bottom="#141a26", spot="#304060",
                             surface="#212a3b", surface_2="#2a3447", surface_3="#334059", sunken="#182030",
                             line="#344058", line_2="#4c5b78", text="#eef0f4", text_2="#c4cad6", text_3="#9ca6b8",
                             accent="#dcbd8c", accent_2="#e9d2ad", accent_soft="#3a3a3d", on_accent="#241a0c",
                             select="#ffffff", card="#ece9e2", card_text="#1a1f2b", card_text_2="#4b5161"),
            "aubergine": dict(name="Aubergine", mode="dark", stage_top="#2d232f", stage_bottom="#1d171f", spot="#453748",
                              surface="#2f2632", surface_2="#39303c", surface_3="#463a49", sunken="#241c26",
                              line="#463b49", line_2="#5f5262", text="#f2eef1", text_2="#cdc4cb", text_3="#aa9fa8",
                              accent="#dbbf91", accent_2="#e8d3b0", accent_soft="#3f3530", on_accent="#25190c",
                              select="#ffffff", card="#ede8e4", card_text="#211b22", card_text_2="#544a54"),
            "umber": dict(name="Umber", mode="dark", stage_top="#2e2823", stage_bottom="#1f1b18", spot="#463d35",
                          surface="#302a25", surface_2="#3a332d", surface_3="#3a4246", sunken="#251f1b",
                          line="#463e37", line_2="#5f554c", text="#f1ede8", text_2="#cfc7be", text_3="#aca297",
                          accent="#a9c7d4", accent_2="#c7dce5", accent_soft="#2f3d43", on_accent="#0d1f27",
                          select="#ffffff", card="#ebe7e1", card_text="#231e1a", card_text_2="#57504a"),
            "charcoal": dict(name="Charcoal", mode="dark", stage_top="#222325", stage_bottom="#161718", spot="#36383b",
                             surface="#242528", surface_2="#2d2e32", surface_3="#38393d", sunken="#1b1c1e",
                             line="#38393d", line_2="#505257", text="#f0efed", text_2="#c9c8c4", text_3="#a3a29e",
                             accent="#e0c690", accent_2="#ecd8b0", accent_soft="#3a3529", on_accent="#271d0b",
                             select="#ffffff", card="#ecebe7", card_text="#1c1d1f", card_text_2="#4f5054"),
            "plaster": dict(name="Plaster", mode="light", stage_top="#ebe8e3", stage_bottom="#dbd7d0", spot="#f7f5f1",
                            surface="#f1eee9", surface_2="#e7e3dd", surface_3="#dde3e3", sunken="#f8f6f3",
                            line="#d5d0c8", line_2="#b1aaa0", text="#1d2023", text_2="#45484c", text_3="#64676b",
                            accent="#2c5c61", accent_2="#20474b", accent_soft="#dbe7e7", on_accent="#ffffff",
                            select="#1e3a66", card="#ffffff", card_text="#1d2023", card_text_2="#4f5257"),
            "celadon": dict(name="Celadon", mode="light", stage_top="#e3eae5", stage_bottom="#cdd8d1", spot="#f2f6f3",
                            surface="#e9efeb", surface_2="#dfe7e2", surface_3="#d3e3da", sunken="#f4f7f5",
                            line="#c9d5ce", line_2="#a3b3aa", text="#18221d", text_2="#3d4a43", text_3="#5a6861",
                            accent="#2a5e4c", accent_2="#1f4a3b", accent_soft="#d4e6dc", on_accent="#ffffff",
                            select="#183b30", card="#fbfcfb", card_text="#18221d", card_text_2="#4a5750"),
        },
    },
    "plate": {
        "label": "Plate",
        "fonts": {"ui": "Atkinson Hyperlegible Next", "display": "Atkinson Hyperlegible Next",
                  "reading": "Atkinson Hyperlegible Next", "mono": "Atkinson Hyperlegible Mono"},
        "schemes": {
            "bristol": dict(name="Bristol", mode="light", stage_top="#f7f7f4", stage_bottom="#efefeb", spot="#fbfbf9",
                            surface="#f7f7f4", surface_2="#eeeeea", surface_3="#e3e9f2", sunken="#ffffff",
                            line="#d8d9d3", line_2="#a9aca5", text="#141c25", text_2="#3c4651", text_3="#5d6670",
                            accent="#1f4d8c", accent_2="#173b6c", accent_soft="#e2e9f3", on_accent="#ffffff",
                            select="#1f4d8c"),
            "greycard": dict(name="Grey card", mode="light", stage_top="#e6e7e5", stage_bottom="#dcdedb", spot="#ecedeb",
                             surface="#e6e7e5", surface_2="#dcdedb", surface_3="#d3dce1", sunken="#f2f3f1",
                             line="#c7cac5", line_2="#9ea29c", text="#16191c", text_2="#3a3f44", text_3="#565c62",
                             accent="#2e5468", accent_2="#22404f", accent_soft="#d4dee3", on_accent="#ffffff",
                             select="#12324a"),
            "linen": dict(name="Linen", mode="light", stage_top="#eeebe5", stage_bottom="#e4e0d8", spot="#f3f1ec",
                          surface="#eeebe5", surface_2="#e4e0d8", surface_3="#e3ddd2", sunken="#f8f6f2",
                          line="#d6d0c5", line_2="#aaa294", text="#211d19", text_2="#48413a", text_3="#655d54",
                          accent="#7a4a1f", accent_2="#603917", accent_soft="#ede2d3", on_accent="#ffffff",
                          select="#2b2016"),
            "celadon": dict(name="Celadon", mode="light", stage_top="#e9eeea", stage_bottom="#dfe6e1", spot="#f0f4f1",
                            surface="#e9eeea", surface_2="#dfe6e1", surface_3="#d2e3d9", sunken="#f6f8f6",
                            line="#cad5ce", line_2="#9eaea4", text="#15211b", text_2="#3a4841", text_3="#56655d",
                            accent="#28634f", accent_2="#1d4c3c", accent_soft="#d5e6dc", on_accent="#ffffff",
                            select="#123d30"),
            "newsprint": dict(name="Newsprint", mode="light", stage_top="#ededea", stage_bottom="#e3e3df", spot="#f2f2ef",
                              surface="#ededea", surface_2="#e3e3df", surface_3="#d9d9d4", sunken="#f8f8f6",
                              line="#cfcfc9", line_2="#8f8f89", text="#0f0f10", text_2="#363638", text_3="#55555a",
                              accent="#0f0f10", accent_2="#2a2a2c", accent_soft="#dcdcd7", on_accent="#ffffff",
                              select="#0f0f10"),
            "night": dict(name="Night plate", mode="dark", stage_top="#1b1d20", stage_bottom="#141618", spot="#202326",
                          surface="#1b1d20", surface_2="#24272b", surface_3="#25303f", sunken="#141618",
                          line="#33373c", line_2="#4f545b", text="#eceef0", text_2="#c0c5cb", text_3="#999fa7",
                          accent="#9fc2ef", accent_2="#c0d7f5", accent_soft="#263247", on_accent="#0e1c30",
                          select="#9fc2ef"),
            "slatenight": dict(name="Slate night", mode="dark", stage_top="#222a30", stage_bottom="#192026", spot="#28313a",
                               surface="#222a30", surface_2="#2b343c", surface_3="#26413a", sunken="#192026",
                               line="#37424b", line_2="#526068", text="#ebf0f2", text_2="#bfcad0", text_3="#97a5ad",
                               accent="#a3d8c6", accent_2="#c2e6da", accent_soft="#244038", on_accent="#0b221b",
                               select="#a3d8c6"),
        },
    },
}


def report():
    rows, problems = [], []
    for dkey, design in SCHEMES.items():
        for skey, s in design["schemes"].items():
            surf = s["surface"]
            stage_mid = s["stage_top"]
            if dkey == "overlay":
                surf = over(s["surface"], s["film_alpha"], s["stage_bottom"])
            checks = {
                "text/surface": (s["text"], surf, 7.0),
                "text_2/surface": (s["text_2"], surf, 4.5),
                "text_3/surface": (s["text_3"], surf, 3.0),
                "accent/surface": (s["accent"], surf, 3.0),
                "on_accent/accent": (s["on_accent"], s["accent"], 4.5),
                "text/stage": (s["text"], stage_mid, 7.0),
                "text_2/stage": (s["text_2"], s["stage_bottom"], 4.5),
                "line_2/surface": (s["line_2"], surf, 1.8),
            }
            if "card" in s:
                checks["card_text/card"] = (s["card_text"], s["card"], 7.0)
                checks["card_text_2/card"] = (s["card_text_2"], s["card"], 4.5)
            if s["mode"] == "light" or dkey != "specimen":
                checks["accent_text/surface"] = (s["accent"], surf, 4.5)
            else:
                checks["accent_text/surface"] = (s["accent"], surf, 4.5)
            row = {k: round(contrast(a, b), 2) for k, (a, b, _m) in checks.items()}
            for k, (a, b, need) in checks.items():
                if contrast(a, b) < need:
                    problems.append(f"{dkey}/{skey}: {k} = {contrast(a, b):.2f} < {need}")
            rows.append((dkey, skey, row))
    return rows, problems


def css():
    out = []
    for dkey, design in SCHEMES.items():
        for skey, s in design["schemes"].items():
            vars_ = [f"--{k.replace('_', '-')}: {v};" for k, v in s.items() if isinstance(v, str) and v.startswith("#")]
            if "film_alpha" in s:
                vars_.append(f"--film-alpha: {s['film_alpha']};")
            out.append(f'[data-design="{dkey}"][data-scheme="{skey}"] {{ color-scheme: {s["mode"]}; ' + " ".join(vars_) + " }")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    rows, problems = report()
    for dkey, skey, row in rows:
        print(f"{dkey:9s} {skey:11s} " + "  ".join(f"{k}={v}" for k, v in row.items()))
    print("\nPROBLEMS:" if problems else "\nAll contrast checks pass.")
    for p in problems:
        print("  " + p)
    (HERE / "schemes.json").write_text(json.dumps(SCHEMES, indent=1))
    (HERE / "schemes.css").write_text(css())
    (HERE / "schemes.js").write_text("window.LH_SCHEMES = " + json.dumps(SCHEMES) + ";\n")
