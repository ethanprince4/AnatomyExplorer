"""Public model titles, independent of stable authoring IDs and filenames."""

DISPLAY_NAMES = {
    'eyeball': 'Eye',
    'jejunum_comparison_c': 'Jejunum',
    'lung_acinus': 'Lung acinus',
    'lung_acinus_review_v2': 'Lung acinus (version 2)',
    'thyroid_follicles': 'Thyroid follicles',
    'thyroid_parathyroid_review_v2': 'Thyroid and parathyroid',
    'tooth': 'Tooth',
    'female_reproductive': 'Female reproductive system',
    'male_reproductive': 'Male reproductive system',
    'ileocecal_rectum': 'Ileocecal region and rectum',
    'hepatobiliary': 'Hepatobiliary system',
}


def display_name(model_id, supplied_name):
    return DISPLAY_NAMES.get(model_id, supplied_name)
