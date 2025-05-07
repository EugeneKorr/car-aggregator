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
        
        # Создаем данные для POST-запроса
        post_data = {
            "modelo": filters.get("model", ""),
            "min_price": filters.get("min_price", ""),
            "max_price": filters.get("max_price", ""),
            "action": "filter_cars"  # Предполагаемое действие
        }
        
        # Отправляем POST-запрос к API
        success, response_data = await self.fetch_with_retry(
            self.api_url,
            method="POST",
            data=post_data
        )
        
        if not success or not response_data:
            logger.error("❌ Не удалось получить данные с API KIA Okasion")
            return []
        
        # Обработка JSON-результатов
        cars_data = []
        try:
            # Если результат получен как строка, преобразуем его в JSON
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error("❌ Не удалось декодировать JSON-ответ")
                    return []
            
            # Обрабатываем общую информацию
            total_cars = response_data.get("disponibles", 0)
            logger.info(f"✅ Найдено {total_cars} автомобилей KIA")
            
            # Получаем и обрабатываем данные о моделях
            models_data = response_data.get("modelos", [])
            logger.info(f"✅ Найдено {len(models_data)} моделей KIA")
            
            # Для каждой модели извлекаем доступные автомобили
            for model_data in models_data:
                # Если указана модель в фильтрах и она не совпадает, пропускаем
                if "model" in filters and filters["model"] and model_data.get("nombre", "").lower() != filters["model"].lower():
                    continue
                
                # Проверяем фильтры цены
                model_price = self._extract_price(model_data.get("precio", "0"))
                if "min_price" in filters and model_price < filters["min_price"]:
                    continue
                if "max_price" in filters and model_price > filters["max_price"]:
                    continue
                
                # Обрабатываем каждую модель
                model_name = model_data.get("nombre", "Unknown")
                model_count = int(model_data.get("disponibles", "0"))
                
                # Если это Picanto (или другая модель, которую мы собираем)
                if model_name == "Picanto" or not filters.get("model"):
                    # Получаем дополнительные данные о модели с другим запросом
                    model_cars = await self._fetch_model_details(model_name)
                    cars_data.extend(model_cars)
                    
            logger.info(f"✅ Обработано {len(cars_data)} автомобилей KIA")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных KIA: {e}")
        
        return cars_data
    
    async def _fetch_model_details(self, model_name):
        """
        Получение детальной информации о конкретной модели
        
        Args:
            model_name: Название модели
            
        Returns:
            list: Список автомобилей данной модели
        """
        logger.info(f"🔍 Запрос деталей для модели KIA {model_name}")
        
        # Данные для фильтрации по модели
        post_data = {
            "modelo": model_name,
            "action": "buscar_modelo"  # Предполагаемое действие
        }
        
        # Отправляем POST-запрос к API для получения деталей модели
        success, response_data = await self.fetch_with_retry(
            self.api_url,
            method="POST",
            data=post_data
        )
        
        if not success or not response_data:
            logger.error(f"❌ Не удалось получить детали для модели {model_name}")
            return []
        
        model_cars = []
        try:
            # Преобразуем ответ в JSON если это строка
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error("❌ Не удалось декодировать JSON-ответ для деталей модели")
                    return []
            
            # Пытаемся извлечь данные об автомобилях этой модели
            cars_list = response_data.get("coches", [])
            if not cars_list:
                # Альтернативный поиск, если данные в другом формате
                cars_list = response_data.get("vehiculos", [])
            
            if not cars_list:
                # Если нет явного списка автомобилей, создаем записи из общих данных
                cars_list = [{"modelo": model_name, "precio": response_data.get("preciominimo", 0)}]
            
            # Обрабатываем каждый автомобиль
            for idx, car in enumerate(cars_list):
                car_data = await self.process_car_data(car, model_name)
                if car_data:
                    model_cars.append(car_data)
                    # Сохраняем в базу данных
                    await self.db.save_car(car_data)
            
            logger.info(f"✅ Найдено {len(model_cars)} автомобилей модели {model_name}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных модели {model_name}: {e}")
        
        return model_cars
    
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
            price_clean = price_str.replace(".", "").replace(",", ".").replace("€", "").strip()
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
                url = f"{self.base_url}vehiculo?id={car_id}"
            
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
        
        # Данные для запроса конкретного автомобиля
        post_data = {
            "car_id": car_id,
            "action": "get_car_details"  # Предполагаемое действие
        }
        
        # Отправляем POST-запрос к API
        success, response_data = await self.fetch_with_retry(
            self.api_url,
            method="POST",
            data=post_data
        )
        
        if not success or not response_data:
            logger.error(f"❌ Не удалось получить детали для автомобиля {car_id}")
            return None
        
        try:
            # Преобразуем ответ в JSON если это строка
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error("❌ Не удалось декодировать JSON-ответ для деталей автомобиля")
                    return None
            
            # Обрабатываем данные об автомобиле
            car_details = await self.process_car_data(response_data)
            
            if car_details:
                # Сохраняем в базу данных
                await self.db.save_car(car_details)
                
            return car_details
                
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке деталей автомобиля {car_id}: {e}")
            
        return None
