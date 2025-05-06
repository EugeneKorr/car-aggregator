cat > api.py << 'EOF'
import os
import json
import asyncio
from aiohttp import web
from dotenv import load_dotenv

from database.mongo_client import MongoDB
from scrapers.kia_scraper import KiaScraper
from utils.logger import logger

# Загружаем переменные окружения
load_dotenv()

# Инициализируем MongoDB
db = MongoDB()

async def initialize():
    """Инициализация базы данных"""
    await db.connect()

# Определяем обработчики API
async def handle_get_cars(request):
    """
    Обработчик запроса на получение автомобилей
    
    Поддерживаемые параметры:
    - min_price: Минимальная цена
    - max_price: Максимальная цена
    - brand: Фильтр по марке
    - model: Фильтр по модели
    - limit: Максимальное количество результатов
    """
    # Получаем параметры запроса
    params = request.query
    
    # Формируем запрос к MongoDB
    query = {}
    
    # Обработка ценового диапазона
    price_query = {}
    if "min_price" in params:
        price_query["$gte"] = int(params["min_price"])
    if "max_price" in params:
        price_query["$lte"] = int(params["max_price"])
    if price_query:
        query["price"] = price_query
    
    # Фильтр по марке
    if "brand" in params:
        query["brand"] = params["brand"]
        
    # Фильтр по модели
    if "model" in params:
        query["model"] = {"$regex": params["model"], "$options": "i"}
    
    # Ограничение количества результатов
    limit = int(params.get("limit", 100))
    
    try:
        # Выполняем запрос к базе данных
        cars = await db.cars_collection.find(query).sort("price", 1).limit(limit).to_list(length=limit)
        
        # Преобразуем ObjectId в строки для JSON-сериализации
        for car in cars:
            if "_id" in car:
                car["_id"] = str(car["_id"])
        
        return web.json_
