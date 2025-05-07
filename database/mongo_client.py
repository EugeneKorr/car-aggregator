import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime
from config import Config
from utils.logger import logger

class MongoDB:
    def __init__(self):
        self.client = None
        self.db = None
        self.cars_collection = None
        self.stats_collection = None  # Новая коллекция для статистики
        
    async def connect(self):
        """Подключение к MongoDB"""
        try:
            self.client = AsyncIOMotorClient(Config.MONGO_URL, serverSelectionTimeoutMS=5000)
            # Проверка соединения
            await self.client.admin.command("ping")
            
            # Инициализация БД и коллекций
            self.db = self.client["test"]
            self.cars_collection = self.db["cars"]
            self.stats_collection = self.db["stats"]  # Инициализация коллекции статистики
            
            # Создание индексов
            await self.cars_collection.create_index("car_id", unique=True)
            await self.cars_collection.create_index("idcoche")  # Индекс по ID автомобиля с сайта
            await self.cars_collection.create_index("price")
            await self.cars_collection.create_index("brand")
            await self.cars_collection.create_index("model")
            await self.cars_collection.create_index("is_active")  # Индекс для статуса активности
            await self.stats_collection.create_index("date")  # Индекс для даты статистики
            
            logger.info("✅ MongoDB подключена успешно")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка подключения к MongoDB: {e}")
            return False
            
    async def disconnect(self):
        """Отключение от MongoDB"""
        if self.client:
            self.client.close()
            logger.info("✅ MongoDB отключена")
    
    async def save_car(self, car_data):
        """Сохранение или обновление информации об автомобиле"""
        try:
            # Добавляем поля даты и статуса активности, если их нет
            if "first_seen" not in car_data:
                car_data["first_seen"] = datetime.now().isoformat()
            
            car_data["last_updated"] = datetime.now().isoformat()
            car_data["is_active"] = True  # Автомобиль активен
            
            result = await self.cars_collection.update_one(
                {"car_id": car_data["car_id"]},
                {"$set": car_data},
                upsert=True
            )
            
            # Проверяем, был ли это новый автомобиль
            is_new = result.upserted_id is not None
            
            if is_new:
                logger.info(f"✅ Новый автомобиль {car_data['car_id']} добавлен в базу")
            else:
                logger.debug(f"✅ Автомобиль {car_data['car_id']} обновлен")
                
            return True, is_new
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении автомобиля: {e}")
            return False, False
    
    async def mark_car_inactive(self, car_id):
        """Пометка автомобиля как неактивного"""
        try:
            await self.cars_collection.update_one(
                {"car_id": car_id},
                {"$set": {
                    "is_active": False,
                    "inactive_since": datetime.now().isoformat()
                }}
            )
            logger.debug(f"✅ Автомобиль {car_id} помечен как неактивный")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при пометке автомобиля как неактивного: {e}")
            return False
    
    async def get_car_ids_by_model(self, model):
        """Получение списка ID автомобилей определенной модели"""
        try:
            cars = await self.cars_collection.find(
                {"model": model, "is_active": True}
            ).project({"car_id": 1, "idcoche": 1, "_id": 0}).to_list(length=1000)
            
            return cars
        except Exception as e:
            logger.error(f"❌ Ошибка при получении списка ID автомобилей: {e}")
            return []
    
    async def save_model_stats(self, model_stats):
        """Сохранение статистики моделей"""
        try:
            # Добавляем дату статистики
            model_stats["date"] = datetime.now().isoformat()
            
            await self.stats_collection.insert_one(model_stats)
            logger.info(f"✅ Статистика моделей сохранена")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении статистики: {e}")
            return False
    
    async def get_cars_by_price_range(self, min_price, max_price, limit=100, include_inactive=False):
        """Получение автомобилей в заданном ценовом диапазоне"""
        try:
            query = {"price": {"$gte": min_price, "$lte": max_price}}
            
            # Добавляем фильтр по активности, если требуется
            if not include_inactive:
                query["is_active"] = True
                
            cars = await self.cars_collection.find(query).sort("price", 1).limit(limit).to_list(length=limit)
            return cars
        except Exception as e:
            logger.error(f"❌ Ошибка при получении автомобилей: {e}")
            return []
