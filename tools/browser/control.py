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
    Asynchronously clicks an element on a web page based on a given selector.
    This function attempts to click an element on the currently active browser page.
    It first tries to use the provided selector directly. If that fails, it falls
    back to searching for elements (input, button, or anchor tags) and matches their
    inner text with the selector.
    Args:
        context (RunContext): The runtime context for the operation.
        selector (str): The CSS selector or text to identify the element to click.
    Returns:
        str: A message indicating the result of the click operation:
             - "Clicked successfully." if the click was successful.
             - "Could not find clickable element: {selector}" if no matching element was found.
             - "Click failed." if an unexpected error occurred.
    Raises:
        Exception: Logs and raises exceptions encountered during the operation.
    """

    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]

        # Try raw selector first
        try:
            await page.click(selector, timeout=5000)
            logger.info(f"Clicked selector: {selector}")
            return "Clicked successfully."
        except Exception:
            logger.warning(f"Raw selector failed: {selector}")

        # Fallback: try text-based matching
        elements = await page.query_selector_all("input, button, a")
        for el in elements:
            text = (await el.inner_text() or "").lower()
            if selector.lower() in text:
                await el.click()
                logger.info(f"Clicked element by text match: {selector}")
                return "Clicked successfully."

        return f"Could not find clickable element: {selector}"

    except Exception:
        logger.exception("Click failed")
        return "Click failed."


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

@function_tool()
async def close_current_tab(context: RunContext) -> str:
    """
    Close the currently active browser tab.

    This function retrieves the current browser instance and closes the most
    recently opened page (assumed to be the active tab). Errors are caught and
    logged to ensure the agent does not crash if the operation fails.

    Args:
        context (RunContext): The runtime context for the operation, supplied
            by the agent framework.

    Returns:
        str: A message confirming that the tab was closed, or an error message
        if the operation could not be completed.
    """
     
    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]
        await page.close()
        logger.info("Closed current tab")
        return "Closed current tab."
    except Exception:
        logger.exception("Failed to close current tab")
        return "Could not close current tab."


@function_tool()
async def close_tab_by_index(context: RunContext, index: int) -> str:
    """
    Close a browser tab by its index in the browser's page list.

    This function retrieves the current browser instance and attempts to close
    the tab located at the specified index in the list of open pages.

    Args:
        context (RunContext): The runtime context provided by the agent framework.
        index (int): The zero-based index of the tab to close.

    Returns:
        str: A confirmation message if the tab was successfully closed,
        or an error message if the index is invalid or the operation fails.
    """
    try:
        ctx = await _get_browser()
        await ctx.pages[index].close()
        logger.info(f"Closed tab {index}")
        return f"Closed tab {index}."
    except Exception:
        logger.exception(f"Failed to close tab {index}")
        return f"Could not close tab {index}."

@function_tool()
async def close_tab_by_title(context: RunContext, title: str) -> str:
    """
    Close a browser tab whose title matches or contains a given string.

    This function searches through all open browser tabs and compares their
    titles against the provided string (case-insensitive). The first matching
    tab is closed.

    Args:
        context (RunContext): The runtime context provided by the agent framework.
        title (str): A partial or full title string used to identify the tab.

    Returns:
        str: A confirmation message if a matching tab was found and closed,
        or a message indicating that no matching tab exists.
    """
    try:
        ctx = await _get_browser()
        for page in ctx.pages:
            if title.lower() in (await page.title()).lower():
                await page.close()
                logger.info(f"Closed tab with title: {title}")
                return f"Closed tab containing {title}."
        return f"No tab found containing {title}."
    except Exception:
        logger.exception("Failed to close tab by title")
        return "Could not close the tab."


@function_tool()
async def close_all_tabs(context: RunContext) -> str:
    """
    Close all currently open browser tabs.

    This function iterates through every open page in the browser instance
    and closes them one by one. Errors are handled to prevent agent failure.

    Args:
        context (RunContext): The runtime context provided by the agent framework.

    Returns:
        str: A confirmation message indicating all tabs were closed,
        or an error message if the operation failed.
    """
    try:
        ctx = await _get_browser()
        for page in ctx.pages:
            await page.close()
        logger.info("Closed all tabs")
        return "All tabs closed."
    except Exception:
        logger.exception("Failed to close all tabs")
        return "Could not close all tabs."

@function_tool()
async def smart_click(context: RunContext, intent: str) -> str:
    """
    Attempt to intelligently locate and click an element based on user intent.

    This function scans common interactive elements (inputs, buttons, links,
    and role-based elements) on the active page. It attempts to match the
    provided intent string against accessible labels such as aria-label,
    placeholder text, or visible inner text.
    """
    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]
        intent_lc = intent.lower()

        # Use locators instead of ElementHandles (DOM-safe)
        locator = page.locator(
            "input, button, a, div[role='button'], span"
        )

        count = await locator.count()

        for i in range(count):
            el = locator.nth(i)

            try:
                label = (
                    ((await el.get_attribute("aria-label")) or "") +
                    ((await el.get_attribute("placeholder")) or "") +
                    ((await el.inner_text()) or "")
                ).lower()

                if intent_lc in label:
                    # Ensure element is stable and visible
                    await el.scroll_into_view_if_needed()
                    await el.wait_for(state="visible", timeout=3000)

                    # Click safely (handles DOM re-renders)
                    await el.click(timeout=5000)

                    logger.info(f"Smart clicked element for intent: {intent}")
                    return f"Clicked {intent}"

            except Exception:
                # Ignore transient DOM failures and continue scanning
                continue

        return f"Could not locate clickable element related to {intent}"

    except Exception:
        logger.exception("Smart click failed")
        return "Smart click failed"

@function_tool()
async def submit_search(context: RunContext) -> str:
    """
    Submit the current search or form by simulating an Enter key press.

    This function sends an "Enter" keypress event to the active page, which
    typically triggers form submission or search execution depending on
    the focused element.

    Args:
        context (RunContext): The runtime context provided by the agent framework.

    Returns:
        str: A confirmation message indicating the search was submitted,
        or an error message if the operation failed.
    """
    try:
        ctx = await _get_browser()
        page = ctx.pages[-1]

        await page.keyboard.press("Enter")
        logger.info("Search submitted via keyboard")
        return "Search submitted"

    except Exception:
        logger.exception("Search submit failed")
        return "Could not submit search"