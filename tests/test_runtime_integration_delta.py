"""Focused retention/outcome patch fixtures; tiny arrays, no native window or GL."""
import gc
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref
import numpy as np

from app.variants.anatomy_runtime_adapters.runtime import _retire_native_backing
from app.variants.anatomy_runtime_adapters.entry import VariantEntry


class InsetSchemaTests(unittest.TestCase):
    def test_glb_inspector_adapts_store_two_argument_protocol(self):
        from app.variants.anatomy_runtime_adapters.registry import adapter_specs
        from app.variants.anatomy_variants import AdapterSpec
        calls = []
        def inspect(path):
            calls.append(path)
            return 'a' * 64
        spec = adapter_specs(AdapterSpec, glb_inspector=inspect)['ae.kidney_nephron.runtime.v1']
        path = Path('literal-fixture.glb')
        self.assertEqual(spec.inspector(path, 'gltf2-glb'), 'a' * 64)
        self.assertEqual(calls, [path])
        with self.assertRaisesRegex(ValueError, 'schema'):
            spec.inspector(path, 'unrecognized')
        self.assertEqual(calls, [path])

    def test_shipped_inset_schema_matches_verified_component_primary(self):
        from app.variants.anatomy_runtime_adapters.registry import adapter_specs
        from app.variants.anatomy_variants import AdapterSpec
        spec = adapter_specs(AdapterSpec)['ae.axillary_skin.runtime.v1']
        self.assertEqual(spec.required_roles['cell_inset'], spec.components[0].primary_types)
        self.assertNotIn(('npz', 'ae-model-data-v1'), spec.required_roles['cell_inset'])


class RetentionTests(unittest.TestCase):
    def test_source_mesh_color_and_morph_arrays_are_released_after_conversion(self):
        arrays = [np.zeros((3, 3), np.float32) for _ in range(4)]
        refs = [weakref.ref(value) for value in arrays]
        raw_part = SimpleNamespace(mesh=SimpleNamespace(arrays=arrays[:3]), anim={"morph": arrays[3]})
        raw_parts = [raw_part]
        provider = lambda _name, _positions, colors=arrays[0]: colors
        animation = SimpleNamespace(frame=lambda t: t, identity="retained animation dispatch")
        source = SimpleNamespace(_parts=raw_parts, parts=lambda: raw_parts, viewer_vertex_colors=provider,
                                 animation=animation, viewer_teaching_design={"opening": "verified"},
                                 viewer_function_design={"sequences": ["verified"]})
        vertices = np.ones((3, 16), np.float32)
        indices = np.array([0, 1, 2], np.uint32)
        anim_vertices = np.ones((3, 4), np.float16)
        model = SimpleNamespace(source=source, _part_sources=raw_parts, vertices=vertices,
                                indices=indices, anim_vertices=anim_vertices, animation=animation)
        rows = [{"name": "fixture", "clip": False, "bulk": True, "feature": "preserved metadata"}]
        _retire_native_backing(model, rows)
        del arrays, raw_part, raw_parts, provider
        gc.collect()
        self.assertTrue(all(ref() is None for ref in refs), "unneeded decoded backing arrays must not be retained")
        self.assertIs(model.vertices, vertices)
        self.assertIs(model.indices, indices)
        self.assertIs(model.anim_vertices, anim_vertices)
        self.assertIs(model.animation, animation)
        self.assertIs(source.animation, animation)
        self.assertEqual(source.viewer_teaching_design, {"opening": "verified"})
        self.assertEqual(source.viewer_function_design, {"sequences": ["verified"]})
        self.assertTrue(source._parts[0].bulk)
        self.assertFalse(source._parts[0].clip)
        self.assertEqual(source.part_metadata[0]["feature"], "preserved metadata")
        self.assertEqual(model._part_sources, [])
        self.assertIsNone(source.viewer_vertex_colors)
        with self.assertRaisesRegex(RuntimeError, "no rebuild"):
            source.parts()

    def test_metadata_is_detached_from_mutable_input_and_has_no_mesh(self):
        row = {"name": "fixture", "detail": [0, 0, 0, 0], "clip": False}
        source = SimpleNamespace(_parts=[], parts=lambda: [])
        model = SimpleNamespace(source=source, _part_sources=[])
        _retire_native_backing(model, [row])
        row["detail"][0] = 1
        self.assertEqual(source.part_metadata[0]["detail"], [0, 0, 0, 0])
        self.assertFalse(hasattr(source._parts[0], "mesh"))


class OutcomeTests(unittest.TestCase):
    def entry(self, outcome):
        asset = SimpleNamespace(path=Path("unused"), format="npz")
        descriptor = SimpleNamespace(model_id="spleen", adapter_id="ae.spleen.runtime.v1", variant="post",
            label="Post refine", primary=asset, assets={"runtime_controls": asset}, outcome=outcome,
            provenance={"outcome": "changed"}, validation_receipt=Path("unverified-receipt-must-not-be-read"))
        controls = {"native": {"labels_on_open": False, "scale_note": "Verified model scale"}}
        with patch("app.variants.anatomy_runtime_adapters.entry.read_json", return_value=controls) as read:
            entry = VariantEntry({"id": "spleen", "name": "fixture"}, SimpleNamespace(), descriptor)
        self.assertEqual(read.call_count, 1, "only the verified runtime controls are read")
        return entry

    def test_no_change_reads_verified_descriptor_outcome(self):
        entry = self.entry("no_change")
        self.assertEqual(entry.outcome, "no_change")
        self.assertEqual(entry.microrefine_outcome, "no_change")

    def test_unrecognized_verified_outcome_fails_closed(self):
        with self.assertRaises(ValueError):
            self.entry("assumed-copy")


if __name__ == "__main__":
    unittest.main()
