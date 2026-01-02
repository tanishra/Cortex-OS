import logging
import requests
from bs4 import BeautifulSoup
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.WebScraper")


@function_tool()
async def scrape_page(context: RunContext, url: str, max_chars: int = 4000) -> str:
    """
    Scrape the content of a web page and return a cleaned text snippet.
    This function fetches the content of the specified URL, removes unnecessary
    elements such as scripts, styles, and noscripts, and extracts readable text.
    The extracted text is truncated to a maximum number of characters specified
    by `max_chars`.
    Args:
        context (RunContext): The runtime context for the operation.
        url (str): The URL of the web page to scrape. If the URL does not start
            with "http", "https://" will be prepended automatically.
        max_chars (int, optional): The maximum number of characters to return
            from the scraped content. Defaults to 4000.
    Returns:
        str: A cleaned and truncated snippet of the web page content. If no
        readable content is found, or if an error occurs, an appropriate error
        message is returned.
    Raises:
        None: All exceptions are caught and logged, and an error message is
        returned instead of raising exceptions.
    Notes:
        - The function uses a custom User-Agent header to mimic a browser request.
        - The function logs the scraping process, including errors, for debugging.
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