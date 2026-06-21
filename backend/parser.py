import json
import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

# Define the precise data structure you want back from the LLM
class LocalDiscovery(BaseModel):
    name: str
    category: Literal["Food", "Event", "View"] = Field(description="The primary classification of the discovery: Food, Event, or View.")
    neighborhood: str = Field(description="Specific neighborhood (e.g., 'Mission District', 'Berkeley', 'Oakland'). If the specific neighborhood is not mentioned, use the city name (e.g., 'San Francisco', 'Oakland') or fall back to 'Bay Area' instead of using 'Unknown' or empty string.")
    description: str = Field(description="A brief 2-sentence hook of why this is worth checking out.")
    date_or_hours: Optional[str] = Field(description="Date of event or operational hours if a business.")
    image_url: str = Field(description="Direct URL to the banner or thumbnail image. If no image is found, return an empty string.")
    url: str = Field(description="The absolute URL of the event's detail page, extracted from the markdown link like [Name](URL). If no URL is found, return an empty string.")
    is_enriched: bool = Field(default=False, description="True if detailed second-hop enrichment has finished.")

class DiscoveryList(BaseModel):
    items: List[LocalDiscovery]
    is_syncing: bool = Field(default=False, description="True if a background scraping task is currently running on the server.")

class EventDetails(BaseModel):
    description: str = Field(description="A brief 2-sentence hook of why this is worth checking out.")
    neighborhood: str = Field(description="Specific neighborhood or venue name (e.g., 'Mission District', 'Golden Gate Park'). If not mentioned, use the city name or fall back to 'San Francisco'.")
    date_or_hours: Optional[str] = Field(description="Date of the event or operational hours.")

def parse_text_to_json(raw_scraped_text: str) -> dict:
    """Uses a local LLM via Ollama to pull structured events out of raw text."""
    url = "http://localhost:11434/api/chat"
    
    system_prompt = (
        "You are a local data extraction engine for the San Francisco Bay Area. "
        "Your job is to read messy, scraped webpage text and extract valid events, restaurants, or views. "
        "Ignore site ads, layout text, and generic links. Return data strictly matching the requested JSON schema."
    )
    
    user_prompt = (
        "Extract up to 10 main unique local entities from this text. "
        "CRITICAL: For the 'url' field, you MUST extract and copy the exact absolute URL found inside the parenthesis "
        "of the markdown link `[Text](URL)`. Do NOT alter, abbreviate, or guess the URL path.\n\n"
        f"Text:\n{raw_scraped_text[:16000]}"
    )
    
    payload = {
        "model": "llama3.2", # Free 3B parameter model perfect for structured extraction
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "format": DiscoveryList.model_json_schema(), # Forces the LLM to adhere to your Pydantic schema
        "options": {
            "num_predict": 2048 # Prevent infinite JSON generation loops while avoiding truncation
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        response_json = response.json()
        output_content = response_json['message']['content']
        return json.loads(output_content)
    except Exception as e:
        print(f"Error communicating with local LLM: {e}")
        return {"items": []}

def parse_detail_text_to_json(raw_scraped_text: str) -> dict:
    """Uses a local LLM via Ollama to extract details of a single event from its detail page."""
    url = "http://localhost:11434/api/chat"
    
    system_prompt = (
        "You are a local data extraction engine. "
        "Your job is to read scraped detail page text and extract details about the main event described. "
        "Return data strictly matching the requested JSON schema."
    )
    
    user_prompt = f"Extract details for the main event described in this text. Provide a rich description summarizing what the event is, along with the neighborhood and date/hours:\n\n{raw_scraped_text[:5000]}"
    
    payload = {
        "model": "llama3.2",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "stream": False,
        "format": EventDetails.model_json_schema(),
        "options": {
            "num_predict": 512
        }
    }
    
    try:
        response = requests.post(url, json=payload)
        response_json = response.json()
        output_content = response_json['message']['content']
        return json.loads(output_content)
    except Exception as e:
        print(f"Error parsing event details: {e}")
        return {}

def parse_index_with_selectors(url: str, html: str) -> dict:
    """Dispatches page parsing to site-specific CSS selector engines."""
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    
    items = []
    
    if "funcheap.com" in domain:
        items = _parse_funcheap_index(html)
    elif "secretsanfrancisco.com" in domain:
        items = _parse_secretsf_index(html)
    elif "dothebay.com" in domain:
        items = _parse_dothebay_index(html)
        
    return {"items": items}

def parse_detail_with_selectors(url: str, html: str) -> dict:
    """Extracts description, neighborhood/venue, and date details from known domains."""
    soup = BeautifulSoup(html, "html.parser")
    parsed_url = urlparse(url)
    domain = parsed_url.netloc.lower()
    
    description = ""
    neighborhood = ""
    date_or_hours = ""
    
    if "funcheap.com" in domain:
        entry = soup.find(class_="entry")
        if entry:
            p_texts = [p.text.strip() for p in entry.find_all("p") if p.text.strip()]
            clean_p = [p for p in p_texts if not any(w in p.lower() for w in ["email list", "newsletter", "subscribe", "funcheap", "sponsor"])]
            description = " ".join(clean_p[:2])
            
        details = []
        for tag in soup.find_all(['p', 'span', 'li', 'td', 'tr', 'strong']):
            text = tag.get_text().strip()
            if any(text.startswith(prefix) for prefix in ["Date:", "Time:", "Cost:", "Venue:"]):
                details.append(text)
        if details:
            date_or_hours = " | ".join(list(dict.fromkeys(details))[:3])
            
    elif "secretsanfrancisco.com" in domain:
        content = soup.find(class_="smn-post-content") or soup.find("article")
        if content:
            p_texts = [p.text.strip() for p in content.find_all("p") if p.text.strip()]
            clean_p = [p for p in p_texts if len(p) > 20]
            description = " ".join(clean_p[:2])
            
    elif "dothebay.com" in domain:
        desc_div = soup.find(class_="ds-event-description")
        if desc_div:
            description = desc_div.text.strip()
            lines = [l.strip() for l in description.splitlines() if l.strip()]
            if len(lines) > 2:
                description = " ".join(lines[:3])
                
        venue_div = soup.find(class_="ds-venue-name")
        if venue_div:
            neighborhood = venue_div.text.strip()
            
        time_span = soup.find(class_="ds-event-time")
        if time_span:
            date_or_hours = time_span.text.strip()
            
    return {
        "description": description[:300] if description else None,
        "neighborhood": neighborhood if neighborhood else None,
        "date_or_hours": date_or_hours if date_or_hours else None
    }

def _parse_funcheap_index(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.find_all("div", class_="onecolumn"):
        title_tag = card.find("span", class_="entry-title")
        if not title_tag:
            continue
        a_tag = title_tag.find("a")
        if not a_tag:
            continue
            
        name = a_tag.text.strip()
        url = a_tag.get("href")
        
        img_url = ""
        noscript = card.find("noscript")
        if noscript:
            img_tag = noscript.find("img")
            if img_tag:
                img_url = img_tag.get("src")
        if not img_url:
            img_tag = card.find("img")
            if img_tag:
                img_url = img_tag.get("src")
                if img_url and img_url.startswith("data:image"):
                    img_url = img_tag.get("data-u") or ""
                    
        category = "Event"
        cat_tag = card.find("span", class_="blog-category")
        tags_text = cat_tag.text.strip() if cat_tag else ""
        combined_text = (name + " " + tags_text).lower()
        if any(w in combined_text for w in ["food", "eat", "drink", "sushi", "bakery", "restaurant", "brewery", "tasty"]):
            category = "Food"
        elif any(w in combined_text for w in ["view", "park", "garden", "hike", "beach", "scenic", "sunset", "rooftop"]):
            category = "View"
            
        desc_span = card.find("span", style="color:black;")
        description = desc_span.text.strip() if desc_span else ""
        
        items.append({
            "name": name,
            "category": category,
            "neighborhood": "San Francisco",
            "description": description or f"A local {category.lower()} worth exploring in the Bay Area.",
            "date_or_hours": "",
            "image_url": img_url,
            "url": url,
            "is_enriched": False
        })
    return items

def _parse_secretsf_index(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for article in soup.find_all("article", class_="smn-post-list-item"):
        title_tag = article.find("h2", class_="smn-post-list-item-info__title")
        if not title_tag:
            continue
        a_tag = title_tag.find("a")
        if not a_tag:
            continue
            
        name = a_tag.text.strip()
        url = a_tag.get("href")
        
        img_url = ""
        img_tag = article.find("img")
        if img_tag:
            img_url = img_tag.get("src") or img_tag.get("data-src") or ""
            
        category = "Event"
        cat_links = article.find_all("a", class_="smn-post-list-item-categories__link")
        cats_text = " ".join([c.text.strip() for c in cat_links])
        combined_text = (name + " " + cats_text).lower()
        if any(w in combined_text for w in ["food", "eat", "drink", "restaurant", "bar", "cafe", "dining", "cocktail"]):
            category = "Food"
        elif any(w in combined_text for w in ["view", "scenic", "hike", "nature", "park", "garden", "rooftop", "beach"]):
            category = "View"
            
        items.append({
            "name": name,
            "category": category,
            "neighborhood": "San Francisco",
            "description": f"Explore this exciting {category.lower()} in San Francisco.",
            "date_or_hours": "",
            "image_url": img_url,
            "url": url,
            "is_enriched": False
        })
    return items

def _parse_dothebay_index(html: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for card in soup.find_all(class_="event-card"):
        title_tag = card.find("a", class_="ds-listing-event-title")
        if not title_tag:
            continue
        url_path = title_tag.get("href")
        url = urljoin("https://dothebay.com", url_path)
        
        title_span = card.find(class_="ds-listing-event-title-text")
        name = title_span.text.strip() if title_span else "Local Event"
        
        img_url = ""
        img_div = card.find(class_="ds-cover-image")
        if img_div and img_div.get("style"):
            style = img_div["style"]
            match = re.search(r"url\(['\"]?(https?://[^'\")]+)['\"]?\)", style)
            if match:
                img_url = match.group(1)
                
        venue_span = card.find(class_="ds-venue-name")
        venue_name = venue_span.text.strip() if venue_span else ""
        neighborhood = "San Francisco"
        meta_loc = card.find("meta", itemprop="addressLocality")
        if meta_loc and meta_loc.get("content"):
            neighborhood = meta_loc["content"].strip()
        elif venue_name:
            neighborhood = venue_name
            
        category = "Event"
        classes = " ".join(card.get("class", []))
        if "food" in classes or "drink" in classes:
            category = "Food"
        elif "park" in classes or "view" in classes or "outdoor" in classes:
            category = "View"
            
        date_series = card.find(class_="ds-listing-series")
        date_text = date_series.text.strip() if date_series else ""
        time_div = card.find(class_="ds-event-time")
        time_text = time_div.text.strip() if time_div else ""
        date_or_hours = f"{date_text} {time_text}".strip()
        
        items.append({
            "name": name,
            "category": category,
            "neighborhood": neighborhood,
            "description": f"Check out {name} at {venue_name or 'the venue'}.",
            "date_or_hours": date_or_hours,
            "image_url": img_url,
            "url": url,
            "is_enriched": False
        })
    return items

# Testing the workflow
if __name__ == "__main__":
    sample_text = "Join us this Friday night for the Mission District Art Walk! Starting at 6 PM on Valencia St. Enjoy street tacos and local galleries."
    structured_data = parse_text_to_json(sample_text)
    print(json.dumps(structured_data, indent=2))