#!/usr/bin/env python3
"""Compare two batches of TimeAtlas RDE JSON files."""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


RDE_TYPE_ORDER = [
    "dataset",
    "map",
    "layer",
    "area",
    "geometry",
    "historical_record",
    "observation",
    "poi",
]


@dataclass
class Batch:
    path: Path
    objects: list[dict[str, Any]]
    warnings: list[str]


@dataclass
class Difference:
    path: str
    left: Any
    right: Any


def iter_json_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"Batch path does not exist: {path}")
    return sorted(p for p in path.iterdir() if p.is_file() and p.suffix == ".json")


def normalize_feature(obj: dict[str, Any]) -> dict[str, Any]:
    if obj.get("type") != "Feature" or "properties" not in obj:
        return obj

    props = dict(obj.get("properties") or {})
    if "id" not in props and "uuid" in props:
        props["id"] = props["uuid"]
    props["geometry"] = obj.get("geometry")
    return props


def objects_from_files(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    objects: list[dict[str, Any]] = []
    warnings: list[str] = []

    for file_path in iter_json_files(path):
        try:
            with file_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as exc:
            warnings.append(f"Skipped malformed JSON {file_path}: {exc}")
            continue

        if isinstance(data, dict) and isinstance(data.get("rde_objects"), list):
            objects.extend(normalize_feature(obj) for obj in data["rde_objects"] if isinstance(obj, dict))
        elif isinstance(data, dict) and data.get("type") == "FeatureCollection":
            objects.extend(normalize_feature(obj) for obj in data.get("features", []) if isinstance(obj, dict))
        elif isinstance(data, dict) and "rde_type" in data and "id" in data:
            objects.append(normalize_feature(data))
        else:
            warnings.append(f"Skipped non-RDE JSON file {file_path}")

    return objects, warnings


def load_batch(path_arg: str) -> Batch:
    path = Path(path_arg).expanduser().resolve()
    objects, warnings = objects_from_files(path)
    return Batch(path=path, objects=objects, warnings=warnings)


def rde_type(obj: dict[str, Any]) -> str:
    value = obj.get("rde_type") or obj.get("type")
    return str(value) if value is not None else "<missing rde_type>"


def rde_id(obj: dict[str, Any]) -> str:
    value = obj.get("id") or obj.get("uuid")
    return str(value) if value is not None else "<missing id>"


def should_ignore(path: str, ignored_fields: set[str]) -> bool:
    if not ignored_fields:
        return False
    parts = [part for part in path.replace("[", ".").replace("]", "").split(".") if part]
    return any(part in ignored_fields for part in parts)


def normalize_for_compare(value: Any, path: str, ignored_fields: set[str], sort_scalar_lists: bool) -> Any:
    if should_ignore(path, ignored_fields):
        return "<ignored>"

    if isinstance(value, dict):
        return {
            key: normalize_for_compare(val, f"{path}.{key}" if path else key, ignored_fields, sort_scalar_lists)
            for key, val in sorted(value.items())
            if not should_ignore(f"{path}.{key}" if path else key, ignored_fields)
        }

    if isinstance(value, list):
        normalized = [
            normalize_for_compare(item, f"{path}[{idx}]", ignored_fields, sort_scalar_lists)
            for idx, item in enumerate(value)
        ]
        if sort_scalar_lists and all(not isinstance(item, (dict, list)) for item in normalized):
            return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
        return normalized

    return value


def values_equal(left: Any, right: Any, float_tolerance: float) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, bool) or isinstance(right, bool):
            return left == right
        if math.isnan(left) and math.isnan(right):
            return True
        return abs(float(left) - float(right)) <= float_tolerance
    return left == right


def diff_values(
    left: Any,
    right: Any,
    path: str = "",
    *,
    float_tolerance: float,
    max_diffs: int,
) -> list[Difference]:
    if values_equal(left, right, float_tolerance):
        return []

    diffs: list[Difference] = []

    if isinstance(left, dict) and isinstance(right, dict):
        all_keys = sorted(set(left) | set(right))
        for key in all_keys:
            if len(diffs) >= max_diffs:
                break
            key_path = f"{path}.{key}" if path else key
            if key not in left:
                diffs.append(Difference(key_path, "<missing>", right[key]))
            elif key not in right:
                diffs.append(Difference(key_path, left[key], "<missing>"))
            else:
                diffs.extend(
                    diff_values(
                        left[key],
                        right[key],
                        key_path,
                        float_tolerance=float_tolerance,
                        max_diffs=max_diffs - len(diffs),
                    )
                )
        return diffs

    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            diffs.append(Difference(f"{path}.length" if path else "length", len(left), len(right)))
        for idx, (left_item, right_item) in enumerate(zip(left, right)):
            if len(diffs) >= max_diffs:
                break
            diffs.extend(
                diff_values(
                    left_item,
                    right_item,
                    f"{path}[{idx}]",
                    float_tolerance=float_tolerance,
                    max_diffs=max_diffs - len(diffs),
                )
            )
        return diffs

    return [Difference(path or "<root>", left, right)]


def index_objects(objects: list[dict[str, Any]]) -> tuple[dict[str, dict[str, dict[str, Any]]], list[tuple[str, str, int]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    key_counts = Counter((rde_type(obj), rde_id(obj)) for obj in objects)
    duplicates = [(tpe, uid, count) for (tpe, uid), count in sorted(key_counts.items()) if count > 1]

    for obj in objects:
        grouped[rde_type(obj)][rde_id(obj)] = obj

    return dict(grouped), duplicates


def short_json(value: Any, max_chars: int = 220) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def ordered_types(*indexes: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
    found = set().union(*(index.keys() for index in indexes))
    known = [tpe for tpe in RDE_TYPE_ORDER if tpe in found]
    unknown = sorted(found - set(known))
    return known + unknown


def print_report(args: argparse.Namespace) -> int:
    left = load_batch(args.left)
    right = load_batch(args.right)

    left_index, left_duplicates = index_objects(left.objects)
    right_index, right_duplicates = index_objects(right.objects)

    ignored_fields = set(args.ignore_field)
    total_added = total_removed = total_modified = 0

    print("TimeAtlas RDE Batch Comparison")
    print("=" * 34)
    print(f"Left:  {left.path}")
    print(f"Right: {right.path}")
    print(f"Float tolerance: {args.float_tolerance:g}")
    if ignored_fields:
        print(f"Ignored fields: {', '.join(sorted(ignored_fields))}")
    print()

    print("Input Status")
    print("-" * 12)
    for label, batch in (("Left", left), ("Right", right)):
        print(f"{label}: {len(batch.objects)} RDE objects")
        for warning in batch.warnings:
            print(f"  warning: {warning}")
    print()

    if left_duplicates or right_duplicates:
        print("Duplicate Keys")
        print("-" * 14)
        for label, duplicates in (("Left", left_duplicates), ("Right", right_duplicates)):
            if not duplicates:
                continue
            print(f"{label}: {len(duplicates)} duplicate (rde_type, id) keys; last object is used for comparison")
            for tpe, uid, count in duplicates[: args.max_examples]:
                print(f"  {tpe} {uid}: {count} occurrences")
            if len(duplicates) > args.max_examples:
                print(f"  ... {len(duplicates) - args.max_examples} more")
        print()

    print("Summary By Type")
    print("-" * 15)
    changed_by_type: dict[str, list[tuple[str, list[Difference]]]] = {}

    for tpe in ordered_types(left_index, right_index):
        left_entities = left_index.get(tpe, {})
        right_entities = right_index.get(tpe, {})
        left_ids = set(left_entities)
        right_ids = set(right_entities)
        added = sorted(right_ids - left_ids)
        removed = sorted(left_ids - right_ids)
        common = sorted(left_ids & right_ids)
        modified: list[tuple[str, list[Difference]]] = []

        for uid in common:
            left_obj = normalize_for_compare(left_entities[uid], "", ignored_fields, args.sort_scalar_lists)
            right_obj = normalize_for_compare(right_entities[uid], "", ignored_fields, args.sort_scalar_lists)
            diffs = diff_values(
                left_obj,
                right_obj,
                float_tolerance=args.float_tolerance,
                max_diffs=args.max_diffs_per_entity,
            )
            if diffs:
                modified.append((uid, diffs))

        total_added += len(added)
        total_removed += len(removed)
        total_modified += len(modified)
        changed_by_type[tpe] = modified

        print(
            f"{tpe}: left={len(left_entities)} right={len(right_entities)} "
            f"added={len(added)} removed={len(removed)} modified={len(modified)}"
        )

    print()
    print("Detailed Differences")
    print("-" * 20)

    any_detail = False
    for tpe in ordered_types(left_index, right_index):
        left_entities = left_index.get(tpe, {})
        right_entities = right_index.get(tpe, {})
        added = sorted(set(right_entities) - set(left_entities))
        removed = sorted(set(left_entities) - set(right_entities))
        modified = changed_by_type.get(tpe, [])

        if not (added or removed or modified):
            continue
        any_detail = True
        print(f"\n{tpe}")

        if added:
            print(f"  Added in right ({len(added)}): {', '.join(added[: args.max_examples])}")
            if len(added) > args.max_examples:
                print(f"    ... {len(added) - args.max_examples} more")
        if removed:
            print(f"  Removed from right ({len(removed)}): {', '.join(removed[: args.max_examples])}")
            if len(removed) > args.max_examples:
                print(f"    ... {len(removed) - args.max_examples} more")
        if modified:
            print(f"  Modified ({len(modified)}):")
            for uid, diffs in modified[: args.max_examples]:
                print(f"    {uid}")
                for diff in diffs:
                    print(f"      {diff.path}:")
                    print(f"        left:  {short_json(diff.left)}")
                    print(f"        right: {short_json(diff.right)}")
            if len(modified) > args.max_examples:
                print(f"    ... {len(modified) - args.max_examples} more modified entities")

    if not any_detail:
        print("No differences found.")

    print()
    print("Totals")
    print("-" * 6)
    print(f"Added in right: {total_added}")
    print(f"Removed from right: {total_removed}")
    print(f"Modified common entities: {total_modified}")

    return 1 if args.fail_on_difference and (total_added or total_removed or total_modified) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare two TimeAtlas RDE data batches and print a detailed difference report."
    )
    parser.add_argument("left", help="Path to the reference batch directory or RDE JSON file.")
    parser.add_argument("right", help="Path to the comparison batch directory or RDE JSON file.")
    parser.add_argument(
        "--float-tolerance",
        type=float,
        default=1e-12,
        help="Absolute tolerance for numeric/geometry coordinate comparisons. Default: 1e-12.",
    )
    parser.add_argument(
        "--ignore-field",
        action="append",
        default=["creation_time"],
        help="Field name to ignore anywhere in an object. Can be repeated. Default: creation_time.",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=10,
        help="Maximum added/removed/modified entity examples to print per type. Default: 10.",
    )
    parser.add_argument(
        "--max-diffs-per-entity",
        type=int,
        default=8,
        help="Maximum field-level differences to print per modified entity. Default: 8.",
    )
    parser.add_argument(
        "--sort-scalar-lists",
        action="store_true",
        help="Sort lists made only of scalar values before comparison.",
    )
    parser.add_argument(
        "--fail-on-difference",
        action="store_true",
        help="Exit with code 1 if differences are found.",
    )
    return parser


def main() -> int:
    return print_report(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
