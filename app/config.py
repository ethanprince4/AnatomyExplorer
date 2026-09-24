"""Central place for paths and look-and-feel settings you may want to customize."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "anatomy"
APP_NAME = "Anatomy Explorer"
ORG_NAME = "AnatomyExplorer"

# Surface response per material category: (specular strength, glossiness exponent, rim strength)
SHADING = {
    "bone": (0.10, 18.0, 0.10),
    "suture": (0.05, 10.0, 0.05),
    "tooth": (0.45, 70.0, 0.10),
    "cartilage": (0.35, 48.0, 0.15),
    "ligament": (0.30, 36.0, 0.12),
    "capsule": (0.25, 30.0, 0.12),
    "bursa": (0.50, 60.0, 0.20),
    "tendon": (0.40, 52.0, 0.15),
    "fascia": (0.25, 30.0, 0.10),
    "muscle": (0.18, 26.0, 0.12),
    "heart": (0.30, 40.0, 0.12),
    "origin": (0.15, 20.0, 0.05),
    "insertion": (0.15, 20.0, 0.05),
    "artery": (0.40, 56.0, 0.15),
    "pulm_artery": (0.40, 56.0, 0.15),
    "vein": (0.40, 56.0, 0.15),
    "pulm_vein": (0.40, 56.0, 0.15),
    "duct": (0.35, 48.0, 0.12),
    "nerve": (0.30, 36.0, 0.15),
    "nucleus": (0.15, 20.0, 0.08),
    "white_matter": (0.15, 20.0, 0.08),
    "brain": (0.20, 24.0, 0.10),
    "csf": (0.60, 80.0, 0.25),
    "eye": (0.70, 110.0, 0.20),
    "lymph": (0.30, 40.0, 0.12),
    "gland": (0.30, 36.0, 0.12),
    "organ": (0.35, 44.0, 0.12),
    "lung": (0.25, 30.0, 0.12),
    "airway": (0.35, 44.0, 0.12),
    "gut": (0.40, 48.0, 0.12),
    "mucosa": (0.45, 56.0, 0.12),
    "serosa": (0.50, 60.0, 0.20),
    "biliary": (0.40, 50.0, 0.12),
    "fat": (0.30, 36.0, 0.10),
    "nail": (0.50, 64.0, 0.10),
    "skin": (0.12, 14.0, 0.10),
    "reference": (0.10, 12.0, 0.10),
    "other": (0.20, 24.0, 0.10),
}

BACKGROUND_DARK = ((0.115, 0.130, 0.155), (0.035, 0.040, 0.050))
BACKGROUND_LIGHT = ((0.930, 0.945, 0.960), (0.760, 0.790, 0.830))

DEFAULT_SETTINGS = {
    # appearance
    "color_mode": 0,          # 0 realistic, 1 distinct segments, 2 by system
    "ssao": True,
    "ssao_strength": 1.0,
    "fxaa": True,
    "render_scale": 1.0,
    "dark_background": True,
    "custom_background": False,
    "bg_top": "#1d2127",
    "bg_bottom": "#090a0d",
    "selection_color": "#4dc7ff",
    "hover_color": "#ffd966",
    "ui_scale": 1.0,
    "details_scale": 1.0,
    "label_size": 8.6,
    "max_landmarks": 60,
    "show_gizmo": True,
    "show_hover_tooltip": True,
    "hover_outline": True,
    "show_perf": True,
    # focus
    "ghost_alpha": 0.10,
    "xray_on_search": True,
    "show_landmarks": True,
    "section_labels": True,
    "max_section_labels": 22,
    # mouse & camera
    "fov": 32.0,
    "orbit_sensitivity": 0.35,
    "pan_sensitivity": 1.0,
    "zoom_sensitivity": 1.0,
    "invert_orbit_x": False,
    "invert_orbit_y": False,
    "invert_zoom": False,
    "zoom_to_cursor": True,
    "orbit_around_cursor": False,
    "orbit_button": "Left",
    "pan_button": "Right",
    "key_orbit_step": 15.0,
    "camera_duration": 0.55,
    "auto_rotate_speed": 20.0,
    # behavior
    "click_action": "Select",            # Select | Select and focus
    "double_click_action": "Focus",      # Focus | Isolate | X-ray focus
    "select_both_sides": False,
    "restore_session": True,
}
