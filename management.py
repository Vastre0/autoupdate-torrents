import tkinter as tk
from tkinter import filedialog, messagebox
from rutt_to_qb import update_torrents, add_torrent_from_url
import os


class TorrentApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Torrent Manager")
        self.root.geometry("300x160")
        self.root.resizable(False, False)  # Запрет изменения размеров

        # Переменная для хранения пути
        self.selected_path = ""

        # Стили
        self.font = ('Arial', 10)
        self.padx = 5
        self.pady = 3

        # Создаем элементы интерфейса
        self.create_widgets()

    def create_widgets(self):
        # Поле для ввода ссылки
        tk.Label(self.root, text="Введите ссылку:", font=self.font).pack(pady=(10, 0))

        url_frame = tk.Frame(self.root)
        url_frame.pack(pady=self.pady)

        self.url_entry = tk.Entry(url_frame, font=self.font, width=25)
        self.url_entry.pack(side="left", padx=(0, 5))

        paste_btn = tk.Button(
            url_frame,
            text="📋",  # Можно заменить на "Вставить" или "+"
            width=3,
            command=self.paste_from_clipboard
        )
        paste_btn.pack(side="right")

        # Поле для отображения пути
        tk.Label(self.root, text="Выберите папку:", font=self.font).pack(pady=(5, 0))

        path_frame = tk.Frame(self.root)
        path_frame.pack(pady=self.pady)

        self.path_label = tk.Label(
            path_frame,
            text="Папка не выбрана",
            font=self.font,
            bg="#f0f0f0",
            width=25,
            relief="sunken",
            anchor="w",
            padx=5
        )
        self.path_label.pack(side="left", fill="x", expand=True)

        browse_btn = tk.Button(
            path_frame,
            text="...",
            command=self.pick_folder,
            width=3
        )
        browse_btn.pack(side="right", padx=(5, 0))

        # Кнопки действий
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(pady=(10, 0))

        add_btn = tk.Button(
            btn_frame,
            text="Добавить",
            command=self.add_action,
            width=10
        )
        add_btn.pack(side="left", padx=5)

        update_btn = tk.Button(
            btn_frame,
            text="Обновить",
            command=self.update_action,
            width=10
        )
        update_btn.pack(side="right", padx=5)

    def pick_folder(self):
        folder_path = filedialog.askdirectory(title="Выберите папку")
        if folder_path:
            self.selected_path = folder_path
            folder_name = os.path.basename(folder_path)
            self.path_label.config(text=folder_name)

    def add_action(self):
        url = self.url_entry.get()
        if not url:
            messagebox.showerror("Ошибка", "Введите ссылку!")
            return

        if not self.selected_path:
            messagebox.showerror("Ошибка", "Выберите папку!")
            return

        add_torrent_from_url(url, self.selected_path)
        messagebox.showinfo("Успех", "Данные добавлены!")

    def update_action(self):
        update_torrents()
        messagebox.showinfo("Успех", "Торренты обновлены!")

    def paste_from_clipboard(self):
        try:
            clipboard_text = self.root.clipboard_get()
            self.url_entry.delete(0, tk.END)
            self.url_entry.insert(0, clipboard_text)
        except tk.TclError:
            messagebox.showerror("Ошибка", "Буфер обмена пуст или содержит неверные данные.")



if __name__ == "__main__":
    root = tk.Tk()
    app = TorrentApp(root)
    root.mainloop()