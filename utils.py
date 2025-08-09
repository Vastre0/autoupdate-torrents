
import os
import sys

def load_stylesheet(filename: str) -> str:
    """Загружает файл стилей и возвращает его содержимое."""
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: Stylesheet file not found: {filename}")
        return ""

# --- НОВАЯ ФУНКЦИЯ ---
def resource_path(relative_path: str) -> str:
    """ Получает абсолютный путь к ресурсу, работает как для IDE, так и для .exe """
    try:
        # PyInstaller создает временную папку и сохраняет путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)