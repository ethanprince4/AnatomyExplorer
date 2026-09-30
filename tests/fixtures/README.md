# Immutable launcher fixture

`legacy_updater_v3_1_1.py` is the original `app/updater.py` from the released
stable 3.1.1 source (commit `4f3a56a`), captured unchanged before channel edits.
It is test evidence, not app code or an alternate updater distributed to users.

Channel tests execute its real downloader, version parser, state parser,
activation, rollback and cleanup. They exercise 3.1.1 to stable 3.1.2, several
numeric previews and back to the retained stable version. In particular its
three-pointer cleanup remains unchanged; new children must protect the stable
anchor before writing the readiness marker.
