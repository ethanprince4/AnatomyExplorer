"""Builds the --script string for a plate run (see capture.sh). Usage: make_script.py <batch1..batch6|test>"""
import sys
P = "__import__('plates')"
def ev(code): return f"eval:{code}"
def wait(ms): return f"wait:{ms}"
def plate(name, settle=9000):
    return [wait(settle), ev(f"{P}.bg(w,'#000000')"), wait(7000), ev(f"{P}.grab(w,'{name}__b')"),
            ev(f"{P}.bg(w,'#ffffff')"), wait(7000), ev(f"{P}.grab(w,'{name}__w')")]
runs = {}
W, H = 3200, 2400
base = [wait(3000), ev(f"{P}.prep(w,{W},{H})"), wait(6000)]
# test run: two plates
runs["test"] = base + [ev(f"{P}.view(w,'anterior')")] + plate("t_muscles") + \
    [ev(f"{P}.depth(w,0.40)")] + plate("t_dissect40") + ["quit"]
DEF = "skeletal,joints,muscular,cardiovascular,lymphatic,nervous,visceral"
b1 = base + [ev(f"{P}.view(w,'anterior')")] + plate("body_muscles")
b1 += [ev(f"{P}.systems(w,'{DEF},regions')")] + plate("peel_00_skin")
for d, n in ((0.16, "peel_16_fascia"), (0.26, "peel_26_superficial"), (0.40, "peel_40_deep"), (0.55, "peel_55_skeleton"), (0.70, "peel_70_cavities")):
    b1 += [ev(f"{P}.depth(w,{d})")] + plate(n)
b1 += [ev(f"{P}.depth(w,0.0)"), ev(f"{P}.systems(w,'skeletal,joints')")] + plate("body_skeleton")
b1 += [ev(f"{P}.systems(w,'visceral,cardiovascular,lymphatic,nervous')")] + plate("body_organs")
b1 += [ev(f"{P}.systems(w,'cardiovascular,nervous,skeletal')")] + plate("body_vessels_nerves")
b1 += [ev(f"{P}.default_systems(w)"), ev(f"{P}.view(w,'posterior')")] + plate("body_back")
b1 += [ev(f"{P}.view(w,'anterior')"), ev(f"{P}.orbit(w,140,0)")] + plate("body_three_quarter")
b1 += ["quit"]
runs["batch1"] = b1
if __name__ == "__main__" and sys.argv[1] == "batch1":
    pass

SEL_COLOURS = ['#7cc8da', '#a3b8ff', '#8fd6b4', '#c6b5ff', '#ffffff', '#1f6b82', '#3450a6', '#58468c', '#1e3a66', '#183b30', '#1f4d8c', '#12324a', '#2b2016', '#123d30', '#0f0f10', '#9fc2ef', '#a3d8c6']
b2 = base + [ev(f"{P}.view(w,'anterior')"), ev(f"{P}.select_names(w,'biceps brachii','insertion|origin')"), wait(4000)]
b2 += [wait(6000), ev(f"{P}.idmap(w,'hero')")]
for c in SEL_COLOURS:
    b2 += [ev(f"{P}.selcolor(w,'{c}')")] + plate("hero_sel_" + c.lstrip("#"), settle=5000)
b2 += [ev(f"{P}.deselect(w)"), ev(f"{P}.depth(w,0.40)"), wait(8000), ev(f"{P}.idmap(w,'peel40')")] + plate("peel40_ids", settle=3000)
b2 += [ev(f"{P}.depth(w,0.0)"), ev(f"{P}.view(w,'anterior')"), ev(f"{P}.dolly(w,0.55)"), wait(9000), ev(f"{P}.info(w)"), ev(f"{P}.idmap(w,'thorax')")] + plate("thorax_close", settle=3000)
b2 += ["quit"]
runs["batch2"] = b2

b3 = base + [ev(f"{P}.radiology_nolabels(w,'cxr_pa')"), wait(20000), ev(f"{P}.hide_rad_labels(w)"), wait(8000), ev(f"{P}.info(w)"), ev(f"{P}.idmap(w,'cxr')")] + plate("cxr_model", settle=3000)
b3 += [ev(f"{P}.radiology_nolabels(w,'cxr_effusion')"), wait(20000), ev(f"{P}.hide_rad_labels(w)"), wait(8000), ev(f"{P}.idmap(w,'cxreff')")] + plate("cxr_effusion_model", settle=3000)
b3 += ["quit"]
runs["batch3"] = b3

b3 += []
b3 = b3[:-1]  # drop quit, append more
b3 += [ev(f"{P}.close_rad(w)"), wait(6000), ev(f"{P}.default_systems(w)"), ev(f"{P}.view(w,'inferior')"), ev(f"{P}.clip(w,2,True,0.72,False)"), wait(12000), ev(f"{P}.info(w)"), ev(f"{P}.idmap(w,'secinf')")] + plate("section_inferior", settle=3000)
b3 += [ev(f"{P}.clip(w,2,True,0.72,True)"), ev(f"{P}.view(w,'anterior')"), ev(f"{P}.orbit(w,0,120)"), wait(12000), ev(f"{P}.idmap(w,'secobl')")] + plate("section_oblique", settle=3000)
b3 += ["quit"]
runs["batch3"] = b3
b4 = base + [ev(f"{P}.view(w,'anterior')"), ev(f"{P}.systems(w,'{DEF},regions')"), ev(f"{P}.depth(w,0.26)"), wait(8000), ev(f"{P}.select_names(w,'biceps brachii','insertion|origin')"), wait(8000), ev(f"{P}.idmap(w,'hero26')")]
for c in SEL_COLOURS:
    b4 += [ev(f"{P}.selcolor(w,'{c}')")] + plate("hero26_sel_" + c.lstrip("#"), settle=5000)
b4 += [ev(f"{P}.deselect(w)"), ev(f"{P}.depth(w,0.0)"), ev(f"{P}.default_systems(w)"), ev(f"{P}.view(w,'anterior')"), ev(f"{P}.dolly(w,0.55)"), ev(f"{P}.hide_names(w,'pectoralis major|pectoralis minor')"), wait(10000), ev(f"{P}.idmap(w,'thoraxpeeled')")] + plate("thorax_peeled", settle=3000)
b4 += ["quit"]
runs["batch4"] = b4

b5 = base + [ev(f"{P}.view(w,'anterior')"), ev(f"{P}.systems(w,'{DEF},regions')"), ev(f"{P}.depth(w,0.08)")] + plate("peel_08_supfascia")
b5 += [ev(f"{P}.depth(w,0.85)")] + plate("peel_85_deepest")
b5 += ["quit"]
runs["batch5"] = b5

# chest-framed practice plate: pectorals peeled away, framed from the clavicles to the costal margin
b6 = base + [ev(f"{P}.default_systems(w)"), ev(f"{P}.view(w,'anterior')"), wait(3000),
             ev(f"{P}.hide_names(w,'pectoralis major|pectoralis minor')"),
             ev(f"{P}.frame_names(w,'sternum|clavicle|first rib|tenth rib',1.55,-0.02)"), wait(10000), ev(f"{P}.info(w)"),
             ev(f"{P}.idmap(w,'thoraxchest')")] + plate("thorax_chest", settle=3000)
b6 += ["quit"]
runs["batch6"] = b6

print(";".join(runs[sys.argv[1]]))
