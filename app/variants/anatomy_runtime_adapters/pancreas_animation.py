"""Shipped pancreas source-bound four-channel presentation animation."""
def make_animation():
    from app.micro.anim import Track, Animation, MODE_FLOW, window
    def _gate(t):
        return window(t,0.06,0.16,0.86,0.97)
    def _insulin(t):
        return window(t, 0.48, 0.58, 0.72, 0.84)


    PHASES = [
        (0.00, 0.12, "Exocrine example: cholinergic stimulus; acinar Ca2+ signal (schematic)"),
        (0.12, 0.38, "Acinar enzyme release into lumen; ducts add bicarbonate/water in response to secretin"),
        (0.38, 0.48, "Separate endocrine example: increased glucose; beta-cell metabolism, KATP closure and Ca2+ entry"),
        (0.48, 0.84, "Beta-cell insulin transfer to blood; capillary transport, separate from duct juice"),
        (0.84, 1.00, "Demonstration resets; sequence and four-second period are schematic"),
    ]


    def pancreas_animation():
        flow = lambda gate, rate: Track(
            lambda t: (0.0, 0.0, 0.0, gate(t)), glow=0.45,
            mode=MODE_FLOW, rate=rate)
        tracks = {
            "Zymogen granules": Track(
                lambda t: (0.0, 0.0, 0.0, 1.0),
                glow=lambda t: 0.25 * window(t, 0.02, 0.1, 0.3, 0.45),
                mode=MODE_FLOW, rate=1.0),
            "Pancreatic juice (secretion flow)": flow(_gate, 6.0),
            "Pancreatic juice in intralobular ducts": flow(_gate, 6.0),
            "Insulin release from beta cells": flow(_insulin, 1.0),
            "Insulin into islet capillaries": flow(_insulin, 5.0),
            "Beta cells": Track(glow=lambda t: 0.30 * _insulin(t)),
        }
        return Animation(4.0, tracks, phases=PHASES,
                         title="Secretory routes (schematic; separate triggers)",
                         speeds=(1.0, 0.5, 0.25))
    return pancreas_animation()
