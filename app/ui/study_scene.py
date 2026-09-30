"""Restore the learner's scene and history after a temporary study session."""


def capture_scene(window):
    return {"view": window.capture_view(), "undo": list(window.state._undo),
            "center": window.center.currentWidget()}


def restore_scene(window, snapshot):
    window.apply_view(snapshot["view"], animate=False)
    # Restoring a saved view normally adds an undo entry. Study setup and the
    # question's peel operations belong to the temporary session instead.
    window.state._undo = snapshot["undo"]
    try:
        index = window.center.indexOf(snapshot["center"])
    except RuntimeError:  # the learner closed that model tab during the session
        index = -1
    window.center.setCurrentIndex(max(0, index))
