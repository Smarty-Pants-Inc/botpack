from __future__ import annotations

from typing import Any


def _is_type(value: Any, t: str) -> bool:
    if t == "object":
        return isinstance(value, dict)
    if t == "array":
        return isinstance(value, list)
    if t == "string":
        return isinstance(value, str)
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    if t == "boolean":
        return isinstance(value, bool)
    if t == "null":
        return value is None
    return False


def validate_json_schema(instance: Any, schema: dict[str, Any], *, path: str = "$") -> list[str]:
    """Validate a JSON instance against a small, deterministic schema subset.

    Supported keywords:
      - type
      - required
      - properties
      - items
      - minItems / maxItems
      - const
      - enum

    Returns a list of human-readable error strings. Empty list means valid.
    """

    errors: list[str] = []

    if "const" in schema:
        if instance != schema["const"]:
            errors.append(f"{path}: expected const {schema['const']!r}, got {instance!r}")
        return errors

    if "enum" in schema:
        allowed = schema["enum"]
        if not isinstance(allowed, list):
            errors.append(f"{path}: schema.enum must be an array")
            return errors
        if instance not in allowed:
            errors.append(f"{path}: expected one of {allowed!r}, got {instance!r}")
            return errors

    t = schema.get("type")
    if t is not None:
        if not isinstance(t, str):
            errors.append(f"{path}: schema.type must be a string")
            return errors
        if not _is_type(instance, t):
            errors.append(f"{path}: expected type {t}, got {type(instance).__name__}")
            return errors

    if isinstance(instance, dict):
        req = schema.get("required")
        if req is not None:
            if not isinstance(req, list) or not all(isinstance(x, str) for x in req):
                errors.append(f"{path}: schema.required must be an array of strings")
            else:
                for k in req:
                    if k not in instance:
                        errors.append(f"{path}: missing required property {k!r}")

        props = schema.get("properties")
        if props is not None:
            if not isinstance(props, dict):
                errors.append(f"{path}: schema.properties must be an object")
            else:
                for k, subschema in props.items():
                    if k not in instance:
                        continue
                    if not isinstance(subschema, dict):
                        errors.append(f"{path}.{k}: subschema must be an object")
                        continue
                    errors.extend(validate_json_schema(instance[k], subschema, path=f"{path}.{k}"))

    if isinstance(instance, list):
        min_items = schema.get("minItems")
        max_items = schema.get("maxItems")
        if min_items is not None:
            if not isinstance(min_items, int):
                errors.append(f"{path}: schema.minItems must be an integer")
            elif len(instance) < min_items:
                errors.append(f"{path}: expected minItems {min_items}, got {len(instance)}")
        if max_items is not None:
            if not isinstance(max_items, int):
                errors.append(f"{path}: schema.maxItems must be an integer")
            elif len(instance) > max_items:
                errors.append(f"{path}: expected maxItems {max_items}, got {len(instance)}")

        items = schema.get("items")
        if items is not None:
            if not isinstance(items, dict):
                errors.append(f"{path}: schema.items must be an object")
            else:
                for i, it in enumerate(instance):
                    errors.extend(validate_json_schema(it, items, path=f"{path}[{i}]"))

    return errors
