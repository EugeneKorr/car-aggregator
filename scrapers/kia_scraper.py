import json
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from config import Config
from scrapers.base_scraper import BaseScraper
from utils.logger import logger

class KiaScraper(BaseScraper):
    def __init__(self, db):
        super().__init__(db)
        self.base_url = Config.KIA_BASE_URL
        self.api_url = Config.KIA_API_URL
    
    async def fetch_cars(self, filters=None):
        """
        Получение списка автомобилей KIA с применением фильтров
        
        Args:
            filters: Словарь с фильтрами (цена, модель и т.д.)
            
        Returns:
            list: Список обработанных данных об автомобилях
        """
        if filters is None:
            filters = {}
        
        # Настройка параметров запроса
        payload = {
            "filter": {
                "price": {
                    "min": filters.get("min_price", 0),
                    "max": filters.get("max_price", 100000)
                },
                "mileage": {
                    "min": filters.get("min_mileage", 0),
                    "max": filters.get("max_mileage", 200000)
                }
            },
            "pagination": {
                "page": 1,
                "size": 100  # Максимальное количество результатов
            },
            "sort": {
                "field": "price",
                "direction": "ASC"
            }
        }
        
        # Добавление фильтров по модели, если указаны
        if "models" in filters and filters["models"]:
            payload["filter"]["models"] = filters["models"]
        
        # Дополнительные заголовки для имитации запроса с сайта
        headers = self.get_headers()
        headers.update({
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.base_url
        })
        
        # Выполнение запроса к API
        logger.info(f"🔍 Запрос автомобилей KIA с фильтрами: {json.dumps(filters)}")
        
        success, response_data = await self.fetch_with_retry(
            self.api_url,
            method="POST",
            json=payload
        )
        
        if not success or not response_data:
            logger.error("❌ Не удалось получить данные от KIA API")
            return []
        
        # Обработка результатов
        cars_data = []
        try:
            # Проверка на наличие ключа content, где хранятся данные об автомобилях
            if "content" in response_data:
                cars = response_data["content"]
                logger.info(f"✅ Получено {len(cars)} автомобилей KIA")
                
                for car in cars:
                    processed_car = await self.process_car_data(car)
                    if processed_car:
                        cars_data.append(processed_car)
                        
                        # Сохраняем в базу данных
                        await self.db.save_car(processed_car)
            else:
                logger.warning("⚠️ Неожиданный формат ответа от KIA API")
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных KIA: {e}")
        
        return cars_data
    
    async def process_car_data(self, car_data):
        """
        Обработка и нормализация данных об автомобиле KIA
        
        Args:
            car_data: Словарь с сырыми данными об автомобиле
            
        Returns:
            dict: Обработанные данные об автомобиле
        """
        try:
            # Проверка на наличие обязательных полей
            if not car_data.get("id") or not car_data.get("price"):
                logger.warning(f"⚠️ Отсутствуют обязательные поля в данных KIA")
                return None
            
            # Формирование URL страницы автомобиля
            car_url = f"{self.base_url}?id={car_data['id']}"
            
            # Обработка цены (убираем лишние символы и преобразуем в число)
            price = car_data.get("price", 0)
            if isinstance(price, str):
                price = price.replace(".", "").replace(",", ".").replace("€", "").strip()
                price = float(price) if price else 0
            
            # Извлечение изображений
            images = []
            if "thumbnailImages" in car_data and car_data["thumbnailImages"]:
                images = [img for img in car_data["thumbnailImages"] if img]
            elif "images" in car_data and car_data["images"]:
                images = [img for img in car_data["images"] if img]
            
            # Нормализованные данные об автомобиле
            normalized_car = {
                "car_id": str(car_data["id"]),
                "brand": "KIA",
                "model": car_data.get("modelDisplayName", "Unknown"),
                "title": f"KIA {car_data.get('modelDisplayName', '')} {car_data.get('year', '')}",
                "year": car_data.get("year", None),
                "mileage": car_data.get("mileage", 0),
                "fuel_type": car_data.get("fuelType", "Unknown"),
                "transmission": car_data.get("transmissionType", "Unknown"),
                "color": car_data.get("exteriorColorName", "Unknown"),
                "power": car_data.get("power", 0),
                "price": price,
                "images": images,
                "features": car_data.get("features", []),
                "description": car_data.get("description", ""),
                "dealer": "KIA Outlet",
                "dealer_location": car_data.get("dealerCity", "Unknown"),
                "url": car_url,
                "warranty": car_data.get("warranty", ""),
                "last_updated": datetime.now().isoformat()
            }
            
            return normalized_car
            
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных автомобиля KIA: {e}")
            return None
    
    async def fetch_car_details(self, car_id):
        """
        Получение детальной информации об автомобиле
        
        Args:
            car_id: ID автомобиля
            
        Returns:
            dict: Полные данные об автомобиле
        """
        # Формируем URL для запроса деталей автомобиля
        details_url = f"{self.api_url}/{car_id}"
        
        success, car_details = await self.fetch_with_retry(details_url)
        
        if not success or not car_details:
            logger.error(f"❌ Не удалось получить детали автомобиля KIA {car_id}")
            return None
        
        # Обрабатываем полученные данные
        processed_car = await self.process_car_data(car_details)
        
        # Если получили данные, сохраняем их в базу
        if processed_car:
            await self.db.save_car(processed_car)
        
        return processed_car
