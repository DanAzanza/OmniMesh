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


def _safe_glob(directory: Path, pattern: str, *, recursive: bool = False) -> list[Path]:
    """Lists matching entries in ``directory``, logging and returning empty on OS errors."""
    try:
        iterator = directory.rglob(pattern) if recursive else directory.glob(pattern)
        return list(iterator)
    except OSError as exc:
        logger.warning("Failed scanning '%s' (%s): %s", directory, pattern, exc)
        return []


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
class MSFSModelOptions:
    """Represents options parsed from [model.options] in model.cfg."""

    with_exterior_show_interior: bool = True
    with_exterior_show_interior_hide_first_lod: bool = False
    with_interior_force_first_lod: bool = False
    with_interior_show_exterior: bool = True
    is_msfs_2024: bool = True
    has_explicit_section: bool = False


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
    model_options: MSFSModelOptions = field(default_factory=MSFSModelOptions)
    attached_objects_cfg_path: Optional[Path] = None

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


_DTD_OR_ENTITY_RE = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def _find_child_ci(directory: Path, target_lower: str) -> Optional[Path]:
    """Finds a direct child of ``directory`` matching ``target_lower`` case-insensitively."""
    try:
        for entry in directory.iterdir():
            if entry.name.lower() == target_lower:
                return entry
    except OSError as exc:
        logger.debug("Failed traversing '%s': %s", directory, exc)
    return None


def _is_within_boundary(candidate: Path, boundary_root: Optional[Path]) -> bool:
    """Returns True when ``candidate`` resolves inside ``boundary_root`` (or no boundary is set)."""
    if boundary_root is None:
        return True
    try:
        return candidate.resolve().is_relative_to(boundary_root.resolve())
    except OSError:
        return False


def _has_unsafe_path_syntax(part_clean: str) -> bool:
    """Rejects null bytes, UNC paths, and drive-letter prefixes in relative path segments."""
    if "\x00" in part_clean or part_clean.startswith(("\\\\", "//")):
        return True
    if len(part_clean) >= 2 and part_clean[1] == ":" and part_clean[0].isalpha():
        return True
    return False


def resolve_path_ci(
    base: Path,
    *parts: str,
    boundary_root: Optional[Path] = None,
) -> Optional[Path]:
    """Resolves a relative path case-insensitively across all operating systems.

    Correctly resolves parent traversal ('..') and current directory ('.') while
    enforcing optional ``boundary_root`` confinement and blocking absolute/UNC escapes.
    Returns the actual filesystem Path if found, or None if missing or out of bounds.
    """
    current = base.resolve()
    resolved_boundary = boundary_root.resolve() if boundary_root is not None else None
    if not _is_within_boundary(current, resolved_boundary):
        return None

    for part in parts:
        part_clean = part.strip()
        if not part_clean:
            continue
        if _has_unsafe_path_syntax(part_clean):
            logger.warning("Rejected unsafe relative path segment: %r", part)
            return None
        for sp in re.split(r"[/\\]+", part_clean):
            if not sp or sp == ".":
                continue
            if sp == "..":
                current = current.parent
            else:
                if not current.is_dir():
                    return None
                match = _find_child_ci(current, sp.lower())
                if match is None:
                    return None
                current = match
            if not _is_within_boundary(current, resolved_boundary):
                logger.warning("Rejected path escaping package boundary '%s': %r", resolved_boundary, part)
                return None
    return current


def _safe_parse_xml(xml_str: str) -> ET.Element:
    """Parses XML while rejecting DTD/ENTITY declarations."""
    if _DTD_OR_ENTITY_RE.search(xml_str):
        raise ValueError("Forbidden DTD or XML entity declaration in ModelInfo XML")
    return ET.fromstring(xml_str)  # noqa: S314


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

    # 3. Check child directories recursively up to 4 levels down (e.g. PackageSources/SimObjects/Airplanes/<Asset>)
    candidates = [
        candidate
        for candidate in _safe_glob(path, "*", recursive=True)
        if candidate.is_dir() and is_package_root(candidate)
    ]
    if candidates:
        # Score candidates: prefer complete airplane packages over sub-parts (AirplaneParts)
        def _score_candidate(c: Path) -> tuple[int, int, int]:
            # Negative priority for AirplaneParts, positive for Airplanes or common/
            part_penalty = 1 if "airplaneparts" in [p.lower() for p in c.parts] else 0
            has_common = 0 if resolve_path_ci(c, "common", "model", "model.cfg") else 1
            return (part_penalty, has_common, len(c.parts))

        candidates.sort(key=_score_candidate)
        return candidates[0]

    # 4. Fallback: if direct model.cfg or flight_model.cfg in path
    if (path / "model.cfg").is_file() or (path / "flight_model.cfg").is_file():
        return path

    return path if path.is_dir() else None


def parse_model_options(model_cfg_path: Path) -> MSFSModelOptions:
    """Parses [model.options] section in model.cfg if present."""
    if not model_cfg_path.is_file():
        return MSFSModelOptions(has_explicit_section=False)

    options_dict: dict[str, bool] = {}
    current_section = ""
    has_section = False

    def _to_bool(val: str, default: bool) -> bool:
        v = val.strip().lower()
        if v in ("true", "1", "yes"):
            return True
        if v in ("false", "0", "no"):
            return False
        return default

    try:
        with open(model_cfg_path, "r", encoding="utf-8-sig", errors="replace") as f:
            for line in f:
                line_str = line.strip()
                if not line_str or line_str.startswith(";"):
                    continue
                if ";" in line_str:
                    line_str = line_str.split(";", 1)[0].strip()

                if line_str.startswith("[") and line_str.endswith("]"):
                    current_section = line_str[1:-1].strip().lower()
                    if current_section == "model.options":
                        has_section = True
                    continue

                if current_section == "model.options" and "=" in line_str:
                    key, val = line_str.split("=", 1)
                    options_dict[key.strip().lower()] = _to_bool(val, False)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("Error reading [model.options] from '%s': %s", model_cfg_path, exc)

    if not has_section:
        return MSFSModelOptions(has_explicit_section=False, is_msfs_2024=False)

    return MSFSModelOptions(
        with_exterior_show_interior=options_dict.get("withexterior_showinterior", True),
        with_exterior_show_interior_hide_first_lod=options_dict.get("withexterior_showinterior_hidefirstlod", False),
        with_interior_force_first_lod=options_dict.get("withinterior_forcefirstlod", False),
        with_interior_show_exterior=options_dict.get("withinterior_showexterior", True),
        is_msfs_2024=True,
        has_explicit_section=True,
    )


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
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        logger.warning("Error reading model.cfg '%s': %s", model_cfg_path, exc)

    return result


def _resolve_bounded_child(base_dir: Path, rel_path: str, boundary_root: Optional[Path]) -> Optional[Path]:
    """Resolves ``rel_path`` relative to ``base_dir`` (with CI match fallback) inside ``boundary_root``."""
    cleaned = rel_path.strip()
    if not cleaned or _has_unsafe_path_syntax(cleaned):
        return None
    resolved_ci = resolve_path_ci(base_dir, cleaned, boundary_root=boundary_root)
    if resolved_ci is not None:
        return resolved_ci
    candidate = (base_dir / cleaned).resolve()
    if not _is_within_boundary(candidate, boundary_root):
        logger.warning("Rejected path outside package boundary '%s': %r", boundary_root, rel_path)
        return None
    return candidate


def parse_model_xml(xml_path: Path, *, boundary_root: Optional[Path] = None) -> list[MSFSLODInfo]:
    """Parses ModelInfo XML file and extracts <LODS> entries with minSize and glTF file paths."""
    if not xml_path.is_file():
        return []

    lods: list[MSFSLODInfo] = []
    xml_dir = xml_path.parent
    eff_boundary = boundary_root if boundary_root is not None else xml_dir.parent

    try:
        raw_bytes = xml_path.read_bytes()
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            raw_bytes = raw_bytes[3:]
        try:
            xml_str = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            xml_str = raw_bytes.decode("cp1252", errors="replace")
        root = _safe_parse_xml(xml_str)

        lods_elem = next((elem for elem in root.iter() if elem.tag.lower() == "lods"), None)
        if lods_elem is not None:
            for child in lods_elem:
                if child.tag.lower() != "lod":
                    continue
                raw_min = child.attrib.get("minSize") or child.attrib.get("minsize") or "0"
                try:
                    min_size = float(raw_min)
                except ValueError:
                    min_size = 0.0

                model_file = (
                    child.attrib.get("ModelFile")
                    or child.attrib.get("modelfile")
                    or child.attrib.get("modelFile")
                    or ""
                )
                target_path = _resolve_bounded_child(xml_dir, model_file, eff_boundary) if model_file else None
                if target_path is not None:
                    lods.append(
                        MSFSLODInfo(
                            index=len(lods),
                            min_size=min_size,
                            gltf_path=target_path,
                            exists=target_path.is_file(),
                        )
                    )

    except (ET.ParseError, OSError, ValueError) as exc:
        logger.warning("Failed parsing ModelInfo XML '%s': %s", xml_path, exc)

    # Sort descending by min_size to guarantee highest LOD first, then re-index 0..N
    lods.sort(key=lambda item: item.min_size, reverse=True)
    return [
        MSFSLODInfo(index=i, min_size=lod_item.min_size, gltf_path=lod_item.gltf_path, exists=lod_item.exists)
        for i, lod_item in enumerate(lods)
    ]


class MSFSProjectScanner:
    """High-level scanner that resolves an MSFS aircraft package and yields a typed project manifest."""

    @classmethod
    def _discover_model_cfg(cls, root: Path) -> Optional[Path]:
        """Finds the primary model.cfg within ``root``."""
        cfg = (
            resolve_path_ci(root, "common", "model", "model.cfg", boundary_root=root)
            or resolve_path_ci(root, "model", "model.cfg", boundary_root=root)
            or resolve_path_ci(root, "model.cfg", boundary_root=root)
        )
        if cfg is not None:
            return cfg
        for candidate in _safe_glob(root, "model.cfg", recursive=True):
            if candidate.is_file() and _is_within_boundary(candidate, root):
                return candidate
        return None

    @classmethod
    def _scan_base_models(
        cls,
        root: Path,
        model_cfg_path: Optional[Path],
    ) -> tuple[dict[str, MSFSModelTargetInfo], MSFSModelOptions]:
        """Loads primary model targets and [model.options] from ``model.cfg`` or fallback XMLs."""
        models_dict: dict[str, MSFSModelTargetInfo] = {}
        model_options = MSFSModelOptions(has_explicit_section=False)

        if model_cfg_path and model_cfg_path.is_file():
            model_dir = model_cfg_path.parent
            model_options = parse_model_options(model_cfg_path)
            for target_type, xml_rel in parse_model_cfg(model_cfg_path).items():
                xml_path = _resolve_bounded_child(model_dir, xml_rel, root)
                if xml_path is None:
                    continue
                lods = parse_model_xml(xml_path, boundary_root=root) if xml_path.is_file() else []
                models_dict[target_type] = MSFSModelTargetInfo(
                    target_type=target_type,
                    xml_path=xml_path if xml_path.is_file() else None,
                    lods=lods,
                )
            return models_dict, model_options

        for sdir in (root / "common" / "model", root / "model", root):
            if not sdir.is_dir():
                continue
            for xf in _safe_glob(sdir, "*.xml"):
                lods = parse_model_xml(xf, boundary_root=root)
                if lods:
                    models_dict["normal"] = MSFSModelTargetInfo(target_type="normal", xml_path=xf, lods=lods)
                    return models_dict, model_options
        return models_dict, model_options

    @classmethod
    def _scan_variant_models(
        cls,
        root: Path,
        model_cfg_path: Optional[Path],
        models_dict: dict[str, MSFSModelTargetInfo],
    ) -> dict[str, MSFSModelTargetInfo]:
        """Discovers sibling ``model.<variant>`` directories and classifies base vs variant targets."""
        variants_dict: dict[str, MSFSModelTargetInfo] = {}
        search_roots = [root]
        common_dir = resolve_path_ci(root, "common", boundary_root=root)
        if common_dir and common_dir.is_dir():
            search_roots.append(common_dir)
        if model_cfg_path and model_cfg_path.is_file():
            for p_dir in (model_cfg_path.parent, model_cfg_path.parent.parent):
                if p_dir.is_dir() and _is_within_boundary(p_dir, root) and p_dir not in search_roots:
                    search_roots.append(p_dir)

        variant_dirs: list[Path] = []
        for sroot in search_roots:
            for entry in _safe_glob(sroot, "*"):
                if entry.is_dir() and entry.name.lower().startswith("model."):
                    v_name = entry.name.split(".", 1)[1].strip()
                    if v_name and entry not in variant_dirs:
                        variant_dirs.append(entry)

        for vdir in variant_dirs:
            variant_key = vdir.name.split(".", 1)[1].strip().lower()
            v_cfg = resolve_path_ci(vdir, "model.cfg", boundary_root=root) or (vdir / "model.cfg")
            if not v_cfg.is_file():
                continue
            v_targets = parse_model_cfg(v_cfg)
            v_xml_rel = v_targets.get("normal") or v_targets.get("exterior") or v_targets.get("interior")
            if not v_xml_rel:
                continue
            v_xml_path = _resolve_bounded_child(vdir, v_xml_rel, root)
            if v_xml_path is None:
                continue
            v_lods = parse_model_xml(v_xml_path, boundary_root=root) if v_xml_path.is_file() else []
            xml_if_exists = v_xml_path if v_xml_path.is_file() else None
            if variant_key in ("interior", "cockpit") or (
                "interior" in v_targets and "normal" not in v_targets and "exterior" not in v_targets
            ):
                models_dict["interior"] = MSFSModelTargetInfo(
                    target_type="interior", xml_path=xml_if_exists, lods=v_lods
                )
            elif variant_key in ("exterior", "normal", "base") and "normal" not in models_dict:
                models_dict["normal"] = MSFSModelTargetInfo(target_type="normal", xml_path=xml_if_exists, lods=v_lods)
            else:
                variants_dict[variant_key] = MSFSModelTargetInfo(
                    target_type="variant", xml_path=xml_if_exists, lods=v_lods
                )
        return variants_dict

    @classmethod
    def _discover_attached_objects_cfg(cls, root: Path) -> Optional[Path]:
        """Finds MSFS 2024 ``attached_objects.cfg`` or ``attachment.cfg`` within ``root``."""
        direct = (
            resolve_path_ci(root, "common", "config", "attached_objects.cfg", boundary_root=root)
            or resolve_path_ci(root, "config", "attached_objects.cfg", boundary_root=root)
            or resolve_path_ci(root, "attached_objects.cfg", boundary_root=root)
        )
        if direct is not None:
            return direct
        att_root = resolve_path_ci(root, "attachments", boundary_root=root)
        if att_root and att_root.is_dir():
            for cand in _safe_glob(att_root, "*.cfg", recursive=True):
                if cand.name.lower() in ("attached_objects.cfg", "attachment.cfg") and cand.is_file():
                    return cand
        return None

    @classmethod
    def scan(cls, folder_path: Path | str) -> MSFSProjectManifest:
        """Scans the given folder or auto-discovered package root and builds an MSFSProjectManifest."""
        root = find_package_root(folder_path) or Path(folder_path).resolve()
        asset_name = sanitize_asset_name(root.name)

        model_cfg_path = cls._discover_model_cfg(root)
        models_dict, model_options = cls._scan_base_models(root, model_cfg_path)
        variants_dict = cls._scan_variant_models(root, model_cfg_path, models_dict)

        flight_model_cfg = (
            resolve_path_ci(root, "common", "config", "flight_model.cfg", boundary_root=root)
            or resolve_path_ci(root, "config", "flight_model.cfg", boundary_root=root)
            or resolve_path_ci(root, "flight_model.cfg", boundary_root=root)
        )
        systems_cfg = (
            resolve_path_ci(root, "common", "config", "systems.cfg", boundary_root=root)
            or resolve_path_ci(root, "config", "systems.cfg", boundary_root=root)
            or resolve_path_ci(root, "systems.cfg", boundary_root=root)
            or resolve_path_ci(root, "common", "config", "light.cfg", boundary_root=root)
            or resolve_path_ci(root, "config", "light.cfg", boundary_root=root)
            or resolve_path_ci(root, "light.cfg", boundary_root=root)
        )
        cameras_cfg = (
            resolve_path_ci(root, "common", "config", "cameras.cfg", boundary_root=root)
            or resolve_path_ci(root, "config", "cameras.cfg", boundary_root=root)
            or resolve_path_ci(root, "cameras.cfg", boundary_root=root)
        )
        attached_objects_cfg = cls._discover_attached_objects_cfg(root)

        return MSFSProjectManifest(
            package_root=root,
            asset_name=asset_name,
            model_cfg_path=model_cfg_path,
            models=models_dict,
            flight_model_cfg_path=flight_model_cfg,
            systems_cfg_path=systems_cfg,
            cameras_cfg_path=cameras_cfg,
            variants=variants_dict,
            model_options=model_options,
            attached_objects_cfg_path=attached_objects_cfg,
        )
