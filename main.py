import os, requests, json, re, asyncio
from bs4 import BeautifulSoup
from telegram import Bot
from telegram.error import TelegramError, RetryAfter
from time import sleep
from datetime import datetime, timedelta


TOKEN = os.getenv("TG_TOKEN")
GROUP_ID = os.getenv("TG_GROUP_ID")


# URL страницы
base_url = "https://www.microsoft.com/tr-tr/store/deals/games/xbox"
headers = {
    'Accept': '*/*',
    'accept-encoding' : 'gzip, deflate, br, zstd',
    'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'cache-control': 'no-cache, no-store',
    'client-id': 'NO_AUTH',
    'client-version': '1DS-Web-JS-3.2.18'
}


def is_price(value: str) -> bool:
    """
    Проверяет, является ли строка ценой в формате "₺XXX.XXX,XX" или "Ücretsiz".
    Возвращает True, если строка соответствует формату цены, иначе False.
    """
    pattern = r"^₺\d{1,3}(\.\d{3})*,\d{2}\+?$"
    return bool(re.fullmatch(pattern, value) or value == "Ücretsiz")


def create_empty_file_if_not_exists(filename):
    """
    Создаёт файл с пустым телом JSON ({}) в случае, если он не существует.
    """
    if not os.path.exists(filename):
        with open(filename, 'w', encoding='utf-8') as file:
            json.dump({}, file, ensure_ascii=False, indent=4)


def read_file(filename):
    # Проверяем и создаем файл, если его нет
    create_empty_file_if_not_exists(filename)

    try:
        with open(filename, 'r', encoding="utf-8") as file:
            # Загружаем данные из JSON файла
            loaded_data = json.load(file)

            # Проверяем, что это словарь
            if isinstance(loaded_data, dict):
                return loaded_data
            else:
                return {}  # Возвращаем пустой словарь, если данные не словарь
    except (json.JSONDecodeError, IOError):  # Обрабатываем некорректный синтаксис или ошибки ввода/вывода
        return {}


def save_data(filename, dictionary):
    # Проверяем и создаем файл, если его нет
    create_empty_file_if_not_exists(filename)
    
    # Сохраняем словарь в файл в формате JSON
    with open(filename, 'w', encoding="utf-8") as file:
        json.dump(dictionary, file, ensure_ascii=False, indent=4)


def fetch_url_with_retry(url, headers=headers, retries=5, delay=5):
    """
    Выполняет GET-запрос с повторными попытками в случае ошибки.
    
    :param url: URL для запроса
    :param headers: Заголовки для запроса
    :param retries: Количество повторных попыток
    :param delay: Задержка между попытками в секундах
    :return: Ответ (response) или None, если все попытки неудачны
    """
    session = requests.Session()
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, headers=headers)
            # print(response.status_code)
            # print(response.cookies)
            # response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:  # Проверяем успешность ответа
                return response
            else:
                print(f"Attempt {attempt}: received status {response.status_code}. Retrying...")
        except requests.exceptions.RequestException as e:
            print(f"Attempt {attempt}: error - {e}. Retrying...")
        
        if attempt < retries:
            sleep(delay)  # Задержка перед повторной попыткой
    return None  # Если все попытки неудачны


def games_parsing(url):
    games_data = {}
    while True:
        # Отправляем GET-запрос к текущему URL
        print(f"Loading page: {url}")
        response = fetch_url_with_retry(url)

        if response is None:
            return None
        else:
            soup = BeautifulSoup(response.text, 'html.parser')

        # Находим все карточки с играми
        game_cards = soup.find_all('div', class_='card h-100 material-card depth-4 depth-8-hover pb-4')
        if len(game_cards) == 0:
            return None
        
        for card in game_cards:
            title = card.get('data-bi-prdname')
            
            old_price_element = card.find('span', class_='text-line-through text-muted')
            old_price = old_price_element.text.strip() if old_price_element else 'N/A'
            
            new_price_element = card.find('span', class_='font-weight-semibold')
            new_price = new_price_element.text.strip() if new_price_element else 'N/A'

            image_element = card.find('img')
            image = image_element['src'].split('?q')[0] if image_element and 'src' in image_element.attrs else 'N/A'

            date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # "2025-03-10 14:30:15"

            if is_price(new_price) and image != 'N/A':
                games_data[title] = {
                    'old_price': old_price,
                    'new_price': new_price,
                    'image_url': image,
                    'date':      date_str
                }
        
        # Находим последний элемент с классом "page-item"
        pagination_items = soup.find_all('li', class_='page-item')
        if pagination_items:
            last_page_item = pagination_items[-1]
            
            # Проверяем, имеет ли он класс "disabled"
            if 'disabled' in last_page_item.get('class', []):
                break
            
            # Если не имеет, извлекаем ссылку для следующей страницы
            next_link = last_page_item.find('a', class_='page-link')
            url = next_link['href']
        else:
            break
    return games_data


def find_differences(games_data, parsed_data):
    """
    Находит различия между games_data и parsed_data.
    Возвращает словарь с различиями.
    """
    differences = {}
    
    all_keys = set(games_data.keys()).union(parsed_data.keys())
    for key in all_keys:
        if key not in games_data:
            differences[key] = {"old": None, "new": parsed_data[key]}  # Новый ключ в parsed_data
        elif key not in parsed_data:
            differences[key] = {"old": games_data[key], "new": None}  # Ключ удален в parsed_data
        elif games_data[key] != parsed_data[key]:
            differences[key] = {"old": games_data[key], "new": parsed_data[key]}  # Изменение значений
    return differences


def update_games_data(games_data, parsed_data):
    # Удаляет из games_data только те игры, у которых прошло 7 дней с даты сохранения.
    now = datetime.now()
    keys_to_remove = set()

    for game_id, attributes in games_data.items():
        saved_date_str = attributes.get("date")
        if saved_date_str:
            saved_date = datetime.strptime(saved_date_str, "%Y-%m-%d %H:%M:%S")
            if now >= saved_date + timedelta(days=7):
                keys_to_remove.add(game_id)
                
    for key in keys_to_remove:
        del games_data[key]
    
    for game_id, new_attributes in parsed_data.items():
        if game_id in games_data:
            # Проверяем, изменился ли хотя бы один атрибут, кроме "date"
            attributes_to_update = {k: v for k, v in new_attributes.items() if k != "date" and games_data[game_id].get(k) != v}
            
            if attributes_to_update:
                # Если были изменения, обновляем все атрибуты
                games_data[game_id].update(attributes_to_update)
        else:
            # Добавляем новую игру
            games_data[game_id] = new_attributes


def prepare_messages(filename):
    """
    Подготавливает сообщения из JSON-файла для отправки в Telegram.

    :param filename: Путь к JSON-файлу
    :return: Список сообщений в формате текста и ссылок на изображения
    """
    try:
        # Чтение данных из файла с использованием вашей функции read_file
        data = read_file(filename)

        messages = []

        for key, value in data.items():
            # Проверяем, что ключ "new" существует и не равен None
            if value.get("new") is not None:
                new_data = value["new"]
                title = key
                old_price = new_data.get("old_price", "No Old Price")
                new_price = new_data.get("new_price", "No New Price")
                image_url = new_data.get("image_url", "")

                message = f"{title}\nLast: {old_price}\nSale: {new_price}"
                messages.append({"text": message, "image_url": image_url})

        return messages

    except Exception as e:
        print(f"Ошибка при обработке JSON-файла: {e}")
        return []


async def send_photo_with_retry(bot_token, chat_id, photo_path, caption):
    """
    Отправляет фото с подписью через Telegram с обработкой ошибок и retry.

    :param bot_token: Токен бота Telegram
    :param chat_id: ID чата для отправки
    :param photo_path: Путь к фото для отправки
    :param caption: Подпись к фото
    """
    bot = Bot(token=bot_token)
    max_retries = 5  # Максимальное количество попыток
    attempt = 0

    while attempt < max_retries:
        try:
            await bot.send_photo(chat_id=chat_id, photo=photo_path, caption=caption)
            print("Фото успешно отправлено")
            return  # Успешная отправка - завершаем функцию
        except RetryAfter as e:
            # Динамическая задержка из ошибки RetryAfter
            delay = int(e.retry_after)
            print(f"Превышение лимита запросов. Повтор через {delay} секунд.")
            await asyncio.sleep(delay)
        except TelegramError as e:
            # Обработка других ошибок Telegram API
            print(f"Ошибка Telegram API: {e}. Попытка {attempt + 1} из {max_retries}.")
        except Exception as e:
            # Общая обработка ошибок
            print(f"Неожиданная ошибка: {e}. Попытка {attempt + 1} из {max_retries}.")
        finally:
            attempt += 1
            if attempt < max_retries:
                await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка между попытками

    print("Не удалось отправить фото после нескольких попыток.")


async def main():
    parsed_data = games_parsing(base_url)
    if parsed_data is None:
        print("Unable to complete website parsing successfully...")
    else:
        games_data = read_file('games_data.json')
        diff = find_differences(games_data, parsed_data)
        save_data('diff_data.json', diff)
        update_games_data(games_data, parsed_data)
        save_data('games_data.json', games_data)
        print("Task completed successfully!")

        messages = prepare_messages('diff_data.json')
        for msg in messages:
            print("Сообщение:")
            print(msg["text"])
            print(f"Ссылка на изображение: {msg['image_url']}")
            await send_photo_with_retry(TOKEN, GROUP_ID, msg['image_url'], msg["text"])

if __name__ == "__main__":
    asyncio.run(main())
    
