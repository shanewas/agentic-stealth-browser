"""Tests for selector auto-heal and confidence scoring in v1.2.0."""

import pytest

from workflows.selector_generator import SelectorGenerator


class TestConfidenceScoring:
    def test_id_selector_high_confidence(self):
        info = {"tagName": "button", "id": "submit-btn", "className": "btn", "textContent": "Submit"}
        candidates = SelectorGenerator.generate_candidates(info)
        confidence = SelectorGenerator.compute_confidence(candidates)
        assert confidence == 0.95

    def test_class_only_medium_confidence(self):
        info = {"tagName": "div", "id": "", "className": "container", "textContent": "Hello"}
        candidates = SelectorGenerator.generate_candidates(info)
        confidence = SelectorGenerator.compute_confidence(candidates)
        assert confidence == 0.50

    def test_tag_only_low_confidence(self):
        info = {"tagName": "span", "id": "", "className": "", "textContent": ""}
        candidates = SelectorGenerator.generate_candidates(info)
        confidence = SelectorGenerator.compute_confidence(candidates)
        assert confidence <= 0.30

    def test_empty_element_zero_confidence(self):
        confidence = SelectorGenerator.compute_confidence([])
        assert confidence == 0.0

    def test_get_best_selector_with_confidence(self):
        info = {"tagName": "button", "id": "save-btn", "className": "primary large", "textContent": "Save"}
        selector, confidence = SelectorGenerator.get_best_selector_with_confidence(info)
        assert selector == "#save-btn"
        assert confidence == 0.95

    def test_get_best_selector_with_confidence_empty(self):
        selector, confidence = SelectorGenerator.get_best_selector_with_confidence({})
        assert isinstance(selector, str)
        assert len(selector) > 0
        assert confidence >= 0.0


class TestAutoHealSelector:
    def test_heal_id_selector(self):
        healed = SelectorGenerator.auto_heal_selector("#react-a1b2c3d4")
        assert len(healed) > 0

    def test_heal_class_selector(self):
        healed = SelectorGenerator.auto_heal_selector("button.btn-primary.large")
        assert any("btn-primary" in h for h in healed)

    def test_heal_text_selector(self):
        healed = SelectorGenerator.auto_heal_selector('button:has-text("Submit")')
        assert any('has-text' in h for h in healed) or any('text*=' in h for h in healed)

    def test_heal_nth_child(self):
        healed = SelectorGenerator.auto_heal_selector("div:nth-child(3)")
        assert any(h == "div" for h in healed)

    def test_heal_attribute_selector(self):
        healed = SelectorGenerator.auto_heal_selector('[data-testid="save-btn"]')
        assert any(h == "[data-testid]" for h in healed)

    def test_heal_empty_returns_empty(self):
        healed = SelectorGenerator.auto_heal_selector("")
        assert healed == []

    def test_heal_does_not_duplicate_original(self):
        healed = SelectorGenerator.auto_heal_selector("#my-btn")
        assert "#my-btn" not in healed

    def test_heal_no_duplicates(self):
        healed = SelectorGenerator.auto_heal_selector("button.btn.btn")
        assert len(healed) == len(set(healed))


class TestDynamicClassDetection:
    def test_is_dynamic_class_hash_based(self):
        assert SelectorGenerator.is_dynamic_class("css-1a2b3c4")
        assert SelectorGenerator.is_dynamic_class("m-a1b2c3d4")
        assert SelectorGenerator.is_dynamic_class("sc-bdVaJa")

    def test_is_dynamic_class_scoped(self):
        assert SelectorGenerator.is_dynamic_class("m-a1b2c3d4")
        assert SelectorGenerator.is_dynamic_class("s-a1b2c3d4")

    def test_static_class_not_dynamic(self):
        assert not SelectorGenerator.is_dynamic_class("btn")
        assert not SelectorGenerator.is_dynamic_class("container")
        assert not SelectorGenerator.is_dynamic_class("text-primary")

    def test_strip_dynamic_classes(self):
        result = SelectorGenerator.strip_dynamic_classes("btn css-1a2b3c4 primary")
        assert result == "btn primary"

    def test_strip_only_static_classes(self):
        result = SelectorGenerator.strip_dynamic_classes("btn primary")
        assert result == "btn primary"

    def test_strip_only_dynamic_returns_none(self):
        result = SelectorGenerator.strip_dynamic_classes("css-1a2b3c4")
        assert result is None

    def test_strip_empty_returns_none(self):
        result = SelectorGenerator.strip_dynamic_classes("")
        assert result is None


class TestElementInfoAttributes:
    def test_attributes_as_list(self):
        info = {
            "tagName": "button",
            "id": "",
            "className": "",
            "textContent": "",
            "attributes": [{"data-testid": "btn"}, {"role": "button"}],
        }
        candidates = SelectorGenerator.generate_candidates(info)
        assert any("data-testid" in c["selector"] for c in candidates)

    def test_aria_label_attribute(self):
        info = {
            "tagName": "button",
            "id": "",
            "className": "btn",
            "textContent": "Click",
            "attributes": {"aria-label": "Close dialog"},
        }
        candidates = SelectorGenerator.generate_candidates(info)
        assert any("aria-label" in c["selector"] for c in candidates)
