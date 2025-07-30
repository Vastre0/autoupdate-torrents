import re
import os
import json
import requests
from bs4 import BeautifulSoup
from qbittorrentapi import Client

CONFIG_FILE = 'torrent_config.json'
COOKIES_FILE = 'cookies.json'

# Данные входа в qBittorrent
QB_HOST = 'localhost:8080'
QB_USERNAME = 'admin'
QB_PASSWORD = 'adminadmin'

if not os.path.exists(COOKIES_FILE):
    raise FileNotFoundError(f"Файл {COOKIES_FILE} не найден! Создайте его с куки в формате JSON (см. инструкцию выше).")

try:
    with open(COOKIES_FILE, 'r', encoding='utf-8') as f:
        cookies = json.load(f)
except json.JSONDecodeError as e:
    raise ValueError(f"Ошибка в формате JSON в {COOKIES_FILE}: {e}")

# Headers (можно hardcoded или загрузить аналогично куки, если нужно)
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
    # Добавьте другие headers, если они были в val.py
}


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
            msg = f"Повреждённый конфиг ({e}), пересоздаём..."
            if log_func:
                log_func(msg)
            else:
                print(msg)
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
    else:
        raise ValueError(f"Не удалось извлечь ID из ссылки: {url}")


def add_torrent_from_url(topic_url, save_path, log_func=None):
    """Добавляет новую раздачу по ссылке"""
    torrent_id = extract_torrent_id(topic_url)
    config = load_config(log_func)  # Передаём log_func
    config['torrents'][torrent_id] = {"save_path": save_path, "url": topic_url}
    save_config(config)
    if log_func:
        log_func(f"Добавлена новая раздача: ID {torrent_id}, путь: {save_path}")
    else:
        print(f"Добавлена новая раздача: ID {torrent_id}, путь: {save_path}")


def download_torrent(torrent_id, log_func=None):
    """Скачивает торрент-файл с Rutracker"""
    base_url = "https://rutracker.org/forum/"
    topic_url = f"viewtopic.php?t={torrent_id}"

    response = requests.get(base_url + topic_url, cookies=cookies, headers=headers)
    if response.status_code != 200:
        msg = f"Ошибка загрузки страницы: {response.status_code}"
        if log_func:
            log_func(msg)
        else:
            print(msg)
        return None

    soup = BeautifulSoup(response.text, 'html.parser')
    dl_link = soup.find('a', class_='dl-link')
    if not dl_link:
        msg = "Ошибка: Ссылка на скачивание не найдена!"
        if log_func:
            log_func(msg)
        else:
            print(msg)
        return None

    torrent_url = base_url + dl_link['href']
    torrent_response = requests.get(torrent_url, cookies=cookies, headers=headers)
    if torrent_response.status_code != 200:
        msg = f"Ошибка загрузки торрента: {torrent_response.status_code}"
        if log_func:
            log_func(msg)
        else:
            print(msg)
        return None

    content_disposition = torrent_response.headers.get('Content-Disposition', '')
    filename = (
        requests.utils.unquote(re.findall(r"filename\*=UTF-8''(.+)", content_disposition)[0])
        if 'filename*=' in content_disposition
        else f"torrent_{torrent_id}.torrent"
    )

    with open(filename, 'wb') as f:
        f.write(torrent_response.content)

    msg = f"Торрент сохранен как: {filename}"
    if log_func:
        log_func(msg)
    else:
        print(msg)
    return filename


def add_to_qbittorrent(torrent_file, save_path, log_func=None):
    """Добавляет торрент в qBittorrent"""
    qb = Client(host=QB_HOST, username=QB_USERNAME, password=QB_PASSWORD)

    try:
        with open(torrent_file, 'rb') as f:
            qb.torrents_add(torrent_files=f, save_path=save_path)
        os.remove(torrent_file)
        return True
    except Exception as e:
        msg = f"Ошибка при добавлении в qBittorrent: {e}"
        if log_func:
            log_func(msg)
        else:
            print(msg)
        return False


def update_torrents(log_func=None):
    """Обновляет все раздачи из конфига"""
    config = load_config(log_func)  # Передаём log_func
    for torrent_id, settings in config['torrents'].items():
        msg = f"\nОбработка раздачи ID: {torrent_id}"
        if log_func:
            log_func(msg)
        else:
            print(msg)

        torrent_file = download_torrent(torrent_id, log_func)
        if torrent_file and add_to_qbittorrent(torrent_file, settings['save_path'], log_func):
            msg = f"Раздача {torrent_id} успешно добавлена в qBittorrent"
            if log_func:
                log_func(msg)
            else:
                print(msg)
        else:
            msg = f"Не удалось обработать раздачу {torrent_id}"
            if log_func:
                log_func(msg)
            else:
                print(msg)