import logging
from livekit.agents import function_tool, RunContext
import requests

@function_tool()
async def get_weather(context: RunContext, city: str) -> str:
    """
    Fetches the current weather information for a specified city.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        city (str): The name of the city for which to retrieve the weather.
    Returns:
        str: A string containing the weather information in a concise format, or an error message if the request fails.
    Raises:
        Exception: Logs and handles any exceptions that occur during the HTTP request.
    Note:
        This function uses the wttr.in service to fetch weather data. Ensure that the `requests` library is installed
        and that the service is accessible from the network.
    """
    try:
        response = requests.get(
            f"https://wttr.in/{city}?format=3"
        )

        if response.status_code == 200:
            logging.info(f"Weather for {city} : {response.text.strip()}")
            return response.text.strip()

        else:
            logging.error(f"Failed to get weather for {city}: {response.status_code}")
            return response.text.strip()
    except Exception as e:
        logging.error(f"Error retrieving weather for {city} : {e}")
        return f"An error occurred while retrieving weather for {city}"