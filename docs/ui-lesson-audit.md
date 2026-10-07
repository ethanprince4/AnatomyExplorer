# UI and lesson cleanup

Histology lists tissue images only. The model catalogue owns 3D models. Lesson scenes use anatomy, diagrams, histology or a reading canvas appropriate to the step; a diagram step cannot leave an empty atlas in the main canvas.

Lab groups end at Practical 2. Lecture groups expand as Exam > Chapter > Lesson. Resume is outside the selector. Lesson readers float over their workspaces, do not inherit radiology, and hide model-library instruments. Sequential lessons finish at the next lesson overview. Cardiac muscle starts with every part visible, and the single generic Parts group is flattened.

The complete lesson library has no missing model, part, image or cross-reference targets under the validator. Unsupported model click exercises were removed; authored recall questions and available practice tasks remain. Excluded tissue models link to available histology instead. Renal angiogram labels resolve whole arterial families in the kidney model. Atlas-only controls are disabled outside the atlas.

Unused Sketchfab downloads, their catalogues and download tools were removed from source and packaging. Inactive local-model folders and scratch outputs were archived outside the worktree. Local preview launchers and review history are excluded from Git. Active refined assets, protected GLBs, histology and radiology images are retained.

Validation: 87 focused native-widget tests passed, covering lessons, navigation, catalogues, images, selectors and controls. The lesson validator passed for 303 lessons, 1612 steps, 1523 recall questions and 2418 practice items. Clinical, radiology (104 cases and 452 labels), and licence checks passed. These are CPU/data and native-widget checks, without GPU rendering or screenshot verification. Geometry refinements remain separate from this UI commit.
