"""OmniMesh Global Pytest Configuration and Shared Test Fixtures."""

from __future__ import annotations
import os
from typing import TYPE_CHECKING as _TC, Any as _Any, Generator

if _TC:
    _MockBase: type[_Any] = object
else:
    _MockBase = object

import math
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock
import numpy as np
import pytest


# --- Vector & Matrix Mocks ---


class MockVector(_MockBase):
    """Mock Blender/mathutils 3D Vector."""

    def __init__(self, x: float | Tuple[float, float, float] | List[float] = 0.0, y: float = 0.0, z: float = 0.0):
        if isinstance(x, (tuple, list)):
            self.x = float(x[0])
            self.y = float(x[1])
            self.z = float(x[2])
        else:
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)

    def __getitem__(self, idx: int) -> float:
        if idx in (0, 1, 2):
            return (self.x, self.y, self.z)[idx]
        raise IndexError(f"Index {idx} out of range for MockVector (dim=3)")

    def __setitem__(self, idx: int, val: float) -> None:
        if idx in (0, 1, 2):
            setattr(self, ("x", "y", "z")[idx], float(val))
        else:
            raise IndexError(f"Index {idx} out of range for MockVector (dim=3)")

    def __sub__(self, other: Any) -> MockVector:
        ox = other[0] if isinstance(other, (list, tuple)) else getattr(other, "x", other[0])
        oy = other[1] if isinstance(other, (list, tuple)) else getattr(other, "y", other[1])
        oz = other[2] if isinstance(other, (list, tuple)) else getattr(other, "z", other[2])
        return MockVector(self.x - ox, self.y - oy, self.z - oz)

    def __add__(self, other: Any) -> MockVector:
        ox = other[0] if isinstance(other, (list, tuple)) else getattr(other, "x", other[0])
        oy = other[1] if isinstance(other, (list, tuple)) else getattr(other, "y", other[1])
        oz = other[2] if isinstance(other, (list, tuple)) else getattr(other, "z", other[2])
        return MockVector(self.x + ox, self.y + oy, self.z + oz)

    def __mul__(self, scalar: float) -> MockVector:
        return MockVector(self.x * scalar, self.y * scalar, self.z * scalar)

    @property
    def length(self) -> float:
        return math.sqrt(self.x**2 + self.y**2 + self.z**2)

    def dot(self, other: Any) -> float:
        ox = other[0] if isinstance(other, (list, tuple)) else getattr(other, "x", other[0])
        oy = other[1] if isinstance(other, (list, tuple)) else getattr(other, "y", other[1])
        oz = other[2] if isinstance(other, (list, tuple)) else getattr(other, "z", other[2])
        return self.x * ox + self.y * oy + self.z * oz

    def normalized(self) -> MockVector:
        mag = self.length
        if mag < 1e-12:
            return MockVector(0.0, 0.0, 0.0)
        return MockVector(self.x / mag, self.y / mag, self.z / mag)

    def copy(self) -> MockVector:
        return MockVector(self.x, self.y, self.z)

    def __repr__(self) -> str:
        return f"MockVector(({self.x:.4f}, {self.y:.4f}, {self.z:.4f}))"


class MockQuaternion(_MockBase):
    """Mock Blender/mathutils Quaternion."""

    def __init__(
        self,
        w: float | Tuple[float, float, float, float] | List[float] = 1.0,
        x: float = 0.0,
        y: float = 0.0,
        z: float = 0.0,
    ):
        if isinstance(w, (tuple, list)):
            self.w = float(w[0])
            self.x = float(w[1])
            self.y = float(w[2])
            self.z = float(w[3])
        else:
            self.w = float(w)
            self.x = float(x)
            self.y = float(y)
            self.z = float(z)

    def __getitem__(self, idx: int) -> float:
        if idx == 0:
            return self.w
        elif idx == 1:
            return self.x
        elif idx == 2:
            return self.y
        elif idx == 3:
            return self.z
        raise IndexError(f"Index {idx} out of range for MockQuaternion (dim=4)")

    def __setitem__(self, idx: int, val: float) -> None:
        if idx == 0:
            self.w = float(val)
        elif idx == 1:
            self.x = float(val)
        elif idx == 2:
            self.y = float(val)
        elif idx == 3:
            self.z = float(val)
        else:
            raise IndexError(f"Index {idx} out of range for MockQuaternion (dim=4)")

    def dot(self, other: Any) -> float:
        ow = other[0] if isinstance(other, (list, tuple)) else getattr(other, "w", other[0])
        ox = other[1] if isinstance(other, (list, tuple)) else getattr(other, "x", other[1])
        oy = other[2] if isinstance(other, (list, tuple)) else getattr(other, "y", other[2])
        oz = other[3] if isinstance(other, (list, tuple)) else getattr(other, "z", other[3])
        return self.w * ow + self.x * ox + self.y * oy + self.z * oz

    @property
    def magnitude(self) -> float:
        return math.sqrt(self.w**2 + self.x**2 + self.y**2 + self.z**2)

    def normalized(self) -> MockQuaternion:
        mag = self.magnitude
        if mag < 1e-12:
            return MockQuaternion(1.0, 0.0, 0.0, 0.0)
        return MockQuaternion(self.w / mag, self.x / mag, self.y / mag, self.z / mag)

    def normalize(self) -> None:
        mag = self.magnitude
        if mag > 1e-12:
            self.w /= mag
            self.x /= mag
            self.y /= mag
            self.z /= mag

    def copy(self) -> MockQuaternion:
        return MockQuaternion(self.w, self.x, self.y, self.z)

    def __repr__(self) -> str:
        return f"MockQuaternion(({self.w:.4f}, {self.x:.4f}, {self.y:.4f}, {self.z:.4f}))"


# --- Shader Node & Socket Mocks ---


class MockSocket(_MockBase):
    """Mock Blender NodeSocket with default values, link support, and connection state."""

    def __init__(self, default_value: Any = 0.0, linked_node: Optional[Any] = None, name: str = "Socket"):
        self.name = name
        self.default_value = default_value
        self.is_linked = linked_node is not None
        self.links: List[Any] = []
        if linked_node:

            class MockLink:
                def __init__(self, from_node: Any):
                    self.from_node = from_node

            self.links = [MockLink(linked_node)]


class MockShaderNode(_MockBase):
    """Mock Blender ShaderNode (BSDF, TexImage, NormalMap, Reroute)."""

    def __init__(self, node_type: str = "BSDF_PRINCIPLED", name: str = "Node", inputs: Optional[Dict[str, Any]] = None):
        self.type = node_type
        self.name = name
        self.inputs = inputs or {}
        self.image: Optional[Any] = None


class MockImage(_MockBase):
    """Mock Blender Image datablock with fast vectorized foreach_get pixel buffer."""

    def __init__(self, size: Tuple[int, int] = (64, 64), name: str = "T_MockImage", fill_val: float = 0.5):
        self.size = size
        self.name = name
        self.colorspace_settings = MagicMock()
        self.colorspace_settings.name = "Non-Color"
        num_floats = size[0] * size[1] * 4
        self._pixels = np.full(num_floats, fill_val, dtype=np.float32)

    @property
    def pixels(self) -> Any:
        raw = self._pixels

        class PixelsWrapper:
            def __init__(self, data: np.ndarray):
                self.data = data

            def foreach_get(self, dest: np.ndarray) -> None:
                np.copyto(dest, self.data)

            def foreach_set(self, src: np.ndarray) -> None:
                np.copyto(self.data, src)

        return PixelsWrapper(raw)


class MockConstraintList(list):
    """List subclass simulating Blender obj.constraints collection."""

    def new(self, type: str = "") -> Any:
        c = MagicMock()
        c.type = type
        self.append(c)
        return c

    def remove(self, c: Any) -> None:
        if c in self:
            super().remove(c)


class MockNodeList(list):
    """List subclass simulating Blender node_tree.nodes container."""

    def new(self, type: str = "") -> Any:
        from collections import defaultdict

        node = MagicMock()
        node.type = type
        node.inputs = defaultdict(MagicMock)
        node.outputs = defaultdict(MagicMock)
        self.append(node)
        return node

    def remove(self, node: Any) -> None:
        if node in self:
            super().remove(node)

    def get(self, name: str, default: Any = None) -> Any:
        for node in self:
            if getattr(node, "name", None) == name:
                return node
        return default


class MockScene(_MockBase):
    """Mock Blender Scene datablock."""

    def __init__(self, name: str = "Scene"):
        self.name = name
        self.collection = MockCollection(name=f"{name} Collection")
        self.camera = None
        self.world = None
        self.render = MagicMock()
        self.view_layers: list[Any] = []
        self.objects: list[Any] = []


class MockMaterial(_MockBase):
    """Mock Blender Material datablock with Principled BSDF node tree."""

    def __init__(self, name: str = "M_MockMaterial", use_nodes: bool = True):
        self.name = name
        self.use_nodes = use_nodes
        self.diffuse_color = (0.8, 0.8, 0.8, 1.0)
        self.users = 1
        self.blend_method = "OPAQUE"
        self.surface_render_method = "DITHERED"
        self.use_transparent_shadow = True
        self.use_backface_culling = False
        self.use_backface_culling_shadow = False

        if use_nodes:
            self.bsdf = MockShaderNode(
                node_type="BSDF_PRINCIPLED",
                name="Principled BSDF",
                inputs={
                    "Base Color": MockSocket([0.8, 0.8, 0.8, 1.0], name="Base Color"),
                    "Metallic": MockSocket(0.0, name="Metallic"),
                    "Roughness": MockSocket(0.5, name="Roughness"),
                    "Ambient Occlusion": MockSocket(1.0, name="Ambient Occlusion"),
                    "Normal": MockSocket([0.0, 0.0, 0.0], name="Normal"),
                },
            )
            self.node_tree = MagicMock()
            self.node_tree.nodes = MockNodeList([self.bsdf])
            self.node_tree.links = MagicMock()
        else:
            self.bsdf = None
            self.node_tree = None


# --- Geometry & Scene Graph Mocks ---


class MockPolygon(_MockBase):
    """Mock Blender MeshPolygon with area and material index."""

    def __init__(self, material_index: int = 0, area: float = 1.0):
        self.material_index = material_index
        self.area = area


class MockMaterialSlot(_MockBase):
    """Mock Blender MaterialSlot."""

    def __init__(self, material: Optional[MockMaterial] = None):
        self.material = material


class MockMeshObject(_MockBase):
    """Standard Mock Blender Mesh Object with polygons, material slots, and visibility."""

    def __init__(
        self,
        name: str = "SM_MockObject",
        obj_type: str = "MESH",
        poly_count: int = 10,
        area_per_poly: float = 1.0,
    ):
        self.name = name
        self.type = obj_type
        self.hide_viewport = False
        self._hidden_layer = False
        self._selected = False
        self.custom_props: Dict[str, Any] = {}

        # Material slots and mesh data
        self.material_slots: List[MockMaterialSlot] = [MockMaterialSlot(MockMaterial("M_Default"))]
        self.data = MagicMock()
        self.data.polygons = [MockPolygon(material_index=0, area=area_per_poly) for _ in range(poly_count)]
        self.data.vertices = []
        self.data.materials = [slot.material for slot in self.material_slots if slot.material]
        self.modifiers: List[Any] = []
        self.bound_box: Tuple[Tuple[float, float, float], ...] = (
            (-1.0, -1.0, -1.0),
            (-1.0, -1.0, 1.0),
            (-1.0, 1.0, 1.0),
            (-1.0, 1.0, -1.0),
            (1.0, -1.0, -1.0),
            (1.0, -1.0, 1.0),
            (1.0, 1.0, 1.0),
            (1.0, 1.0, -1.0),
        )
        self.users_collection: List[Any] = []
        self.parent: Optional[Any] = None
        self.children: List[Any] = []
        self.matrix_world = MagicMock()
        self.matrix_parent_inverse = MagicMock()
        self.matrix_basis = MagicMock()
        self.matrix_local = MagicMock()
        self.parent_bone: str = ""
        self.parent_type: str = "OBJECT"
        self.vertex_groups = MockBlendDataContainer()
        self.scale = MockVector(1.0, 1.0, 1.0)
        self.location = MockVector(0.0, 0.0, 0.0)
        self.rotation_euler = MockVector(0.0, 0.0, 0.0)
        self.library: Optional[Any] = None
        self.constraints = MockConstraintList()
        self.animation_data: Optional[Any] = None

    def visible_get(self, view_layer: Optional[Any] = None) -> bool:
        return not self.hide_viewport and not self._hidden_layer

    def evaluated_get(self, depsgraph: Optional[Any] = None) -> Any:
        return self

    def to_mesh(self, preserve_all_data_layers: bool = False, depsgraph: Optional[Any] = None) -> Any:
        return self.data

    def to_mesh_clear(self) -> None:
        pass

    def hide_get(self, view_layer: Optional[Any] = None) -> bool:
        return self._hidden_layer

    def hide_set(self, val: bool, view_layer: Optional[Any] = None) -> None:
        self._hidden_layer = val

    def select_set(self, val: bool) -> None:
        self._selected = val

    def get(self, key: str, default: Any = None) -> Any:
        return self.custom_props.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self.custom_props[key]

    def __setitem__(self, key: str, val: Any) -> None:
        self.custom_props[key] = val


class MockCollectionObjects(list):
    """Simulates Blender Collection.objects RNA collection with link/unlink."""

    def link(self, obj: Any) -> None:
        if obj not in self:
            self.append(obj)

    def unlink(self, obj: Any) -> None:
        if obj in self:
            self.remove(obj)


class MockChildrenDict(_MockBase):
    """Simulates Blender Collection.children with dictionary mapping and link/unlink."""

    def __init__(self, d: Dict[str, MockCollection]):
        self._d = d

    def get(self, k: str, default: Any = None) -> Any:
        return self._d.get(k, default)

    def link(self, child: Any) -> None:
        self._d[child.name] = child

    def unlink(self, child: Any) -> None:
        if child.name in self._d:
            del self._d[child.name]

    def __iter__(self):
        return iter(self._d.values())

    def __contains__(self, k: str) -> bool:
        return k in self._d

    def values(self):
        return self._d.values()


class MockCollection(_MockBase):
    """Mock Blender Collection with object list and hierarchical children."""

    def __init__(self, name: str = "Collection"):
        self.name = name
        self.color_tag: str = "NONE"
        self.hide_viewport: bool = False
        self.hide_render: bool = False
        self.objects: MockCollectionObjects = MockCollectionObjects()
        self._children: Dict[str, MockCollection] = {}
        self.children = MockChildrenDict(self._children)
        self._custom_props: Dict[str, Any] = {}

    def __setitem__(self, key: str, value: Any) -> None:
        self._custom_props[key] = value

    def __getitem__(self, key: str) -> Any:
        return self._custom_props[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._custom_props.get(key, default)

    def add_child(self, child: MockCollection) -> None:
        self._children[child.name] = child

    @property
    def all_objects(self) -> List[Any]:
        objs = list(self.objects)
        for c in self._children.values():
            objs.extend(c.all_objects)
        return objs


# --- BMesh Mocks ---


class MockVert(_MockBase):
    """Canonical Mock BMesh Vertex with deform weights and topological links."""

    def __init__(self, index: int, co: Tuple[float, float, float] = (0.0, 0.0, 0.0)):
        self.index = index
        self.co = MockVector(co)
        self.is_valid = True
        self.link_edges: List[MockEdge] = []
        self.link_faces: List[MockFace] = []
        self._deform_dict: Dict[int, float] = {}

    def __getitem__(self, item: Any) -> Any:
        return self._deform_dict


class MockEdge(_MockBase):
    """Canonical Mock BMesh Edge with length calculation and boundary flags."""

    def __init__(
        self, verts: Tuple[MockVert, MockVert], is_boundary: bool = False, seam: bool = False, smooth: bool = True
    ):
        self.verts = verts
        self.is_valid = True
        self.is_boundary = is_boundary
        self.seam = seam
        self.smooth = smooth
        self.link_faces: List[MockFace] = []
        for v in verts:
            v.link_edges.append(self)

    def calc_length(self) -> float:
        v0, v1 = self.verts
        dx = v0.co[0] - v1.co[0]
        dy = v0.co[1] - v1.co[1]
        dz = v0.co[2] - v1.co[2]
        return math.sqrt(dx * dx + dy * dy + dz * dz)


class MockUVLoop(_MockBase):
    """Canonical Mock BMesh Loop with UV layers."""

    def __init__(self, vert: MockVert, uv: Tuple[float, float] = (0.0, 0.0)):
        self.vert = vert
        self._uv_data = {0: MagicMock(uv=MockVector((uv[0], uv[1], 0.0)))}

    def __getitem__(self, item: Any) -> Any:
        return self._uv_data.get(item, MagicMock(uv=MockVector((0.0, 0.0, 0.0))))


class MockFace(_MockBase):
    """Canonical Mock BMesh Face with area calculation and winding loops."""

    def __init__(
        self,
        verts: List[MockVert],
        material_index: int = 0,
        normal: Tuple[float, float, float] = (0.0, 0.0, 1.0),
    ):
        self.verts = verts
        self.is_valid = True
        self.material_index = material_index
        self.smooth = True
        self.normal = MockVector(normal)
        self.edges: List[MockEdge] = []
        self.loops: List[MockUVLoop] = [MockUVLoop(v) for v in verts]
        for v in verts:
            v.link_faces.append(self)

    def calc_area(self) -> float:
        if len(self.verts) < 3:
            return 0.0
        v0 = self.verts[0].co
        v1 = self.verts[1].co
        v2 = self.verts[2].co
        ax, ay, az = v1[0] - v0[0], v1[1] - v0[1], v1[2] - v0[2]
        bx, by, bz = v2[0] - v0[0], v2[1] - v0[1], v2[2] - v0[2]
        cx = ay * bz - az * by
        cy = az * bx - ax * bz
        cz = ax * by - ay * bx
        return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


class MockBMesh(_MockBase):
    """Canonical Mock BMesh structure containing vertices, edges, and faces."""

    def __init__(self, verts: List[MockVert], edges: List[MockEdge], faces: List[MockFace]):
        self.verts = MagicMock()
        self.verts.__iter__ = lambda self: iter(verts)
        self.verts.__len__ = lambda self: len(verts)
        self.verts.__getitem__ = lambda self, idx: verts[idx]
        self.verts.ensure_lookup_table = MagicMock()
        self.verts.index_update = MagicMock()

        self.edges = MagicMock()
        self.edges.__iter__ = lambda self: iter(edges)
        self.edges.__len__ = lambda self: len(edges)
        self.edges.__getitem__ = lambda self, idx: edges[idx]
        self.edges.ensure_lookup_table = MagicMock()
        self.edges.index_update = MagicMock()

        self.faces = MagicMock()
        self.faces.__iter__ = lambda self: iter(faces)
        self.faces.__len__ = lambda self: len(faces)
        self.faces.__getitem__ = lambda self, idx: faces[idx]
        self.faces.ensure_lookup_table = MagicMock()
        self.faces.index_update = MagicMock()
        self.faces.active = faces[0] if faces else None

        class MockUVLayers(dict):
            active = 0

            def verify(self):
                return 0

        self.loops = MagicMock()
        self.loops.layers = MagicMock()
        self.loops.layers.uv = MockUVLayers({0: 0})

        self.normal_update = MagicMock()
        self.is_wrapped = False

    def free(self) -> None:
        pass


# --- Pytest Fixtures ---


@pytest.fixture
def mock_mesh_factory() -> Callable[[str, int], MockMeshObject]:
    """Factory fixture for quickly instantiating mock meshes."""

    def _create(name: str = "SM_MockMesh", poly_count: int = 10) -> MockMeshObject:
        return MockMeshObject(name=name, poly_count=poly_count)

    return _create


@pytest.fixture
def mock_material_factory() -> Callable[[str], MockMaterial]:
    """Factory fixture for creating mock principled materials."""

    def _create(name: str = "M_MockMaterial") -> MockMaterial:
        return MockMaterial(name=name)

    return _create


class MockBlendDataContainer(_MockBase):
    """Dictionary-backed container simulating bpy.data collections/objects/meshes."""

    def __init__(self, factory: Callable[..., Any] | None = None) -> None:
        self._items: dict[str, Any] = {}
        self._factory = factory

    def get(self, name: str, default: Any = None) -> Any:
        return self._items.get(name, default)

    def new(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if self._factory:
            obj = self._factory(name, *args, **kwargs)
        else:
            obj = MagicMock(name=name)
        obj.name = name
        self._items[name] = obj
        return obj

    def load(self, filepath: str, check_existing: bool = False) -> Any:
        import os

        name = os.path.basename(filepath)
        obj = self.get(name)
        if obj is None:
            obj = MagicMock(name=name, filepath=filepath)
            self._items[name] = obj
        return obj

    def remove(self, obj: Any, do_unlink: bool = True) -> None:
        name = getattr(obj, "name", None)
        if name in self._items:
            del self._items[name]
        else:
            for k, v in list(self._items.items()):
                if v == obj:
                    del self._items[k]
                    break

    def values(self) -> Any:
        return list(self._items.values())

    def keys(self) -> Any:
        return list(self._items.keys())

    def items(self) -> Any:
        return list(self._items.items())

    def __contains__(self, item: Any) -> bool:
        if isinstance(item, str):
            return item in self._items
        return item in self._items.values()

    def __iter__(self) -> Any:
        return iter(self._items.values())

    def __getitem__(self, key: str | int) -> Any:
        if isinstance(key, int):
            return list(self._items.values())[key]
        return self._items[key]

    def __setitem__(self, key: str, item: Any) -> None:
        self._items[key] = item

    def __len__(self) -> int:
        return len(self._items)


class MockBlendData(_MockBase):
    """Canonical Mock Blender Database (bpy.types.BlendData) for DI tests."""

    def __init__(self) -> None:
        self.filepath: str = ""
        self.collections = MockBlendDataContainer(factory=lambda name, *a, **kw: MockCollection(name=name))
        self.objects = MockBlendDataContainer(factory=lambda name, *a, **kw: MockMeshObject(name=name))
        self.meshes = MockBlendDataContainer(factory=lambda name, *a, **kw: MagicMock(name=name))
        self.materials = MockBlendDataContainer(factory=lambda name, *a, **kw: MockMaterial(name=name))
        self.images = MockBlendDataContainer(factory=lambda name, *a, **kw: MagicMock(name=name, filepath=name))
        self.scenes = MockBlendDataContainer(factory=lambda name, *a, **kw: MockScene(name=name))
        self.scenes.new("Scene")
        self.lights = MockBlendDataContainer()
        self.cameras = MockBlendDataContainer(factory=lambda name, *a, **kw: MagicMock(name=name))
        self.actions = MockBlendDataContainer()
        self.armatures = MockBlendDataContainer()
        self.worlds = MockBlendDataContainer(
            factory=lambda name, *a, **kw: MagicMock(name=name, node_tree=MagicMock(nodes=MockBlendDataContainer()))
        )

    def orphans_purge(self, do_local_ids: bool = True, do_linked_ids: bool = True, do_recursive: bool = False) -> int:
        return 0


@pytest.fixture
def mock_scene_context() -> MagicMock:
    """Provides a cleanly initialized mock Blender context."""
    ctx = MagicMock()
    ctx.scene = MagicMock()
    ctx.view_layer = MagicMock()
    ctx.view_layer.objects.active = None
    ctx.selected_objects = []
    ctx.active_object = None
    ctx.blend_data = MockBlendData()
    return ctx


@pytest.fixture(autouse=True, scope="session")
def isolate_session_presets(tmp_path_factory: pytest.TempPathFactory) -> Generator[None, None, None]:
    """Isolate OmniMesh custom preset storage to a transient session directory."""
    temp_dir = tmp_path_factory.mktemp("om_presets")
    old_env = os.environ.get("OMNIMESH_PRESETS_DIR")
    os.environ["OMNIMESH_PRESETS_DIR"] = str(temp_dir)
    try:
        yield
    finally:
        if old_env is not None:
            os.environ["OMNIMESH_PRESETS_DIR"] = old_env
        else:
            os.environ.pop("OMNIMESH_PRESETS_DIR", None)
