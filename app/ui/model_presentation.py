"""Plain display names and selectable families, preserving authored model keys."""
import re

from ..terminology import american_text


VIEW_TITLES = {
    'kidney_nephron': {
        'Family overview (nephron 15x)': 'Kidney and nephron',
        'Kidney': 'Whole kidney',
        'Nephron (15x schematic)': 'Nephron · enlarged 15×',
        'Source section overview': 'Kidney tissue section',
        'Source section opened': 'Kidney tissue section, opened',
        'Source section lobule': 'Renal lobule section',
    },
    'blood_cells': {'Preserved nuclear sections': 'Blood cell nuclei in section'},
    'colon_wall': {'Whole block': 'Colon wall'},
    'duodenum': {'Whole block': 'Duodenal wall'},
    'ear': {'Inner ear and VIII sample': 'Inner ear and vestibulocochlear nerve'},
    'female_reproductive': {
        'Existing development source inset': 'Development',
        'Ovarian source section': 'Ovary section',
        'Ampullary source section': 'Uterine tube section',
        'Endometrial source section': 'Endometrium section',
        'Mammary source section': 'Breast section',
    },
    'compact_bone': {'12 Native corner section': 'Corner cutaway'},
    'trachea_wall': {'08 Restored posterior gland': 'Posterior gland, intact'},
    'male_reproductive': {'Source overview': 'Male reproductive anatomy'},
    'neuron': {'Whole model': 'Neuron, node and synapse',
               'Cleft proteins (membranes hidden)': 'Synaptic cleft proteins'},
    'spleen': {'07 Slit transit end-on': 'Splenic sinus slit, end-on'},
    'liver_lobule': {
        'Restored hepatocyte host': 'Hepatocyte and surrounding tissue',
        'Endothelial whole nucleus and local host': 'Sinusoidal endothelial nucleus',
        'Restored endothelial nuclear bulge': 'Endothelial nucleus at sinusoid wall',
    },
    'lung_acinus_review_v2': {
        'Restored local specimen walls': 'Alveolar walls',
        'Type I lining in its intact septal host': 'Type I pneumocyte in alveolar septum',
        'Type II cell in its intact alveolar host': 'Type II pneumocyte in alveolar wall',
    },
    'thin_skin': {'Opened gross context': 'Opened skin', 'Intact restored specimen': 'Intact skin'},
    'tongue_papillae': {'Muscle host section': 'Tongue muscle section',
                       'Muscle host restored': 'Tongue muscle, intact'},
}

# These presets remain callable by authored lessons and saved view references.
HIDDEN_CHOOSER_VIEWS = {'kidney_nephron': {'Lobe', 'Lobe opened'}}

# Location-qualified mesh patches are one continuous anatomical structure.
# The separate, schematic source-section model retains its own hierarchy.
STRUCTURE_FAMILIES = {'kidney_nephron': {
    'Gross / renal cortex': 'Renal cortex',
    'Gross / renal column': 'Renal columns',
}}


def view_title(model_id, key, record=None):
    record = record or {}
    if key == 'Full teaching model':
        return 'Overview'
    supplied = str(record.get('title') or record.get('label') or key).strip()
    title = VIEW_TITLES.get(model_id, {}).get(key, supplied)
    title = re.sub(r'^\d+\s*[.:-]?\s+(?=\D)', '', title)
    if title.casefold() == 'overview' and key != 'Full teaching model' and model_id != 'whole_heart':
        title = 'Main specimen'
    return american_text(title)


def chooser_views(model_id, names):
    hidden = HIDDEN_CHOOSER_VIEWS.get(model_id, ())
    return [name for name in names if name not in hidden]


def structure_family_title(model_id, group_key):
    return STRUCTURE_FAMILIES.get(model_id, {}).get(group_key)
