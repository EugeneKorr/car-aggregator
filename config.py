import os
from dotenv import load_dotenv

# Загружаем переменные окружения из .env файла
load_dotenv()

class Config:
    # Настройки MongoDB
    MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
    
    # Настройки скрапера
    CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "3600"))  # 1 час по умолчанию
    MAX_RETRIES = int(os.getenv("MAX_RETRIES", "3"))
    RETRY_DELAY = int(os.getenv("RETRY_DELAY", "5"))
    
    # URL для KIA Outlet
    KIA_BASE_URL = "https://kiaokasion.net/kia/"
    KIA_API_URL = "https://kiaokasion.net/kia/async/metodos.aspx"
    
    # Настройки логирования
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
