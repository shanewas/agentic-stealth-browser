import re
from typing import Any, Dict, List

_GENERATED_ID_PATTERNS = [
    re.compile(r"^[a-f0-9]{8,}$", re.I),
    re.compile(r"^[a-z]+-[a-f0-9]{4,}", re.I),
    re.compile(r"^[a-z]+\d{3,}$", re.I),
    re.compile(r"^\d+$"),
]

_COMMON_GENERATED_PREFIXES = [
    "ember", "react-", "vue-", "ng-", "__", "_", "data-v-",
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
    def get_best_selector(element_info: dict) -> str:
        candidates = SelectorGenerator.generate_candidates(element_info)
        return candidates[0]["selector"] if candidates else "*"

    @staticmethod
    def get_fallback_set(element_info: dict) -> List[str]:
        candidates = SelectorGenerator.generate_candidates(element_info)
        return [c["selector"] for c in candidates]
