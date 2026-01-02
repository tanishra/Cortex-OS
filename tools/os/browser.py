import logging
import webbrowser
import subprocess
import platform
from urllib.parse import quote_plus
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.OS.Browser")


def _open(url: str):
    """
    Open a URL in the default web browser based on the operating system.
    Args:
        url (str): The URL to be opened.
    Behavior:
        - On macOS (Darwin), it uses the `open` command.
        - On Windows, it uses the `start` command.
        - On Linux/Unix, it uses the `xdg-open` command.
    Note:
        This function spawns a subprocess to execute the appropriate command
        for opening the URL in the default browser.
    """

    system = platform.system()

    if system == "Darwin":
        subprocess.Popen(["open", url])
    elif system == "Windows":
        subprocess.Popen(["start", url], shell=True)
    else:
        subprocess.Popen(["xdg-open", url])


@function_tool()
async def open_url(context: RunContext, url: str) -> str:
    """
    Asynchronously opens a given URL in the default web browser.
    Args:
        context (RunContext): The execution context for the function.
        url (str): The URL to be opened. If the URL does not start with "http",
                   "https://" will be prefixed automatically.
    Returns:
        str: A message indicating whether the URL was successfully opened or not.
    Raises:
        Exception: Logs an exception if there is an error while attempting to open the URL.
    """

    try:
        if not url.startswith("http"):
            url = "https://" + url

        _open(url)
        logger.info(f"Opened URL: {url}")
        return f"Opened {url}"

    except Exception as e:
        logger.exception(f"Failed to open URL {url}")
        return f"Could not open {url}"


@function_tool()
async def search_google(context: RunContext, query: str) -> str:
    """
    Perform a Google search for the given query.
    This function constructs a Google search URL using the provided query,
    opens the URL in the default web browser, and logs the search activity.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        query (str): The search query string.
    Returns:
        str: A message indicating the search query or an error message if the search fails.
    Raises:
        Exception: Logs an exception if the Google search fails.
    """

    try:
        url = f"https://www.google.com/search?q={quote_plus(query)}"
        _open(url)
        logger.info(f"Google search: {query}")
        return f"Searched Google for: {query}"

    except Exception:
        logger.exception("Google search failed")
        return "Google search failed"


@function_tool()
async def search_youtube(context: RunContext, query: str) -> str:
    """
    Searches YouTube for the given query and opens the results page in the default web browser.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        query (str): The search query to look up on YouTube.
    Returns:
        str: A message indicating the search query was executed, or an error message if the search failed.
    Raises:
        Exception: Logs an exception if the YouTube search fails.
    """

    try:
        url = f"https://www.youtube.com/results?search_query={quote_plus(query)}"
        _open(url)
        logger.info(f"YouTube search: {query}")
        return f"Searched YouTube for: {query}"

    except Exception:
        logger.exception("YouTube search failed")
        return "YouTube search failed"


@function_tool()
async def open_github(context: RunContext, repo: str) -> str:
    """
    Asynchronously opens a GitHub repository in the default web browser.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        repo (str): The GitHub repository in the format "owner/repository".
    Returns:
        str: A message indicating whether the GitHub repository was successfully opened 
             or if the operation failed.
    Logs:
        Logs an informational message if the repository is successfully opened.
        Logs an exception message if an error occurs during the operation.
    Raises:
        Exception: If an unexpected error occurs while attempting to open the repository.
    """

    try:
        url = f"https://github.com/{repo}"
        _open(url)
        logger.info(f"Opened GitHub repo: {repo}")
        return f"Opened GitHub repo {repo}"

    except Exception:
        logger.exception("Failed to open GitHub repository")
        return "Failed to open GitHub repository"


@function_tool()
async def open_stackoverflow(context: RunContext, query: str) -> str:
    """
    Asynchronously performs a search on StackOverflow with the given query and opens the results in a web browser.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        query (str): The search query to be used on StackOverflow.
    Returns:
        str: A message indicating the search query that was performed, or an error message if the search failed.
    Raises:
        Exception: Logs an exception if the search operation fails.
    """

    try:
        url = f"https://stackoverflow.com/search?q={quote_plus(query)}"
        _open(url)
        logger.info(f"StackOverflow search: {query}")
        return f"Searched StackOverflow for: {query}"

    except Exception:
        logger.exception("StackOverflow search failed")
        return "StackOverflow search failed"