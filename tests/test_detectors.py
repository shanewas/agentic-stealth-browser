"""
Tests for the pluggable detector interface (#185).
"""

import pytest
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recovery.detectors import (
    BlockDetector,
    DetectionResult,
    TitleDetector,
    ContentDetector,
    DetectorRegistry,
)
from recovery.anti_block_orchestrator import BlockType, RecoveryContext


class TestDetectionResult:
    """Test DetectionResult dataclass."""

    def test_creation(self):
        result = DetectionResult(
            is_blocked=True,
            block_type=BlockType.CAPTCHA,
            confidence=0.9,
            details={"test": "value"},
            detector_name="test_detector",
        )
        assert result.is_blocked is True
        assert result.block_type == BlockType.CAPTCHA
        assert result.confidence == 0.9
        assert result.details == {"test": "value"}
        assert result.detector_name == "test_detector"


class TestTitleDetector:
    """Test TitleDetector."""

    def test_name(self):
        detector = TitleDetector()
        assert detector.name == "title_detector"

    def test_detect_blocked_title(self):
        detector = TitleDetector()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def title(self):
                return "Just a moment..."

        async def _run():
            return await detector.detect(context, MockPage())

        result = asyncio.run(_run())
        assert result.is_blocked is True
        assert result.detector_name == "title_detector"

    def test_detect_clean_title(self):
        detector = TitleDetector()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def title(self):
                return "Example Domain"

        async def _run():
            return await detector.detect(context, MockPage())

        result = asyncio.run(_run())
        assert result.is_blocked is False
        assert result.block_type == BlockType.NONE

    def test_detect_error_handling(self):
        detector = TitleDetector()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def title(self):
                raise Exception("Page closed")

        async def _run():
            return await detector.detect(context, MockPage())

        result = asyncio.run(_run())
        assert result.is_blocked is False
        assert "error" in result.details


class TestContentDetector:
    """Test ContentDetector."""

    def test_name(self):
        detector = ContentDetector()
        assert detector.name == "content_detector"

    def test_detect_cloudflare(self):
        detector = ContentDetector()
        context = RecoveryContext(platform="cloudflare", url="https://example.com")

        class MockPage:
            async def content(self):
                return "<html><body>Just a moment... Checking your browser before accessing the site. Cloudflare Ray ID.</body></html>"

        async def _run():
            return await detector.detect(context, MockPage())

        result = asyncio.run(_run())
        assert result.is_blocked is True

    def test_detect_linkedin_block(self):
        detector = ContentDetector()
        context = RecoveryContext(platform="linkedin", url="https://linkedin.com")

        class MockPage:
            async def content(self):
                return "<html><body>Unusual activity detected on your account.</body></html>"

        async def _run():
            return await detector.detect(context, MockPage())

        result = asyncio.run(_run())
        assert result.is_blocked is True

    def test_detect_clean_page(self):
        detector = ContentDetector()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def content(self):
                return "<html><body><h1>Welcome</h1><p>This is a clean page.</p></body></html>"

        async def _run():
            return await detector.detect(context, MockPage())

        result = asyncio.run(_run())
        assert result.is_blocked is False


class TestDetectorRegistry:
    """Test DetectorRegistry."""

    def test_default_detectors(self):
        registry = DetectorRegistry()
        names = registry.list_detectors()
        assert "title_detector" in names
        assert "content_detector" in names

    def test_register_custom_detector(self):
        registry = DetectorRegistry()

        class CustomDetector(BlockDetector):
            @property
            def name(self):
                return "custom"

            async def detect(self, context, page):
                return DetectionResult(
                    is_blocked=False,
                    block_type=BlockType.NONE,
                    confidence=1.0,
                    details={},
                    detector_name=self.name,
                )

        registry.register(CustomDetector())
        assert "custom" in registry.list_detectors()

    def test_unregister_detector(self):
        registry = DetectorRegistry()
        assert registry.unregister("title_detector") is True
        assert "title_detector" not in registry.list_detectors()
        assert registry.unregister("nonexistent") is False

    def test_register_invalid_detector(self):
        registry = DetectorRegistry()
        with pytest.raises(TypeError):
            registry.register("not a detector")

    def test_detect_all(self):
        registry = DetectorRegistry()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def title(self):
                return "Example Domain"

            async def content(self):
                return "<html><body>Clean page</body></html>"

        async def _run():
            return await registry.detect_all(context, MockPage())

        results = asyncio.run(_run())
        assert len(results) >= 2

    def test_consensus_blocked(self):
        registry = DetectorRegistry()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def title(self):
                return "Just a moment..."

            async def content(self):
                return "<html><body>Checking your browser...</body></html>"

        async def _run():
            results = await registry.detect_all(context, MockPage())
            return registry.get_consensus(results)

        consensus = asyncio.run(_run())
        assert consensus.is_blocked is True
        assert consensus.details.get("consensus") is True

    def test_consensus_not_blocked(self):
        registry = DetectorRegistry()
        context = RecoveryContext(platform="test", url="https://example.com")

        class MockPage:
            async def title(self):
                return "Example Domain"

            async def content(self):
                return "<html><body>Clean page</body></html>"

        async def _run():
            results = await registry.detect_all(context, MockPage())
            return registry.get_consensus(results)

        consensus = asyncio.run(_run())
        assert consensus.is_blocked is False
