import asyncio
import aiohttp
import ssl
import random
import json
from datetime import datetime
from utils.logger import logger
from config import Config

class BaseScraper:
    def __init__(self, db):
        """
        Инициализация базового скрапера
        
        Args:
            db: Экземпляр класса MongoDB для сохранения данных
        """
        self.db = db
        self.session = None
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0"
        ]
    
    async def create_session(self):
        """Создание HTTP-сессии с настройками для скрапинга"""
        if self.session is None or self.session.closed:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context, limit=5)
            timeout = aiohttp.ClientTimeout(total=30, connect=10)
            
            self.session = aiohttp.ClientSession(
                connector=connector, 
                timeout=timeout,
                headers=self.get_headers()
            )
            logger.debug("✅ HTTP-сессия создана")
    
    async def close_session(self):
        """Закрытие HTTP-сессии"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("✅ HTTP-сессия закрыта")
    
    def get_headers(self):
        """Получение заголовков для HTTP-запросов с ротацией User-Agent"""
        return {
            "User-Agent": random.choice(self.user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;application/json;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        }
    
    async def fetch_with_retry(self, url, method="GET", json=None, data=None, params=None):
        """
        Выполнение HTTP-запроса с повторными попытками при ошибках
        
        Args:
            url: URL для запроса
            method: HTTP-метод (GET, POST)
            json: JSON-данные для тела запроса
            data: Данные формы для тела запроса
            params: URL-параметры запроса
            
        Returns:
            tuple: (статус_запроса, данные_ответа)
        """
        await self.create_session()
        
        for attempt in range(1, Config.MAX_RETRIES + 1):
            try:
                # Задержка между запросами для имитации поведения пользователя
                await asyncio.sleep(random.uniform(1, 3))
                
                # Обновляем заголовки для каждого запроса
                headers = self.get_headers()
                
                if method.upper() == "GET":
                    async with self.session.get(url, headers=headers, params=params) as response:
                        logger.debug(f"📡 GET-запрос к {url}, статус: {response.status}")
                        if response.status == 200:
                            if 'application/json' in response.headers.get('Content-Type', ''):
                                data = await response.json()
                            else:
                                data = await response.text()
                            return True, data
                        else:
                            logger.warning(f"⚠️ Статус {response.status} при запросе {url} (попытка {attempt})")
                            # Логируем текст ответа для отладки
                            error_text = await response.text()
                            logger.debug(f"📄 Текст ошибки: {error_text[:500]}...")
                
                elif method.upper() == "POST":
                    # Логируем параметры запроса для отладки
                    logger.debug(f"📡 POST-запрос к {url}")
                    if json:
                        logger.debug(f"📦 JSON-данные: {json}")
                    if data:
                        logger.debug(f"📦 Form-данные: {data}")
                    if params:
                        logger.debug(f"📦 URL-параметры: {params}")
                    
                    async with self.session.post(url, headers=headers, json=json, data=data, params=params) as response:
                        logger.debug(f"📡 POST-запрос к {url}, статус: {response.status}")
                        if response.status == 200:
                            content_type = response.headers.get('Content-Type', '')
                            logger.debug(f"📄 Content-Type: {content_type}")
                            
                            if 'application/json' in content_type:
                                data = await response.json()
                            else:
                                data = await response.text()
                                # Пытаемся распарсить JSON, даже если Content-Type не JSON
                                if data and (data.startswith('{') or data.startswith('[')):
                                    try:
                                        data = json.loads(data)
                                        logger.debug(f"📊 Успешно распарсили JSON из текстового ответа")
                                    except json.JSONDecodeError:
                                        logger.debug(f"📝 Ответ не является JSON, оставляем текстовым")
                            
                            return True, data
                        else:
                            logger.warning(f"⚠️ Статус {response.status} при запросе {url} (попытка {attempt})")
                            # Логируем текст ответа для отладки
                            error_text = await response.text()
                            logger.debug(f"📄 Текст ошибки: {error_text[:500]}...")
                
                # Экспоненциальное увеличение времени ожидания при повторных попытках
                wait_time = Config.RETRY_DELAY * (2 ** (attempt - 1))
                logger.debug(f"⏱️ Ожидание {wait_time} секунд перед следующей попыткой")
                await asyncio.sleep(wait_time)
                
            except Exception as e:
                logger.error(f"❌ Ошибка при запросе {url} (попытка {attempt}): {e}")
                await asyncio.sleep(Config.RETRY_DELAY * attempt)
        
        logger.error(f"❌ Все попытки запроса {url} не удались")
        return False, None
    
    async def fetch_cars(self, filters=None):
        """
        Метод для получения списка автомобилей с применением фильтров
        Должен быть переопределен в дочерних классах
        """
        raise NotImplementedError("Метод должен быть реализован в дочернем классе")
    
    async def process_car_data(self, car_data):
        """
        Обработка и нормализация данных об автомобиле
        Преобразует сырые данные в единый формат
        """
        raise NotImplementedError("Метод должен быть реализован в дочернем классе")
