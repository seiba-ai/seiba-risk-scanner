from pathlib import Path

def read_text_file(file_path: str) -> str:
    """
    Reads a text file using pathlib and returns its content as a string.
    
    Args:
        file_path (str): Path to the text (.txt) file.
        
    Returns:
        str: Content of the file as a string.
    """
    return Path(file_path).read_text(encoding="utf-8")