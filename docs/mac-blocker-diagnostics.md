Mac diagnostics remain separate from releases while the publication hold is active.

The `Mac blocker diagnostics` PR workflow uses macOS 14, Qt/PySide 6.11.2 and an
actual Cocoa/OpenGL context. Its independent controls render fixed CPU IDs 2, 257,
3922 at predetermined triangle interiors through uniform, integer vertex and
production renderer paths. Atlas pointer checks remain integration coverage: their
expected IDs come from the same attachment, so they do not prove anatomical ID
fidelity. CI's OS/driver differs from the reported macOS 26.6.2 device.

The tree job queries the diagnostic's own synthetic tree using the exact native
`accessibilitySelectedChildren` getter, comparing one/two columns and retained-item
selection follow-ups. It requests no Accessibility permission, touches no study
app, and uploads synthetic JSONL only. It is a discriminator; a pass does not
validate the user's external AX client or physical tree interaction.

The separate `AnatomyExplorer-Mac-Diagnostic` artifact contains an ad-hoc signed
Apple-silicon app with Python/Qt/NumPy/ModernGL and packaged CA roots. It contains
no anatomy geometry, model drafts, updater activation, installer, or personal
data. Its default launch automatically collects GPU controls, runtime/DPR,
loaded Cocoa plugin UUID, installed VERSION/source hashes if present at the fixed
/Applications location, and bounded HTTPS API/manifest/chunk/installer checks.
It compares default OpenSSL trust with explicit packaged roots without disabling
verification. The default-trust control belongs to this diagnostic interpreter,
not the original installed client's interpreter. It performs no tree crash probe.

After its artifact is verified, extract `AnatomyExplorer-Mac-Diagnostic.zip` into
Downloads and launch `Anatomy Explorer Diagnostic.app`. macOS may require the same
normal Open action as the existing ad-hoc app; no quarantine removal, security
setting or new permission is part of these instructions. Alternatively the single
Terminal command after extraction is:

```sh
"$HOME/Downloads/Anatomy Explorer Diagnostic.app/Contents/MacOS/AnatomyExplorerDiagnostic"
```

Allow approximately 30–90 seconds with working HTTPS; network timeouts can take
up to three minutes per isolated task. The completion dialog gives the report
location and Finder selects it: `/tmp/AnatomyExplorer-Diagnostic-*/report.json`
(macOS may display the equivalent `/var/folders/.../T/` temporary path).
Share that JSON manually. Nothing uploads automatically. No source checkout,
Python install, Xcode, or study-app interaction is required. The diagnostic app
and report folder can be removed afterward.

A separate tree action on the user's Mac will only be proposed if CI evidence
requires it: the GPU/TLS command intentionally avoids invoking the known crashing
accessibility getter in the study app. Artifact existence and exact checksum must
be verified before these instructions are presented as ready to run.
