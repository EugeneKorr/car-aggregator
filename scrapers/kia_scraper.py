import json
from datetime import datetime
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
        
        logger.info(f"🔍 Запрос автомобилей KIA с фильтрами: {json.dumps(filters)}")
        
        # Создаем сессию
        await self.create_session()
        
        # Обновляем заголовки в объекте сессии
        if self.session and not self.session.closed:
            self.session.headers.update({
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "es-ES,es;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": "https://kiaokasion.net/kia/",
                "Origin": "https://kiaokasion.net"
            })
        
        # По данным из скриншотов видно, что запрос к API выполняется без параметров
        # Отправляем пустой POST-запрос к API для получения всех моделей и базовой информации
        success, response_data = await self.fetch_with_retry(
            self.api_url,
            method="POST"
        )
        
        # Логируем подробности запроса
        logger.info(f"📡 Запрос к API: {self.api_url}")
        logger.info(f"📊 Результат запроса: {'успешно' if success else 'неудачно'}")
        
        if not success or not response_data:
            logger.error("❌ Не удалось получить данные с API KIA Okasion")
            return []
        
        # Логируем ответ для отладки
        logger.debug(f"📥 Ответ API: {response_data[:500]}..." if isinstance(response_data, str) else f"📥 Ответ API: {str(response_data)[:500]}...")
        
        # Обработка JSON-результатов
        cars_data = []
        try:
            # Если результат получен как строка, преобразуем его в JSON
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError as e:
                    logger.error(f"❌ Не удалось декодировать JSON-ответ: {e}")
                    logger.debug(f"📄 Начало ответа: {response_data[:200]}")
                    return []
            
            # Обрабатываем общую информацию
            disponibles = response_data.get("disponibles", 0)
            logger.info(f"✅ Всего доступно автомобилей: {disponibles}")
            
            # Получаем и обрабатываем данные о моделях
            models_data = response_data.get("modelos", [])
            logger.info(f"✅ Найдено {len(models_data)} моделей KIA")
            
            # Для каждой модели обрабатываем базовую информацию
            for model_data in models_data:
                model_name = model_data.get("nombre", "Unknown")
                model_price = self._extract_price(model_data.get("precio", "0"))
                model_count = int(model_data.get("disponibles", "0"))
                
                logger.info(f"✨ Модель: {model_name}, Цена от: {model_price}€, Доступно: {model_count} шт.")
                
                # Если указана модель в фильтрах и она не совпадает, пропускаем
                if "model" in filters and filters["model"] and model_name.lower() != filters["model"].lower():
                    continue
                
                # Проверяем фильтры цены
                if "min_price" in filters and model_price < filters["min_price"]:
                    continue
                if "max_price" in filters and model_price > filters["max_price"]:
                    continue
                
                # Добавляем базовую информацию о модели
                for i in range(model_count):
                    car_id = f"kia_{model_name.lower().replace(' ', '_')}_{i}"
                    
                    car_data = {
                        "car_id": car_id,
                        "brand": "KIA",
                        "model": model_name,
                        "title": f"KIA {model_name}",
                        "price": model_price,
                        "dealer": "KIA Okasion",
                        "dealer_location": "España",
                        "url": f"{self.base_url}?modelo={model_name}",
                        "last_updated": datetime.now().isoformat()
                    }
                    
                    cars_data.append(car_data)
                    
                    # Сохраняем в базу данных
                    await self.db.save_car(car_data)
                
                # Если это Picanto или другая интересующая модель, запрашиваем подробности
                if model_name == "Picanto" or model_name == filters.get("model", ""):
                    await self._fetch_additional_model_info(model_name)
            
            logger.info(f"✅ Обработано {len(cars_data)} автомобилей KIA")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных KIA: {e}")
        
        return cars_data
    
    async def _fetch_additional_model_info(self, model_name):
        """
        Получение дополнительной информации о модели
        
        Args:
            model_name: Название модели
        """
        logger.info(f"🔍 Запрос дополнительной информации для модели {model_name}")
        
        # На основе анализа XHR-запросов, создаем запрос для получения дополнительной информации
        # Это может быть другой URL или параметры для API
        try:
            # Пример: запрос, имитирующий выбор модели на сайте
            post_data = {
                "modelo": model_name
            }
            
            success, response_data = await self.fetch_with_retry(
                self.api_url,
                method="POST",
                data=post_data
            )
            
            if success and response_data:
                logger.info(f"✅ Получена дополнительная информация для модели {model_name}")
                
                # Обрабатываем данные так же, как в основном методе
                if isinstance(response_data, str):
                    try:
                        response_data = json.loads(response_data)
                        
                        # Логируем некоторые ключи из ответа
                        logger.debug(f"📊 Ключи в ответе: {list(response_data.keys())}")
                        
                        # Обработка данных...
                        
                    except json.JSONDecodeError:
                        logger.error(f"❌ Не удалось декодировать JSON-ответ для {model_name}")
            else:
                logger.error(f"❌ Не удалось получить дополнительную информацию для {model_name}")
                
        except Exception as e:
            logger.error(f"❌ Ошибка при запросе дополнительной информации для {model_name}: {e}")
    
    def _extract_price(self, price_str):
        """
        Извлекает числовое значение цены из строки
        
        Args:
            price_str: Строка с ценой
            
        Returns:
            float: Числовое значение цены
        """
        if not price_str:
            return 0
            
        try:
            # Удаляем нечисловые символы и конвертируем
            price_clean = str(price_str).replace(".", "").replace(",", ".").replace("€", "").strip()
            return float(price_clean)
        except (ValueError, TypeError):
            return 0
    
    async def process_car_data(self, car_data, model_name=None):
        """
        Обработка и нормализация данных об автомобиле KIA
        
        Args:
            car_data: Словарь с сырыми данными об автомобиле
            model_name: Название модели (если известно)
            
        Returns:
            dict: Обработанные данные об автомобиле
        """
        try:
            # Определяем модель
            model = model_name or car_data.get("modelo", car_data.get("nombre", "Unknown"))
            
            # Генерируем ID
            car_id = car_data.get("id", car_data.get("car_id", f"kia_{model}_{hash(str(car_data)) % 10000}"))
            
            # Извлекаем цену
            price = self._extract_price(car_data.get("precio", car_data.get("price", "0")))
            
            # Извлекаем год
            year = car_data.get("year", car_data.get("ano", None))
            if not year and "title" in car_data:
                import re
                year_match = re.search(r'(\d{4})', car_data["title"])
                if year_match:
                    year = int(year_match.group(1))
            
            # Извлекаем изображения
            images = []
            if "imagenes" in car_data and car_data["imagenes"]:
                images = [img for img in car_data["imagenes"] if img]
            elif "image" in car_data and car_data["image"]:
                images = [car_data["image"]]
            
            # Формируем URL автомобиля
            url = car_data.get("url", "")
            if not url:
                url = f"{self.base_url}?modelo={model}"
            
            # Нормализованные данные об автомобиле
            normalized_car = {
                "car_id": str(car_id),
                "brand": "KIA",
                "model": model,
                "title": f"KIA {model} {year or ''}".strip(),
                "year": year,
                "mileage": car_data.get("kilometros", car_data.get("kms", 0)),
                "fuel_type": car_data.get("combustible", "Unknown"),
                "transmission": car_data.get("cambio", "Unknown"),
                "color": car_data.get("color", "Unknown"),
                "power": car_data.get("potencia", 0),
                "price": price,
                "images": images,
                "features": car_data.get("equipamiento", []),
                "description": car_data.get("descripcion", f"KIA {model}"),
                "dealer": "KIA Okasion",
                "dealer_location": car_data.get("ubicacion", "España"),
                "url": url,
                "warranty": "Garantía Oficial KIA",
                "last_updated": datetime.now().isoformat()
            }
            
            return normalized_car
            
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных автомобиля KIA: {e}")
            return None
    
    async def fetch_car_details(self, car_id):
        """
        Получение детальной информации об автомобиле по ID
        
        Args:
            car_id: ID автомобиля
            
        Returns:
            dict: Полные данные об автомобиле
        """
        logger.info(f"🔍 Запрос деталей для автомобиля KIA с ID: {car_id}")
        
        # Так как у нас нет точного API для получения деталей конкретного авто,
        # мы извлечем эту информацию из базы данных
        car = await self.db.cars_collection.find_one({"car_id": car_id})
        
        if car:
            # Удаляем _id для JSON-сериализации
            if "_id" in car:
                car["_id"] = str(car["_id"])
            return car
        
        # Если не нашли в базе, возвращаем базовую информацию
        return None
