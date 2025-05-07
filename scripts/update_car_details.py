import asyncio
import json
import os
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
import aiohttp
import random
import time

# Загружаем переменные окружения
load_dotenv()

# Подключение к MongoDB
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client["test"]
cars_collection = db["cars"]
car_ids_collection = db["car_ids"]

# Настройки API
API_URL = "https://kiaokasion.net/kia/async/metodos.aspx"
BASE_URL = "https://kiaokasion.net/kia/"

# Заголовки для HTTP-запросов
def get_headers():
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0"
    ]
    
    return {
        "User-Agent": random.choice(user_agents),
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Requested-With": "XMLHttpRequest",
        "Referer": BASE_URL,
        "Origin": "https://kiaokasion.net",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7"
    }

# Получение детальной информации об автомобиле
async def get_car_details(session, car_id):
    try:
        # Формируем данные для запроса
        data = {
            "accion": "actualizarFicha",
            "idcoche": car_id
        }
        
        # Отправляем POST-запрос
        async with session.post(API_URL, data=data, headers=get_headers()) as response:
            if response.status == 200:
                # Получаем ответ
                content_type = response.headers.get('Content-Type', '')
                
                if 'application/json' in content_type:
                    return await response.json()
                else:
                    text = await response.text()
                    try:
                        return json.loads(text)
                    except json.JSONDecodeError:
                        print(f"Ошибка при декодировании JSON-ответа для ID {car_id}")
                        return None
            else:
                print(f"Ошибка при запросе детальной информации об автомобиле {car_id}: {response.status}")
                return None
    
    except Exception as e:
        print(f"Ошибка при получении детальной информации об автомобиле {car_id}: {e}")
        return None

# Обработка и сохранение данных об автомобиле
async def process_car_data(car_data, car_id, model_name):
    if not car_data:
        return False
    
    try:
        # Извлекаем основные данные
        modelo = car_data.get("modelo", model_name)
        version = car_data.get("version", "")
        brand = car_data.get("marca", "KIA")
        
        # Если модель не указана, используем переданное имя модели
        if not modelo:
            modelo = model_name
        
        # Генерируем уникальный car_id для нашей системы
        unique_car_id = f"kia_{modelo.lower().replace(' ', '_')}_{car_id}"
        
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
        
        # Извлекаем цену
        price = 0
        if car_data.get("precio"):
            price_str = car_data["precio"].replace(".", "").replace(",", ".").replace("€", "").strip()
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                pass
        
        # Извлекаем год
        year = None
        if car_data.get("any"):
            try:
                year = int(car_data["any"])
            except (ValueError, TypeError):
                pass
        
        # Формируем данные об автомобиле
        processed_car = {
            "car_id": unique_car_id,
            "idcoche": car_id,  # Сохраняем оригинальный ID
            "brand": brand,
            "model": modelo,
            "version": version,
            "title": f"{brand} {modelo} {version}".strip(),
            "year": year,
            "mileage": _extract_number(car_data.get("kilometros", "0")),
            "fuel_type": car_data.get("combustible", "Unknown"),
            "transmission": car_data.get("transmision", "Unknown"),
            "color_exterior": car_data.get("color_exterior", "Unknown"),
            "color_interior": car_data.get("color_interior", "Unknown"),
            "body_type": car_data.get("carroceria", "Unknown"),
            "power": _extract_number(car_data.get("potencia", "0")),
            "price": price,
            "price_cash": _extract_price(car_data.get("precio_alcontado", "0")),
            "images": images,
            "features": features,
            "dealer": car_data.get("concesionario", "KIA Okasion"),
            "dealer_location": car_data.get("poblacion", "España"),
            "dealer_email": car_data.get("emailconcesionario", ""),
            "dealer_phone": car_data.get("telefono", ""),
            "dealer_address": car_data.get("direccion", ""),
            "matriculation_date": car_data.get("matriculacion", ""),
            "license_plate": car_data.get("matricula", ""),
            "url": f"{BASE_URL}?idcoche={car_id}",
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
        
        # Если это новый автомобиль, добавляем дату первого обнаружения
        existing_car = await cars_collection.find_one({"car_id": unique_car_id})
        if not existing_car:
            processed_car["first_seen"] = datetime.now().isoformat()
        
        # Сохраняем в базу данных
        result = await cars_collection.update_one(
            {"car_id": unique_car_id},
            {"$set": processed_car},
            upsert=True
        )
        
        return True
    
    except Exception as e:
        print(f"Ошибка при обработке данных об автомобиле {car_id}: {e}")
        return False

# Вспомогательные функции для извлечения числовых значений
def _extract_price(price_str):
    if not price_str:
        return 0
        
    try:
        price_clean = str(price_str).replace(".", "").replace(",", ".").replace("€", "").strip()
        return float(price_clean)
    except (ValueError, TypeError):
        return 0

def _extract_number(number_str):
    if not number_str:
        return 0
        
    try:
        import re
        number_match = re.search(r'(\d[\d\.,]*)', str(number_str))
        if number_match:
            number_clean = number_match.group(1).replace(".", "").replace(",", ".")
            return int(float(number_clean))
        return 0
    except (ValueError, TypeError):
        return 0

# Основная функция
async def main():
    print("Запуск обновления детальной информации об автомобилях...")
    
    # Создаем HTTP-сессию
    async with aiohttp.ClientSession() as session:
        # Получаем все модели с их ID
        models = await car_ids_collection.find().to_list(length=100)
        
        total_updated = 0
        total_errors = 0
        
        for model_data in models:
            model_name = model_data["model"]
            car_ids = model_data.get("ids", [])
            
            print(f"Обработка модели {model_name}: найдено {len(car_ids)} ID автомобилей")
            
            model_updated = 0
            model_errors = 0
            
            for car_id in car_ids:
                # Получаем детальную информацию
                car_details = await get_car_details(session, car_id)
                
                if car_details:
                    # Обрабатываем и сохраняем данные
                    success = await process_car_data(car_details, car_id, model_name)
                    
                    if success:
                        model_updated += 1
                        total_updated += 1
                    else:
                        model_errors += 1
                        total_errors += 1
                else:
                    model_errors += 1
                    total_errors += 1
                
                # Делаем паузу между запросами
                await asyncio.sleep(random.uniform(1, 2))
            
            print(f"Модель {model_name}: обновлено {model_updated}, ошибок {model_errors}")
        
        print(f"Обновление завершено. Всего обновлено {total_updated}, ошибок {total_errors}")

if __name__ == "__main__":
    asyncio.run(main())
