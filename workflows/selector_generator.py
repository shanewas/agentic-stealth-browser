import re
from typing import Any, Dict, List, Optional

_GENERATED_ID_PATTERNS = [
    re.compile(r"^[a-f0-9]{8,}$", re.I),
    re.compile(r"^[a-z]+-[a-f0-9]{4,}", re.I),
    re.compile(r"^[a-z]+\d{3,}$", re.I),
    re.compile(r"^\d+$"),
]

_COMMON_GENERATED_PREFIXES = [
    "ember", "react-", "vue-", "ng-", "__", "_", "data-v-",
]

DYNAMIC_CLASS_PATTERNS = [
    re.compile(r"^[a-z]+_[a-f0-9]{4,}$", re.I),
    re.compile(r"^[a-z]+--[a-f0-9]{4,}$", re.I),
    re.compile(r"^_[a-zA-Z0-9]+_[a-f0-9]{4,}$"),
    re.compile(r"^[a-z]+__[a-z0-9]+--[a-f0-9]+$"),
    re.compile(r"^m-[a-f0-9]+$"),
    re.compile(r"^css-[a-f0-9]+$"),
    re.compile(r"^sc-[a-zA-Z]+$"),
    re.compile(r"^s-[a-f0-9]+$"),
]


def _is_generated_id(id_val: str) -> bool:
    if not id_val:
        return True
    for pattern in _GENERATED_ID_PATTERNS:
        if pattern.match(id_val):
            return True
    for prefix in _COMMON_GENERATED_PREFIXES:
        if id_val.lower().startswith(prefix):
            return True
    return False


def _escape_css_string(value: str) -> str:
    return value.replace('"', '\\"').replace("'", "\\'")


class SelectorGenerator:

    @staticmethod
    def generate_candidates(element_info: dict) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        tag = element_info.get("tagName", "").lower()
        el_id = element_info.get("id", "")
        class_name = element_info.get("className", "")
        text_content = element_info.get("textContent", "")
        attributes = element_info.get("attributes", {})
        text_content = (text_content or "").strip()

        if isinstance(attributes, list):
            attr_dict = {}
            for item in attributes:
                if isinstance(item, dict):
                    attr_dict.update({k.lower(): v for k, v in item.items()})
            attributes = attr_dict
        elif isinstance(attributes, dict):
            attributes = {k.lower(): v for k, v in attributes.items()}

        if el_id and not _is_generated_id(el_id):
            candidates.append({
                "selector": f"#{el_id}",
                "strategy": "id",
                "stability": 0.95,
            })

        for attr_key in ("data-testid", "data-test", "data-qa", "aria-label"):
            val = attributes.get(attr_key)
            if val:
                candidates.append({
                    "selector": f'[{attr_key}="{_escape_css_string(str(val))}"]',
                    "strategy": "attribute",
                    "stability": 0.90,
                })

        for attr_key, attr_val in attributes.items():
            if attr_key.startswith("data-") and attr_key not in ("data-testid", "data-test", "data-qa"):
                candidates.append({
                    "selector": f'[{attr_key}="{_escape_css_string(str(attr_val))}"]',
                    "strategy": "attribute",
                    "stability": 0.80,
                })

        if class_name and tag:
            classes = class_name.strip().split()
            for cls in classes:
                if not cls:
                    continue
                candidates.append({
                    "selector": f"{tag}.{cls}",
                    "strategy": "class",
                    "stability": 0.60,
                })

        if text_content and tag in ("button", "a", "input", "span"):
            safe_text = _escape_css_string(text_content[:80])
            if len(text_content) > 80:
                candidates.append({
                    "selector": f'{tag}[text*="{safe_text[:40]}"]',
                    "strategy": "text",
                    "stability": 0.50,
                })
            else:
                candidates.append({
                    "selector": f'{tag}:has-text("{safe_text}")',
                    "strategy": "text",
                    "stability": 0.50,
                })

        if tag:
            candidates.append({
                "selector": tag,
                "strategy": "tag",
                "stability": 0.40,
            })

        candidates.append({
            "selector": f"{tag}:nth-child(1)" if tag else "*:nth-child(1)",
            "strategy": "nth",
            "stability": 0.30,
        })

        candidates.sort(key=lambda c: c["stability"], reverse=True)
        return candidates

    @staticmethod
    def compute_confidence(candidates: List[Dict[str, Any]]) -> float:
        if not candidates:
            return 0.0
        best_stability = candidates[0]["stability"]
        if best_stability >= 0.90:
            return 0.95
        elif best_stability >= 0.70:
            return 0.75
        elif best_stability >= 0.50:
            return 0.50
        elif best_stability >= 0.30:
            return 0.30
        return 0.15

    @staticmethod
    def get_best_selector(element_info: dict) -> str:
        candidates = SelectorGenerator.generate_candidates(element_info)
        return candidates[0]["selector"] if candidates else "*"

    @staticmethod
    def get_best_selector_with_confidence(element_info: dict) -> tuple:
        candidates = SelectorGenerator.generate_candidates(element_info)
        if not candidates:
            return "*", 0.0
        confidence = SelectorGenerator.compute_confidence(candidates)
        return candidates[0]["selector"], confidence

    @staticmethod
    def get_fallback_set(element_info: dict) -> List[str]:
        candidates = SelectorGenerator.generate_candidates(element_info)
        return [c["selector"] for c in candidates]

    @staticmethod
    def auto_heal_selector(original: str) -> List[str]:
        healed: List[str] = []
        if not original:
            return healed

        if "#" in original:
            base = original.split("#")[0]
            id_part = original.split("#")[1]
            id_part = id_part.split(".")[0].split(":")[0].split("[")[0]
            if base:
                healed.append(base)
            if id_part:
                healed.append(f"[id*=\"{_escape_css_string(id_part[-8:])}\"]")
                for attr_test in ("data-testid", "data-test", "data-qa", "aria-label"):
                    healed.append(f"[{attr_test}*=\"{_escape_css_string(id_part[-4:])}\"]")

        if "." in original:
            parts = original.split(".")
            tag = parts[0] if parts[0] else "*"
            for cls in parts[1:]:
                if not cls:
                    continue
                cls_base = re.split(r'[:\[#]', cls)[0]
                if cls_base:
                    healed.append(f"{tag}.{cls_base}")
                    healed.append(f"[class*=\"{_escape_css_string(cls_base)}\"]")
            if not healed:
                healed.append(tag)

        text_match = re.search(r':has-text\("([^"]+)"\)', original)
        if text_match:
            text_content = text_match.group(1)
            healed.append(f'*:has-text("{_escape_css_string(text_content)}")')
            healed.append(f'[text*="{_escape_css_string(text_content[:20])}"]')

        if ":nth-child" in original or ":nth-of-type" in original:
            bare = re.sub(r':nth-(?:child|of-type)\(\d+\)', '', original)
            if bare and bare not in healed:
                healed.append(bare)

        if "[" in original and "]" in original:
            attr_match = re.search(r'\[(\w+(?:-\w+)*)(?:\*?=)?\s*"([^"]+)"\]', original)
            if attr_match:
                healed.append(f"[{attr_match.group(1)}]")

        unique = []
        seen = set()
        for h in healed:
            if h not in seen and h != original:
                seen.add(h)
                unique.append(h)

        return unique

    @staticmethod
    def is_dynamic_class(class_name: str) -> bool:
        for pattern in DYNAMIC_CLASS_PATTERNS:
            if pattern.match(class_name):
                return True
        return False

    @staticmethod
    def strip_dynamic_classes(class_value: str) -> Optional[str]:
        if not class_value:
            return None
        classes = class_value.strip().split()
        static = [c for c in classes if c and not SelectorGenerator.is_dynamic_class(c)]
        return " ".join(static) if static else None
