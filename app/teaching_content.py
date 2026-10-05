"""Reviewed Content03 presentation-only correction. Never modifies geometry caches."""
ORIGINAL = 'Endoneurium: loose connective tissue (fine collagen, fibroblasts, a few mast cells and macrophages) between the individual nerve fibres inside a fascicle, bathed in endoneurial fluid. After an axon is cut, its endoneurial tube with the Schwann cells inside (bands of Büngner) guides regrowth at about 1–3 mm per day - which is why axonotmesis recovers and neurotmesis needs repair.'
CORRECTED = 'Endoneurium: loose connective tissue between individual nerve fibres inside a fascicle. After axonal injury, repair Schwann cells form guidance tracks (bands of Büngner) within surviving basal-lamina tubes. Preserved pathways favour directed regrowth; disrupted pathways and scarring can misdirect or block it. Axonal regrowth alone does not guarantee useful functional recovery.'
SAMPLE_NOTE = ' Representative teaching sample: three fascicles and enlarged fibres; not a literal nerve census or clinical fibre scale.'
def description(model_id, part_name, current):
    if model_id == "peripheral_nerve" and part_name == "Endoneurium":
        if current not in (ORIGINAL, CORRECTED, ORIGINAL + SAMPLE_NOTE, CORRECTED + SAMPLE_NOTE):
            raise ValueError("Endoneurium source content drift; editorial review required")
        return CORRECTED + (SAMPLE_NOTE if current.endswith(SAMPLE_NOTE) else "")
    return current
