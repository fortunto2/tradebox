# Настройка обработчика логов
import logging
from logging.handlers import TimedRotatingFileHandler

log_handler = TimedRotatingFileHandler(
    filename="app.log",
    when="midnight",
    interval=1,
    backupCount=7  # Хранение логов за последние 7 дней
)
log_handler.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
log_handler.setFormatter(formatter)

# Настройка логгера
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(log_handler)
