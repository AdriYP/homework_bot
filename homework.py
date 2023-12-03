import logging
import logging.config
import os
import time
import datetime

import requests
import telegram
import urllib3
from dotenv import load_dotenv

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
    if "PRACTICUM_TOKEN" not in os.environ or PRACTICUM_TOKEN is None:
        raise Exception(f"PRACTICUM_TOKEN = '{PRACTICUM_TOKEN}'")
    if "TELEGRAM_TOKEN" not in os.environ or TELEGRAM_TOKEN is None:
        raise Exception(f"TELEGRAM_TOKEN = '{TELEGRAM_TOKEN}'")
    if "TELEGRAM_CHAT_ID" not in os.environ or TELEGRAM_CHAT_ID is None:
        raise Exception(f"TELEGRAM_CHAT_ID = '{TELEGRAM_CHAT_ID}'")
    return True


def unix_date(timestamp):
    """Получение даты в формате Unix time."""
    if timestamp == 0:
        return 0
    return str(int(time.mktime(timestamp.timetuple())))


def send_message(bot, message):
    """Отправляет сообщение в Telegram чат."""
    if message is not None:
        try:
            bot.send_message(TELEGRAM_CHAT_ID, message)
            logger.debug(f"Бот отправил сообщение '{message}'")
        except Exception:
            raise Exception("Сбой при отправке сообщения в Telegram")
    else:
        raise Exception("Попытка отправки пустого сообщения в Telegram")


def get_api_answer(timestamp):
    """Запрос к эндпоинту API-сервиса Яндекс."""
    url = "https://practicum.yandex.ru/api/user_api/homework_statuses/"
    headers = {"Authorization": f"OAuth {PRACTICUM_TOKEN}"}
    if isinstance(timestamp, datetime.date):
        timestamp = unix_date(timestamp)
    payload = {"from_date": timestamp}
    try:
        homework_statuses = requests.get(url, headers=headers, params=payload)
        if homework_statuses.status_code == 200:
            return homework_statuses.json()
        else:
            raise Exception(
                f"Эндпоинт {url} недоступен. Код ответа API: "
                f"{homework_statuses.status_code}"
            )
    except Exception:
        raise Exception(
            f"Эндпоинт {url} недоступен. Код ответа API: "
            f"{homework_statuses.status_code}"
        )


def check_response(response):
    """Проверка ответа API на соответствие API сервиса Практикум.Домашка."""
    try:
        homeworks = response["homeworks"]
    except KeyError as error:
        raise KeyError("В запросе отсуствует список домашних работ.", error)
    if type(homeworks) is not list:
        raise TypeError("Данные в API не в виде спсика.")
    keys = ["homework_name", "status"]
    for homework in homeworks:
        for key in keys:
            if key not in homework:
                raise KeyError("В списоке домашних работ не найден ключ "
                               f"'{key}'")
    return True


def parse_status(homework):
    """извлекает статус из последней домашней работы."""
    if "homework_name" in homework:
        homework_name = homework["homework_name"]
    else:
        raise ValueError("В ответе API нет ключа 'homework_name'")
    if homework["status"] in HOMEWORK_VERDICTS:
        verdict = HOMEWORK_VERDICTS[homework["status"]]
        return f'Изменился статус проверки работы "{homework_name}". {verdict}'
    else:
        raise ValueError(
            f"API содержит не документированный статус: {homework['status']}"
        )


def main():
    """Основная логика работы бота."""
    from_date = datetime.date(2023, 10, 30)
    try:
        check_tokens()
        logger.debug("Переменные окружения доступны")
    except Exception as error:
        logger.critical(f"Ошибка в переменных окружения: {error}")
        return
    bot = telegram.Bot(token=TELEGRAM_TOKEN)
    prev_response = None
    while True:
        try:
            response = get_api_answer(from_date)
            logger.debug("Успешный запрос к API.")
            check_response(response)
            if prev_response != response["homeworks"]:
                prev_response = response["homeworks"]
                if len(response["homeworks"]) > 0:
                    send_message(bot, parse_status(response["homeworks"][0]))
                else:
                    logger.warning("Ответ API не содержит домашних работ")
            else:
                logger.debug("В ответе API отсутствуют новые статусы.")
        except Exception as error:
            message = f"Сбой в работе программы: {error}"
            logger.error(message)
        finally:
            time.sleep(600)


class TelegramBotHandler(logging.Handler):
    """Handler для telegramm."""

    def __init__(self, token: str, chat_id: str):
        """Конструктор."""
        super().__init__()
        self.token = token
        self.chat_id = chat_id

    def emit(self, record):
        """Отправка сообщения."""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        post_data = {"chat_id": self.chat_id, "text": self.format(record)}
        http = urllib3.PoolManager()
        http.request(method="POST", url=url, fields=post_data)


class msg_filter(logging.Filter):
    """Класс для фитрации log сообщений в чат бота."""

    def __init__(self, param=None):
        """Конструктор."""
        self.param = param

    def filter(self, record):
        """Параметры фильтрации."""
        global prev_err_msg
        words = ["telegram"]
        for word in words:
            if word.lower() in record.msg.lower():
                return False
        if prev_err_msg == record.msg:
            return False
        else:
            prev_err_msg = record.msg
            return True


def log_config():
    """JSON конфигурация логгера."""
    return {
        "version": 1,
        "filters": {"filter": {"()": "homework.msg_filter",
                               "param": "noshow"}},
        "formatters": {
            "detailed": {"format": "%(asctime)s [%(levelname)s] %(message)s"}
        },
        "handlers": {
            "std": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "level": "DEBUG",
                "formatter": "detailed",
            },
            "tgh": {
                "class": "homework.TelegramBotHandler",
                "level": "WARNING",
                "filters": ["filter"],
                "token": TELEGRAM_TOKEN,
                "chat_id": TELEGRAM_CHAT_ID,
            },
        },
        "loggers": {
            "app": {
                "handlers": ["std", "tgh"],
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
