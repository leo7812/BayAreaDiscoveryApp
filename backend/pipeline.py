import asyncio
import json
from scrapers import scrape_bay_area_page
from parser import parse_text_to_json, parse_detail_text_to_json

async def run_pipeline():
    print("🚀 Starting Local Bay Area Discovery Pipeline...")
    
    # A great test case: standard local entertainment/event listing
    target_url = "https://sf.funcheap.com/"
    
    # 1. Scrape the page text and image
    scraped_data = await scrape_bay_area_page(target_url)
    
    if not scraped_data or not scraped_data.get("text"):
        print("❌ Pipeline aborted: Scraping returned no text.")
        return
        
    print(f"🧠 Passing {len(scraped_data['text'])} characters of text to Llama 3.2...")
    print(f"🖼️ Scraped Banner Image URL: {scraped_data.get('image_url')}")
    
    # 2. Let the LLM structure the data
    structured_json = parse_text_to_json(scraped_data["text"])
    
    print("\n🎉 Hop 1 Complete! Structured Discoveries Found:")
    print(json.dumps(structured_json, indent=2))
    
    # 3. Test Hop 2 details enrichment on the first item with a URL
    items = structured_json.get("items", [])
    if items:
        # Find first item with a URL
        target_item = None
        for item in items:
            if item.get("url") and item["url"].startswith("http"):
                target_item = item
                break
                
        if target_item:
            print(f"\n🔗 Testing Hop 2 details enrichment on: {target_item['name']} ({target_item['url']})...")
            try:
                detail_scraped = await scrape_bay_area_page(target_item["url"])
                if detail_scraped and detail_scraped.get("text"):
                    print(f"🧠 Parsing detail page: {len(detail_scraped['text'])} chars...")
                    detail_parsed = parse_detail_text_to_json(detail_scraped["text"])
                    print("🎉 Detail Parsed Results:")
                    print(json.dumps(detail_parsed, indent=2))
                    
                    if detail_parsed:
                        for field in ["description", "neighborhood", "date_or_hours"]:
                            val = detail_parsed.get(field)
                            if val:
                                target_item[field] = val
                        if detail_scraped.get("image_url"):
                            target_item["image_url"] = detail_scraped["image_url"]
                            
                    print("\n🎉 Hop 2 Complete! Enriched Item:")
                    print(json.dumps(target_item, indent=2))
            except Exception as e:
                print(f"❌ Hop 2 failed: {e}")
                
    # Optionally save results locally for previewing
    with open("discoveries_preview.json", "w") as f:
        json.dump(structured_json, f, indent=2)
    print("\n💾 Saved to discoveries_preview.json")

if __name__ == "__main__":
    asyncio.run(run_pipeline())