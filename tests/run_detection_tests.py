"""
Basic Automated Detection Test Runner
Checks common vectors that LinkedIn and other platforms use
"""

import asyncio
from playwright.async_api import async_playwright


async def check_detection_vectors():
    print("Running basic detection checks...\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Check navigator.webdriver
        webdriver = await page.evaluate("navigator.webdriver")
        print(f"navigator.webdriver: {webdriver} (should be None or undefined)")
        
        # Check hardwareConcurrency
        hw = await page.evaluate("navigator.hardwareConcurrency")
        print(f"hardwareConcurrency: {hw}")
        
        # Check deviceMemory
        mem = await page.evaluate("navigator.deviceMemory")
        print(f"deviceMemory: {mem}")
        
        # Check plugins length
        plugins = await page.evaluate("navigator.plugins.length")
        print(f"plugins.length: {plugins}")
        
        await browser.close()
    
    print("\nBasic checks completed.")


if __name__ == "__main__":
    asyncio.run(check_detection_vectors())
