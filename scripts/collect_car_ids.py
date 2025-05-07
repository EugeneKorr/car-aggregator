import json
import os
import time
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from pymongo import MongoClient
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

# Подключение к MongoDB
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = MongoClient(MONGO_URL)
db = client["test"]
cars_collection = db["cars"]
car_ids_collection = db["car_ids"]  # Новая коллекция для хранения ID

# Конфигурация Selenium
def setup_driver():
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Запуск в фоновом режиме
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Добавляем User-Agent
    chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    return driver

# Получение данных о моделях
def get_models():
    # Список моделей KIA
    models = [
        "Ceed", "Ceed Sportswagon", "EV6", "EV9", "Niro", "Niro EV", 
        "Picanto", "ProCeed", "Rio", "Sorento", "Soul Ev", 
        "Sportage", "Stinger", "Stonic", "XCeed"
    ]
    
    return models

# Обработка данных о модели и получение ID автомобилей
def get_model_car_ids(driver, model_name):
    print(f"Обработка модели: {model_name}")
    
    # Открываем страницу KIA
    driver.get("https://kiaokasion.net/kia/")
    time.sleep(3)  # Ждем загрузку страницы
    
    # Ищем фильтр модели или форму поиска
    try:
        # Этот селектор нужно адаптировать под реальную структуру сайта
        search_input = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".search-input, .model-selector, input[name='modelo']"))
        )
        search_input.clear()
        search_input.send_keys(model_name)
        
        # Нажимаем кнопку поиска
        search_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, ".search-button, button.buscar, button[type='submit']"))
        )
        search_button.click()
        
        # Ждем загрузку результатов
        time.sleep(3)
        
        # Проверяем наличие запросов XHR в консоли
        xhr_data = driver.execute_script("return window.xhrData;")
        
        if xhr_data:
            print(f"Получены XHR-данные для модели {model_name}")
            try:
                data = json.loads(xhr_data)
                cars = data.get("vehiculos", [])
                return [car["id"] for car in cars if "id" in car]
            except json.JSONDecodeError:
                print(f"Ошибка при разборе JSON-данных для модели {model_name}")
        else:
            print(f"Не удалось получить XHR-данные для модели {model_name}")
        
        # Альтернативный способ: поиск ID непосредственно в HTML
        try:
            car_elements = driver.find_elements(By.CSS_SELECTOR, ".car-item, .vehicle-card")
            car_ids = []
            
            for element in car_elements:
                car_id = element.get_attribute("data-id") or element.get_attribute("id")
                if car_id:
                    car_ids.append(car_id)
            
            return car_ids
        except Exception as e:
            print(f"Ошибка при поиске ID автомобилей в HTML: {e}")
            return []
    
    except Exception as e:
        print(f"Ошибка при обработке модели {model_name}: {e}")
        return []

# Добавление JavaScript для отслеживания XHR-запросов
def add_xhr_monitoring(driver):
    script = """
        window.xhrData = null;
        
        // Создаем перехватчик XHR
        var originalXHR = window.XMLHttpRequest;
        window.XMLHttpRequest = function() {
            var xhr = new originalXHR();
            
            // Отслеживаем ответ
            xhr.addEventListener('load', function() {
                if (this.responseURL.includes('metodos.aspx')) {
                    try {
                        window.xhrData = this.responseText;
                        console.log('XHR Data captured:', window.xhrData);
                    } catch (e) {
                        console.error('Error parsing XHR response:', e);
                    }
                }
            });
            
            return xhr;
        };
    """
    
    driver.execute_script(script)

# Сохранение ID автомобилей в базу данных
def save_car_ids(model_name, car_ids):
    if not car_ids:
        print(f"Нет ID автомобилей для сохранения для модели {model_name}")
        return
    
    # Создаем запись в коллекции car_ids
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
    
    print(f"Сохранено {len(car_ids)} ID автомобилей для модели {model_name}")

# Основная функция
def main():
    print("Запуск сбора ID автомобилей...")
    
    driver = setup_driver()
    add_xhr_monitoring(driver)
    
    try:
        # Получаем список моделей
        models = get_models()
        
        # Сохраняем данные для статистики
        all_ids_count = 0
        models_stats = {}
        
        # Обрабатываем каждую модель
        for model in models:
            car_ids = get_model_car_ids(driver, model)
            save_car_ids(model, car_ids)
            
            all_ids_count += len(car_ids)
            models_stats[model] = len(car_ids)
            
            # Делаем паузу между запросами к разным моделям
            time.sleep(random.uniform(3, 5))
        
        print(f"Сбор завершен. Всего собрано {all_ids_count} ID автомобилей.")
        print(f"Статистика по моделям: {json.dumps(models_stats, indent=2)}")
    
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
