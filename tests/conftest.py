"""
OmniMesh Global Pytest Configuration and Shared Test Fixtures.
Provides standard, reusable mock primitives for Blender RNA data structures
(Objects, Meshes, Materials, Sockets, Collections, and Contexts) to avoid
boilerplate proliferation across test modules.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, List, Optional, Tuple
from unittest.mock import MagicMock
import numpy as np
import pytest


# ==============================================================================
# Vector & Matrix Mocks
# ==============================================================================


class MockVector:
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
        if idx == 0:
            return self.x
        elif idx == 1:
            return self.y
        elif idx == 2:
            return self.z
        raise IndexError(f"Index {idx} out of range for MockVector (dim=3)")

    def __setitem__(self, idx: int, val: float) -> None:
        if idx == 0:
            self.x = float(val)
        elif idx == 1:
            self.y = float(val)
        elif idx == 2:
            self.z = float(val)
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


# ==============================================================================
# Shader Node & Socket Mocks
# ==============================================================================


class MockSocket:
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


class MockShaderNode:
    """Mock Blender ShaderNode (BSDF, TexImage, NormalMap, Reroute)."""

    def __init__(self, node_type: str = "BSDF_PRINCIPLED", name: str = "Node", inputs: Optional[Dict[str, Any]] = None):
        self.type = node_type
        self.name = name
        self.inputs = inputs or {}
        self.image: Optional[Any] = None


class MockImage:
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


class MockMaterial:
    """Mock Blender Material datablock with Principled BSDF node tree."""

    def __init__(self, name: str = "M_MockMaterial", use_nodes: bool = True):
        self.name = name
        self.use_nodes = use_nodes
        self.diffuse_color = (0.8, 0.8, 0.8, 1.0)

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
            self.node_tree.nodes = [self.bsdf]
        else:
            self.bsdf = None
            self.node_tree = None


# ==============================================================================
# Geometry & Scene Graph Mocks
# ==============================================================================


class MockPolygon:
    """Mock Blender MeshPolygon with area and material index."""

    def __init__(self, material_index: int = 0, area: float = 1.0):
        self.material_index = material_index
        self.area = area


class MockMaterialSlot:
    """Mock Blender MaterialSlot."""

    def __init__(self, material: Optional[MockMaterial] = None):
        self.material = material


class MockMeshObject:
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
        self.data.materials = [slot.material for slot in self.material_slots if slot.material]
        self.matrix_world = MagicMock()

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


class MockCollection:
    """Mock Blender Collection with object list and hierarchical children."""

    def __init__(self, name: str = "Collection"):
        self.name = name
        self.objects: List[Any] = []
        self._children: Dict[str, MockCollection] = {}

        class ChildrenDict:
            def __init__(self, d: Dict[str, MockCollection]):
                self._d = d

            def get(self, k: str, default: Any = None) -> Any:
                return self._d.get(k, default)

            def __iter__(self):
                return iter(self._d.values())

            def __contains__(self, k: str) -> bool:
                return k in self._d

            def values(self):
                return self._d.values()

        self.children = ChildrenDict(self._children)

    def add_child(self, child: MockCollection) -> None:
        self._children[child.name] = child

    @property
    def all_objects(self) -> List[Any]:
        objs = list(self.objects)
        for c in self._children.values():
            objs.extend(c.all_objects)
        return objs


# ==============================================================================
# Pytest Fixtures
# ==============================================================================


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


@pytest.fixture
def mock_scene_context() -> MagicMock:
    """Provides a cleanly initialized mock Blender context."""
    ctx = MagicMock()
    ctx.scene = MagicMock()
    ctx.view_layer = MagicMock()
    ctx.view_layer.objects.active = None
    ctx.selected_objects = []
    ctx.active_object = None
    return ctx
