"""Temporary study feedback must preserve a learner's authored colors."""


def highlight(state, sids, color, previous=None):
    previous = {} if previous is None else previous
    sids = list(sids)
    for sid in sids:
        previous.setdefault(sid, state.custom_colors.get(sid))
    state.set_custom_color(sids, color)
    return previous


def restore_colors(state, previous):
    for sid, color in previous.items():
        state.set_custom_color([sid], color)
