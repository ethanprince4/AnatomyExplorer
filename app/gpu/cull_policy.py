"""Per-frame choice between the cluster culler and the plain draw (ANATOMY_CULL=auto). Pure Python, no GPU objects.

Both paths give the same picture; they differ in cost. The culler spends a fixed amount per frame (cluster tests, the depth pyramid,
the id decode in the resolve) and saves the triangles it does not draw. So it pays when the triangles it saves are worth more than
that fixed amount: ``saved = drawn - kept`` (kept = clusters of both phases x 64, with the clusters over the compact-index budget
counted ``pull_cost`` times, because the vertex-pulled draw costs about 3 vertex invocations per triangle on integrated GPUs).
Measured on an RTX 3080 and a UHD 770 (docs/renderer-perf), culling won from about 1.2M saved triangles on the UHD and from about
0.35M on the 3080, and lost below 0.4M / 0.1M. ``save_tris`` is that break-even per adapter class.

The culler's own counters give ``kept`` for free (read back asynchronously, a few frames late, never waited for). They only exist
for frames the culler really culled, and only mean something from the third culled frame in a row (the first ones draw a stale or empty visible set). While the plain path is chosen the governor probes: it runs the culler for a few frames, waits for the counters of a
warm frame, and decides again; probes get rarer (back off) while they keep finding the culler not worth it, and happen at once when the
view changes a lot (drawn triangles x1.5 or /1.5, cut on/off).

Usage per frame: ``want = gov.decide(drawn_tris, key)``; after encoding a culled frame hand ``gov.tag`` to the counter readback; when
counters arrive: ``gov.observe(tag, kept_clusters, pulled_clusters)``.
"""
from __future__ import annotations

from collections import deque

CLUSTER_TRIS = 64
SAVE_TRIS = {"integrated": 1_000_000, "discrete": 600_000}     # triangles the culler must save per frame to be worth its fixed cost
PULL_COST = {"integrated": 3.0, "discrete": 1.0}             # cost of a triangle of the pulled draw against an indexed one


def adapter_class(adapter_type: str) -> str:
    """"discrete" for a discrete GPU, "integrated" for everything else (Apple GPUs, Intel, unknown): the safe side."""
    return "discrete" if str(adapter_type).lower().startswith("discrete") else "integrated"


class CullGovernor:
    PROBE_FIRST = 64            # plain frames before the first probe
    PROBE_MAX = 1024            # ... and the longest wait after probes that keep failing
    WARM_FRAMES = 3             # culled frames in a row before the counters mean something: the first has no visible set, in the second
                                # phase 1 draws everything that survived the first one's empty depth pyramid, the third is steady
    PROBE_LEN = 10              # culled frames a probe may take before it gives up (counters arrive a few frames late)
    HYSTERESIS = 0.7            # a culled path leaves for plain when it saves less than this fraction of save_tris
    WINDOW = 2                  # counters averaged
    VIEW_CHANGE = 1.5           # drawn triangles x or / by this since the last verdict: probe at once
    SAMPLE_EVERY = 16           # while culling steadily the counters are read on every 16th frame only (a map_async costs the frame loop a little)
    SILENT_FRAMES = 150         # culled frames in a row without any counters: they are not coming
    BLIND_AFTER = 3             # probes that got no counters at all: fall back to the drawn-triangle rule

    def __init__(self, save_tris: int, pull_cost: float, blind_min_tris: int = 4_000_000):
        self.save_tris = float(save_tris)
        self.pull_cost = float(pull_cost)
        self.blind_min_tris = int(blind_min_tris)
        self.state = "probe"            # "probe": culling until a verdict; "cull": culling, counters watched; "plain"
        self.frame = 0
        self.epoch = 0                  # counters of an older epoch (before the last state change) are ignored
        self.consec = 0                 # consecutive culled frames, this one included
        self.tag = None                 # (epoch, warm, drawn_tris) of the frame decide() just chose, for the counters
        self.probe_frames = 0
        self.interval = self.PROBE_FIRST
        self.since = 0
        self.verdict_tris = 0
        self.key = None
        self.recent = deque(maxlen=self.WINDOW)      # kept fraction (effective, pull-weighted) of recent warm counters
        self.got_counters = False
        self.probes_blind = 0
        self.last_obs = 0
        self.log = []                   # (frame, state) transitions, for tests and diagnostics

    # ------------------------------------------------------------------
    @classmethod
    def for_adapter(cls, adapter_type: str, save_tris=None, **kw):
        c = adapter_class(adapter_type)
        return cls(SAVE_TRIS[c] if save_tris is None else save_tris, PULL_COST[c], **kw)

    def _to(self, state):
        if state != self.state:
            self.log.append((self.frame, state))
        self.state = state
        self.epoch += 1
        self.recent.clear()
        self.since = self.frame

    def saved(self, drawn_tris) -> float | None:
        """Triangles the culler saves at ``drawn_tris`` drawn, from the recent counters (None: none yet)."""
        if not self.recent:
            return None
        return (1.0 - sum(self.recent) / len(self.recent)) * float(drawn_tris)

    # ------------------------------------------------------------------
    def decide(self, drawn_tris: int, key=None) -> bool:
        """True: this frame goes through the culler (real culling)."""
        self.frame += 1
        d = float(drawn_tris)
        if self.probes_blind >= self.BLIND_AFTER:                  # no counters ever came: the old rule
            want = d >= self.blind_min_tris
        elif self.state == "plain":
            changed = (key != self.key) or (self.verdict_tris > 0 and not (1 / self.VIEW_CHANGE <= d / self.verdict_tris <= self.VIEW_CHANGE))
            if d >= self.save_tris and (changed or self.frame - self.since >= self.interval):
                if changed:
                    self.interval = self.PROBE_FIRST
                self._to("probe")
                self.probe_frames = 0
            want = self.state != "plain"
        elif self.state == "probe":
            self.probe_frames += 1
            if d < self.save_tris:                                # cannot save enough whatever the counters say
                self._back_to_plain(d, key, failed=False)
                want = False
            elif self.probe_frames > self.PROBE_LEN:                # no verdict in time
                if not self.got_counters:
                    self.probes_blind += 1
                self._back_to_plain(d, key, failed=False)
                want = False
            else:
                want = True
        else:                                                     # "cull"
            if self.frame - max(self.last_obs, self.since) > self.SILENT_FRAMES:
                self.probes_blind = self.BLIND_AFTER
            s = self.saved(d)
            if d < self.save_tris * self.HYSTERESIS or (s is not None and s < self.save_tris * self.HYSTERESIS):
                self._back_to_plain(d, key, failed=True)
                want = False
            else:
                want = True
        self.key = key
        self.consec = self.consec + 1 if want else 0
        self.tag = (self.epoch, self.consec >= self.WARM_FRAMES, int(drawn_tris))
        return want

    def want_counters(self) -> bool:
        """Should the culled frame decide() just chose have its counters read back? Every frame while probing, sparsely after."""
        return self.state == "probe" or (self.state == "cull" and self.frame % self.SAMPLE_EVERY == 0)

    def _back_to_plain(self, d, key, failed):
        self._to("plain")
        self.verdict_tris = d
        self.key = key
        self.interval = min(self.interval * 2, self.PROBE_MAX) if failed else self.interval

    def observe(self, tag, kept_clusters: int, pulled_clusters: int = 0) -> None:
        """Counters of the frame that was tagged ``tag`` by decide(): visible clusters of both phases and how many of them went
        over the compact-index budget (and so through the pulled draw)."""
        epoch, warm, drawn = tag
        self.got_counters = True
        self.last_obs = self.frame
        self.probes_blind = 0
        if epoch != self.epoch or not warm or drawn <= 0 or self.state == "plain":
            return
        kept = max(int(kept_clusters) - int(pulled_clusters), 0) + self.pull_cost * int(pulled_clusters)
        self.recent.append(min(1.0, kept * CLUSTER_TRIS / float(drawn)))
        if self.state == "probe":
            s = self.saved(drawn)
            if s >= self.save_tris:
                self._to("cull")
                self.verdict_tris = drawn
                self.interval = self.PROBE_FIRST
            else:
                self._back_to_plain(drawn, self.key, failed=True)
