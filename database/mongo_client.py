mkdir -p database
cat > database/mongo_client.py << 'EOF'
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from config import Config
from utils.logger import logger

class MongoDB:
    def __init__(self):
        self.client = None
        self.db = None
        self.cars_collection = None
        
    async def connect(self):
        """Подключение к MongoDB"""
        try:
            self.client = AsyncIOMotorClient(Config.MONGO_URL, serverSelectionTimeoutMS=5000)
            # Проверка соединения
            await self.client.admin.command("ping")
            
            # Инициализация БД и коллекций
            self.db = self.client["test"]
            self.cars_collection = self.db["cars"]
            
            # Создание индексов
            await self.cars_collection.create_index("car_id", unique=True)
            await self.cars_collection.create_index("price")
            await self.cars_collection.create_index("brand")
            await self.cars_collection.create_index("model")
            
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
            result = await self.cars_collection.update_one(
                {"car_id": car_data["car_id"]},
                {"$set": car_data},
                upsert=True
            )
            logger.debug(f"✅ Автомобиль {car_data['car_id']} сохранен/обновлен")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении автомобиля: {e}")
            return False
    
    async def get_cars_by_price_range(self, min_price, max_price, limit=100):
        """Получение автомобилей в заданном ценовом диапазоне"""
        try:
            query = {"price": {"$gte": min_price, "$lte": max_price}}
            cars = await self.cars_collection.find(query).sort("price", 1).limit(limit).to_list(length=limit)
            return cars
        except Exception as e:
            logger.error(f"❌ Ошибка при получении автомобилей: {e}")
            return []
EOF
