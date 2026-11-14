"""Shared Blender RNA lifecycle, deferred enum assignment, and config-collection helpers for UI modules."""

from __future__ import annotations

import logging
from typing import Any, Callable, Sequence

_logger = logging.getLogger(__name__)


def mock_prop(*_args: Any, **_kwargs: Any) -> Any:
    """Fallback bpy.props factory for headless imports; returns typing.Any for get_type_hints()."""
    return Any


def unregister_existing_class(
    bpy_mod: Any,
    cls: Any,
    *,
    logger_inst: logging.Logger | None = None,
) -> None:
    """Unregister any previously registered RNA class with the same name before reload/teardown."""
    if not bpy_mod or not hasattr(bpy_mod, "utils"):
        return
    log = logger_inst or _logger
    cls_name = getattr(cls, "__name__", "cls")
    bpy_types = getattr(bpy_mod, "types", None)
    existing = getattr(bpy_types, cls_name, None) if bpy_types is not None else None
    for candidate in (existing, cls):
        if candidate is None or not getattr(candidate, "is_registered", False):
            continue
        try:
            bpy_mod.utils.unregister_class(candidate)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            log.debug("Safe unregister skipped %s: %s", cls_name, exc)


def register_classes(
    bpy_mod: Any,
    classes: Sequence[Any],
    *,
    logger_inst: logging.Logger | None = None,
) -> None:
    """Safely (re)register Blender RNA classes in declaration order, clearing stale reload entries first."""
    if not bpy_mod or not hasattr(bpy_mod, "utils"):
        return
    log = logger_inst or _logger
    for cls in classes:
        unregister_existing_class(bpy_mod, cls, logger_inst=log)
        try:
            bpy_mod.utils.register_class(cls)
        except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
            log.warning("Could not register %s: %s", getattr(cls, "__name__", "cls"), exc)


def unregister_classes(
    bpy_mod: Any,
    classes: Sequence[Any],
    *,
    logger_inst: logging.Logger | None = None,
) -> None:
    """Safely unregister Blender RNA classes in reverse registration order."""
    if not bpy_mod or not hasattr(bpy_mod, "utils"):
        return
    log = logger_inst or _logger
    bpy_types = getattr(bpy_mod, "types", None)
    for cls in reversed(classes):
        cls_name = getattr(cls, "__name__", "cls")
        existing = getattr(bpy_types, cls_name, None) if bpy_types is not None else None
        unregistered_any = False
        if existing is not None and existing is not cls and getattr(existing, "is_registered", False):
            try:
                bpy_mod.utils.unregister_class(existing)
                unregistered_any = True
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                log.debug("Safe unregister skipped %s: %s", cls_name, exc)
        if not unregistered_any or getattr(cls, "is_registered", False):
            try:
                bpy_mod.utils.unregister_class(cls)
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                log.debug("Safe unregister skipped %s: %s", cls_name, exc)


def assign_or_defer_enum(
    bpy_mod: Any,
    assign_fn: Callable[[], None],
    *,
    first_interval: float = 0.005,
    label: str = "enum assignment",
    logger_inst: logging.Logger | None = None,
) -> None:
    """Execute ``assign_fn`` immediately, deferring via ``bpy.app.timers`` if dynamic enum items are cached."""
    log = logger_inst or _logger
    try:
        assign_fn()
        return
    except (TypeError, ValueError, AttributeError, RuntimeError) as exc:
        log.debug("Immediate %s deferred: %s", label, exc)

    timers = getattr(getattr(bpy_mod, "app", None), "timers", None) if bpy_mod else None
    if timers is None or not hasattr(timers, "register"):
        return

    def _deferred() -> None:
        try:
            assign_fn()
        except Exception as defer_exc:  # noqa: BLE001 - timer callback runs outside operator boundary
            log.debug("Deferred %s skipped: %s", label, defer_exc)

    try:
        timers.register(_deferred, first_interval=first_interval)
    except Exception as timer_exc:  # noqa: BLE001 - headless/mock timer fallback
        log.debug("Could not register timer for %s: %s", label, timer_exc)


def assign_enum_property(
    bpy_mod: Any,
    target: Any,
    attr_name: str,
    value: Any,
    *,
    first_interval: float = 0.005,
    logger_inst: logging.Logger | None = None,
) -> None:
    """Assign a dynamic Blender EnumProperty immediately or via one-shot timer if items are stale."""
    assign_or_defer_enum(
        bpy_mod,
        lambda: setattr(target, attr_name, value),
        first_interval=first_interval,
        label=f"{attr_name} enum assignment",
        logger_inst=logger_inst,
    )


def resolve_config_target_asset(context: Any, asset_name: str = "") -> str:
    """Resolve the active asset name for config subcollections without mutating state."""
    props = getattr(getattr(context, "scene", None), "lod_tool", None)
    target_asset = asset_name or (getattr(props, "export_base_name", "") if props else "")
    if not target_asset and props and hasattr(props, "active_asset") and props.active_asset not in ("AUTO", "NONE"):
        target_asset = props.active_asset
    return str(target_asset or "")


def find_config_role_collection(
    bpy_mod: Any,
    context: Any,
    *,
    role: str,
    suffix: str,
    legacy_names: Sequence[str] = (),
    asset_name: str = "",
) -> Any | None:
    """Locate an existing ``{Asset}_Config/{Asset}_{Suffix}`` subcollection by role or legacy name."""
    if not bpy_mod or not hasattr(bpy_mod, "data"):
        return None
    collections = bpy_mod.data.collections
    target_asset = resolve_config_target_asset(context, asset_name=asset_name)
    col_name = f"{target_asset}_{suffix}" if target_asset else ""

    if target_asset:
        cfg_col = collections.get(f"{target_asset}_Config")
        if cfg_col and hasattr(cfg_col, "children"):
            child = cfg_col.children.get(col_name)
            if child:
                return child
        if col_name in collections:
            return collections[col_name]

    for col in collections:
        if col.get("_omnimesh_role") == role:
            if not target_asset or col.name == col_name or col.get("_omnimesh_parent") == target_asset:
                return col

    for legacy_name in legacy_names:
        if legacy_name in collections:
            return collections[legacy_name]
    return None


def get_or_create_config_role_collection(
    bpy_mod: Any,
    context: Any,
    *,
    role: str,
    suffix: str,
    legacy_names: Sequence[str] = (),
    asset_name: str = "",
    logger_inst: logging.Logger | None = None,
) -> Any | None:
    """Find or create ``{Asset}_Config/{Asset}_{Suffix}`` via hierarchy engine with safe fallback."""
    if not bpy_mod or not context:
        return None
    log = logger_inst or _logger

    existing = find_config_role_collection(
        bpy_mod,
        context,
        role=role,
        suffix=suffix,
        legacy_names=legacy_names,
        asset_name=asset_name,
    )
    if existing:
        return existing

    target_asset = resolve_config_target_asset(context, asset_name=asset_name) or "Asset"
    try:
        from .utils import get_or_create_engine_import_collection

        return get_or_create_engine_import_collection(context, target_asset, role)
    except Exception as exc:  # noqa: BLE001 - fallback ensures manual scene authoring still works
        log.error("Failed creating %s collection via hierarchy: %s", role.lower(), exc, exc_info=True)
        collections = bpy_mod.data.collections
        root_col = collections.get(target_asset)
        if not root_col:
            root_col = collections.new(target_asset)
            context.scene.collection.children.link(root_col)

        cfg_col = collections.get(f"{target_asset}_Config")
        if not cfg_col:
            cfg_col = collections.new(f"{target_asset}_Config")
            cfg_col["_omnimesh_role"] = "CONFIG"
            root_col.children.link(cfg_col)

        role_col_name = f"{target_asset}_{suffix}"
        role_col = collections.get(role_col_name)
        if not role_col:
            role_col = collections.new(role_col_name)
            cfg_col.children.link(role_col)
        elif role_col.name not in cfg_col.children:
            try:
                cfg_col.children.link(role_col)
            except RuntimeError as link_exc:
                log.debug("%s collection already linked to cfg_col: %s", role, link_exc)

        role_col["_omnimesh_role"] = role
        role_col["_omnimesh_parent"] = target_asset
        return role_col


__all__ = [
    "assign_enum_property",
    "assign_or_defer_enum",
    "find_config_role_collection",
    "get_or_create_config_role_collection",
    "mock_prop",
    "register_classes",
    "resolve_config_target_asset",
    "unregister_classes",
    "unregister_existing_class",
]
