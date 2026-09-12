"""
OmniMesh MSFS Project Scanner Subsystem.
Provides pure Python, headless auto-discovery and manifest parsing for MSFS 2020 / 2024 aircraft packages.
Discovers model XMLs, LOD glTFs, screen sizes (minSize), flight_model.cfg, systems.cfg, and cameras.cfg.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
from pathlib import Path
import re
from typing import Optional
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MSFSLODInfo:
    """Represents a single LOD entry declared in a ModelInfo XML."""

    index: int
    min_size: float
    gltf_path: Path
    exists: bool


@dataclass(frozen=True)
class MSFSModelTargetInfo:
    """Represents a model target (e.g. 'normal' for exterior or 'interior' for flight deck)."""

    target_type: str  # "normal" or "interior"
    xml_path: Optional[Path]
    lods: list[MSFSLODInfo] = field(default_factory=list)


@dataclass(frozen=True)
class MSFSProjectManifest:
    """Comprehensive manifest discovered for an MSFS aircraft project package."""

    package_root: Path
    asset_name: str
    model_cfg_path: Optional[Path]
    models: dict[str, MSFSModelTargetInfo]  # "normal" -> info, "interior" -> info
    flight_model_cfg_path: Optional[Path]
    systems_cfg_path: Optional[Path]
    cameras_cfg_path: Optional[Path]
    variants: dict[str, MSFSModelTargetInfo] = field(default_factory=dict)

    @property
    def has_geometry(self) -> bool:
        """Returns True if at least one model target or variant has at least one valid glTF LOD."""
        has_base = any(any(lod.exists for lod in m.lods) for m in self.models.values())
        has_var = any(any(lod.exists for lod in v.lods) for v in self.variants.values())
        return has_base or has_var

    @property
    def exterior_model(self) -> Optional[MSFSModelTargetInfo]:
        """Returns the 'normal' (exterior) model info if present."""
        return self.models.get("normal")

    @property
    def interior_model(self) -> Optional[MSFSModelTargetInfo]:
        """Returns the 'interior' model info if present."""
        return self.models.get("interior")


def resolve_path_ci(base: Path, *parts: str) -> Optional[Path]:
    """Resolves a relative path case-insensitively across all operating systems.

    Correctly resolves parent traversal ('..') and current directory ('.').
    Returns the actual filesystem Path if found, or None if any segment does not exist.
    """
    current = base.resolve()
    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        # Sub-split any internal slashes (both / and \)
        subparts = re.split(r"[/\\]+", part_clean)
        for sp in subparts:
            if not sp or sp == ".":
                continue
            if sp == "..":
                current = current.parent
                continue
            if not current.is_dir():
                return None
            target_lower = sp.lower()
            match = None
            try:
                for entry in current.iterdir():
                    if entry.name.lower() == target_lower:
                        match = entry
                        break
            except OSError as exc:
                logger.debug("Failed traversing '%s': %s", current, exc)
                return None
            if match is None:
                return None
            current = match
    return current


def sanitize_asset_name(raw_name: str) -> str:
    """Sanitizes a string into a clean, valid Blender identifier without unwanted vendor prefixes."""
    clean = raw_name.strip()
    # Strip common package prefixes like "MyCompany_" or "asobo-"
    clean = re.sub(r"^(?:mycompany[_\-]|asobo[_\-]|microsoft[_\-])+", "", clean, flags=re.IGNORECASE)
    # Replace non-alphanumeric chars with underscore
    clean = re.sub(r"[^\w]", "_", clean)
    clean = re.sub(r"_+", "_", clean).strip("_")
    if not clean:
        clean = "Aircraft"
    # Ensure it starts with a letter or underscore
    if clean[0].isdigit():
        clean = f"Asset_{clean}"
    return clean[:64]


def find_package_root(start_path: Path | str) -> Optional[Path]:
    """Heuristically detects the aircraft package directory given any folder inside or around it.

    Supports:
    - Package root (e.g. .../MyCompany_Simple_Aircraft)
    - Subdirectories (common, model, config, liveries, presets)
    - Parent directories (e.g. Airplanes/ which contains package directories)
    """
    path = Path(start_path).resolve()
    if not path.exists():
        return None
    if not path.is_dir():
        path = path.parent

    known_subdirs = {
        "config",
        "model",
        "common",
        "flt",
        "panel",
        "sound",
        "soundai",
        "texture",
        "texture.base",
        "liveries",
        "presets",
    }

    def is_package_root(d: Path) -> bool:
        if d.name.lower() in known_subdirs:
            return False
        # Check common/ subdirectory (typical in MSFS 2024 SDK)
        if resolve_path_ci(d, "common", "model", "model.cfg") or resolve_path_ci(
            d, "common", "config", "flight_model.cfg"
        ):
            return True
        # Check if direct child has model or config
        if resolve_path_ci(d, "model", "model.cfg") or resolve_path_ci(d, "config", "flight_model.cfg"):
            return True
        return False

    # 1. Walk up parents up to 4 levels if we might be in a package subfolder
    curr = path
    for _ in range(4):
        if is_package_root(curr):
            return curr
        if curr.parent == curr:
            break
        curr = curr.parent

    # 2. Check current directory
    if is_package_root(path):
        return path

    # 3. Check child directories 1 level down
    try:
        for child in path.iterdir():
            if child.is_dir() and is_package_root(child):
                return child
    except OSError:
        pass

    # 4. Fallback: if direct model.cfg or flight_model.cfg in path
    if (path / "model.cfg").is_file() or (path / "flight_model.cfg").is_file():
        return path

    return path if path.is_dir() else None


def parse_model_cfg(model_cfg_path: Path) -> dict[str, str]:
    """Parses [models] section in model.cfg to extract XML references (normal, interior).

    Returns a mapping such as: {"normal": "SimpleAircraft.xml", "interior": "SimpleAircraft_interior.xml"}
    """
    if not model_cfg_path.is_file():
        return {}
    result: dict[str, str] = {}
    current_section = ""

    try:
        with open(model_cfg_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith(";"):
                    continue
                # Strip inline comments
                if ";" in line_str:
                    line_str = line_str.split(";", 1)[0].strip()

                if line_str.startswith("[") and line_str.endswith("]"):
                    current_section = line_str[1:-1].strip().lower()
                    continue

                if current_section == "models" and "=" in line_str:
                    key, val = line_str.split("=", 1)
                    key = key.strip().lower()
                    val = val.strip().strip("\"'")
                    if key == "exterior":
                        key = "normal"
                    if key and val:
                        result[key] = val
    except Exception as exc:
        logger.warning("Error reading model.cfg '%s': %s", model_cfg_path, exc)

    return result


def parse_model_xml(xml_path: Path) -> list[MSFSLODInfo]:
    """Parses ModelInfo XML file and extracts <LODS> entries with minSize and glTF file paths."""
    if not xml_path.is_file():
        return []

    lods: list[MSFSLODInfo] = []
    xml_dir = xml_path.parent

    try:
        # Parse XML with BOM and encoding tolerance
        raw_bytes = xml_path.read_bytes()
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            raw_bytes = raw_bytes[3:]
        try:
            xml_str = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            xml_str = raw_bytes.decode("cp1252", errors="replace")
        root = ET.fromstring(xml_str)  # noqa: S314

        # Find LODS section (case-insensitive)
        lods_elem = None
        for elem in root.iter():
            if elem.tag.lower() == "lods":
                lods_elem = elem
                break

        if lods_elem is not None:
            lod_index = 0
            for child in lods_elem:
                if child.tag.lower() == "lod":
                    # Extract minSize
                    raw_min = child.attrib.get("minSize") or child.attrib.get("minsize") or "0"
                    try:
                        min_size = float(raw_min)
                    except ValueError:
                        min_size = 0.0

                    # Extract ModelFile
                    model_file = (
                        child.attrib.get("ModelFile")
                        or child.attrib.get("modelfile")
                        or child.attrib.get("modelFile")
                        or ""
                    )
                    if model_file:
                        # Case-insensitive resolution relative to xml_dir
                        resolved_gltf = resolve_path_ci(xml_dir, model_file)
                        target_path = resolved_gltf if resolved_gltf else (xml_dir / model_file)
                        exists = target_path.is_file()

                        lods.append(
                            MSFSLODInfo(
                                index=lod_index,
                                min_size=min_size,
                                gltf_path=target_path,
                                exists=exists,
                            )
                        )
                        lod_index += 1

    except Exception as exc:
        logger.warning("Failed parsing ModelInfo XML '%s': %s", xml_path, exc)

    # Sort descending by min_size to guarantee highest LOD first
    lods.sort(key=lambda item: item.min_size, reverse=True)
    # Re-index to be 0..N strictly sequential
    reindexed = [
        MSFSLODInfo(index=i, min_size=lod_item.min_size, gltf_path=lod_item.gltf_path, exists=lod_item.exists)
        for i, lod_item in enumerate(lods)
    ]
    return reindexed


class MSFSProjectScanner:
    """High-level scanner that resolves an MSFS aircraft package and yields a typed project manifest."""

    @classmethod
    def scan(cls, folder_path: Path | str) -> MSFSProjectManifest:
        """Scans the given folder or auto-discovered package root and builds an MSFSProjectManifest."""
        root = find_package_root(folder_path)
        if root is None:
            root = Path(folder_path).resolve()

        asset_name = sanitize_asset_name(root.name)

        # 1. Locate model.cfg
        model_cfg_path = (
            resolve_path_ci(root, "common", "model", "model.cfg")
            or resolve_path_ci(root, "model", "model.cfg")
            or resolve_path_ci(root, "model.cfg")
        )

        # If model_cfg_path not found, search first matching model.cfg in subdirectories
        if model_cfg_path is None:
            try:
                for candidate in root.rglob("model.cfg"):
                    if candidate.is_file():
                        model_cfg_path = candidate
                        break
            except OSError:
                pass

        # 2. Parse model.cfg targets
        models_dict: dict[str, MSFSModelTargetInfo] = {}
        if model_cfg_path and model_cfg_path.is_file():
            model_dir = model_cfg_path.parent
            model_targets = parse_model_cfg(model_cfg_path)
            for target_type, xml_rel in model_targets.items():
                xml_path = resolve_path_ci(model_dir, xml_rel) or (model_dir / xml_rel)
                lods = parse_model_xml(xml_path) if xml_path.is_file() else []
                models_dict[target_type] = MSFSModelTargetInfo(
                    target_type=target_type,
                    xml_path=xml_path if xml_path.is_file() else None,
                    lods=lods,
                )

        # Fallback if no model.cfg: search for any .xml containing <LODS> in model/ or root
        if not models_dict:
            search_dirs = [root / "common" / "model", root / "model", root]
            for sdir in search_dirs:
                if sdir.is_dir():
                    for xf in sdir.glob("*.xml"):
                        lods = parse_model_xml(xf)
                        if lods:
                            models_dict["normal"] = MSFSModelTargetInfo(
                                target_type="normal",
                                xml_path=xf,
                                lods=lods,
                            )
                            break
                if models_dict:
                    break

        # 3. Discover sibling variant model folders (e.g. model.floats, model.skis)
        variants_dict: dict[str, MSFSModelTargetInfo] = {}
        variant_dirs: list[Path] = []
        search_roots = [root]
        common_dir = resolve_path_ci(root, "common")
        if common_dir and common_dir.is_dir():
            search_roots.append(common_dir)
        if model_cfg_path and model_cfg_path.is_file():
            for p_dir in (model_cfg_path.parent, model_cfg_path.parent.parent):
                if p_dir.is_dir() and p_dir not in search_roots:
                    search_roots.append(p_dir)

        for sroot in search_roots:
            try:
                for entry in sroot.iterdir():
                    if entry.is_dir() and entry.name.lower().startswith("model."):
                        v_name = entry.name.split(".", 1)[1].strip()
                        if v_name and entry not in variant_dirs:
                            variant_dirs.append(entry)
            except OSError:
                pass

        for vdir in variant_dirs:
            variant_key = vdir.name.split(".", 1)[1].strip().lower()
            v_cfg = resolve_path_ci(vdir, "model.cfg") or (vdir / "model.cfg")
            if v_cfg.is_file():
                v_targets = parse_model_cfg(v_cfg)
                v_xml_rel = v_targets.get("normal") or v_targets.get("exterior") or v_targets.get("interior")
                if v_xml_rel:
                    v_xml_path = resolve_path_ci(vdir, v_xml_rel) or (vdir / v_xml_rel)
                    v_lods = parse_model_xml(v_xml_path) if v_xml_path.is_file() else []
                    if variant_key in ("interior", "cockpit") or (
                        "interior" in v_targets and "normal" not in v_targets and "exterior" not in v_targets
                    ):
                        models_dict["interior"] = MSFSModelTargetInfo(
                            target_type="interior",
                            xml_path=v_xml_path if v_xml_path.is_file() else None,
                            lods=v_lods,
                        )
                    elif variant_key in ("exterior", "normal", "base") and "normal" not in models_dict:
                        models_dict["normal"] = MSFSModelTargetInfo(
                            target_type="normal",
                            xml_path=v_xml_path if v_xml_path.is_file() else None,
                            lods=v_lods,
                        )
                    else:
                        variants_dict[variant_key] = MSFSModelTargetInfo(
                            target_type="variant",
                            xml_path=v_xml_path if v_xml_path.is_file() else None,
                            lods=v_lods,
                        )

        # 4. Locate flight_model.cfg
        flight_model_cfg = (
            resolve_path_ci(root, "common", "config", "flight_model.cfg")
            or resolve_path_ci(root, "config", "flight_model.cfg")
            or resolve_path_ci(root, "flight_model.cfg")
        )

        # 5. Locate systems.cfg or light.cfg
        systems_cfg = (
            resolve_path_ci(root, "common", "config", "systems.cfg")
            or resolve_path_ci(root, "config", "systems.cfg")
            or resolve_path_ci(root, "systems.cfg")
            or resolve_path_ci(root, "common", "config", "light.cfg")
            or resolve_path_ci(root, "config", "light.cfg")
            or resolve_path_ci(root, "light.cfg")
        )

        # 6. Locate cameras.cfg
        cameras_cfg = (
            resolve_path_ci(root, "common", "config", "cameras.cfg")
            or resolve_path_ci(root, "config", "cameras.cfg")
            or resolve_path_ci(root, "cameras.cfg")
        )

        return MSFSProjectManifest(
            package_root=root,
            asset_name=asset_name,
            model_cfg_path=model_cfg_path,
            models=models_dict,
            flight_model_cfg_path=flight_model_cfg,
            systems_cfg_path=systems_cfg,
            cameras_cfg_path=cameras_cfg,
            variants=variants_dict,
        )
