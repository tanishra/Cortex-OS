import logging
from playwright.async_api import async_playwright
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.Browser")

browser_context = None


async def _get_browser():
    global browser_context
    if browser_context is None:
        p = await async_playwright().start()
        browser = await p.webkit.launch(headless=False)
        browser_context = await browser.new_context()
    return browser_context


@function_tool()
async def open_new_tab(context: RunContext, url: str) -> str:
    """
    Opens a new browser tab and navigates to the specified URL.
    Args:
        context (RunContext): The runtime context for the operation.
        url (str): The URL to navigate to in the new tab.
    Returns:
        str: A message indicating the success or failure of the operation.
    Raises:
        Exception: If an error occurs while opening the new tab or navigating to the URL.
    Logs:
        Logs the success or failure of the operation.
    """

    try:
        ctx = await _get_browser()
        page = await ctx.new_page()
        await page.goto(url)
        logger.info(f"Opened new tab: {url}")
        return f"Opened {url}"
    except Exception:
        logger.exception("Failed to open new tab")
        return "Failed to open new tab."


@function_tool()
async def search_on_page(context: RunContext, query: str) -> str:
    """
    Searches for a given query string on the currently active browser page.
    This function uses the browser context to simulate a "find" operation 
    on the page by pressing the "Meta+F" key combination and typing the 
    query string. It logs the search operation and returns a success message 
    if the operation is completed successfully. If an error occurs, it logs 
    the exception and returns a failure message.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        query (str): The string to search for on the page.
    Returns:
        str: A message indicating the result of the search operation.
    """

    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]
        await page.keyboard.press("Meta+F")
        await page.keyboard.type(query)
        logger.info(f"Searched on page: {query}")
        return f"Searched for {query}"
    except Exception:
        logger.exception("Search failed")
        return "Search failed."


@function_tool()
async def click_element(context: RunContext, selector: str) -> str:
    """
    Clicks on an HTML element specified by the given selector.
    Args:
        context (RunContext): The runtime context for the operation.
        selector (str): The CSS selector of the HTML element to click.
    Returns:
        str: A message indicating whether the click operation was successful or not.
    Raises:
        Exception: Logs and handles any exceptions that occur during the click operation.
    """

    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]
        await page.click(selector)
        logger.info(f"Clicked element: {selector}")
        return "Clicked successfully."
    except Exception:
        logger.exception("Click failed")
        return "Could not click element."

@function_tool()
async def switch_tab(context: RunContext, index: int) -> str:
    """
    Switches to the specified browser tab by its index.
    Args:
        context (RunContext): The runtime context for the operation.
        index (int): The index of the tab to switch to.
    Returns:
        str: A message indicating the result of the operation, either confirming
             the tab switch or reporting a failure.
    Raises:
        Exception: If the tab switch operation fails, an exception is logged.
    """

    try:
        ctx = await _get_browser()
        await ctx.pages[index].bring_to_front()
        return f"Switched to tab {index}"
    except Exception:
        logger.exception("Tab switch failed")
        return "Failed to switch tab"


@function_tool()
async def scroll_page(context: RunContext, amount: int) -> str:
    """
    Scrolls the current browser page vertically by the specified amount.
    Args:
        context (RunContext): The runtime context for the operation.
        amount (int): The vertical scroll amount. Positive values scroll down, 
                      and negative values scroll up.
    Returns:
        str: A message indicating whether the scroll operation was successful 
             ("Scrolled") or failed ("Failed to scroll").
    Raises:
        Exception: Logs an exception if the scroll operation fails.
    """

    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]
        await page.mouse.wheel(0, amount)
        return "Scrolled"
    except Exception:
        logger.exception("Scroll failed")
        return "Failed to scroll"


@function_tool()
async def go_back(context: RunContext) -> str:
    """
    Navigate the browser to the previous page in its history.
    Args:
        context (RunContext): The runtime context for the operation.
    Returns:
        str: A confirmation message indicating the browser navigated back.
    Raises:
        Any exceptions raised by `_get_browser` or the `go_back` method of the page.
    """

    ctx = await _get_browser()
    await ctx.pages[-1].go_back()
    return "Went back"


@function_tool()
async def go_forward(context: RunContext) -> str:
    """
    Navigate the browser forward in its history.
    This function retrieves the current browser context and navigates the most recently
    opened page forward in its history, if possible.
    Args:
        context (RunContext): The runtime context for the operation.
    Returns:
        str: A confirmation message indicating the action was performed.
    """

    ctx = await _get_browser()
    await ctx.pages[-1].go_forward()
    return "Went forward"