"""Public model titles, independent of stable authoring IDs and filenames."""

DISPLAY_NAMES = {'elastic_artery': 'Elastic Artery', 'eyeball': 'Eye', 'female_reproductive': 'Female Reproductive System', 'hepatobiliary': 'Hepatobiliary System', 'ileocecal_rectum': 'Ileocecal Region and Rectum', 'kidney_section': 'Kidney Section', 'liver_lobule': 'Liver Lobule', 'lung_acinus_review_v2': 'Lung Acinus', 'lymph_node': 'Lymph Node', 'male_reproductive': 'Male Reproductive System', 'muscular_artery': 'Muscular Artery', 'peripheral_nerve': 'Peripheral Nerve', 'retina': 'Retina', 'skeletal_muscle': 'Skeletal Muscle', 'trachea_wall': 'Tracheal Wall', 'vein_wall': 'Vein Wall', 'thyroid_parathyroid_review_v2': 'Thyroid and Parathyroid', 'whole_heart': 'Heart', 'cardiac_muscle': 'Cardiac Muscle', 'kidney_nephron': 'Kidney', 'axillary_skin': 'Axillary Skin', 'blood_cells': 'Blood Cells', 'cornea': 'Cornea', 'compact_bone': 'Compact Bone', 'ear': 'Ear'}


def display_name(model_id, supplied_name):
    return DISPLAY_NAMES.get(model_id, supplied_name)
