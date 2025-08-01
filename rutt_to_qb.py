import re
import os
import json
import requests
from bs4 import BeautifulSoup
from qbittorrentapi import Client, APIConnectionError, NotFound404Error

CONFIG_FILE = 'torrent_config.json'
COOKIES_FILE = 'cookies.json'

# Данные входа в qBittorrent
QB_HOST = 'localhost:8080'
QB_USERNAME = 'admin'
QB_PASSWORD = 'adminadmin'

# --- Проверки файлов (без изменений) ---
if not os.path.exists(COOKIES_FILE):
    raise FileNotFoundError(f"Файл {COOKIES_FILE} не найден! Создайте его с куки в формате JSON.")

try:
    with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
        cookies = json.load(f)
except json.JSONDecodeError as e:
    raise ValueError(f"Ошибка в формате JSON в {COOKIES_FILE}: {e}")

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
}


def _log(message, log_func=None):
    """Вспомогательная функция для логирования."""
    if log_func:
        log_func(message)
    else:
        print(message)


def load_config(log_func=None):
    """Загружает или создает конфигурационный файл"""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if not content:
                    raise ValueError("Файл пустой")
                return json.loads(content)
        except (json.JSONDecodeError, ValueError) as e:
            _log(f"Повреждённый конфиг ({e}), пересоздаём...", log_func)
            os.remove(CONFIG_FILE)

    config = {"torrents": {}}
    save_config(config)
    return config


def save_config(config):
    """Сохраняет конфигурацию в файл"""
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)


def extract_torrent_id(url):
    """Извлекает ID торрента из ссылки"""
    match = re.search(r'[?&]t=(\d+)', url)
    if match:
        return match.group(1)
    raise ValueError(f"Не удалось извлечь ID из ссылки: {url}")


def add_torrent_from_url(topic_url, save_path, log_func=None):
    """Добавляет новую раздачу по ссылке"""
    try:
        torrent_id = extract_torrent_id(topic_url)
        config = load_config(log_func)
        if torrent_id in config['torrents']:
            _log(f"Торрент с ID {torrent_id} уже есть в конфиге. Обновляем путь.", log_func)
        config['torrents'][torrent_id] = {"save_path": save_path, "url": topic_url}
        save_config(config)
        _log(f"Добавлена новая раздача в конфиг: ID {torrent_id}, путь: {save_path}", log_func)
    except ValueError as e:
        _log(f"Ошибка при добавлении торрента: {e}", log_func)
        raise


def download_torrent(torrent_id, log_func=None):
    """Скачивает торрент-файл с Rutracker"""
    base_url = "https://rutracker.org/forum/"
    topic_url = f"viewtopic.php?t={torrent_id}"

    _log(f"Загрузка страницы для ID {torrent_id}...", log_func)
    try:
        response = requests.get(base_url + topic_url, cookies=cookies, headers=headers, timeout=15)
        response.raise_for_status()  # Проверка на ошибки HTTP (4xx, 5xx)
    except requests.RequestException as e:
        _log(f"Ошибка загрузки страницы {topic_url}: {e}", log_func)
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    dl_link = soup.find('a', class_='dl-link')
    if not dl_link:
        _log(f"Ошибка: Ссылка на скачивание для ID {torrent_id} не найдена!", log_func)
        return None

    torrent_download_url = base_url + dl_link['href']
    _log(f"Загрузка .torrent файла с {torrent_download_url}", log_func)
    try:
        torrent_response = requests.get(torrent_download_url, cookies=cookies, headers=headers, timeout=15)
        torrent_response.raise_for_status()
    except requests.RequestException as e:
        _log(f"Ошибка загрузки .torrent файла: {e}", log_func)
        return None

    # Возвращаем содержимое файла и оригинальный URL темы для записи в комментарий
    return torrent_response.content, base_url + topic_url


def add_to_qbittorrent(torrent_content, save_path, original_url, log_func=None):
    """Добавляет торрент в qBittorrent, добавляя URL в комментарий."""
    try:
        qb = Client(host=QB_HOST, username=QB_USERNAME, password=QB_PASSWORD)
        qb.auth_log_in()
        _log(f"Подключен к qBittorrent: {qb.app.version}", log_func)

        # Добавляем торрент с указанием пути и комментария
        result = qb.torrents_add(
            torrent_files=torrent_content,
            save_path=save_path,
            comment=original_url  # Это ключ к поиску при удалении
        )
        _log(f"Задание на добавление торрента в qBittorrent отправлено. Результат: {result}", log_func)
        return True
    except APIConnectionError as e:
        _log(f"Ошибка подключения к qBittorrent: {e}. Проверьте хост, порт, логин и пароль.", log_func)
    except Exception as e:
        _log(f"Ошибка при добавлении в qBittorrent: {e}", log_func)
    return False


def update_torrents(log_func=None):
    """Обновляет все раздачи из конфига"""
    config = load_config(log_func)
    if not config['torrents']:
        _log("В конфиге нет торрентов для обновления.", log_func)
        return

    for torrent_id, settings in config['torrents'].items():
        _log(f"\n--- Обработка раздачи ID: {torrent_id} ---", log_func)

        download_result = download_torrent(torrent_id, log_func)
        if download_result:
            torrent_content, original_url = download_result
            if add_to_qbittorrent(torrent_content, settings['save_path'], original_url, log_func):
                _log(f"Раздача {torrent_id} успешно отправлена на обновление в qBittorrent.", log_func)
            else:
                _log(f"Не удалось обновить раздачу {torrent_id} в qBittorrent.", log_func)
        else:
            _log(f"Не удалось скачать .torrent файл для раздачи {torrent_id}, обновление пропущено.", log_func)


def delete_torrent(torrent_id, delete_files, log_func=None):
    """
    Удаляет торрент из qBittorrent и из файла конфигурации.
    """
    config = load_config(log_func)
    torrent_data = config.get('torrents', {}).get(str(torrent_id))

    if not torrent_data:
        _log(f"Торрент с ID {torrent_id} не найден в конфигурации.", log_func)
        return True  # Считаем успешным, т.к. его и так нет

    torrent_url_to_find = torrent_data.get('url')

    # Шаг 1: Удаление из qBittorrent
    try:
        qb = Client(host=QB_HOST, username=QB_USERNAME, password=QB_PASSWORD)
        qb.auth_log_in()

        found_hash = None
        _log("Поиск торрента в qBittorrent клиенте...", log_func)
        # Ищем торрент по комментарию, куда мы записали URL
        for torrent in qb.torrents_info():
            if torrent.comment and torrent_id in torrent.comment:
                found_hash = torrent.hash
                _log(f"Найден торрент в qBittorrent: {torrent.name} (hash: {found_hash})", log_func)
                break

        if found_hash:
            qb.torrents_delete(torrent_hashes=found_hash, delete_files=delete_files)
            _log(f"Торрент (hash: {found_hash}) удален из qBittorrent. Удаление файлов: {delete_files}", log_func)
        else:
            _log(f"Торрент с ID {torrent_id} не найден в qBittorrent. Возможно, он был удален ранее.", log_func)

    except APIConnectionError as e:
        _log(f"Не удалось подключиться к qBittorrent для удаления: {e}. Пропускаем этот шаг.", log_func)
    except NotFound404Error:
        _log(f"Торрент уже был удален из qBittorrent (ошибка 404).", log_func)
    except Exception as e:
        _log(f"Произошла ошибка при удалении из qBittorrent: {e}", log_func)
        # Решаем, прерывать ли операцию. Лучше не прерывать, чтобы можно было удалить из конфига.

    # Шаг 2: Удаление из конфига
    config = load_config(log_func)  # Перезагружаем на всякий случай
    if str(torrent_id) in config['torrents']:
        del config['torrents'][str(torrent_id)]
        save_config(config)
        _log(f"Торрент с ID {torrent_id} удален из файла конфигурации.", log_func)
    else:
        _log(f"Торрент с ID {torrent_id} уже был удален из файла конфигурации.", log_func)

    return True