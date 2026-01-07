import logging
import subprocess
import os
from pathlib import Path
from difflib import get_close_matches
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.OS.Apps")

APPLICATION_DIRS = [
    "/Applications",
    "/System/Applications",
    str(Path.home() / "Applications")
]


def _run_applescript(script: str):
    return subprocess.check_output(["osascript", "-e", script], text=True)


def _list_installed_apps():
    apps = []
    for directory in APPLICATION_DIRS:
        if os.path.exists(directory):
            for item in os.listdir(directory):
                if item.endswith(".app"):
                    apps.append(item.replace(".app", ""))
    return apps


def _resolve_app_name(name: str) -> str:
    installed = _list_installed_apps()
    match = get_close_matches(name, installed, n=1, cutoff=0.6)
    return match[0] if match else name


@function_tool()
async def open_app(context: RunContext, app_name: str) -> str:
    """
    Asynchronously opens a specified application on macOS using AppleScript.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        app_name (str): The name of the application to open.
    Returns:
        str: A message indicating whether the application was successfully opened 
             or if an error occurred.
    Raises:
        Exception: Logs an exception if the application cannot be opened.
    Note:
        This function uses AppleScript to activate the application. Ensure that the
        application name is resolvable and that the script has the necessary permissions.
    """

    try:
        resolved = _resolve_app_name(app_name)
        logger.info(f"Opening app: {resolved}")
        _run_applescript(f'tell application "{resolved}" to activate')
        return f"Opened {resolved}"
    except Exception:
        logger.exception(f"Failed to open app {app_name}")
        return f"Could not open application: {app_name}"


@function_tool()
async def quit_app(context: RunContext, app_name: str) -> str:
    """
    Asynchronously quits a specified application on macOS.
    This function attempts to resolve the given application name, logs the action,
    and uses AppleScript to quit the application. If the operation fails, it logs
    the exception and returns an error message.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        app_name (str): The name of the application to quit.
    Returns:
        str: A message indicating whether the application was successfully closed
             or if an error occurred.
    """

    try:
        resolved = _resolve_app_name(app_name)
        logger.info(f"Quitting app: {resolved}")
        _run_applescript(f'tell application "{resolved}" to quit')
        return f"Closed {resolved}"
    except Exception:
        logger.exception(f"Failed to quit app {app_name}")
        return f"Could not close application: {app_name}"


@function_tool()
async def focus_app(context: RunContext, app_name: str) -> str:
    """
    Focuses on the specified application by bringing it to the foreground.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        app_name (str): The name of the application to focus on.
    Returns:
        str: A message indicating whether the application was successfully focused or not.
    Raises:
        Exception: Logs an exception if the application cannot be focused.
    Notes:
        - The function resolves the application name using `_resolve_app_name`.
        - It uses AppleScript to activate the application.
        - Ensure that the application name provided is valid and resolvable.
    """

    try:
        resolved = _resolve_app_name(app_name)
        logger.info(f"Focusing app: {resolved}")
        _run_applescript(f'tell application "{resolved}" to activate')
        return f"Focused on {resolved}"
    except Exception:
        logger.exception(f"Failed to focus app {app_name}")
        return f"Could not focus application: {app_name}"


@function_tool()
async def list_apps(context: RunContext) -> str:
    """
    Asynchronously retrieves and returns a sorted list of installed applications.
    Args:
        context (RunContext): The runtime context in which the function is executed.
    Returns:
        str: A newline-separated string of sorted application names if successful,
             or an error message if the retrieval fails.
    Logs:
        - Logs an informational message upon successfully fetching the list of applications.
        - Logs an exception message if an error occurs during the process.
    """

    try:
        apps = _list_installed_apps()
        logger.info("Fetched installed applications list")
        return "\n".join(sorted(apps))
    except Exception:
        logger.exception("Failed to list applications")
        return "Could not retrieve applications."