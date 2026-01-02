import logging
import requests
from bs4 import BeautifulSoup
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.WebScraper")


@function_tool()
async def scrape_page(context: RunContext, url: str, max_chars: int = 4000) -> str:
    """
    Scrape visible text content from a web page.

    Args:
        url: Web page URL (scheme optional)
        max_chars: Maximum characters to return
    """

    try:
        if not url.startswith("http"):
            url = "https://" + url

        logger.info(f"Scraping URL: {url}")

        headers = {
            "User-Agent": "Mozilla/5.0 (CortexOS/1.0)"
        }

        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        text = " ".join(soup.stripped_strings)

        if not text:
            return "No readable content found on the page."

        cleaned = text[:max_chars]

        logger.info(f"Scraped {len(cleaned)} characters from {url}")
        return cleaned

    except requests.Timeout:
        logger.error(f"Timeout while scraping {url}")
        return "Request timed out while accessing the web page."

    except requests.HTTPError as e:
        logger.error(f"HTTP error while scraping {url}: {e}")
        return "Failed to retrieve the page due to HTTP error."

    except Exception:
        logger.exception(f"Unexpected error scraping {url}")
        return "An unexpected error occurred while scraping the web page."