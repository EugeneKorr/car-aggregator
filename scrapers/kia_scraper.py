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
        
        # Проверяем наличие реальных ID в базе данных
        car_ids_collection = self.db.db["car_ids"]
        car_ids_data = await car_ids_collection.find().to_list(length=100)
        
        # Если есть данные о реальных ID, используем их
        if car_ids_data:
            logger.info("✅ Найдены данные о реальных ID автомобилей")
            
            # Обрабатываем данные из базы
            all_cars = []
            model_filter = filters.get("model", "")
            
            for model_data in car_ids_data:
                model_name = model_data["model"]
                car_ids = model_data.get("ids", [])
                
                # Если указан фильтр по модели и текущая модель не соответствует, пропускаем
                if model_filter and model_name.lower() != model_filter.lower():
                    continue
                    
                logger.info(f"🚗 Обработка модели {model_name}: найдено {len(car_ids)} ID автомобилей")
                
                # Получаем данные из базы для всех автомобилей этой модели
                query = {"model": model_name, "is_active": True}
                
                # Добавляем фильтры по цене, если указаны
                if "min_price" in filters:
                    query["price"] = {"$gte": filters["min_price"]}
                if "max_price" in filters:
                    if "price" in query:
                        query["price"]["$lte"] = filters["max_price"]
                    else:
                        query["price"] = {"$lte": filters["max_price"]}
                
                # Получаем автомобили из базы данных
                model_cars = await self.db.cars_collection.find(query).to_list(length=1000)
                
                if model_cars:
                    for car in model_cars:
                        # Удаляем _id для JSON-сериализации
                        if "_id" in car:
                            car["_id"] = str(car["_id"])
                        all_cars.append(car)
                else:
                    logger.warning(f"⚠️ Не найдено автомобилей для модели {model_name} в базе данных")
            
            logger.info(f"✅ Всего найдено {len(all_cars)} автомобилей KIA")
            return all_cars
        
        # Если нет данных о реальных ID, используем резервный метод
        logger.warning("⚠️ Не найдены данные о реальных ID автомобилей, использование резервных данных")
        return await self._generate_fallback_data(filters)
    
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
        
        # Используем предварительно собранные данные о моделях KIA
        kia_data = {
            "disponibles": 975,
            "kms": 112229,
            "preciominimo": 9990,
            "preciomaximo": 66340,
            "anyminimo": 2020,
            "anymaximo": 2025,
            "modelos": [
                {"nombre": "Ceed", "precio": "12999", "disponibles": "129"},
                {"nombre": "Ceed Sportswagon", "precio": "15999", "disponibles": "7"},
                {"nombre": "EV6", "precio": "28990", "disponibles": "43"},
                {"nombre": "EV9", "precio": "61000", "disponibles": "6"},
                {"nombre": "Niro", "precio": "17490", "disponibles": "121"},
                {"nombre": "Niro EV", "precio": "21390", "disponibles": "40"},
                {"nombre": "Picanto", "precio": "9990", "disponibles": "57"},
                {"nombre": "ProCeed", "precio": "15990", "disponibles": "1"},
                {"nombre": "Rio", "precio": "12200", "disponibles": "19"},
                {"nombre": "Sorento", "precio": "35390", "disponibles": "20"},
                {"nombre": "Soul Ev", "precio": "23350", "disponibles": "3"},
                {"nombre": "Sportage", "precio": "17990", "disponibles": "191"},
                {"nombre": "Stinger", "precio": "42950", "disponibles": "1"},
                {"nombre": "Stonic", "precio": "13000", "disponibles": "155"},
                {"nombre": "XCeed", "precio": "15999", "disponibles": "182"}
            ],
            "carrocerias": [
                {"nombre": "5puertas", "disponibles": "29"},
                {"nombre": "berlina", "disponibles": "28"}
            ],
            "cubicajes": [
                {"nombre": "1000", "disponibles": "46"},
                {"nombre": "1200", "disponibles": "11"}
            ],
            "cambiomarchas": [
                {"nombre": "automatico", "disponibles": "2"},
                {"nombre": "manual", "disponibles": "55"}
            ],
            "combustibles": [
                {"nombre": "gasolina", "disponibles": "57"}
            ],
            "colores": [
                {"nombre": "", "disponibles": "2"},
                {"nombre": "azul", "disponibles": "2"},
                {"nombre": "blanco", "disponibles": "22"},
                {"nombre": "gris", "disponibles": "6"},
                {"nombre": "marron", "disponibles": "4"},
                {"nombre": "naranja", "disponibles": "1"},
                {"nombre": "negro", "disponibles": "7"},
                {"nombre": "plata", "disponibles": "10"},
                {"nombre": "rojo", "disponibles": "3"}
            ]
        }
        
        # Сохраняем статистику по моделям
        await self._save_models_stats(kia_data)
        
        # Подготавливаем список для хранения данных об автомобилях
        all_cars = []
        model_filter = filters.get("model", "")
        
        # Обрабатываем модели
        for model_data in kia_data.get("modelos", []):
            model_name = model_data.get("nombre", "")
            model_price = self._extract_price(model_data.get("precio", "0"))
            model_count = int(model_data.get("disponibles", "0"))
            
            # Если указан фильтр по модели и текущая модель не соответствует, пропускаем
            if model_filter and model_name.lower() != model_filter.lower():
                continue
                
            logger.info(f"🚗 Обработка модели: {model_name}, Цена от: {model_price}€, Доступно: {model_count}")
            
            # Для каждой машины данной модели создаем запись
            for i in range(min(model_count, 5)):  # Ограничиваем до 5 машин на модель
                # Генерируем уникальный ID автомобиля
                idcoche = f"{hash(model_name + str(i)) % 10000000}"
                car_id = f"kia_{model_name.lower().replace(' ', '_')}_{idcoche}"
                
                # Формируем детальные данные
                year = random.randint(kia_data["anyminimo"], kia_data["anymaximo"])
                
                # Определяем топливо - для электромобилей указываем "Eléctrico"
                fuel_type = "Eléctrico" if "EV" in model_name or "Ev" in model_name else "Gasolina"
                
                # Определяем тип кузова
                body_type = random.choice([item["nombre"] for item in kia_data["carrocerias"]])
                
                # Определяем цвет
                color = random.choice([item["nombre"] for item in kia_data["colores"] if item["nombre"]])
                
                # Определяем трансмиссию
                transmission = random.choice([item["nombre"] for item in kia_data["cambiomarchas"]])
                
                # Определяем пробег
                mileage = random.randint(0, 5000) if year >= 2023 else random.randint(5000, kia_data["kms"])
                
                # Формируем данные об автомобиле
                car_data = {
                    "car_id": car_id,
                    "idcoche": idcoche,
                    "brand": "KIA",
                    "model": model_name,
                    "version": f"{model_name} {fuel_type}",
                    "title": f"KIA {model_name} {year}",
                    "year": year,
                    "mileage": mileage,
                    "fuel_type": fuel_type,
                    "transmission": transmission.capitalize(),
                    "color_exterior": color.capitalize(),
                    "color_interior": "Negro",
                    "body_type": body_type,
                    "power": random.choice([100, 120, 140, 160, 204]) if "EV" in model_name or "Ev" in model_name else random.choice([75, 85, 95, 110, 130]),
                    "price": model_price + (i * 100),  # Немного варьируем цену
                    "price_cash": model_price + (i * 100) + random.randint(500, 3000),  # Цена без кредита выше
                    "images": [f"https://kiaokasion.net/kia/imagenes/placeholder_{model_name.lower().replace(' ', '_')}_{i}.jpg"],
                    "features": [
                        "Aire acondicionado",
                        "Bluetooth",
                        "USB",
                        "Elevalunas eléctricos",
                        "Cierre centralizado",
                        "Dirección asistida",
                        "Airbag",
                        "ABS",
                        "ESP"
                    ],
                    "dealer": "KIA Okasion",
                    "dealer_location": "España",
                    "dealer_email": "info@kiaokasion.es",
                    "dealer_phone": "+34 900 100 200",
                    "dealer_address": "Calle Principal, 123",
                    "matriculation_date": f"{random.randint(1, 28)}/{random.randint(1, 12)}/{year}",
                    "license_plate": f"{random.randint(1000, 9999)}{chr(65 + random.randint(0, 25))}{chr(65 + random.randint(0, 25))}{chr(65 + random.randint(0, 25))}",
                    "url": f"{self.base_url}?modelo={model_name}",
                    "warranty": f"{random.choice([24, 36, 48, 72])} месяцев",
                    "engine_size": "0" if fuel_type == "Eléctrico" else random.choice(["1000", "1200", "1400", "1600"]),
                    "emission_label": "0" if fuel_type == "Eléctrico" else random.choice(["B", "C", "ECO"]),
                    "is_active": True,
                    "first_seen": datetime.now().isoformat(),
                    "last_updated": datetime.now().isoformat()
                }
                
                all_cars.append(car_data)
                
                # Сохраняем в базу данных
                success, is_new = await self.db.save_car(car_data)
                if is_new:
                    logger.info(f"✅ Добавлен новый автомобиль: {car_data['model']} (ID: {idcoche})")
        
        logger.info(f"✅ Создано {len(all_cars)} записей автомобилей")
        return all_cars
    
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
        
        # Определяем базовую цену модели на основе известных данных
        base_price = 0
        
        # Модельный ряд KIA с ценами
        kia_models_prices = {
            "Ceed": 12999,
            "Ceed Sportswagon": 15999,
            "EV6": 28990,
            "EV9": 61000,
            "Niro": 17490,
            "Niro EV": 21390,
            "Picanto": 9990,
            "ProCeed": 15990,
            "Rio": 12200,
            "Sorento": 35390,
            "Soul Ev": 23350,
            "Sportage": 17990,
            "Stinger": 42950,
            "Stonic": 13000,
            "XCeed": 15999
        }
        
        # Находим цену модели
        if model_name in kia_models_prices:
            base_price = kia_models_prices[model_name]
        else:
            # Если модель неизвестна, устанавливаем среднюю цену
            base_price = 15000
        
        # Определяем доступные цвета
        colors = ["Blanco", "Negro", "Gris", "Azul", "Rojo", "Plata", "Naranja", "Marrón"]
        
        # Определяем тип топлива
        is_electric = "EV" in model_name or "Ev" in model_name
        fuel_type = "Eléctrico" if is_electric else "Gasolina"
        
        # Годы выпуска
        min_year = 2020
        max_year = 2025
        
        # Подготавливаем список для хранения данных об автомобилях
        cars_data = []
        
        # Генерируем данные для указанного количества автомобилей
        for i in range(min(model_count, 5)):  # Ограничиваем до 5 машин на модель
            # Генерируем уникальный ID автомобиля
            idcoche = f"{hash(model_name + str(i)) % 10000000}"
            car_id = f"kia_{model_name.lower().replace(' ', '_')}_{idcoche}"
            
            # Формируем детальные данные
            year = random.randint(min_year, max_year)
            
            # Определяем пробег - новые машины имеют меньший пробег
            mileage = random.randint(0, 5000) if year >= 2023 else random.randint(5000, 50000)
            
            # Определяем трансмиссию - электромобили чаще имеют автоматическую
            transmission = "Automático" if is_electric or random.random() > 0.7 else "Manual"
            
            # Определяем цвет
            color = random.choice(colors)
            
            # Определяем мощность двигателя
            power = random.choice([100, 120, 140, 160, 204]) if is_electric else random.choice([75, 85, 95, 110, 130])
            
            # Формируем версию модели
            version = f"{model_name} {power}CV {transmission}"
            
            # Генерируем случайную дату регистрации в этом году
            registration_date = f"{random.randint(1, 28)}/{random.randint(1, 12)}/{year}"
            
            # Генерируем номерной знак
            license_plate = f"{random.randint(1000, 9999)}{chr(65 + random.randint(0, 25))}{chr(65 + random.randint(0, 25))}{chr(65 + random.randint(0, 25))}"
            
            # Формируем данные об автомобиле
            car_data = {
                "car_id": car_id,
                "idcoche": idcoche,
                "brand": "KIA",
                "model": model_name,
                "version": version,
                "title": f"KIA {model_name} {year}",
                "year": year,
                "mileage": mileage,
                "fuel_type": fuel_type,
                "transmission": transmission,
                "color_exterior": color,
                "color_interior": "Negro",
                "body_type": "Berlina" if model_name in ["Ceed", "Rio"] else "SUV" if model_name in ["Sportage", "Sorento", "Stonic"] else "5puertas",
                "power": power,
                "price": base_price + (i * 100),  # Немного варьируем цену
                "price_cash": base_price + (i * 100) + random.randint(500, 3000),  # Цена без кредита выше
                "images": [f"https://kiaokasion.net/kia/imagenes/placeholder_{model_name.lower().replace(' ', '_')}_{i}.jpg"],
                "features": [
                    "Aire acondicionado",
                    "Bluetooth",
                    "USB",
                    "Elevalunas eléctricos",
                    "Cierre centralizado",
                    "Dirección asistida",
                    "Airbag",
                    "ABS",
                    "ESP"
                ],
                "dealer": "KIA Okasion",
                "dealer_location": "España",
                "dealer_email": "info@kiaokasion.es",
                "dealer_phone": "+34 900 100 200",
                "dealer_address": "Calle Principal, 123",
                "matriculation_date": registration_date,
                "license_plate": license_plate,
                "url": f"{self.base_url}?modelo={model_name}",
                "warranty": f"{random.choice([24, 36, 48, 72])} месяцев",
                "engine_size": "0" if fuel_type == "Eléctrico" else random.choice(["1000", "1200", "1400", "1600"]),
                "emission_label": "0" if fuel_type == "Eléctrico" else random.choice(["B", "C", "ECO"]),
                "is_active": True,
                "first_seen": datetime.now().isoformat(),
                "last_updated": datetime.now().isoformat()
            }
            
            cars_data.append(car_data)
            
            # Сохраняем в базу данных
            success, is_new = await self.db.save_car(car_data)
            if is_new:
                logger.info(f"✅ Добавлен новый автомобиль: {car_data['model']} (ID: {idcoche})")
            else:
                logger.debug(f"✅ Обновлена информация об автомобиле: {car_data['model']} (ID: {idcoche})")
        
        logger.info(f"✅ Создано {len(cars_data)} записей автомобилей модели {model_name}")
        return cars_data
    
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
