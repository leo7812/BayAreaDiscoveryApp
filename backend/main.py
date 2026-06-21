import os
import json
import asyncio
import requests
from typing import List, Optional
from pydantic import BaseModel, Field

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

# Import local modules
from scrapers import scrape_bay_area_page
from parser import (
    parse_text_to_json,
    parse_detail_text_to_json,
    parse_index_with_selectors,
    parse_detail_with_selectors,
    LocalDiscovery,
    DiscoveryList
)

# Initialize FastAPI application
app = FastAPI(
    title="Bay Area Discovery API",
    description="Local backend API serving scraped and LLM-extracted Bay Area food, events, and scenic views.",
    version="1.0.0"
)

# Enable CORS for local cross-origin requests (e.g., simulators, frontend frameworks)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database file setup
DB_FILE = os.path.join(os.path.dirname(__file__), "discoveries.json")

# Global tracking variable for active background scraper runs
is_scraping_active = False

# Global tracking variable for active background enrichment worker runs
is_enrichment_active = False

# Lock to serialize file read/write access across concurrent scrape tasks
db_lock = asyncio.Lock()

async def async_save_discoveries(data: dict):
    """Saves structured discoveries list to discoveries.json asynchronously under a lock."""
    async with db_lock:
        try:
            with open(DB_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"Error saving discoveries to disk: {e}")

async def update_item_in_db(enriched_item: dict):
    """Updates a single discovery item's detailed properties in discoveries.json under a lock."""
    async with db_lock:
        # Load discoveries safely
        if not os.path.exists(DB_FILE):
            db = {"items": []}
        else:
            try:
                with open(DB_FILE, "r") as f:
                    db = json.load(f)
            except Exception:
                db = {"items": []}
                
        # Find item by name (case-insensitive)
        for i, item in enumerate(db.get("items", [])):
            if item["name"].lower() == enriched_item["name"].lower():
                db["items"][i] = enriched_item
                break
        else:
            db["items"].append(enriched_item)
            
        try:
            with open(DB_FILE, "w") as f:
                json.dump(db, f, indent=2)
        except Exception as e:
            print(f"Error updating enriched item in discoveries.json: {e}")

class ScrapeRequest(BaseModel):
    url: str = Field(description="The target web URL to scrape and extract discoveries from.")

def load_discoveries() -> dict:
    """Reads structured discoveries list from local discoveries.json file."""
    if not os.path.exists(DB_FILE):
        return {"items": []}
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading discoveries from disk: {e}")
        return {"items": []}

def save_discoveries(data: dict):
    """Saves structured discoveries list to local discoveries.json file."""
    try:
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Error saving discoveries to disk: {e}")
        raise HTTPException(status_code=500, detail="Failed to save data to local storage.")

@app.on_event("startup")
def on_startup():
    """Trigger background enrichment worker on startup if there are pending items."""
    print("🚀 FastAPI application started. Checking for pending enrichments...")
    start_enrichment_worker()

@app.get("/health")
def health_check():
    """Checks the status of the local server dependencies (Ollama connection & File Storage)."""
    ollama_online = False
    try:
        # Quick non-blocking connection check to local Ollama service
        response = requests.get("http://localhost:11434/api/tags", timeout=1.5)
        if response.status_code == 200:
            ollama_online = True
    except Exception:
        pass

    return {
        "status": "healthy",
        "ollama_connected": ollama_online,
        "storage_exists": os.path.exists(DB_FILE)
    }

def clean_discovery_item(item: dict) -> dict:
    """Post-processes extracted fields to sanitize values for the iOS UI."""
    if "name" in item:
        item["name"] = item["name"].strip()
        
    neighborhood = item.get("neighborhood", "").strip()
    if not neighborhood or neighborhood.lower() in ["unknown", "n/a", "none", "false", "null", "state", "other"]:
        item["neighborhood"] = "San Francisco"
    else:
        item["neighborhood"] = neighborhood
        
    category = item.get("category", "Event").strip()
    if category.lower() == "food":
        item["category"] = "Food"
    elif category.lower() == "view":
        item["category"] = "View"
    else:
        item["category"] = "Event"
        
    desc = item.get("description", "").strip()
    if not desc:
        item["description"] = f"A local {item['category'].lower()} worth exploring in {item['neighborhood']}."
    else:
        item["description"] = desc
        
    item["image_url"] = item.get("image_url") or ""
    item["url"] = item.get("url") or ""
    
    # Determine enrichment status
    if "is_enriched" not in item:
        # If there is no URL, it is as enriched as it will ever be.
        if not item["url"] or not item["url"].startswith("http"):
            item["is_enriched"] = True
        else:
            item["is_enriched"] = False
            
    return item

async def enrich_discovery_item_from_detail(item: dict, browser=None) -> dict:
    """Visits the event's detail URL, scrapes the page, and extracts detailed fields."""
    url = item.get("url")
    if not url or not url.startswith("http"):
        item["is_enriched"] = True
        return item
        
    print(f"🔗 Hop 2: Scraping detail page: {url}...")
    try:
        scraped_data = await scrape_bay_area_page(url, browser=browser)
        if scraped_data:
            # Detail page images are usually higher quality banners
            detail_image = scraped_data.get("image_url")
            if detail_image:
                item["image_url"] = detail_image
                
            # Run structured parsing (code-based selectors or LLM fallback)
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower()
            
            detail_data = None
            if any(k in domain for k in ["funcheap.com", "secretsanfrancisco.com", "dothebay.com"]) and scraped_data.get("html"):
                print(f"🧩 Enriching details with BeautifulSoup selectors for: {url}...")
                detail_data = parse_detail_with_selectors(url, scraped_data["html"])
            elif scraped_data.get("text"):
                print(f"🤖 Falling back to LLM details parsing for: {url}...")
                loop = asyncio.get_running_loop()
                detail_data = await loop.run_in_executor(None, parse_detail_text_to_json, scraped_data["text"])
                
            if detail_data:
                # Enrich neighborhood, description, and hours if present
                for field in ["description", "neighborhood", "date_or_hours"]:
                    val = detail_data.get(field)
                    if val and val.strip() and val.lower() not in ["unknown", "n/a", "none", "false", "null", "state"]:
                        item[field] = val.strip()
        item["is_enriched"] = True
    except Exception as e:
        print(f"⚠️ Error enriching item '{item.get('name')}' from detail page: {e}")
        item["is_enriched"] = True
        
    return item

async def enrich_and_save_item(item: dict, browser=None):
    """Performs detailed scraping/enrichment and writes it directly to the database."""
    enriched = await enrich_discovery_item_from_detail(item, browser=browser)
    enriched = clean_discovery_item(enriched)
    await update_item_in_db(enriched)
    print(f"💾 Dynamically saved enriched event: {enriched.get('name')}")

async def enrichment_worker():
    """Background loop that sequentially scrapes and enriches discoveries using a reused browser."""
    global is_enrichment_active
    print("👷 Starting sequential background enrichment worker...")
    
    from playwright.async_api import async_playwright
    
    try:
        async with async_playwright() as p:
            # Launch exactly ONE headless browser to share
            browser = await p.chromium.launch(headless=True)
            
            while True:
                db = load_discoveries()
                # Find all items where is_enriched is False and we have a valid URL
                unenriched_items = [
                    item for item in db.get("items", [])
                    if not item.get("is_enriched", False) and item.get("url") and item.get("url").startswith("http")
                ]
                
                if not unenriched_items:
                    print("👷 No more unenriched items. Enrichment worker stopping.")
                    break
                
                # Fetch the first one in the list
                target_item = unenriched_items[0]
                item_name = target_item["name"]
                
                print(f"👷 Worker processing enrichment for: '{item_name}'")
                try:
                    await enrich_and_save_item(target_item, browser=browser)
                except Exception as e:
                    print(f"⚠️ Worker error enriching '{item_name}': {e}")
                    # Mark as enriched anyway to prevent infinite loops on failing URLs
                    target_item["is_enriched"] = True
                    await update_item_in_db(clean_discovery_item(target_item))
                
                # Small pause to yield control and be polite to the host websites
                await asyncio.sleep(0.5)
                
            await browser.close()
    except Exception as e:
        print(f"⚠️ Critical error in background enrichment worker: {e}")
    finally:
        is_enrichment_active = False
        print("👷 Sequential background enrichment worker stopped.")

def start_enrichment_worker():
    """Starts the sequential enrichment worker in the background if it is not already running."""
    global is_enrichment_active
    if is_enrichment_active:
        print("👷 Enrichment worker is already active. Skipping duplicate startup.")
        return
    is_enrichment_active = True
    asyncio.create_task(enrichment_worker())

@app.get("/discoveries", response_model=DiscoveryList)
def get_discoveries():
    """Retrieve all stored discoveries with proactive sanitization."""
    db = load_discoveries()
    needs_save = False
    cleaned_items = []
    
    for item in db.get("items", []):
        original_keys = set(item.keys())
        # Copy item to avoid modifying in-place before comparison
        cleaned = clean_discovery_item(dict(item))
        cleaned_items.append(cleaned)
        
        if set(cleaned.keys()) != original_keys or cleaned != item:
            needs_save = True
            
    if needs_save:
        db["items"] = cleaned_items
        save_discoveries(db)
        
    db["is_syncing"] = is_scraping_active
    return db

@app.post("/discoveries", response_model=LocalDiscovery)
def create_discovery(discovery: LocalDiscovery):
    """Manually add a discovery, checking for duplicate names."""
    db = load_discoveries()
    
    # Check if a discovery with the same name already exists (case-insensitive)
    if any(item["name"].lower() == discovery.name.lower() for item in db["items"]):
        raise HTTPException(
            status_code=400, 
            detail=f"A discovery named '{discovery.name}' already exists."
        )
        
    cleaned_dict = clean_discovery_item(discovery.model_dump())
    db["items"].append(cleaned_dict)
    save_discoveries(db)
    return cleaned_dict

@app.post("/discoveries/scrape", response_model=DiscoveryList)
async def scrape_and_extract(request: ScrapeRequest):
    """
    Asynchronously scrape a URL using playwright, clean it, pass to local Ollama,
    and persist new discovery entities into local storage. Returns only newly added items.
    """
    url = str(request.url)
    
    # 1. Scrape content and og:image
    try:
        scraped_data = await scrape_bay_area_page(url)
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Web scraper failed: {str(e)}"
        )
        
    if not scraped_data or not scraped_data.get("text"):
        raise HTTPException(
            status_code=400, 
            detail="Failed to retrieve readable content from the provided URL."
        )
        
    # 2. Extract structured list using hybrid parser (Code-based selectors or LLM fallback)
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        if any(k in domain for k in ["funcheap.com", "secretsanfrancisco.com", "dothebay.com"]):
            print(f"🧩 Parsing index with BeautifulSoup selectors: {url}...")
            structured_data = parse_index_with_selectors(url, scraped_data["html"])
        else:
            print(f"🤖 Falling back to LLM index parsing: {url}...")
            loop = asyncio.get_running_loop()
            structured_data = await loop.run_in_executor(None, parse_text_to_json, scraped_data["text"])
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Extraction engine failed: {str(e)}"
        )
        
    # 3. Deduplicate, enrich from detail pages (Hop 2), and save
    db = load_discoveries()
    existing_names = {item["name"].lower() for item in db["items"]}
    
    new_items = []
    
    for item in structured_data.get("items", []):
        if item.get("name"):
            clean_name = item["name"].strip()
            if clean_name.lower() not in existing_names:
                # Pre-sanitize basic fields first
                item["image_url"] = scraped_data.get("image_url")
                item = clean_discovery_item(item)
                
                # Append to database immediately as placeholder (not enriched yet)
                db["items"].append(item)
                new_items.append(item)
                existing_names.add(clean_name.lower())
                    
    # Save the initial list with placeholders immediately!
    if new_items:
        await async_save_discoveries(db)
        print(f"⚡ Saved {len(new_items)} placeholders to discoveries.json.")
        start_enrichment_worker()
        
    # Reload the database to return the final (enriched) version of the new items
    final_db = load_discoveries()
    final_new_items = [
        item for item in final_db.get("items", []) 
        if item["name"].lower() in {x["name"].lower() for x in new_items}
    ]
    return {"items": final_new_items}

# Curated list of default sources to scrape when triggering a full refresh
DEFAULT_SCRAPE_URLS = [
    "https://sf.funcheap.com/",
    "https://secretsanfrancisco.com/",
    "https://dothebay.com/events"
]

async def background_scrape_all():
    """Background task to scrape all default sources and parse them sequentially."""
    global is_scraping_active
    is_scraping_active = True
    print("🔄 Starting background scrape of all sources...")
    try:
        # 1. Scrape all source pages in parallel
        scrape_tasks = [scrape_bay_area_page(url) for url in DEFAULT_SCRAPE_URLS]
        scraped_results = await asyncio.gather(*scrape_tasks, return_exceptions=True)
        
        valid_results = []
        for url, res in zip(DEFAULT_SCRAPE_URLS, scraped_results):
            if isinstance(res, Exception):
                print(f"Failed to scrape source '{url}': {res}")
            elif res and res.get("text"):
                valid_results.append(res)
                
        if not valid_results:
            print("❌ Background scrape failed: No readable content found on any source site.")
            return
            
        # 2. Run extraction (Code-based selectors with LLM fallback)
        db = load_discoveries()
        existing_names = {item["name"].lower().strip() for item in db["items"]}
        
        loop = asyncio.get_running_loop()
        new_items_added = 0
        
        for idx, res in enumerate(valid_results):
            url = DEFAULT_SCRAPE_URLS[idx]
            from urllib.parse import urlparse
            domain = urlparse(url).netloc.lower()
            source_new_added = 0
            try:
                if any(k in domain for k in ["funcheap.com", "secretsanfrancisco.com", "dothebay.com"]):
                    print(f"🧩 Background parsing index with BeautifulSoup selectors: {url}...")
                    structured_data = parse_index_with_selectors(url, res["html"])
                else:
                    print(f"🤖 Background falling back to LLM index parsing: {url}...")
                    structured_data = await loop.run_in_executor(None, parse_text_to_json, res["text"])
                
                for item in structured_data.get("items", []):
                    if item.get("name"):
                        clean_name = item["name"].strip()
                        if clean_name.lower() not in existing_names:
                            # Pre-sanitize basic fields first
                            item["image_url"] = item.get("image_url") or res.get("image_url")
                            item = clean_discovery_item(item)
                            
                            # Append to database immediately as placeholder (not enriched yet)
                            db["items"].append(item)
                            existing_names.add(clean_name.lower())
                            new_items_added += 1
                            source_new_added += 1
                                
                if source_new_added > 0:
                    # Instantly save placeholders for this source so the client displays them immediately
                    await async_save_discoveries(db)
                    print(f"⚡ Saved {source_new_added} placeholders from source {idx} to database.")
            except Exception as e:
                print(f"LLM extraction failed for source index {idx} in background: {e}")
                
        # Start sequential background enrichment worker
        if new_items_added > 0:
            print(f"✅ Background scrape complete! Added {new_items_added} new items. Starting enrichment worker...")
            start_enrichment_worker()
        else:
            print("ℹ️ Background scrape complete! No new items were added.")
            
    except Exception as e:
        print(f"❌ Critical error in background_scrape_all: {e}")
    finally:
        is_scraping_active = False

@app.post("/discoveries/scrape-all", response_model=DiscoveryList)
async def scrape_all_sources(background_tasks: BackgroundTasks):
    """
    Triggers a background scrape of all default Bay Area event websites,
    and immediately returns the current stored discoveries list.
    """
    background_tasks.add_task(background_scrape_all)
    return get_discoveries()

@app.post("/discoveries/clear")
def clear_discoveries():
    """Clear all entries from the local database file."""
    save_discoveries({"items": []})
    return {"message": "Database cleared successfully."}

if __name__ == "__main__":
    import uvicorn
    # Local server default port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
