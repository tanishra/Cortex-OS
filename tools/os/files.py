import logging
import os
import shutil
from pathlib import Path
from livekit.agents import function_tool, RunContext

logger = logging.getLogger("JARVIS.OS.File")


def _resolve_path(path: str) -> Path:
    """
    Resolves and returns the absolute path of a given file or directory.
    This function expands the user directory symbol (`~`) in the input path
    and converts it to an absolute path.
    Args:
        path (str): The input file or directory path as a string.
    Returns:
        Path: The resolved absolute path as a `Path` object.
    """

    path = os.path.expanduser(path)
    return Path(path).resolve()


@function_tool()
async def read_file(context: RunContext, path: str, max_chars: int = 4000) -> str:
    """
    Reads the content of a file up to a specified maximum number of characters.
    Args:
        context (RunContext): The execution context in which the function is called.
        path (str): The path to the file to be read.
        max_chars (int, optional): The maximum number of characters to read from the file. Defaults to 4000.
    Returns:
        str: The content of the file up to the specified maximum number of characters, or an error message
             if the file could not be found or read.
    Raises:
        Exception: Logs an exception if an error occurs while reading the file.
    """

    try:
        file_path = _resolve_path(path)

        if not file_path.exists() or not file_path.is_file():
            return f"File not found: {file_path}"

        content = file_path.read_text(errors="ignore")
        logger.info(f"Read file: {file_path}")

        return content[:max_chars]

    except Exception as e:
        logger.exception(f"Failed to read file {path}")
        return f"Could not read file: {path}"


@function_tool()
async def write_file(context: RunContext, path: str, content: str) -> str:
    """
    Asynchronously writes content to a specified file.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        path (str): The file path where the content should be written.
        content (str): The content to write to the file.
    Returns:
        str: A message indicating whether the file was successfully written or if an error occurred.
    Raises:
        Exception: Logs and handles any exceptions that occur during the file writing process.
    """

    try:
        file_path = _resolve_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        file_path.write_text(content)
        logger.info(f"Wrote file: {file_path}")

        return f"File written: {file_path}"

    except Exception as e:
        logger.exception(f"Failed to write file {path}")
        return f"Could not write file: {path}"


@function_tool()
async def copy_file(context: RunContext, source: str, destination: str) -> str:
    """
    Asynchronously copies a file from the source path to the destination path.
    Args:
        context (RunContext): The runtime context for the operation.
        source (str): The path to the source file to be copied.
        destination (str): The path to the destination where the file should be copied.
    Returns:
        str: A message indicating the result of the operation. If the source file does not exist,
             it returns a message stating that the source file does not exist. If the operation
             is successful, it returns a message indicating the destination path. If an error
             occurs, it returns "File copy failed".
    Raises:
        Exception: Logs and handles any exceptions that occur during the file copy operation.
    """

    try:
        src = _resolve_path(source)
        dst = _resolve_path(destination)

        if not src.exists():
            return f"Source file does not exist: {src}"

        shutil.copy2(src, dst)
        logger.info(f"Copied file from {src} to {dst}")

        return f"Copied file to {dst}"

    except Exception as e:
        logger.exception(f"Failed to copy file {source} to {destination}")
        return "File copy failed"


@function_tool()
async def move_file(context: RunContext, source: str, destination: str) -> str:
    """
    Asynchronously moves a file from the source path to the destination path.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        source (str): The path to the source file to be moved.
        destination (str): The path to the destination where the file should be moved.
    Returns:
        str: A message indicating the result of the operation. If successful, it returns
             a message with the destination path. If the source file does not exist or
             an error occurs, it returns an appropriate error message.
    Raises:
        Exception: Logs and handles any exceptions that occur during the file move operation.
    """

    try:
        src = _resolve_path(source)
        dst = _resolve_path(destination)

        if not src.exists():
            return f"Source file does not exist: {src}"

        shutil.move(str(src), str(dst))
        logger.info(f"Moved file from {src} to {dst}")

        return f"Moved file to {dst}"

    except Exception as e:
        logger.exception(f"Failed to move file {source} to {destination}")
        return "File move failed"


@function_tool()
async def delete_file(context: RunContext, path: str) -> str:
    """
    Asynchronously deletes a file at the specified path.
    Args:
        context (RunContext): The runtime context in which the function is executed.
        path (str): The path to the file that needs to be deleted.
    Returns:
        str: A message indicating the result of the file deletion operation. 
             If the file does not exist, it returns a message stating so. 
             If the file is successfully deleted, it returns a confirmation message.
             If an error occurs during deletion, it returns an error message.
    Raises:
        Exception: Logs and handles any exceptions that occur during the file deletion process.
    """

    try:
        file_path = _resolve_path(path)

        if not file_path.exists():
            return f"File does not exist: {file_path}"

        file_path.unlink()
        logger.warning(f"Deleted file: {file_path}")

        return f"File deleted: {file_path}"

    except Exception as e:
        logger.exception(f"Failed to delete file {path}")
        return f"File deletion failed: {path}"