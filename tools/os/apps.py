import logging
import subprocess
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.OS.Apps")


def _run_applescript(script: str):
    return subprocess.check_output(["osascript", "-e", script], text=True)


@function_tool()
async def open_app(context: RunContext, app_name: str) -> str:
    """
    Asynchronously opens a specified application on macOS using AppleScript.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        app_name (str): The name of the application to open.
    Returns:
        str: A message indicating whether the application was successfully opened or if an error occurred.
    Raises:
        Exception: Logs and handles any exceptions that occur during the execution of the AppleScript command.
    """

    try:
        logger.info(f"Opening app: {app_name}")
        _run_applescript(f'tell application "{app_name}" to activate')
        return f"Opened {app_name}"
    except Exception as e:
        logger.exception(f"Failed to open app {app_name}")
        return f"Could not open application: {app_name}"


@function_tool()
async def quit_app(context: RunContext, app_name: str) -> str:
    """
    Asynchronously quits a specified application on macOS using AppleScript.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        app_name (str): The name of the application to quit.
    Returns:
        str: A message indicating whether the application was successfully closed 
             or if an error occurred.
    Raises:
        Exception: Logs an exception if the application could not be closed.
    """

    try:
        logger.info(f"Quitting app: {app_name}")
        _run_applescript(f'tell application "{app_name}" to quit')
        return f"Closed {app_name}"
    except Exception as e:
        logger.exception(f"Failed to quit app {app_name}")
        return f"Could not close application: {app_name}"


@function_tool()
async def focus_app(context: RunContext, app_name: str) -> str:
    """
    Focuses on the specified application by bringing it to the foreground.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        app_name (str): The name of the application to focus.
    Returns:
        str: A message indicating whether the application was successfully focused 
             or if an error occurred.
    Raises:
        Exception: Logs an exception if the application cannot be focused.
    """

    try:
        logger.info(f"Focusing app: {app_name}")
        _run_applescript(f'tell application "{app_name}" to activate')
        return f"Focused on {app_name}"
    except Exception as e:
        logger.exception(f"Failed to focus app {app_name}")
        return f"Could not focus application: {app_name}"


@function_tool()
async def list_apps(context: RunContext) -> str:
    """
    Lists the names of currently running applications on the system.
    This function uses AppleScript to fetch the names of all running applications
    that are not background-only processes. It executes the AppleScript command
    and returns the output as a string. If an error occurs during execution, it
    logs the exception and returns a default error message.
    Args:
        context (RunContext): The runtime context in which the function is executed.
    Returns:
        str: A string containing the names of running applications, separated by commas,
             or an error message if the operation fails.
    """

    try:
        script = 'tell application "System Events" to get name of (processes where background only is false)'
        output = _run_applescript(script)
        logger.info("Fetched running apps")
        return output.strip()
    except Exception as e:
        logger.exception("Failed to list running apps")
        return "Could not retrieve running applications."