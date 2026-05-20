"""
Scraping Utilities for Agentic Browser
Safe page and image scraping with human-like behavior
"""

import asyncio
import time
import random
from typing import List, Dict, Optional
from pathlib import Path


class StealthScraper:
    """High-level scraping with built-in stealth and human behavior"""
    
    def __init__(self, browser, human_behavior, orchestrator):
        self.browser = browser
        self.human = human_behavior
        self.orchestrator = orchestrator
    
    async def scrape_page(self, url: str, extract_images: bool = False) -> Dict:
        """Scrape a page with natural behavior"""
        await self.browser.goto(url)
        
        # Read naturally first
        await self.orchestrator.read_page_naturally(2, 4)
        
        # Extract content
        content = await self.browser.evaluate("""
            () => {
                return {
                    title: document.title,
                    url: window.location.href,
                    text: document.body.innerText.substring(0, 8000),
                    headings: Array.from(document.querySelectorAll('h1,h2,h3')).map(h => h.innerText).slice(0, 10)
                }
            }
        """)
        
        result = {
            "url": url,
            "timestamp": time.monotonic(),
            "content": content
        }
        
        if extract_images:
            result["images"] = await self.extract_images()
        
        return result
    
    async def extract_images(self, max_images: int = 10) -> List[Dict]:
        """Extract image information from current page"""
        images = await self.browser.evaluate(f"""
            () => {{
                return Array.from(document.images)
                    .slice(0, {max_images})
                    .map(img => ({{
                        src: img.src,
                        alt: img.alt || '',
                        width: img.width,
                        height: img.height
                    }}));
            }}
        """)
        return images
    
    async def scrape_amazon_product(self, url: str) -> Dict:
        """Specialized Amazon product scraper with anti-block behavior"""
        await self.browser.goto(url)
        
        # Amazon requires more careful behavior
        await self.human.think(1500, 3000)
        await self.human.scroll_naturally(200)
        
        data = await self.browser.evaluate("""
            () => {
                const title = document.querySelector('#productTitle')?.innerText || '';
                const price = document.querySelector('.a-price .a-offscreen')?.innerText || '';
                const rating = document.querySelector('.a-icon-alt')?.innerText || '';
                
                return { title, price, rating, url: window.location.href };
            }
        """)
        
        await self.human.think(800, 1500)
        return data
