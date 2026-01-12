import logging
import os
import subprocess
import platform
from pathlib import Path
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.OS")

HOME = str(Path.home())

COMMON_PATHS = {
    "desktop": str(Path.home() / "Desktop"),
    "downloads": str(Path.home() / "Downloads"),
    "documents": str(Path.home() / "Documents"),
}


def _resolve_path(path: str) -> str:
    """
    Resolves a given path string to its corresponding absolute path.
    This function first normalizes the input path string by converting it to 
    lowercase and stripping any leading or trailing whitespace. It then checks 
    if the normalized path exists in the `COMMON_PATHS` dictionary. If a match 
    is found, the corresponding value from the dictionary is returned. Otherwise, 
    the function expands the user directory (if present) in the path and returns 
    the expanded path.
    Args:
        path (str): The input path string to resolve.
    Returns:
        str: The resolved absolute path.
    """

    home = str(Path.home())

    if "yourusername" in path.lower():
        return path.lower().replace("/users/yourusername", home)

    if "your_username" in path.lower():
        return path.lower().replace("/users/your_username", home)
    
    key = path.lower().strip()
    return COMMON_PATHS.get(key, os.path.expanduser(path))


def _open_file(path: str):
    """
    Opens a file or directory using the default application based on the operating system.
    Args:
        path (str): The file or directory path to open.
    Behavior:
        - On Windows, uses `os.startfile` to open the file or directory.
        - On macOS (Darwin), uses the `open` command via `subprocess.Popen`.
        - On Linux and other Unix-like systems, uses the `xdg-open` command via `subprocess.Popen`.
    Note:
        Ensure that the provided path exists and is accessible to avoid runtime errors.
    """

    system = platform.system()

    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


@function_tool()
async def open_file(context: RunContext, path: str) -> str:
    """
    Asynchronously opens a file or folder at the specified path.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        path (str): The path to the file or folder to be opened.
    Returns:
        str: A message indicating the result of the operation. If the file or folder
             does not exist, it returns an error message. If the operation is successful,
             it returns a success message.
    Raises:
        Exception: Logs and returns an error message if an unexpected exception occurs
                   during the operation.
    """

    try:
        path = _resolve_path(path)
        if not Path(path).exists():
            return f"File or folder does not exist: {path}"

        _open_file(path)
        logger.info(f"Opened file: {path}")
        return f"Opened {path}"
    except Exception as e:
        logger.error(f"Failed to open file {path}: {e}")
        return f"Failed to open {path}"


@function_tool()
async def list_directory(context: RunContext, path: str = ".") -> str:
    """
    Lists the contents of a directory.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        path (str, optional): The path of the directory to list. Defaults to the current directory (".").
    Returns:
        str: A newline-separated string of the directory's contents, or an error message if the directory cannot be listed.
    Raises:
        None: Any exceptions encountered are logged and handled internally.
    """

    try:
        path = _resolve_path(path)
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        logger.error(f"Failed to list directory {path}: {e}")
        return f"Could not list directory {path}"


@function_tool()
async def create_folder(context: RunContext, path: str) -> str:
    """
    Asynchronously creates a folder at the specified path.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        path (str): The path where the folder should be created.
    Returns:
        str: A message indicating whether the folder was successfully created or if the operation failed.
    Raises:
        Exception: Logs an error message if folder creation fails.
    """

    try:
        path = _resolve_path(path)
        os.makedirs(path, exist_ok=True)
        logger.info(f"Created folder: {path}")
        return f"Folder created: {path}"
    except Exception as e:
        logger.error(f"Failed to create folder {path}: {e}")
        return f"Failed to create folder {path}"


@function_tool()
async def delete_path(context: RunContext, path: str) -> str:
    """
    Asynchronously deletes the specified file or directory.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        path (str): The path to the file or directory to be deleted.
    Returns:
        str: A message indicating whether the deletion was successful or failed.
    Raises:
        Exception: If an error occurs during the deletion process, it is logged and a failure message is returned.
    Notes:
        - If the specified path is a directory, it must be empty to be deleted.
        - The function resolves the given path before attempting deletion.
    """

    try:
        path = _resolve_path(path)
        if os.path.isdir(path):
            os.rmdir(path)
        else:
            os.remove(path)
        logger.warning(f"Deleted path: {path}")
        return f"Deleted {path}"
    except Exception as e:
        logger.error(f"Failed to delete {path}: {e}")
        return f"Failed to delete {path}"


@function_tool()
async def run_command(context: RunContext, command: str) -> str:
    """
    Executes a shell command asynchronously and returns its output.
    Args:
        context (RunContext): The context in which the command is executed.
        command (str): The shell command to execute.
    Returns:
        str: The first 4000 characters of the command's output if successful, 
             or an error message if the command fails.
    Logs:
        - Logs the executed command on success.
        - Logs an error message if the command fails.
    Raises:
        None: Any exceptions are caught and logged internally.
    """

    try:
        output = subprocess.check_output(command, shell=True, text=True)
        logger.info(f"Executed command: {command}")
        return output[:4000]
    except Exception as e:
        logger.error(f"Command failed: {command} : {e}")
        return f"Command execution failed"