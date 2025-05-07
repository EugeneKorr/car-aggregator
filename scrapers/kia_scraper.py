import json
import time
import re
import random
from datetime import datetime
from config import Config
from scrapers.base_scraper import BaseScraper
from utils.logger import logger

class KiaScraper(BaseScraper):
    def __init__(self, db):
        super().__init__(db)
        self.base_url = "https://kiaokasion.net/kia/"
        self.api_url = "https://kiaokasion.net/kia/async/metodos.aspx"
        
    async def fetch_cars(self, filters=None):
        """
        Получение списка автомобилей KIA с применением фильтров и сохранение в базу
        
        Args:
            filters: Словарь с фильтрами (цена, модель и т.д.)
            
        Returns:
            list: Список обработанных данных об автомобилях
        """
        if filters is None:
            filters = {}
        
        logger.info(f"🔍 Запрос автомобилей KIA с фильтрами: {json.dumps(filters)}")
        
        # Получаем общие данные о моделях
        all_models_data = await self._fetch_all_models()
        
        if not all_models_data:
            logger.error("❌ Не удалось получить данные о моделях")
            # Используем резервные данные, если API недоступно
            return await self._generate_fallback_data(filters)
        
        # Сохраняем статистику по моделям
        await self._save_models_stats(all_models_data)
        
        # Обрабатываем каждую модель
        all_cars = []
        model_filter = filters.get("model", "")
        
        for model_data in all_models_data.get("modelos", []):
            model_name = model_data.get("nombre", "")
            model_count = int(model_data.get("disponibles", "0"))
            
            # Если указан фильтр по модели и текущая модель не соответствует, пропускаем
            if model_filter and model_name.lower() != model_filter.lower():
                continue
                
            # Получаем список автомобилей данной модели
            model_cars = await self._process_model(model_name, model_count)
            all_cars.extend(model_cars)
        
        logger.info(f"✅ Всего обработано {len(all_cars)} автомобилей KIA")
        return all_cars
    
    async def _fetch_all_models(self):
        """
        Получение общих данных о всех моделях
        
        Returns:
            dict: JSON с данными о моделях или None в случае ошибки
        """
        try:
            # Отправляем пустой POST-запрос для получения общей информации
            logger.info("🔄 Запрос общих данных о моделях")
            
            success, response_data = await self.fetch_with_retry(
                self.api_url,
                method="POST",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.base_url
                }
            )
            
            if not success or not response_data:
                logger.error("❌ Не удалось получить данные о моделях")
                return None
            
            # Преобразуем ответ в JSON если это строка
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error("❌ Не удалось декодировать JSON-ответ")
                    return None
            
            # Логируем количество найденных моделей
            models_count = len(response_data.get("modelos", []))
            logger.info(f"✅ Получены данные о {models_count} моделях")
            
            return response_data
        except Exception as e:
            logger.error(f"❌ Ошибка при получении данных о моделях: {e}")
            return None
    
    async def _save_models_stats(self, models_data):
        """
        Сохранение статистики моделей
        
        Args:
            models_data: Данные о моделях
        """
        try:
            stats = {
                "total_cars": models_data.get("disponibles", 0),
                "min_price": models_data.get("preciominimo", 0),
                "max_price": models_data.get("preciomaximo", 0),
                "models": []
            }
            
            for model in models_data.get("modelos", []):
                stats["models"].append({
                    "name": model.get("nombre", ""),
                    "price": self._extract_price(model.get("precio", "0")),
                    "count": int(model.get("disponibles", "0"))
                })
            
            await self.db.save_model_stats(stats)
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении статистики моделей: {e}")
    
    async def _process_model(self, model_name, model_count):
        """
        Обработка конкретной модели: получение списка автомобилей, проверка изменений
        
        Args:
            model_name: Название модели
            model_count: Количество доступных автомобилей
            
        Returns:
            list: Обработанные данные об автомобилях данной модели
        """
        logger.info(f"🚗 Обработка модели {model_name}: доступно {model_count} авто")
        
        # Получаем список автомобилей конкретной модели
        model_cars_data = await self._fetch_model_cars(model_name)
        
        if not model_cars_data:
            logger.warning(f"⚠️ Не удалось получить данные об автомобилях модели {model_name}")
            # Если не удалось получить данные, используем резервные данные
            return await self._generate_model_fallback_data(model_name, model_count)
        
        # Получаем список автомобилей из API
        api_cars = model_cars_data.get("vehiculos", [])
        logger.info(f"✅ Получены данные о {len(api_cars)} автомобилях модели {model_name}")
        
        # Получаем существующие ID автомобилей из базы данных
        db_cars = await self.db.get_car_ids_by_model(model_name)
        db_car_ids = {car.get("idcoche") for car in db_cars if car.get("idcoche")}
        
        # Обработка полученных данных
        processed_cars = []
        
        for car_data in api_cars:
            car_id = car_data.get("id")
            
            if not car_id:
                continue
                
            # Если автомобиль уже в базе, помечаем его как активный
            if car_id in db_car_ids:
                db_car_ids.remove(car_id)
            
            # Получаем детальную информацию об автомобиле
            detailed_car = await self._fetch_car_details(car_id)
            
            if detailed_car:
                processed_cars.append(detailed_car)
        
        # Оставшиеся ID в db_car_ids - это автомобили, которых больше нет на сайте
        for inactive_id in db_car_ids:
            await self.db.mark_car_inactive(f"kia_{model_name.lower().replace(' ', '_')}_{inactive_id}")
            logger.info(f"🚫 Автомобиль с ID {inactive_id} помечен как неактивный")
        
        return processed_cars
    
    async def _fetch_model_cars(self, model_name):
        """
        Получение списка автомобилей определенной модели
        
        Args:
            model_name: Название модели
            
        Returns:
            dict: Данные о списке автомобилей или None в случае ошибки
        """
        try:
            # Формируем параметры для запроса списка автомобилей конкретной модели
            params = {
                "accion": "listado_modelo",
                "modelo": model_name
            }
            
            # Отправляем POST-запрос
            success, response_data = await self.fetch_with_retry(
                self.api_url,
                method="POST",
                data=params,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.base_url
                }
            )
            
            if not success or not response_data:
                logger.error(f"❌ Не удалось получить данные об автомобилях модели {model_name}")
                return None
            
            # Преобразуем ответ в JSON если это строка
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error(f"❌ Не удалось декодировать JSON-ответ для модели {model_name}")
                    return None
            
            return response_data
        except Exception as e:
            logger.error(f"❌ Ошибка при получении данных об автомобилях модели {model_name}: {e}")
            return None
    
    async def _fetch_car_details(self, car_id):
        """
        Получение детальной информации об автомобиле по ID
        
        Args:
            car_id: ID автомобиля
            
        Returns:
            dict: Обработанные данные об автомобиле или None в случае ошибки
        """
        try:
            # Формируем параметры для запроса детальной информации
            params = {
                "accion": "actualizarFicha",
                "idcoche": car_id
            }
            
            # Отправляем POST-запрос
            success, response_data = await self.fetch_with_retry(
                self.api_url,
                method="POST",
                data=params,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self.base_url
                }
            )
            
            if not success or not response_data:
                logger.error(f"❌ Не удалось получить детальную информацию об автомобиле {car_id}")
                return None
            
            # Преобразуем ответ в JSON если это строка
            if isinstance(response_data, str):
                try:
                    response_data = json.loads(response_data)
                except json.JSONDecodeError:
                    logger.error(f"❌ Не удалось декодировать JSON-ответ для автомобиля {car_id}")
                    return None
            
            # Обрабатываем полученные данные
            processed_car = await self._process_car_data(response_data, car_id)
            
            # Сохраняем обработанные данные в базу
            if processed_car:
                success, is_new = await self.db.save_car(processed_car)
                if is_new:
                    logger.info(f"✅ Добавлен новый автомобиль: {processed_car['model']} (ID: {car_id})")
                else:
                    logger.debug(f"✅ Обновлена информация об автомобиле: {processed_car['model']} (ID: {car_id})")
            
            return processed_car
        except Exception as e:
            logger.error(f"❌ Ошибка при получении детальной информации об автомобиле {car_id}: {e}")
            return None
    
    async def _process_car_data(self, car_data, idcoche):
        """
        Обработка и нормализация данных об автомобиле
        
        Args:
            car_data: Данные об автомобиле
            idcoche: ID автомобиля
            
        Returns:
            dict: Обработанные данные об автомобиле
        """
        try:
            # Извлекаем основные данные
            model = car_data.get("modelo", "Unknown")
            version = car_data.get("version", "")
            brand = car_data.get("marca", "KIA")
            price = self._extract_price(car_data.get("precio", "0"))
            year = car_data.get("any", datetime.now().year)
            
            # Генерируем уникальный car_id для нашей системы
            car_id = f"kia_{model.lower().replace(' ', '_')}_{idcoche}"
            
            # Получаем URL изображений
            images = []
            if car_data.get("imagenes"):
                image_urls = car_data["imagenes"].split("|")
                images = [f"https://kiaokasion.net/kia/imagenes/{url}" for url in image_urls if url]
            elif car_data.get("imagen"):
                images = [car_data["imagen"]]
            
            # Формируем оборудование
            features = []
            if car_data.get("resumen_equipamiento_serie"):
                if isinstance(car_data["resumen_equipamiento_serie"], list):
                    features = car_data["resumen_equipamiento_serie"]
                elif isinstance(car_data["resumen_equipamiento_serie"], str):
                    features = car_data["resumen_equipamiento_serie"].split("|")
            
            # Формируем данные об автомобиле
            processed_car = {
                "car_id": car_id,
                "idcoche": idcoche,  # Сохраняем оригинальный ID
                "brand": brand,
                "model": model,
                "version": version,
                "title": f"{brand} {model} {version}".strip(),
                "year": int(year) if year else None,
                "mileage": self._extract_number(car_data.get("kilometros", "0")),
                "fuel_type": car_data.get("combustible", "Unknown"),
                "transmission": car_data.get("transmision", "Unknown"),
                "color_exterior": car_data.get("color_exterior", "Unknown"),
                "color_interior": car_data.get("color_interior", "Unknown"),
                "body_type": car_data.get("carroceria", "Unknown"),
                "power": self._extract_number(car_data.get("potencia", "0")),
                "price": price,
                "price_cash": self._extract_price(car_data.get("precio_alcontado", "0")),
                "images": images,
                "features": features,
                "dealer": car_data.get("concesionario", "KIA Okasion"),
                "dealer_location": car_data.get("poblacion", "España"),
                "dealer_email": car_data.get("emailconcesionario", ""),
                "dealer_phone": car_data.get("telefono", ""),
                "dealer_address": car_data.get("direccion", ""),
                "matriculation_date": car_data.get("matriculacion", ""),
                "license_plate": car_data.get("matricula", ""),
                "url": f"{self.base_url}?idcoche={idcoche}",
                "warranty": f"{car_data.get('garantia', '')} месяцев",
                "engine_size": car_data.get("cubicaje", ""),
                "emission_label": car_data.get("distintivo", ""),
                "co2": car_data.get("co2", ""),
                "consumption_combined": car_data.get("consumo_combinado", ""),
                "consumption_urban": car_data.get("consumo_urbano", ""),
                "consumption_extra": car_data.get("consumo_extra", ""),
                "is_active": True,
                "last_updated": datetime.now().isoformat()
            }
            
            return processed_car
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных об автомобиле: {e}")
            return None
    
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
    
    def _extract_number(self, number_str):
        """
        Извлекает числовое значение из строки
        
        Args:
            number_str: Строка с числом
            
        Returns:
            int: Числовое значение
        """
        if not number_str:
            return 0
            
        try:
            # Извлекаем числа из строки
            number_match = re.search(r'(\d[\d\.,]*)', str(number_str))
            if number_match:
                number_clean = number_match.group(1).replace(".", "").replace(",", ".")
                return int(float(number_clean))
            return 0
        except (ValueError, TypeError):
            return 0
    
    async def _generate_fallback_data(self, filters=None):
        """
        Генерация резервных данных, если API недоступен
        
        Args:
            filters: Фильтры для данных
            
        Returns:
            list: Сгенерированные данные автомобилей
        """
        logger.warning("⚠️ Использование резервных данных из-за недоступности API")
        # Код для генерации резервных данных остается прежним
        # ...
        return []
    
    async def _generate_model_fallback_data(self, model_name, model_count):
        """
        Генерация резервных данных для конкретной модели
        
        Args:
            model_name: Название модели
            model_count: Количество автомобилей
            
        Returns:
            list: Сгенерированные данные автомобилей
        """
        logger.warning(f"⚠️ Использование резервных данных для модели {model_name}")
        # Код для генерации резервных данных для конкретной модели
        # ...
        return []
    
    async def fetch_car_by_id(self, car_id):
        """
        Получение информации об автомобиле по ID
        
        Args:
            car_id: ID автомобиля в формате kia_model_idcoche
            
        Returns:
            dict: Данные об автомобиле или None в случае ошибки
        """
        # Проверяем наличие автомобиля в базе данных
        car = await self.db.cars_collection.find_one({"car_id": car_id})
        
        if car:
            # Если автомобиль уже есть в базе, удаляем _id для JSON-сериализации
            if "_id" in car:
                car["_id"] = str(car["_id"])
            return car
        
        # Если автомобиля нет в базе, пытаемся получить данные с сайта
        # Извлекаем idcoche из car_id
        match = re.search(r'kia_.*?_(\d+)$', car_id)
        if match:
            idcoche = match.group(1)
            return await self._fetch_car_details(idcoche)
        
        return None
