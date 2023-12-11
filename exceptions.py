class APIResponseError(Exception):
    """Исключения возникающие при запросе к API."""

    pass


class TGMessageError(Exception):
    """Исключения возникающие при отправки сообщения в telegramm."""

    pass
