import asyncio
import argparse
import os
import sys
import time
import logging
from datetime import datetime

# Настраиваем логирование
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger("kia_updater")

# Проверка наличия директории scripts
if not os.path.exists("scripts"):
    os.makedirs("scripts", exist_ok=True)

# Путь к скриптам
SCRIPTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts")

async def run_selenium_collector():
    """Запуск сбора ID автомобилей с помощью Selenium"""
    try:
        logger.info("🔄 Запуск сбора ID автомобилей с помощью Selenium...")
        
        # Импортируем необходимые библиотеки
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        from webdriver_manager.chrome import ChromeDriverManager
        from dotenv import load_dotenv
        import json
        import random
        
        # Загружаем переменные окружения
        load_dotenv()
        
        # Подключение к MongoDB
        from motor.motor_asyncio import AsyncIOMotorClient
        from pymongo import MongoClient
        
        MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
        client = MongoClient(MONGO_URL)
        db = client["test"]
        car_ids_collection = db["car_ids"]  # Коллекция для хранения ID
        
        # Конфигурация Selenium
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Запуск в фоновом режиме
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Добавляем User-Agent
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15")
        
        logger.info("🔧 Настройка Chrome WebDriver...")
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        
        # JavaScript для мониторинга XHR
        xhr_script = """
            window.xhrData = null;
            
            // Создаем перехватчик XHR
            var originalXHR = window.XMLHttpRequest;
            window.XMLHttpRequest = function() {
                var xhr = new originalXHR();
                
                // Отслеживаем ответ
                xhr.addEventListener('load', function() {
                    if (this.responseURL && this.responseURL.includes('metodos.aspx')) {
                        try {
                            window.xhrData = this.responseText;
                            console.log('XHR Data captured:', window.xhrData.substring(0, 100) + '...');
                        } catch (e) {
                            console.error('Error handling XHR response:', e);
                        }
                    }
                });
                
                return xhr;
            };
        """
        
        driver.execute_script(xhr_script)
        logger.info("✅ WebDriver настроен, добавлен мониторинг XHR")
        
        try:
            # Список моделей KIA
            models = [
                "Ceed", "Ceed Sportswagon", "EV6", "EV9", "Niro", "Niro EV", 
                "Picanto", "ProCeed", "Rio", "Sorento", "Soul Ev", 
                "Sportage", "Stinger", "Stonic", "XCeed"
            ]
            
            all_ids_count = 0
            models_stats = {}
            
            for model_name in models:
                logger.info(f"🚗 Обработка модели: {model_name}")
                
                # Открываем страницу KIA
                driver.get("https://kiaokasion.net/kia/")
                time.sleep(3)  # Ждем загрузку страницы
                
                # Очищаем предыдущие данные XHR
                driver.execute_script("window.xhrData = null;")
                
                try:
                    # Находим и активируем фильтр модели
                    # Эти селекторы нужно адаптировать под реальную структуру сайта!
                    model_selector = WebDriverWait(driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, ".model-selector, .filter-modelo, input[name='modelo']"))
                    )
                    model_selector.clear()
                    model_selector.send_keys(model_name)
                    
                    # Нажимаем кнопку поиска
                    search_button = WebDriverWait(driver, 10).until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, ".search-button, button.buscar, button[type='submit']"))
                    )
                    search_button.click()
                    
                    # Ждем загрузку результатов и XHR-данных
                    time.sleep(5)
                    
                    # Проверяем наличие XHR-данных
                    xhr_data = driver.execute_script("return window.xhrData;")
                    
                    car_ids = []
                    
                    if xhr_data:
                        logger.info(f"✅ Получены XHR-данные для модели {model_name}")
                        try:
                            data = json.loads(xhr_data)
                            if "vehiculos" in data:
                                car_ids = [car["id"] for car in data["vehiculos"] if "id" in car]
                                logger.info(f"✅ Извлечено {len(car_ids)} ID автомобилей из XHR")
                            else:
                                logger.warning(f"⚠️ В XHR-данных нет ключа 'vehiculos' для модели {model_name}")
                        except json.JSONDecodeError as e:
                            logger.error(f"❌ Ошибка при разборе JSON для модели {model_name}: {e}")
                    
                    # Если не удалось получить ID через XHR, пробуем извлечь из HTML
                    if not car_ids:
                        logger.info(f"🔍 Попытка извлечения ID из HTML для модели {model_name}")
                        car_elements = driver.find_elements(By.CSS_SELECTOR, ".car-item, .vehicle-card, [data-id]")
                        
                        for element in car_elements:
                            car_id = element.get_attribute("data-id") or element.get_attribute("id")
                            if car_id:
                                car_ids.append(car_id)
                        
                        logger.info(f"✅ Извлечено {len(car_ids)} ID автомобилей из HTML")
                    
                    # Сохраняем ID в базу данных
                    if car_ids:
                        car_ids_collection.update_one(
                            {"model": model_name},
                            {
                                "$set": {
                                    "ids": car_ids,
                                    "last_updated": datetime.now().isoformat()
                                }
                            },
                            upsert=True
                        )
                        
                        all_ids_count += len(car_ids)
                        models_stats[model_name] = len(car_ids)
                        logger.info(f"✅ Сохранено {len(car_ids)} ID для модели {model_name}")
                    else:
                        logger.warning(f"⚠️ Не удалось получить ID автомобилей для модели {model_name}")
                        models_stats[model_name] = 0
                    
                except Exception as model_error:
                    logger.error(f"❌ Ошибка при обработке модели {model_name}: {model_error}")
                    models_stats[model_name] = 0
                
                # Пауза между запросами к разным моделям
                time.sleep(random.uniform(2, 4))
            
            logger.info(f"✅ Сбор ID завершен. Всего собрано {all_ids_count} ID автомобилей")
            logger.info(f"📊 Статистика по моделям: {json.dumps(models_stats, indent=2)}")
            
            return True
            
        finally:
            # Закрываем драйвер
            driver.quit()
            logger.info("✅ WebDriver закрыт")
            
    except Exception as e:
        logger.error(f"❌ Ошибка при сборе ID автомобилей: {e}")
        return False

async def update_car_details():
    """Обновление детальной информации об автомобилях по их ID"""
    try:
        logger.info("🔄 Запуск обновления детальной информации об автомобилях...")
        
        # Импортируем необходимые библиотеки
        import aiohttp
        import json
        import random
        from dotenv import load_dotenv
        from motor.motor_asyncio import AsyncIOMotorClient
        
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
        
        # Создаем HTTP-сессию
        async with aiohttp.ClientSession() as session:
            # Получаем все модели с их ID
            models = await car_ids_collection.find().to_list(length=100)
            
            if not models:
                logger.warning("⚠️ Не найдено данных о моделях и их ID в базе данных")
                return False
            
            total_updated = 0
            total_errors = 0
            
            for model_data in models:
                model_name = model_data["model"]
                car_ids = model_data.get("ids", [])
                
                logger.info(f"🚗 Обработка модели {model_name}: найдено {len(car_ids)} ID автомобилей")
                
                model_updated = 0
                model_errors = 0
                
                # Ограничиваем количество ID для каждой модели, чтобы не перегружать сервер
                # Для тестирования можно использовать небольшое число, например 5-10
                max_ids_per_model = 20
                
                # Если ID больше лимита, выбираем случайные
                if len(car_ids) > max_ids_per_model:
                    logger.info(f"⚠️ Ограничение количества ID для модели {model_name} до {max_ids_per_model}")
                    car_ids = random.sample(car_ids, max_ids_per_model)
                
                for car_id in car_ids:
                    try:
                        # Формируем данные для запроса
                        data = {
                            "accion": "actualizarFicha",
                            "idcoche": car_id
                        }
                        
                        # Заголовки для запроса
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
                            "Content-Type": "application/x-www-form-urlencoded",
                            "X-Requested-With": "XMLHttpRequest",
                            "Referer": BASE_URL,
                            "Origin": "https://kiaokasion.net",
                            "Accept": "application/json, text/javascript, */*; q=0.01"
                        }
                        
                        # Отправляем POST-запрос
                        async with session.post(API_URL, data=data, headers=headers) as response:
                            if response.status == 200:
                                content_type = response.headers.get('Content-Type', '')
                                
                                car_data = None
                                if 'application/json' in content_type:
                                    car_data = await response.json()
                                else:
                                    try:
                                        text = await response.text()
                                        car_data = json.loads(text)
                                    except json.JSONDecodeError:
                                        logger.error(f"❌ Не удалось декодировать JSON-ответ для ID {car_id}")
                                
                                if car_data:
                                    # Обработка и сохранение данных
                                    success = await process_car_data(car_data, car_id, model_name, cars_collection)
                                    
                                    if success:
                                        model_updated += 1
                                        total_updated += 1
                                        logger.info(f"✅ Обновлен автомобиль: {model_name} (ID: {car_id})")
                                    else:
                                        model_errors += 1
                                        total_errors += 1
                                        logger.error(f"❌ Ошибка при обработке данных автомобиля {car_id}")
                                else:
                                    model_errors += 1
                                    total_errors += 1
                            else:
                                logger.error(f"❌ Ошибка при запросе данных автомобиля {car_id}: код {response.status}")
                                model_errors += 1
                                total_errors += 1
                    
                    except Exception as car_error:
                        logger.error(f"❌ Ошибка при обработке автомобиля {car_id}: {car_error}")
                        model_errors += 1
                        total_errors += 1
                    
                    # Делаем паузу между запросами
                    await asyncio.sleep(random.uniform(1, 3))
                
                logger.info(f"📊 Модель {model_name}: обновлено {model_updated}, ошибок {model_errors}")
            
            logger.info(f"✅ Обновление завершено. Всего обновлено {total_updated}, ошибок {total_errors}")
            
            return True
    
    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении детальной информации: {e}")
        return False

async def process_car_data(car_data, car_id, model_name, cars_collection):
    """Обработка и сохранение данных об автомобиле"""
    try:
        # Извлекаем основные данные
        modelo = car_data.get("modelo", model_name)
        version = car_data.get("version", "")
        brand = car_data.get("marca", "KIA")
        
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
        
        # Извлекаем год выпуска
        year = None
        if car_data.get("any"):
            try:
                year = int(car_data["any"])
            except (ValueError, TypeError):
                pass
        
        # Обработка цены
        price = 0
        if car_data.get("precio"):
            price_str = car_data["precio"].replace(".", "").replace(",", ".").replace("€", "").strip()
            try:
                price = float(price_str)
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
            "mileage": extract_number(car_data.get("kilometros", "0")),
            "fuel_type": car_data.get("combustible", "Unknown"),
            "transmission": car_data.get("transmision", "Unknown"),
            "color_exterior": car_data.get("color_exterior", "Unknown"),
            "color_interior": car_data.get("color_interior", "Unknown"),
            "body_type": car_data.get("carroceria", "Unknown"),
            "power": extract_number(car_data.get("potencia", "0")),
            "price": price,
            "price_cash": extract_price(car_data.get("precio_alcontado", "0")),
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
        logger.error(f"❌ Ошибка при обработке данных автомобиля {car_id}: {e}")
        return False

def extract_price(price_str):
    """Извлечение цены из строки"""
    if not price_str:
        return 0
        
    try:
        price_clean = str(price_str).replace(".", "").replace(",", ".").replace("€", "").strip()
        return float(price_clean)
    except (ValueError, TypeError):
        return 0

def extract_number(number_str):
    """Извлечение числового значения из строки"""
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

async def main():
    """Основная функция запуска обновления данных"""
    parser = argparse.ArgumentParser(description="Обновление данных об автомобилях KIA")
    parser.add_argument("--full", action="store_true", help="Полное обновление (сбор ID и детальной информации)")
    parser.add_argument("--ids-only", action="store_true", help="Только сбор ID автомобилей")
    parser.add_argument("--details-only", action="store_true", help="Только обновление детальной информации")
    
    args = parser.parse_args()
    
    logger.info("🚀 Запуск процесса обновления данных об автомобилях KIA")
    
    # Выбор режима работы
    if args.ids_only:
        # Только сбор ID автомобилей
        await run_selenium_collector()
    elif args.details_only:
        # Только обновление детальной информации
        await update_car_details()
    else:
        # Полный процесс (по умолчанию)
        logger.info("🔄 Запуск полного процесса обновления")
        
        # Шаг 1: Сбор ID автомобилей
        ids_success = await run_selenium_collector()
        
        if ids_success:
            # Шаг 2: Обновление детальной информации
            await update_car_details()
        else:
            logger.error("❌ Пропуск обновления детальной информации из-за ошибок при сборе ID")
    
    logger.info("✅ Процесс обновления завершен")

if __name__ == "__main__":
    asyncio.run(main())
