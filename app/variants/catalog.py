"""Active new-model catalog; never imports legacy registration or builds a cache."""
from collections import OrderedDict
import os
from pathlib import Path
import sys

from ..config import FROZEN, ROOT
from .anatomy_variants import AdapterSpec, VariantStore, default_store_root


class ActiveCatalog(OrderedDict):
    is_new_catalog = True
    error = ""
    ready = False
    generation_id = None
    store = None
    verification_state = "pending"


class DeferredVariantEntry:
    """Catalog/descriptor JSON only; payload authority is obtained on the CPU queue."""
    descriptor = None
    verification_state = "pending"
    outcome = None
    credit_html = ""
    order = 100

    def __init__(self, meta, store, variant=None, *, component=None):
        from .anatomy_runtime_adapters.registry import contract
        local = getattr(store, "is_local", False)
        if local:meta=store.metadata(meta.id)
        self.meta, self.store = meta, store
        self.id = self.model_id = meta.id
        self.available_components = (("main", "cell_inset") if any(("cell_inset" in getattr(d,"components",{}) or "cell_inset" in getattr(d,"companions",{})) for d in meta.variants.values()) else ()) if local else (("main", "cell_inset") if self.id == "axillary_skin" else ())
        self.component = component or "main"
        if self.component != "main" and self.component not in self.available_components:
            raise ValueError("Unknown shipped model scene")
        self.variant = store.preferred(self.id) if variant is None else variant
        if self.variant not in meta.variants:
            raise ValueError("Preferred model version is not declared in this catalog")
        self.label = ({"pre": "Before", "post": "After"} if local else {"pre": "Pre refine", "post": "Post refine"})[self.variant]
        self.available_variants = tuple(key for key in ("pre", "post") if key in meta.variants)
        self.kind = "glb" if (meta.variants[self.variant].primary.format if local else contract(self.id)["primary_format"]) == "glb" else "procedural"
        if local:
            self.descriptor = meta.variants[self.variant]
            self.verification_state = "available"
        self.kind_name = ""
        self.oriented = self.kind == "glb"
        for field in ("name", "summary", "targets", "histology", "related", "clinical", "scale_note", "aliases"):
            setattr(self, field, getattr(meta, field))
        self._retire_from_guide()
        if self.id == "whole_heart":
            self.name = "Heart"

    def _retire_from_guide(self):
        """Atlas structures, aliases and tissues the model's part guide says do not belong to it."""
        from ..viewer.part_guide import load_part_guide
        guide = load_part_guide(self.id)
        if isinstance(self.targets, dict) and guide.excluded_targets:
            self.targets = {**self.targets, "structures": [s for s in self.targets.get("structures") or []
                                                           if s not in guide.excluded_targets]}
        if isinstance(self.aliases, dict) and guide.excluded_aliases:
            self.aliases = {k: v for k, v in self.aliases.items() if k not in guide.excluded_aliases}
        if guide.excluded_histology:
            self.histology = [t for t in self.histology or [] if t not in guide.excluded_histology]

    def resolve(self, model, names):
        from ..viewer.catalog import ModelEntry
        return ModelEntry.resolve(self, model, names)

    def commit_selection(self):
        return self.store.select(self.id, self.variant, expected_token=self.descriptor.token)

    def for_variant(self, variant):
        return type(self)(self.meta, self.store, variant, component=self.component)

    def for_component(self, component):
        return type(self)(self.meta, self.store, self.variant, component=component)

    def prepare_cpu(self, token):
        if getattr(self.store, "is_local", False):
            from .local_runtime import prepare_local_model
            self.descriptor = self.store.resolve(self.id, self.variant)
            return prepare_local_model(self, token)
        from .anatomy_runtime_adapters import VariantEntry
        token.check()
        descriptor = self.store.resolve(self.id, self.variant)
        token.check()
        entry = VariantEntry(self.meta, self.store, descriptor, component=self.component)
        model = entry.prepare_cpu(token)
        model.runtime_entry = entry
        return model


class LocalEntry(DeferredVariantEntry):
    """Local files use the same entry API as prepared versions."""


class VariantPreferenceCommit:
    """Revalidate and persist on the serialized CPU queue after GUI opening succeeds."""
    def __init__(self, entry):
        self.entry = entry

    def prepare_cpu(self, token):
        token.check()
        return self.entry.store.select(self.entry.id, self.entry.variant,
            expected_token=self.entry.descriptor.token, before_persist=token.check)


def create_store():
    from .local_library import LocalLibrary, MergedLocalLibrary
    from ..config import USER_BASE
    requested_local = os.environ.get("AE_LOCAL_MODEL_LIBRARY")
    seed = ROOT / "data" / "local_model_library"
    if requested_local:
        local_root = Path(requested_local)
    elif USER_BASE:
        local_root = Path(USER_BASE) / "model-library"
        if not (local_root / "library.json").exists() and not (seed / "library.json").exists():
            local_root = ROOT.parent / "model-library"
    else:
        local_root = ROOT.parent / "model-library"
    preferences = Path(USER_BASE) / "model-library-preferences.json" if USER_BASE else None
    if (seed / "library.json").exists():
        return MergedLocalLibrary(seed, local_root, preferences_path=preferences)
    if requested_local or (local_root / "library.json").exists():
        return LocalLibrary(local_root, preferences_path=preferences)
    from .anatomy_runtime_adapters import EXPECTED_MODEL_IDS, adapter_specs
    from .anatomy_variants import inspect_glb
    requested = os.environ.get("AE_MODEL_VARIANTS_DIR")
    root = Path(requested) if requested else default_store_root()
    if not root.is_absolute():
        raise ValueError("The model data folder must be an absolute user-owned path")
    forbidden = [ROOT]
    if FROZEN:
        from ..updater import store_for
        updates = store_for()
        forbidden.extend((Path(sys.executable).parent, updates.root, updates.base))
    return VariantStore(root, adapters=adapter_specs(AdapterSpec, glb_inspector=inspect_glb),
                        expected_model_ids=EXPECTED_MODEL_IDS, forbidden_roots=forbidden)


def load_active_catalog(*, store=None):
    catalog = ActiveCatalog()
    try:
        catalog.store = store if store is not None else create_store()
        entries = catalog.store.catalog_index()
        for meta in entries:
            entry = DeferredVariantEntry(meta, catalog.store)
            catalog[entry.id] = entry
        if getattr(catalog.store, "is_local", False):
            catalog.ready = True
            catalog.verification_state = "available"
            catalog.generation_id = "local"
            catalog.warnings = list(catalog.store.warnings)
            return catalog
        required = catalog.store.expected_model_ids
        if set(catalog) != set(required):
            raise ValueError("The complete prepared model generation is not installed")
        generations = {descriptor.generation_id for entry in entries for descriptor in entry.variants.values()}
        if len(generations) != 1:
            raise ValueError("Model versions belong to different prepared generations")
        catalog.generation_id = next(iter(generations))
        # A bounded index is never a verified payload or a readiness result.
        catalog.ready = False
    except (OSError, ValueError, ImportError, KeyError, TypeError) as exc:
        catalog.clear()
        if getattr(catalog.store, "is_local", False):
            catalog.error = "The local model library could not be read: " + str(exc)
            catalog.ready = False
            return catalog
        catalog.error = ("New-model data is not ready. Run or resume the preparation launcher to verify and register "
                         "the Pre refine/Post refine pairs, then reopen the app. " + str(exc))
        catalog.ready = False
    return catalog
