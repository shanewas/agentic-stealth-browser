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
from pathlib import Path
from typing import Any, Dict, List, Optional


def migrate_workflow_yaml(input_path: str, output_path: Optional[str] = None) -> Dict[str, Any]:
    """Convert a v1 workflow YAML to v2 format.

    Key changes:
    - Adds `platform` field if missing (defaults to "generic")
    - Normalizes step keys to v2 naming conventions
    - Adds `version: "2.0.0"` metadata
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

    raw = in_path.read_text()
    data = yaml.safe_load(raw)
    if not isinstance(data, dict):
        print(f"Invalid YAML: expected top-level mapping, got {type(data).__name__}", file=sys.stderr)
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
        new_step: Dict[str, Any] = {}
        new_step["type"] = step.get("type", "unknown")
        new_step["description"] = step.get("description", "")
        params = dict(step) if isinstance(step, dict) else {}
        params.pop("type", None)
        params.pop("description", None)
        new_step["params"] = params
        migrated_steps.append(new_step)
    migrated["steps"] = migrated_steps

    if "variables" in data:
        migrated["variables"] = data["variables"]

    if output_path:
        out_path = Path(output_path)
        out_path.write_text(yaml.dump(migrated, default_flow_style=False, sort_keys=False))
        print(f"Migrated workflow written to {output_path}")

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
        issues.append(f"step count mismatch: {len(v1.get('steps', []))} vs {len(v2.get('steps', []))}")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "v1_name": v1.get("name"),
        "v2_name": v2.get("name"),
        "v1_step_count": len(v1.get("steps", [])),
        "v2_step_count": len(v2.get("steps", [])),
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate v1 workflow YAMLs to v2 format.")
    parser.add_argument("--input", required=True, help="Input v1 workflow YAML path")
    parser.add_argument("--output", help="Output v2 workflow YAML path (default: <input>_v2.yaml)")
    parser.add_argument("--validate", action="store_true", help="Validate v1 workflow loads under v2 shim")
    parser.add_argument("--json", action="store_true", help="Output JSON to stdout")
    args = parser.parse_args(argv)

    if args.validate:
        output_path = args.output or f"{args.input}_v2.yaml"
        migrated = migrate_workflow_yaml(args.input, output_path=output_path)
        result = validate_v1_vs_v2(args.input, output_path)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("valid") else 1

    output_path = args.output or f"{args.input}_v2.yaml"
    migrated = migrate_workflow_yaml(args.input, output_path=output_path)
    if args.json:
        print(json.dumps(migrated, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
