import logging
from livekit.agents import function_tool, RunContext
from langchain_community.tools import DuckDuckGoSearchRun

@function_tool()
async def search(context: RunContext, query: str) -> str:
    """
    Performs a web search using the DuckDuckGo search tool.
    Args:
        context (RunContext): The context in which the tool is being executed.
        query (str): The search query string.
    Returns:
        str: The search results as a string, or an error message if the search fails.
    Logs:
        Logs the search results or any errors encountered during the search process.
    """

    try:
        results = DuckDuckGoSearchRun().run(tool_input=query)
        logging.info(f"Search results for {query} : {results}")
        return results
    except Exception as e:
        logging.error(f"Error searching the web for {query} : {e}")
        return f"An error occurred while searching for {query}"