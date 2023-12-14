import logging
import logging.config
import os
import time
from http import HTTPStatus
from json import JSONDecodeError

import requests
from dotenv import load_dotenv
from telegram import Bot, TelegramError

from exceptions import APIResponseError, TGMessageError

load_dotenv()

prev_err_msg = None

PRACTICUM_TOKEN = os.getenv("PRACTICUM_TOKEN")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RETRY_PERIOD = 600
ENDPOINT = "https://practicum.yandex.ru/api/user_api/homework_statuses/"
HEADERS = {"Authorization": f"OAuth {PRACTICUM_TOKEN}"}


HOMEWORK_VERDICTS = {
    "approved": "Работа проверена: ревьюеру всё понравилось. Ура!",
    "reviewing": "Работа взята на проверку ревьюером.",
    "rejected": "Работа проверена: у ревьюера есть замечания.",
}


def check_tokens():
    """Проверка доступности переменных окружения."""
    environment = {
        "PRACTICUM_TOKEN": PRACTICUM_TOKEN,
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "TELEGRAM_CHAT_ID": TELEGRAM_CHAT_ID,
    }
    for key, val in environment.items():
        if not val:
            logger.critical("Ошибка в переменных окружения: "
                            f"'{key}' = '{val}'")
            return False
    return True


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.debug(f"Бот отправил сообщение '{message}'")
    except TelegramError:
        raise TGMessageError("Сбой при отправке сообщения в Telegram: "
                             f"{message}")


def get_api_answer(timestamp):
    """Запрос к эндпоинту API-сервиса Яндекс."""
    headers = {"Authorization": f"OAuth {PRACTICUM_TOKEN}"}
    payload = {"from_date": timestamp}
    try:
        homework_statuses = requests.get(ENDPOINT,
                                         headers=headers, params=payload)
    except requests.exceptions.RequestException as err:
        raise APIResponseError(headers, payload) from err

    if homework_statuses.status_code != HTTPStatus.OK:
        raise APIResponseError(
            f"Эндпоинт {ENDPOINT} недоступен. Код ответа API: "
            f"{homework_statuses.status_code}. Дополнительная информация:\n"
            f"URL ответа: {homework_statuses.url}\n"
            f"Headers: {homework_statuses.headers}"
        )
    try:
        return homework_statuses.json()
    except JSONDecodeError:
        raise APIResponseError("Ответ от API не в формате JSON.",
                               homework_statuses)


def check_response(response):
    """Проверка ответа API на соответствие API сервиса Практикум.Домашка."""
    if not isinstance(response, dict):
        raise TypeError(
            f"Запрос не является словарём: {type(response)}, {response}"
        )
    if "current_date" not in response:
        raise KeyError("В ответе API отсуствует ключ 'current_date'")
    homeworks = response.get("homeworks")
    if homeworks is None:
        raise KeyError("Отсутствуют данные по домашним работам")
    if not isinstance(homeworks, list):
        raise TypeError("Данные в API не в виде спсика.")
    keys = ["homework_name", "status"]
    if bool(homeworks):
        homework = homeworks[0]
    else:
        raise ValueError("В ответе API нет ни одной домашней работы на дату: "
                         f"{response.get('current_date')}")
    for key in keys:
        if key not in homework:
            raise KeyError(f"В домашней работе не найден ключ '{key}'")
    return True


def parse_status(homework):
    """извлекает статус из последней домашней работы."""
    if not isinstance(homework, dict):
        raise TypeError(
            "Информация о домашней работе не является словарём: "
            f"{type(homework)}, {homework}"
        )
    if "homework_name" not in homework:
        raise ValueError("В ответе API нет ключа 'homework_name'")
    homework_name = homework["homework_name"]
    if "status" not in homework:
        raise ValueError("В ответе API нет ключа 'status'")
    status = homework["status"]
    if status not in HOMEWORK_VERDICTS:
        raise ValueError(f"API содержит не документированный статус: {status}"
                         )
    verdict = HOMEWORK_VERDICTS[status]
    return (f"Изменился статус проверки работы \"{homework_name}\". {verdict}")


def tg_log(bot, message):
    """Фильтрация и отправка log сообщений в telegram."""
    words = ["telegram"]
    for word in words:
        if word.lower() in message.lower():
            return
    global prev_err_msg
    if message != prev_err_msg:
        prev_err_msg = message
        send_message(bot, message)


def main():
    """Основная логика работы бота."""
    from_date = int(time.time())
    if check_tokens():
        logger.debug("Переменные окружения доступны")
    else:
        raise ValueError("Ошибка в переменных окружения. Приложение "
                         "остановлено.")
    bot = Bot(token=TELEGRAM_TOKEN)
    prev_response = None
    while True:
        try:
            response = get_api_answer(from_date)
            logger.debug("Успешный запрос к API.")
            check_response(response)
            if prev_response != response["homeworks"]:
                prev_response = response["homeworks"]
                if response["homeworks"]:
                    send_message(bot, parse_status(response["homeworks"][0]))
                else:
                    logger.warning("Ответ API не содержит домашних работ")
            else:
                logger.debug("В ответе API отсутствуют новые статусы.")
        except Exception as error:
            message = f"Сбой в работе программы: {error}"
            logger.error(message)
            tg_log(bot, message)
        finally:
            time.sleep(RETRY_PERIOD)


def log_config():
    """JSON конфигурация логгера."""
    return {
        "version": 1,
        "formatters": {
            "detailed": {"format": "%(asctime)s [%(levelname)s] %(message)s"}
        },
        "handlers": {
            "std": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "level": "DEBUG",
                "formatter": "detailed",
            }
        },
        "loggers": {
            "app": {
                "handlers": ["std"],
                "level": "DEBUG",
            }
        },
    }


logging.config.dictConfig(log_config())
logger = logging.getLogger("app.homework")

if __name__ == "__main__":
    logger.info("Запуск сервиса...")
    main()
    logger.info("Сервис остановлен.")
