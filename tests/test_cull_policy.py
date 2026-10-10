"""CullGovernor (app/gpu/cull_policy.py): the per-frame culler / plain choice, driven by fake counters. CPU only."""
from app.gpu.cull_policy import CLUSTER_TRIS, PULL_COST, SAVE_TRIS, CullGovernor, adapter_class


def simulate(gov, frames, scenario, lag=3, key=lambda f: 0):
    """scenario(frame) -> (drawn_tris, kept_fraction, pulled_fraction_of_kept). Counters of a culled frame arrive `lag` frames later.
    Returns the list of per-frame decisions."""
    pending, out = [], []
    for f in range(frames):
        while pending and pending[0][0] <= f:
            _, tag, kept, pulled = pending.pop(0)
            gov.observe(tag, kept, pulled)
        drawn, frac, pull = scenario(f)
        want = gov.decide(drawn, key(f))
        out.append(want)
        if want:
            kept = int(frac * drawn / CLUSTER_TRIS)
            pending.append((f + lag, gov.tag, kept, int(kept * pull)))
    return out


def integrated():
    return CullGovernor.for_adapter("IntegratedGPU")


def discrete():
    return CullGovernor.for_adapter("DiscreteGPU")


def test_adapter_class():
    assert adapter_class("DiscreteGPU") == "discrete"
    assert adapter_class("IntegratedGPU") == "integrated"
    assert adapter_class("") == "integrated" and adapter_class("Unknown") == "integrated"
    assert SAVE_TRIS["discrete"] < SAVE_TRIS["integrated"] and PULL_COST["discrete"] < PULL_COST["integrated"]


def test_big_saving_stays_culled():
    g = integrated()
    out = simulate(g, 600, lambda f: (25_000_000, 0.25, 0.0))
    assert all(out) and g.state == "cull"


def test_little_saving_goes_plain_and_rarely_probes():
    g = integrated()                       # 2M drawn, 61 % kept: saves 0.78M, below the 1M break-even
    out = simulate(g, 2000, lambda f: (2_000_000, 0.61, 0.0))
    assert g.state == "plain"
    assert sum(out) < 0.12 * len(out)      # the probes are short and back off
    assert sum(out[1000:]) < 0.06 * 1000


def test_probes_back_off():
    g = integrated()
    simulate(g, 3000, lambda f: (2_000_000, 0.61, 0.0))
    assert g.interval >= 256


def test_never_culls_below_break_even_size():
    g = integrated()
    out = simulate(g, 500, lambda f: (900_000, 0.1, 0.0))      # 0.9M drawn can never save 1M
    assert not any(out)


def test_discrete_threshold_is_lower():
    sc = lambda f: (1_000_000, 0.2, 0.0)                       # saves 0.8M: above the discrete break-even (0.6M), below the integrated one (1M)
    gi = integrated()
    out_i = simulate(gi, 400, sc)
    assert gi.state == "plain" and sum(out_i) < 0.15 * len(out_i)
    d = discrete()
    out = simulate(d, 400, sc)
    assert d.state == "cull" and all(out[20:])


def test_budget_overflow_weighs_pulled_clusters():
    sc = lambda f: (3_000_000, 0.30, 0.8)                     # 30 % kept, 80 % of those pulled: 0.3 * (0.2 + 0.8 * 3) = 78 % effective
    gi = integrated()
    out = simulate(gi, 600, sc)
    assert gi.state == "plain" and sum(out) < 0.2 * len(out)
    gd = discrete()                                            # a pulled triangle costs the same as an indexed one there
    assert all(simulate(gd, 600, sc)) and gd.state == "cull"


def test_view_change_probes_at_once():
    g = integrated()
    sc = lambda f: (2_000_000, 0.7, 0.0) if f < 300 else (4_000_000, 0.2, 0.0)
    out = simulate(g, 400, sc)
    assert g.state == "cull"
    assert not any(out[200:300]) or sum(out[200:300]) < 20
    assert all(out[330:])


def test_key_change_probes_at_once():
    g = integrated()
    sc = lambda f: (3_000_000, 0.9, 0.0) if f < 250 else (3_000_000, 0.2, 0.0)    # a cut view makes culling pay
    out = simulate(g, 400, sc, key=lambda f: 0 if f < 250 else 1)
    assert g.state == "cull" and all(out[290:])


def test_leaves_culled_when_view_gets_worse_with_hysteresis():
    g = integrated()
    sc = lambda f: (3_000_000, 0.2, 0.0) if f < 100 else (3_000_000, 0.70, 0.0)    # saves 2.4M, then 0.9M (band 0.7M..1M)
    out = simulate(g, 200, sc)
    assert g.state == "cull" and all(out)               # 0.9M is in the band between 0.7 x and 1 x break-even: stay
    sc2 = lambda f: (3_000_000, 0.2, 0.0) if f < 100 else (3_000_000, 0.85, 0.0)   # saves 0.45M: under the band
    out2 = simulate(integrated(), 200, sc2)
    assert not out2[-1] and not any(out2[150:])


def test_no_flapping_in_the_band():
    g = integrated()
    simulate(g, 600, lambda f: (3_000_000, 0.2 if f % 2 else 0.6, 0.0))      # noisy: average saves 1.8M
    assert g.state == "cull" and len([x for x in g.log if x[1] == "plain"]) == 0


def test_cold_stale_and_plain_time_counters_are_ignored():
    g = integrated()
    g.decide(5_000_000)
    first = g.tag                                         # first culled frame: not warm
    g.observe(first, 10, 0)                               # a cold frame's counters say 640 tris kept: must not count
    assert g.state == "probe" and not g.recent
    g.decide(5_000_000)
    second = g.tag                                        # the second one still draws what the empty first one left
    g.observe(second, 10, 0)
    assert g.state == "probe" and not g.recent
    g.decide(5_000_000)
    stale = (g.epoch - 1, True, 5_000_000)
    g.observe(stale, 10, 0)
    assert g.state == "probe" and not g.recent
    g.observe(g.tag, 10, 0)
    assert g.state == "cull"


def test_blind_fallback_is_the_drawn_triangle_rule():
    g = integrated()
    out = [g.decide(5_000_000) for _ in range(400)]      # counters never arrive
    assert g.probes_blind >= g.BLIND_AFTER and out[-1]
    g2 = integrated()
    out2 = [g2.decide(2_000_000) for _ in range(400)]
    assert not out2[-1]


def test_silent_culled_frames_fall_back():
    g = integrated()
    for _ in range(3):
        g.decide(5_000_000)
    g.observe(g.tag, 1000, 0)                             # one verdict, then silence
    assert g.state == "cull"
    for _ in range(g.SILENT_FRAMES + 5):
        g.decide(2_000_000)
    assert g.probes_blind >= g.BLIND_AFTER and not g.decide(2_000_000)
