"""Launch this integration checkout with the owner's existing preview data/preferences."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
HUB = Path.home() / "Desktop" / "AnatomyExplorer"
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ["AE_LOCAL_MODEL_LIBRARY"] = str(ROOT / "data" / "local_model_library")
for name in ("AE_REQUIRED_MODEL_GENERATION", "AE_REQUIRED_MODEL_CATALOG_SHA256", "AE_DATASET_READY_FILE"):
    os.environ.pop(name, None)

import app.config as config
config.ORG_NAME = "AnatomyExplorerViewerPreview"
config.USER_DIR = HUB / "Workspace" / "user"
config.LOG_DIR = ROOT / "logs"

from app.__main__ import main
sys.exit(main())
