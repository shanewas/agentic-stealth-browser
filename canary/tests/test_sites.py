"""Tests for canary site catalog."""

from canary.sites import SITE_KEYS, SITES


def test_sites_count() -> None:
    assert len(SITES) == 6


def test_site_keys_unique() -> None:
    assert len(SITE_KEYS) == len(set(SITE_KEYS))


def test_required_fields() -> None:
    for site in SITES:
        assert site["key"]
        assert site["name"]
        assert site["url"].startswith("https://")
        assert site["platform"]
        assert isinstance(site["expected_signals"], list)
        assert len(site["expected_signals"]) > 0