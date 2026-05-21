"""
Pluggable Detector Interface for Block Detection.
Addresses #185: Pluggable "detector" interface so users can bring their own block detection heuristics.

Users can implement custom detectors and register them with the AntiBlockOrchestrator
for site-specific or advanced block detection beyond the built-in patterns.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from recovery.anti_block_orchestrator import BlockType, RecoveryContext


@dataclass
class DetectionResult:
    """Result from a block detector."""
    is_blocked: bool
    block_type: BlockType
    confidence: float  # 0.0 to 1.0
    details: Dict[str, Any]
    detector_name: str


class BlockDetector(ABC):
    """Abstract base class for custom block detectors.
    
    Implement this interface to create custom block detection logic
    for specific sites or advanced heuristics.
    
    Example:
        class CloudflareDetector(BlockDetector):
            async def detect(self, context: RecoveryContext, page) -> DetectionResult:
                # Custom Cloudflare detection logic
                ...
    """
    
    @abstractmethod
    async def detect(self, context: RecoveryContext, page) -> DetectionResult:
        """Detect if the current page is blocked.
        
        Args:
            context: The recovery context with platform, URL, error info, etc.
            page: The Playwright Page object for content inspection.
        
        Returns:
            DetectionResult with block status, type, confidence, and details.
        """
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Name of this detector for logging and debugging."""
        pass


class TitleDetector(BlockDetector):
    """Detect blocks based on page title patterns."""
    
    BLOCK_TITLES = [
        "just a moment",
        "checking your browser",
        "attention required",
        "verify you are human",
        "security check",
        "access denied",
        "forbidden",
        "captcha",
        "challenge",
    ]
    
    @property
    def name(self) -> str:
        return "title_detector"
    
    async def detect(self, context: RecoveryContext, page) -> DetectionResult:
        try:
            title = (await page.title() or "").lower()
            for pattern in self.BLOCK_TITLES:
                if pattern in title:
                    return DetectionResult(
                        is_blocked=True,
                        block_type=BlockType.CAPTCHA if "captcha" in pattern or "challenge" in pattern else BlockType.SOFT_RATE_LIMIT,
                        confidence=0.9,
                        details={"matched_pattern": pattern, "title": title},
                        detector_name=self.name,
                    )
            return DetectionResult(
                is_blocked=False,
                block_type=BlockType.NONE,
                confidence=0.8,
                details={"title": title},
                detector_name=self.name,
            )
        except Exception as e:
            return DetectionResult(
                is_blocked=False,
                block_type=BlockType.UNKNOWN,
                confidence=0.0,
                details={"error": str(e)},
                detector_name=self.name,
            )


class ContentDetector(BlockDetector):
    """Detect blocks based on page content patterns."""
    
    BLOCK_PATTERNS = {
        "cloudflare": ["checking your browser", "just a moment", "cf-challenge", "cloudflare"],
        "linkedin": ["unusual activity", "security verification", "account restricted", "temporarily restricted"],
        "amazon": ["enter the characters", "sorry, we just need to make sure", "robot", "captcha"],
        "generic": ["access denied", "forbidden", "blocked", "rate limit", "too many requests"],
    }
    
    @property
    def name(self) -> str:
        return "content_detector"
    
    async def detect(self, context: RecoveryContext, page) -> DetectionResult:
        try:
            content = (await page.content() or "").lower()[:5000]
            platform = context.platform.lower()
            
            # Check platform-specific patterns first
            if platform in self.BLOCK_PATTERNS:
                for pattern in self.BLOCK_PATTERNS[platform]:
                    if pattern in content:
                        return DetectionResult(
                            is_blocked=True,
                            block_type=BlockType.CAPTCHA if "captcha" in pattern or "robot" in pattern else BlockType.SOFT_RATE_LIMIT,
                            confidence=0.85,
                            details={"matched_pattern": pattern, "platform": platform},
                            detector_name=self.name,
                        )
            
            # Check generic patterns
            for pattern in self.BLOCK_PATTERNS["generic"]:
                if pattern in content:
                    return DetectionResult(
                        is_blocked=True,
                        block_type=BlockType.SOFT_RATE_LIMIT,
                        confidence=0.7,
                        details={"matched_pattern": pattern},
                        detector_name=self.name,
                    )
            
            return DetectionResult(
                is_blocked=False,
                block_type=BlockType.NONE,
                confidence=0.75,
                details={"content_length": len(content)},
                detector_name=self.name,
            )
        except Exception as e:
            return DetectionResult(
                is_blocked=False,
                block_type=BlockType.UNKNOWN,
                confidence=0.0,
                details={"error": str(e)},
                detector_name=self.name,
            )


class DetectorRegistry:
    """Registry for block detectors.
    
    Allows users to register custom detectors and run them all against a page.
    
    Example:
        registry = DetectorRegistry()
        registry.register(CloudflareDetector())
        registry.register(MyCustomDetector())
        
        results = await registry.detect_all(context, page)
    """
    
    def __init__(self):
        self._detectors: List[BlockDetector] = []
        # Register built-in detectors by default
        self.register(TitleDetector())
        self.register(ContentDetector())
    
    def register(self, detector: BlockDetector) -> None:
        """Register a custom block detector."""
        if not isinstance(detector, BlockDetector):
            raise TypeError("Detector must inherit from BlockDetector")
        self._detectors.append(detector)
    
    def unregister(self, detector_name: str) -> bool:
        """Unregister a detector by name."""
        for i, d in enumerate(self._detectors):
            if d.name == detector_name:
                self._detectors.pop(i)
                return True
        return False
    
    def list_detectors(self) -> List[str]:
        """List all registered detector names."""
        return [d.name for d in self._detectors]
    
    async def detect_all(self, context: RecoveryContext, page) -> List[DetectionResult]:
        """Run all registered detectors against the page."""
        results = []
        for detector in self._detectors:
            try:
                result = await detector.detect(context, page)
                results.append(result)
            except Exception as e:
                results.append(DetectionResult(
                    is_blocked=False,
                    block_type=BlockType.UNKNOWN,
                    confidence=0.0,
                    details={"error": str(e), "detector": detector.name},
                    detector_name=detector.name,
                ))
        return results
    
    def get_consensus(self, results: List[DetectionResult], threshold: float = 0.5) -> DetectionResult:
        """Get consensus from multiple detector results.
        
        If enough detectors agree that the page is blocked, return a consensus result.
        """
        if not results:
            return DetectionResult(
                is_blocked=False,
                block_type=BlockType.NONE,
                confidence=0.0,
                details={"message": "no detectors ran"},
                detector_name="consensus",
            )
        
        blocked_results = [r for r in results if r.is_blocked and r.confidence >= threshold]
        
        if len(blocked_results) >= max(1, len(results) * 0.5):
            # Majority agrees it's blocked
            # Use the highest confidence result
            best = max(blocked_results, key=lambda r: r.confidence)
            return DetectionResult(
                is_blocked=True,
                block_type=best.block_type,
                confidence=best.confidence,
                details={
                    "consensus": True,
                    "detectors_agreeing": len(blocked_results),
                    "total_detectors": len(results),
                    "individual_results": [r.details for r in blocked_results],
                },
                detector_name="consensus",
            )
        
        return DetectionResult(
            is_blocked=False,
            block_type=BlockType.NONE,
            confidence=0.6,
            details={
                "consensus": False,
                "blocked_count": len(blocked_results),
                "total_detectors": len(results),
            },
            detector_name="consensus",
        )
