class APIResponseError(Exception):
    """Исключения возникающие при запросе к API."""

    def __init__(self, *args):
        """Конструктор класса."""
        if args:
            self.message = args
