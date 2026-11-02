#!/usr/bin/env python3
"""
Migration script: converts v1 workflow YAMLs to v2 format.

Usage:
    python scripts/migrate_v1_to_v2.py --input my_workflow.yaml [--output my_workflow_v2.yaml]
    python scripts/migrate_v1_to_v2.py --validate --input my_workflow.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List, Optional

# Top-level keys the migrator itself consumes or emits. Any other top-level
# v1 key is carried through verbatim: workflows.schema.load_workflow()
# ignores unknown top-level keys, so carrying them is schema-safe and
# avoids silently dropping user data (L10).
_KNOWN_TOP_LEVEL_KEYS = {
    "name",
    "description",
    "platform",
    "steps",
    "variables",
    "version",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _real_validation_issues(migrated: Dict[str, Any]) -> List[str]:
    """Validate a migrated document with the real v2 schema validator."""
    root = str(_repo_root())
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        from workflows.schema import load_workflow, validate_workflow
    except Exception as e:  # pragma: no cover - import guard
        return [f"Schema validator unavailable: {e}"]
    try:
        workflow = load_workflow(deepcopy(migrated))
    except Exception as e:
        return [f"Schema load failed: {e}"]
    result = validate_workflow(workflow)
    return list(result.errors)


def _write_migrated(migrated: Dict[str, Any], output_path: str) -> None:
    import yaml

    Path(output_path).write_text(
        yaml.dump(migrated, default_flow_style=False, sort_keys=False)
    )
    print(f"Migrated workflow written to {output_path}")


def migrate_workflow_yaml(
    input_path: str, output_path: Optional[str] = None
) -> Dict[str, Any]:
    """Convert a v1 workflow YAML to v2 format.

    Key changes:
    - Adds `platform` field if missing (defaults to "generic")
    - Flattens step keys to v2 naming: workflows.schema itself flattens
      every step key besides ``type`` into ``params``, so the migrated
      document must keep fields such as ``url`` at step level (no nested
      ``params:`` key, no step-level ``description:`` — the validator
      rejects both as unknown fields).
    - Adds `version: "2.0.0"` metadata
    - Carries unknown top-level keys through (schema tolerates them)

    The migrated document is validated with the real
    workflows.schema validator in memory before anything is written;
    an invalid migration exits non-zero and writes no output.
    """
    try:
        import yaml
    except ImportError:
        print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    in_path = Path(input_path)
    if not in_path.exists():
        print(f"File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if output_path and Path(output_path).resolve() == in_path.resolve():
        print(
            "Refusing to migrate: --input and --output resolve to the same file "
            f"({in_path.resolve()}); the v1 original would be overwritten.",
            file=sys.stderr,
        )
        sys.exit(1)

    raw = in_path.read_text()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        print(
            f"Invalid YAML: expected top-level mapping, got {type(data).__name__}",
            file=sys.stderr,
        )
        sys.exit(1)

    migrated: Dict[str, Any] = {}

    migrated["version"] = "2.0.0"
    migrated["name"] = data.get("name", in_path.stem)
    migrated["description"] = data.get("description", "")
    migrated["platform"] = data.get("platform", "generic")

    steps = data.get("steps", [])
    migrated_steps: List[Dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            migrated_steps.append(step)
            continue
        new_step: Dict[str, Any] = {"type": step.get("type", "unknown")}
        # Flatten: a nested v1 `params:` mapping is merged in first, then
        # explicit step-level keys win. `description` is dropped — it is
        # not an allowed field for any v2 step type.
        nested = step.get("params")
        if "params" in step and not isinstance(nested, dict):
            # Malformed params: keep it so the real validator rejects it.
            new_step["params"] = nested
        if isinstance(nested, dict):
            for key, value in nested.items():
                if key not in ("type", "description", "params"):
                    new_step[key] = value
        for key, value in step.items():
            if key in ("type", "description", "params"):
                continue
            new_step[key] = value
        migrated_steps.append(new_step)
    migrated["steps"] = migrated_steps

    if "variables" in data:
        migrated["variables"] = data["variables"]

    # L10 choice: carry unknown top-level keys through. The real schema
    # loader ignores unknown top-level keys, so this loses no data while
    # keeping the document valid.
    for key, value in data.items():
        if key not in _KNOWN_TOP_LEVEL_KEYS and key not in migrated:
            migrated[key] = value

    if output_path:
        issues = _real_validation_issues(migrated)
        if issues:
            print(
                "Migrated workflow failed v2 schema validation; "
                f"not writing {output_path}:",
                file=sys.stderr,
            )
            for issue in issues:
                print(f"  - {issue}", file=sys.stderr)
            sys.exit(1)
        _write_migrated(migrated, output_path)

    return migrated


def validate_v1_vs_v2(v1_path: str, v2_path: str) -> Dict[str, Any]:
    """Validate that a v1 workflow loads correctly under v2 shims."""
    try:
        import yaml
    except ImportError:
        print("PyYAML is required. Install with: pip install pyyaml", file=sys.stderr)
        sys.exit(1)

    v1 = yaml.safe_load(Path(v1_path).read_text())
    v2 = yaml.safe_load(Path(v2_path).read_text())

    issues: List[str] = []

    if not isinstance(v1, dict):
        issues.append("v1 data is not a dict")
    if not isinstance(v2, dict):
        issues.append("v2 data is not a dict")
    if issues:
        return {"valid": False, "issues": issues}

    if v1.get("name") != v2.get("name"):
        issues.append(f"name mismatch: {v1.get('name')} vs {v2.get('name')}")
    if len(v1.get("steps", [])) != len(v2.get("steps", [])):
        issues.append(
            f"step count mismatch: {len(v1.get('steps', []))} vs {len(v2.get('steps', []))}"
        )
    # The real check: the v2 document must pass workflows.schema.
    issues.extend(_real_validation_issues(v2))

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "v1_name": v1.get("name"),
        "v2_name": v2.get("name"),
        "v1_step_count": len(v1.get("steps", [])),
        "v2_step_count": len(v2.get("steps", [])),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Migrate v1 workflow YAMLs to v2 format."
    )
    parser.add_argument("--input", required=True, help="Input v1 workflow YAML path")
    parser.add_argument(
        "--output", help="Output v2 workflow YAML path (default: <input>_v2.yaml)"
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate v1 workflow loads under v2 shim",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args(argv)

    output_path = args.output or f"{args.input}_v2.yaml"

    # Refuse before touching anything: migrating onto the input would
    # destroy the v1 original and make any comparison circular.
    if Path(output_path).resolve() == Path(args.input).resolve():
        print(
            "Refusing to migrate: --input and --output resolve to the same file "
            f"({Path(args.input).resolve()}); the v1 original would be overwritten.",
            file=sys.stderr,
        )
        return 2

    if args.validate:
        # Convert and validate in memory with the real schema validator;
        # only a document that passes is written out.
        migrated = migrate_workflow_yaml(args.input, output_path=None)
        issues = _real_validation_issues(migrated)
        try:
            import yaml

            v1_data = yaml.safe_load(Path(args.input).read_text())
        except Exception:
            v1_data = None
        v1_steps = v1_data.get("steps", []) if isinstance(v1_data, dict) else []
        result = {
            "valid": not issues,
            "issues": issues,
            "v1_name": v1_data.get("name") if isinstance(v1_data, dict) else None,
            "v2_name": migrated.get("name"),
            "v1_step_count": len(v1_steps) if isinstance(v1_steps, list) else 0,
            "v2_step_count": len(migrated.get("steps", [])),
        }
        if not issues:
            _write_migrated(migrated, output_path)
        elif not args.json:
            for issue in issues:
                print(f"Validation failed: {issue}", file=sys.stderr)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        return 0 if result["valid"] else 1

    migrated = migrate_workflow_yaml(args.input, output_path=output_path)
    if args.json:
        print(json.dumps(migrated, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
