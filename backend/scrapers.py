import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup

from urllib.parse import urljoin

def parse_html_to_text(html_content: str, url: str) -> dict:
    """Uses BeautifulSoup to parse HTML and extract OpenGraph images and clean body text."""
    soup = BeautifulSoup(html_content, "html.parser")
    
    og_image_tag = soup.find("meta", property="og:image")
    image_url = og_image_tag["content"].strip() if og_image_tag and og_image_tag.get("content") else None
    
    # Convert <a> tags to markdown-style links so the LLM can extract detail page URLs
    for a in soup.find_all("a", href=True):
        link_text = a.get_text().strip()
        href = a["href"].strip()
        if href.startswith("/"):
            href = urljoin(url, href)
        # Skip noise links (privacy, terms, etc.)
        if link_text and href.startswith("http") and not any(p in href.lower() for p in ["privacy", "terms", "about", "contact", "help", "login", "register", "facebook", "twitter", "instagram"]):
            a.replace_with(f" [{link_text}]({href}) ")
    
    # Clean out scripts, styles, navigation and footers for clear text extraction
    for element in soup(["script", "style", "nav", "footer"]):
        element.decompose()
        
    # Get clean, readable page text
    text_content = soup.get_text(separator="\n")
    clean_lines = [line.strip() for line in text_content.splitlines() if line.strip()]
    
    return {
        "html": html_content,
        "text": "\n".join(clean_lines),
        "image_url": image_url
    }

async def scrape_bay_area_page(url: str, browser=None) -> dict:
    if browser:
        # Reuse the existing browser instance by creating a new page on it
        page = await browser.new_page()
        print(f"Scraping with reused browser: {url}...")
        try:
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                print(f"Warning: Navigation timed out or encountered an issue, proceeding: {e}")
            html_content = await page.content()
            return parse_html_to_text(html_content, url)
        finally:
            await page.close()
    else:
        # Launch a temporary standalone headless browser (backwards compatible)
        async with async_playwright() as p:
            browser_instance = await p.chromium.launch(headless=True)
            page = await browser_instance.new_page()
            print(f"Scraping with standalone browser: {url}...")
            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                except Exception as e:
                    print(f"Warning: Navigation timed out or encountered an issue, proceeding: {e}")
                html_content = await page.content()
                return parse_html_to_text(html_content, url)
            finally:
                await browser_instance.close()

# Example usage to test the output
if __name__ == "__main__":
    test_url = "https://sf.funcheap.com/" # Great local free event source
    result = asyncio.run(scrape_bay_area_page(test_url))
    print("Scraped Image URL:", result["image_url"])
    print("Scraped Text Preview:", result["text"][:1000]) # View the first 1000 characters