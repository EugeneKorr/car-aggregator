print("Starting application...")
import sys
print(f"Python version: {sys.version}")
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
    except Exception as e:
        logger.error(f"❌ Ошибка при получении автомобилей: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)
    
    # Этот return теперь вне блока try-except
    return web.json_response({
        "success": True,
        "count": len(cars),
        "cars": cars
    })
        except Exception as e:
            logger.error(f"❌ Ошибка при получении автомобилей: {e}")
            return web.json_response({
                "success": False,
                "error": str(e)
            }, status=500)

async def handle_trigger_scraping(request):
    """
    Обработчик запроса на ручной запуск скрапинга
    
    Поддерживаемые параметры:
    - filters: JSON со словарем фильтров
    """
    try:
        # Получаем тело запроса
        body = await request.json()
        
        # Извлекаем фильтры
        filters = body.get("filters", {})
        
        # Инициализируем скрапер
        scraper = KiaScraper(db)
        
        # Запускаем скрапинг
        cars = await scraper.fetch_cars(filters)
        
        # Закрываем сессию скрапера
        await scraper.close_session()
        
        return web.json_response({
            "success": True,
            "count": len(cars),
            "message": f"Собрано {len(cars)} автомобилей"
        })
    except Exception as e:
        logger.error(f"❌ Ошибка при запуске скрапинга: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

async def handle_get_car_by_id(request):
    """
    Обработчик запроса на получение конкретного автомобиля по ID
    """
    car_id = request.match_info.get("id")
    
    if not car_id:
        return web.json_response({
            "success": False,
            "error": "ID автомобиля не указан"
        }, status=400)
    
    try:
        # Ищем автомобиль в базе данных
        car = await db.cars_collection.find_one({"car_id": car_id})
        
        if car:
            # Преобразуем ObjectId в строку для JSON-сериализации
            if "_id" in car:
                car["_id"] = str(car["_id"])
                
            return web.json_response({
                "success": True,
                "car": car
            })
        else:
            # Если автомобиль не найден, пытаемся получить его напрямую
            scraper = KiaScraper(db)
            car_details = await scraper.fetch_car_details(car_id)
            await scraper.close_session()
            
            if car_details:
                return web.json_response({
                    "success": True,
                    "car": car_details,
                    "source": "api"
                })
            else:
                return web.json_response({
                    "success": False,
                    "error": "Автомобиль не найден"
                }, status=404)
    except Exception as e:
        logger.error(f"❌ Ошибка при получении автомобиля {car_id}: {e}")
        return web.json_response({
            "success": False,
            "error": str(e)
        }, status=500)

# Создаем маршруты API
app = web.Application()
app.router.add_get('/api/cars', handle_get_cars)
app.router.add_get('/api/cars/{id}', handle_get_car_by_id)
app.router.add_post('/api/scrape', handle_trigger_scraping)

# Обработчик для запуска приложения
async def start_app():
    await initialize()
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    web.run_app(start_app(), port=port, host='0.0.0.0')
