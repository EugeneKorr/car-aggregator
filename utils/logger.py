import logging
import os
from config import Config

def setup_logging():
    """Настройка логирования с ротацией файлов"""
    log_level = getattr(logging, Config.LOG_LEVEL)
    
    # Проверяем наличие папки logs
    if not os.path.exists("logs"):
        os.makedirs("logs")
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/car_aggregator.log", mode="a"),
        ],
    )
    
    return logging.getLogger("car_aggregator")

# Создаем глобальный объект логгера
logger = setup_logging()
