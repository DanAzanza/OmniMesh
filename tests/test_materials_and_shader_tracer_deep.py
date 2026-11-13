"""
Deep tests for core/materials.py covering AST hashing, headless slot compaction,
semantic texture auditing, and micro-material consolidation.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from core import materials as materials_mod
from core.materials import (
    DeepMaterialHasher,
    HeadlessSlotCompactor,
    MaterialCleanOptions,
    MaterialOptimizer,
    SemanticTextureAuditor,
)


class _FakeSocket:
    def __init__(self, name: str, default_value: Any = None) -> None:
        self.name = name
        self.default_value = default_value
        self.links: list[Any] = []

    @property
    def is_linked(self) -> bool:
        return len(self.links) > 0


class _SocketCollection(list):
    def __contains__(self, item: object) -> bool:
        if isinstance(item, str):
            return any(s.name == item for s in self)
        return super().__contains__(item)

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            for sock in self:
                if sock.name == key:
                    return sock
            raise KeyError(key)
        return super().__getitem__(key)

    def get(self, name: str, default: Any = None) -> Any:
        for sock in self:
            if sock.name == name:
                return sock
        return default


class _FakeNode:
    def __init__(self, node_type: str, name: str = "", **attrs: Any) -> None:
        self.type = node_type
        self.name = name or node_type
        self.inputs = _SocketCollection()
        self.outputs = _SocketCollection()
        for key, value in attrs.items():
            setattr(self, key, value)


class _FakeLink:
    def __init__(self, from_node: Any, from_socket: Any, to_node: Any, to_socket: Any) -> None:
        self.from_node = from_node
        self.from_socket = from_socket
        self.to_node = to_node
        self.to_socket = to_socket


class _FakeLinks(list):
    def new(self, from_socket: _FakeSocket, to_socket: _FakeSocket) -> _FakeLink:
        from_node = getattr(from_socket, "_owner", None)
        to_node = getattr(to_socket, "_owner", None)
        link = _FakeLink(from_node, from_socket, to_node, to_socket)
        from_socket.links.append(link)
        to_socket.links.append(link)
        self.append(link)
        return link

    def remove(self, link: Any) -> None:
        if link in self:
            super().remove(link)
        for sock in (getattr(link, "from_socket", None), getattr(link, "to_socket", None)):
            if sock is not None and link in sock.links:
                sock.links.remove(link)


class _FakeNodes(list):
    def __init__(self) -> None:
        super().__init__()
        self.active: Any = None

    def new(self, *, type: str) -> _FakeNode:
        node_type_map = {
            "ShaderNodeEmission": "EMISSION",
            "ShaderNodeTexImage": "TEX_IMAGE",
        }
        node = _FakeNode(node_type_map.get(type, type), name=f"{type}_{len(self)}")
        if type == "ShaderNodeEmission":
            _add_in(node, "Color", (1.0, 1.0, 1.0, 1.0))
            _add_out(node, "Emission")
        self.append(node)
        return node

    def remove(self, node: Any) -> None:
        if node in self:
            super().remove(node)


class _FakeNodeTree:
    def __init__(self) -> None:
        self.nodes = _FakeNodes()
        self.links = _FakeLinks()


def _add_in(node: _FakeNode, name: str, default: Any = None) -> _FakeSocket:
    sock = _FakeSocket(name, default)
    sock._owner = node  # type: ignore[attr-defined]
    node.inputs.append(sock)
    return sock


def _add_out(node: _FakeNode, name: str) -> _FakeSocket:
    sock = _FakeSocket(name, None)
    sock._owner = node  # type: ignore[attr-defined]
    node.outputs.append(sock)
    return sock


def _connect(tree: _FakeNodeTree, from_node: _FakeNode, from_out: str, to_node: _FakeNode, to_in: str) -> _FakeLink:
    link = _FakeLink(from_node, from_node.outputs[from_out], to_node, to_node.inputs[to_in])
    from_node.outputs[from_out].links.append(link)
    to_node.inputs[to_in].links.append(link)
    tree.links.append(link)
    return link


def _make_image(
    name: str = "tex.png",
    *,
    width: int = 2,
    height: int = 2,
    pixels: np.ndarray | None = None,
    colorspace: str = "Non-Color",
    filepath: str = "",
    packed_file: Any = None,
    has_data: bool = False,
    source: str = "FILE",
    raise_foreach: bool = False,
    raise_buffers_free: bool = False,
) -> Any:
    arr = pixels if pixels is not None else np.zeros(width * height * 4, dtype=np.float32)

    class _Pixels:
        def foreach_get(self, out: np.ndarray) -> None:
            if raise_foreach:
                raise RuntimeError("Pixel read error")
            out[:] = arr

    def _buffers_free() -> None:
        if raise_buffers_free:
            raise RuntimeError("Buffer lock")

    return SimpleNamespace(
        name=name,
        size=[width, height],
        pixels=_Pixels(),
        buffers_free=_buffers_free,
        colorspace_settings=SimpleNamespace(name=colorspace),
        filepath=filepath,
        packed_file=packed_file,
        has_data=has_data,
        source=source,
    )


class _FakeMaterial:
    def __init__(self, name: str = "Mat", *, use_nodes: bool = True, tree: _FakeNodeTree | None = None) -> None:
        self.name = name
        self.use_nodes = use_nodes
        self.node_tree = tree
        self.diffuse_color: Any = (0.5, 0.25, 0.1, 1.0)
        self.blend_method = "OPAQUE"
        self.use_backface_culling = False
        self.users = 1


def _make_material(name: str = "Mat", *, use_nodes: bool = True, tree: _FakeNodeTree | None = None) -> Any:
    return _FakeMaterial(name, use_nodes=use_nodes, tree=tree)


def _ns(**kwargs: Any) -> Any:
    return SimpleNamespace(**kwargs)


class TestMaterialsDeep:
    def test_deep_material_hasher_edge_and_isomorphic_graphs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(materials_mod, "bpy", SimpleNamespace(path=SimpleNamespace(abspath=lambda p: p)))

        h_none = DeepMaterialHasher.hash_material(None)
        assert h_none.startswith("") and len(h_none) == 64

        bad_diffuse = _make_material("BadDiff", tree=None)
        bad_diffuse.diffuse_color = 12345  # non-iterable triggers TypeError fallback
        h_bad = DeepMaterialHasher.hash_material(bad_diffuse)
        assert h_bad == DeepMaterialHasher.hash_material(None)

        empty_tree = _FakeNodeTree()
        h_empty_out = DeepMaterialHasher.hash_material(_make_material("NoOut", tree=empty_tree))
        assert len(h_empty_out) == 64 and h_empty_out != h_none

        def _build_graph(prefix: str, use_active_flag: bool) -> Any:
            tree = _FakeNodeTree()
            out_inactive = _FakeNode("OUTPUT_MATERIAL", f"{prefix}_out_inactive", is_active_output=False)
            _add_in(out_inactive, "Surface")
            out_active = _FakeNode("OUTPUT_MATERIAL", f"{prefix}_out_active", is_active_output=use_active_flag)
            _add_in(out_active, "Surface")

            math_node = _FakeNode("MATH", f"{prefix}_math", operation="ADD", blend_type="MIX")
            _add_in(math_node, "Vector", (0.123456, 0.5, "not-float"))
            _add_in(math_node, "Scale", 2.0)
            _add_in(math_node, "Tag", "metallic")
            _add_out(math_node, "Value")

            img = _make_image("Alb.png", width=4, height=4, filepath="//Alb.png", colorspace="sRGB")
            tex = _FakeNode("TEX_IMAGE", f"{prefix}_tex", image=img, color_space="NONE")
            _add_in(tex, "Vector")
            _add_out(tex, "Color")

            # Dangling link with from_node=None + diamond revisit for visited_nodes guard
            dangling = _FakeLink(None, None, math_node, math_node.inputs["Scale"])
            math_node.inputs["Scale"].links.append(dangling)
            tree.nodes.extend([out_inactive, out_active, math_node, tex])
            _connect(tree, math_node, "Value", out_active, "Surface")
            _connect(tree, tex, "Color", math_node, "Vector")
            if not use_active_flag:
                _connect(tree, math_node, "Value", out_inactive, "Surface")
            return _make_material(prefix, tree=tree)

        mat_a = _build_graph("A", True)
        mat_b = _build_graph("B", True)
        assert DeepMaterialHasher.hash_material(mat_a) == DeepMaterialHasher.hash_material(mat_b)

        # Trigger bpy.path.abspath exception fallback & fallback inactive output selection
        monkeypatch.setattr(
            materials_mod,
            "bpy",
            SimpleNamespace(path=SimpleNamespace(abspath=lambda _p: (_ for _ in ()).throw(RuntimeError("bad path")))),
        )
        mat_c = _build_graph("C", False)
        assert len(DeepMaterialHasher.hash_material(mat_c)) == 64

    def test_headless_slot_compactor_numpy_fallback_and_dedup(self) -> None:
        assert HeadlessSlotCompactor.compact_slots(None) == {"slots_removed": 0, "faces_remapped": 0}
        assert HeadlessSlotCompactor.compact_slots(_ns(data=None, material_slots=[])) == {
            "slots_removed": 0,
            "faces_remapped": 0,
        }

        mat_a = _make_material("MatA")
        mat_b = _make_material("MatB")

        class _Slots(list):
            pass

        class _MaterialsList(list):
            def pop(self, index: int = -1) -> Any:  # type: ignore[override]
                return super().pop(index)

        # Scenario 1: early exit when all slots are distinct and used
        polys_clean = [SimpleNamespace(material_index=0), SimpleNamespace(material_index=1)]
        mesh_clean = SimpleNamespace(polygons=polys_clean, materials=_MaterialsList([mat_a, mat_b]))
        obj_clean: Any = SimpleNamespace(
            data=mesh_clean,
            material_slots=_Slots([SimpleNamespace(material=mat_a), SimpleNamespace(material=mat_b)]),
        )
        assert HeadlessSlotCompactor.compact_slots(obj_clean) == {"slots_removed": 0, "faces_remapped": 0}

        # Scenario 2: empty slots + duplicate mat_a + fallback Python polygon remap + positional pop
        class _PositionalMaterialsList(list):
            def pop(self, idx: int = -1) -> Any:  # type: ignore[override]  # no index= kwarg -> forces TypeError fallback
                return super().pop(idx)

        polys = [
            SimpleNamespace(material_index=2),  # duplicate mat_a -> slot 0
            SimpleNamespace(material_index=3),  # mat_b -> slot 1
            SimpleNamespace(material_index=99),  # out of bounds
        ]
        mesh = SimpleNamespace(polygons=polys, materials=_PositionalMaterialsList([None, mat_a, mat_a, mat_b]))
        slots = _Slots(
            [
                SimpleNamespace(material=None),
                SimpleNamespace(material=mat_a),
                SimpleNamespace(material=mat_a),
                SimpleNamespace(material=mat_b),
            ]
        )
        obj: Any = SimpleNamespace(data=mesh, material_slots=slots)
        res = HeadlessSlotCompactor.compact_slots(obj, purge_empty=True, deduplicate_identical=True)
        assert res["slots_removed"] == 2
        assert res["faces_remapped"] == 3
        assert [s.material for s in slots[: len(mesh.materials)]] == [mat_a, mat_b]
        assert len(mesh.materials) == 2

        # Scenario 3: vectorized numpy foreach_get/foreach_set path
        class _NPPolys(list):
            def foreach_get(self, attr: str, arr: np.ndarray) -> None:
                arr[:] = [p.material_index for p in self]

            def foreach_set(self, attr: str, arr: np.ndarray) -> None:
                for p, val in zip(self, arr.tolist(), strict=True):
                    p.material_index = val

        np_polys = _NPPolys([SimpleNamespace(material_index=1), SimpleNamespace(material_index=2)])
        np_mats = _MaterialsList([mat_a, mat_a, mat_b])
        np_slots = _Slots(
            [SimpleNamespace(material=mat_a), SimpleNamespace(material=mat_a), SimpleNamespace(material=mat_b)]
        )
        res_np = HeadlessSlotCompactor.compact_slots(
            _ns(data=SimpleNamespace(polygons=np_polys, materials=np_mats), material_slots=np_slots)
        )
        assert res_np == {"slots_removed": 1, "faces_remapped": 2}
        assert [p.material_index for p in np_polys] == [0, 1]

    def test_semantic_texture_auditor_validity_repair_and_orphans(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_tex = tmp_path / "real.png"
        real_tex.write_bytes(b"png")

        monkeypatch.setattr(materials_mod, "bpy", SimpleNamespace(path=SimpleNamespace(abspath=lambda p: str(p))))

        assert SemanticTextureAuditor.is_image_valid(None) is False
        assert SemanticTextureAuditor.is_image_valid(_make_image(packed_file=object())) is True
        assert SemanticTextureAuditor.is_image_valid(_make_image(has_data=True)) is True
        assert SemanticTextureAuditor.is_image_valid(_make_image(source="GENERATED")) is True
        assert SemanticTextureAuditor.is_image_valid(_make_image(filepath="")) is False
        assert SemanticTextureAuditor.is_image_valid(_make_image(filepath=str(real_tex))) is True
        assert SemanticTextureAuditor.is_image_valid(_make_image(filepath=str(tmp_path / "missing.png"))) is False

        monkeypatch.setattr(
            materials_mod,
            "bpy",
            SimpleNamespace(path=SimpleNamespace(abspath=lambda _p: (_ for _ in ()).throw(RuntimeError("boom")))),
        )
        assert SemanticTextureAuditor.is_image_valid(_make_image(filepath=str(real_tex))) is True

        # Build material with broken TEX_IMAGE feeding SEPARATE_COLOR -> Roughness/Metallic/Base Color/Normal/Other
        assert SemanticTextureAuditor.repair_missing_textures_in_material(None) == 0
        tree = _FakeNodeTree()
        bsdf = _FakeNode("BSDF_PRINCIPLED", "Principled")
        _add_in(bsdf, "Base Color", (0.1, 0.1, 0.1, 1.0))
        _add_in(bsdf, "Roughness", 0.1)
        _add_in(bsdf, "Metallic", 0.9)
        _add_in(bsdf, "Normal")
        _add_in(bsdf, "Custom")

        sep = _FakeNode("SEPARATE_COLOR", "Sep")
        _add_in(sep, "Color")
        _add_out(sep, "Red")
        _add_out(sep, "Green")
        _add_out(sep, "Blue")

        norm_map = _FakeNode("NORMAL_MAP", "NormMap")
        _add_in(norm_map, "Color")
        _add_out(norm_map, "Normal")

        broken_tex = _FakeNode("TEX_IMAGE", "BrokenTex", image=_make_image(filepath=str(tmp_path / "gone.png")))
        _add_out(broken_tex, "Color")

        valid_tex = _FakeNode("TEX_IMAGE", "ValidTex", image=_make_image(filepath=str(real_tex)))
        _add_out(valid_tex, "Color")

        orphan_tex = _FakeNode("TEX_IMAGE", "OrphanTex", image=None)
        _add_out(orphan_tex, "Color")

        tree.nodes.extend([bsdf, sep, norm_map, broken_tex, valid_tex, orphan_tex])
        _connect(tree, broken_tex, "Color", sep, "Color")
        _connect(tree, sep, "Red", bsdf, "Base Color")
        _connect(tree, sep, "Green", bsdf, "Roughness")
        _connect(tree, sep, "Blue", bsdf, "Metallic")
        _connect(tree, broken_tex, "Color", norm_map, "Color")
        _connect(tree, norm_map, "Normal", bsdf, "Normal")
        _connect(tree, broken_tex, "Color", bsdf, "Custom")
        _connect(tree, valid_tex, "Color", bsdf, "Base Color")

        mat = _make_material("RepairMat", tree=tree)
        repaired = SemanticTextureAuditor.repair_missing_textures_in_material(mat)
        assert repaired == 2  # broken_tex and orphan_tex had invalid images
        assert bsdf.inputs["Roughness"].default_value == 0.5
        assert bsdf.inputs["Metallic"].default_value == 0.0
        assert bsdf.inputs["Base Color"].default_value == (0.8, 0.8, 0.8, 1.0)
        assert valid_tex in tree.nodes

        # Remove orphan texture nodes test
        extra_orphan = _FakeNode("TEX_IMAGE", "ExtraOrphan", image=None)
        _add_out(extra_orphan, "Color")
        tree.nodes.append(extra_orphan)
        assert SemanticTextureAuditor.remove_orphan_texture_nodes(None) == 0
        assert SemanticTextureAuditor.remove_orphan_texture_nodes(mat) == 1

    def test_material_optimizer_areas_protection_consolidation_and_full_clean(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert MaterialOptimizer.calculate_material_areas(None) == {}
        assert MaterialOptimizer.get_dominant_material_index({}) == 0
        assert MaterialOptimizer.get_dominant_material_index({0: 1.5, 1: 4.0}) == 1

        # Protection checks
        assert MaterialOptimizer.is_material_protected(None) is False
        assert MaterialOptimizer.is_material_protected(_make_material("Cockpit_Glass", tree=None)) is True
        em_tree = _FakeNodeTree()
        princ = _FakeNode("BSDF_PRINCIPLED", "BSDF")
        _add_in(princ, "Emission Strength", 2.0)
        em_tree.nodes.append(princ)
        assert MaterialOptimizer.is_material_protected(_make_material("Body", tree=em_tree)) is True
        assert MaterialOptimizer.is_material_protected(_make_material("Paint", tree=None)) is False

        # Areas with matrix_world scaling + out-of-range material index
        mat_big = _make_material("Big")
        mat_tiny = _make_material("Tiny")
        mat_glass = _make_material("Glass")

        class _ScaleMatrix:
            def to_scale(self) -> Any:
                return SimpleNamespace(x=2.0, y=2.0, z=2.0)

        polys = [
            SimpleNamespace(material_index=0, area=100.0),
            SimpleNamespace(material_index=1, area=0.1),
            SimpleNamespace(material_index=2, area=0.05),
            SimpleNamespace(material_index=99, area=1.0),
        ]
        mesh = SimpleNamespace(polygons=polys, update=lambda: None, materials=[mat_big, mat_tiny, mat_glass])
        obj: Any = SimpleNamespace(
            type="MESH",
            data=mesh,
            matrix_world=_ScaleMatrix(),
            material_slots=[
                SimpleNamespace(material=mat_big),
                SimpleNamespace(material=mat_tiny),
                SimpleNamespace(material=mat_glass),
            ],
        )
        areas = MaterialOptimizer.calculate_material_areas(obj)
        assert areas[0] == pytest.approx(404.0)
        assert areas[1] == pytest.approx(0.4)

        # Consolidation with fake bmesh
        bm_faces = [SimpleNamespace(material_index=p.material_index) for p in polys]

        class _BMFaces(list):
            def ensure_lookup_table(self) -> None:
                return None

        class _FakeBM:
            def __init__(self) -> None:
                self.faces = _BMFaces(bm_faces)
                self.freed = False

            def from_mesh(self, _m: Any) -> None:
                return None

            def to_mesh(self, _m: Any) -> None:
                for p, bf in zip(polys, bm_faces, strict=True):
                    p.material_index = bf.material_index

            def free(self) -> None:
                self.freed = True

        monkeypatch.setattr(materials_mod, "bpy", SimpleNamespace(path=SimpleNamespace(abspath=lambda p: p)))
        monkeypatch.setattr(materials_mod, "bmesh", SimpleNamespace(new=lambda: _FakeBM()))

        res_cons = MaterialOptimizer.consolidate_micro_materials(
            obj, area_threshold_pct=1.0, protect_semantic_materials=True
        )
        assert res_cons == {"consolidated_slots": 1, "faces_reassigned": 1}
        assert polys[1].material_index == 0
        assert polys[2].material_index == 2  # protected Glass stayed at index 2

        # area_crit branch & all-protected branch
        obj_protected: Any = SimpleNamespace(
            data=SimpleNamespace(polygons=[SimpleNamespace(material_index=0, area=1.0)], update=lambda: None),
            matrix_world=SimpleNamespace(to_scale=lambda: (_ for _ in ()).throw(ValueError("bad mat"))),
            material_slots=[SimpleNamespace(material=mat_glass), SimpleNamespace(material=_make_material("Decal"))],
        )
        assert MaterialOptimizer.consolidate_micro_materials(obj_protected) == {
            "consolidated_slots": 0,
            "faces_reassigned": 0,
        }

        # Scene duplicate merge, orphan purge, clean_orphan_shader_nodes & clean_materials_full
        dup_a1 = _make_material("Hull")
        dup_a2 = _make_material("Hull.001")
        orphan_mat = _make_material("Unused")
        orphan_mat.diffuse_color = (0.1, 0.2, 0.3, 1.0)
        orphan_mat.users = 0

        removed_mats: list[Any] = []

        class _FakeBDataMats(list):
            def remove(self, m: Any, *, do_unlink: bool = True) -> None:
                if m is orphan_mat:
                    raise ReferenceError("cannot remove simulated")
                removed_mats.append(m)
                if m in self:
                    super().remove(m)

        dup_obj: Any = SimpleNamespace(
            type="MESH",
            data=SimpleNamespace(polygons=[SimpleNamespace(material_index=0, area=10.0)], materials=[dup_a2]),
            matrix_world=None,
            material_slots=[SimpleNamespace(material=dup_a2)],
        )
        bdata: Any = SimpleNamespace(materials=_FakeBDataMats([dup_a2, dup_a1, orphan_mat]), objects=[dup_obj])

        opts = MaterialCleanOptions(
            purge_unused_slots=True,
            deduplicate_slots=True,
            merge_duplicate_datablocks=True,
            remove_orphan_nodes=True,
            enable_micro_consolidation=True,
            repair_missing_textures=True,
            purge_orphans_blendfile=True,
        )
        summary = MaterialOptimizer.clean_materials_full([dup_obj], options=opts, blend_data=bdata)
        assert summary["merged_datablocks"] == 1
        assert dup_obj.material_slots[0].material is dup_a1
        assert dup_a2 in removed_mats
        assert summary["purged_orphans"] == 1
        assert MaterialOptimizer.clean_orphan_shader_nodes(blend_data=bdata) == 0
        assert MaterialOptimizer.purge_unused_materials(None) == {"slots_removed": 0, "faces_remapped": 0}
