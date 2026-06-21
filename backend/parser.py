import json
import requests
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

# Testing the workflow
if __name__ == "__main__":
    sample_text = "Join us this Friday night for the Mission District Art Walk! Starting at 6 PM on Valencia St. Enjoy street tacos and local galleries."
    structured_data = parse_text_to_json(sample_text)
    print(json.dumps(structured_data, indent=2))