import json
import time
import asyncio
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
from config import Config
from scrapers.base_scraper import BaseScraper
from utils.logger import logger

class KiaScraper(BaseScraper):
    def __init__(self, db):
        super().__init__(db)
        self.base_url = "https://kiaokasion.net/kia/"
        self.api_url = "https://kiaokasion.net/kia/async/metodos.aspx"
        self.driver = None
        
    async def initialize_driver(self):
        """Инициализация драйвера Selenium"""
        try:
            # Запускаем инициализацию в отдельном потоке, т.к. Selenium не асинхронный
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, self._setup_driver)
        except Exception as e:
            logger.error(f"❌ Ошибка при инициализации Selenium: {e}")
            return False
    
    def _setup_driver(self):
        """Настройка драйвера Chrome"""
        try:
            chrome_options = Options()
            chrome_options.add_argument("--headless")  # Запуск в фоновом режиме
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            
            # Добавляем User-Agent
            chrome_options.add_argument(f"user-agent={self.user_agents[0]}")
            
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
            
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка при настройке драйвера Chrome: {e}")
            return False
    
    async def close_driver(self):
        """Закрытие драйвера Selenium"""
        if self.driver:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, lambda: self.driver.quit())
                logger.debug("✅ Драйвер Selenium закрыт")
            except Exception as e:
                logger.error(f"❌ Ошибка при закрытии драйвера Selenium: {e}")
    
    async def close_session(self):
        """Закрытие всех ресурсов"""
        await self.close_driver()
        await super().close_session()
    
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
        
        # Инициализируем драйвер Selenium
        initialized = await self.initialize_driver()
        if not initialized:
            logger.error("❌ Не удалось инициализировать драйвер Selenium")
            return []
        
        # Загружаем главную страницу KIA
        cars_data = []
        try:
            # Запускаем загрузку страницы в отдельном потоке
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.driver.get(self.base_url))
            
            # Ожидаем загрузки страницы
            await loop.run_in_executor(None, lambda: WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".modelo, .car-title, h2"))
            ))
            
            # Получаем данные о моделях
            model_elements = await loop.run_in_executor(None, lambda: self.driver.find_elements(By.CSS_SELECTOR, ".modelo, .car-item, .car-title"))
            
            logger.info(f"✅ Найдено {len(model_elements)} элементов с моделями KIA")
            
            # Ищем XHR-запросы через анализ Network вкладки
            xhr_data = await self._capture_xhr_data()
            
            if xhr_data:
                # Если удалось перехватить XHR-данные, обрабатываем их
                logger.info("✅ Получены XHR-данные о моделях")
                cars_data = await self._process_xhr_data(xhr_data, filters)
            else:
                # Если не удалось получить XHR-данные, парсим HTML
                logger.info("⚠️ XHR-данные не получены, парсим HTML")
                cars_data = await self._process_html_data(model_elements, filters)
            
            logger.info(f"✅ Обработано {len(cars_data)} автомобилей KIA")
            
        except Exception as e:
            logger.error(f"❌ Ошибка при получении данных KIA: {e}")
        finally:
            # Закрываем драйвер
            await self.close_driver()
        
        return cars_data
    
    async def _capture_xhr_data(self):
        """
        Перехват XHR-данных со страницы
        
        Returns:
            dict: Данные XHR-запроса или None
        """
        try:
            # Выполняем JavaScript для перехвата XHR
            loop = asyncio.get_event_loop()
            
            # Добавляем JavaScript-код для мониторинга XHR-запросов
            await loop.run_in_executor(None, lambda: self.driver.execute_script("""
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
            """))
            
            # Кликаем на фильтр моделей, чтобы вызвать XHR-запрос
            try:
                model_filter = await loop.run_in_executor(None, lambda: WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, ".modelo-filter, .filter-button, button.search"))
                ))
                await loop.run_in_executor(None, lambda: model_filter.click())
                
                # Ожидаем завершения XHR-запроса
                await asyncio.sleep(3)
                
                # Получаем перехваченные данные
                xhr_response = await loop.run_in_executor(None, lambda: self.driver.execute_script("return window.xhrData;"))
                
                if xhr_response:
                    logger.debug(f"✅ Получен ответ XHR: {xhr_response[:200]}...")
                    try:
                        return json.loads(xhr_response)
                    except json.JSONDecodeError:
                        logger.error("❌ Не удалось декодировать JSON из XHR-ответа")
                        return None
            except Exception as e:
                logger.error(f"❌ Ошибка при клике на фильтр моделей: {e}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при перехвате XHR-данных: {e}")
        
        return None
    
    async def _process_xhr_data(self, xhr_data, filters):
        """
        Обработка данных из XHR-ответа
        
        Args:
            xhr_data: Данные XHR-ответа
            filters: Фильтры для обработки данных
            
        Returns:
            list: Обработанные данные автомобилей
        """
        cars_data = []
        
        try:
            # Обрабатываем JSON-данные из XHR
            if "modelos" in xhr_data:
                models = xhr_data["modelos"]
                
                for model in models:
                    model_name = model.get("nombre", "Unknown")
                    model_price = self._extract_price(model.get("precio", "0"))
                    model_count = int(model.get("disponibles", "0"))
                    
                    logger.info(f"🚗 Модель: {model_name}, Цена от: {model_price}€, Доступно: {model_count}")
                    
                    # Применяем фильтры
                    if "model" in filters and filters["model"] and model_name.lower() != filters["model"].lower():
                        continue
                    
                    if "min_price" in filters and model_price < filters["min_price"]:
                        continue
                    
                    if "max_price" in filters and model_price > filters["max_price"]:
                        continue
                    
                    # Создаем запись для каждого автомобиля данной модели
                    for i in range(model_count):
                        car_id = f"kia_{model_name.lower().replace(' ', '_')}_{i}"
                        
                        car_data = {
                            "car_id": car_id,
                            "brand": "KIA",
                            "model": model_name,
                            "title": f"KIA {model_name}",
                            "price": model_price,
                            "dealer": "KIA Okasion",
                            "dealer_location": "España",
                            "url": f"{self.base_url}?modelo={model_name}",
                            "last_updated": datetime.now().isoformat()
                        }
                        
                        cars_data.append(car_data)
                        
                        # Сохраняем в базу данных
                        await self.db.save_car(car_data)
                
                return cars_data
            
            else:
                logger.warning("⚠️ В XHR-данных отсутствует ключ 'modelos'")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке XHR-данных: {e}")
        
        return cars_data
    
    async def _process_html_data(self, model_elements, filters):
        """
        Обработка данных из HTML-элементов
        
        Args:
            model_elements: Список HTML-элементов с моделями
            filters: Фильтры для обработки данных
            
        Returns:
            list: Обработанные данные автомобилей
        """
        cars_data = []
        
        try:
            loop = asyncio.get_event_loop()
            
            for idx, model_elem in enumerate(model_elements):
                # Получаем текст элемента
                model_text = await loop.run_in_executor(None, lambda: model_elem.text.strip())
                
                # Извлекаем название модели и цену
                model_name = "Unknown"
                model_price = 0
                
                # Ищем название модели
                model_match = re.search(r"(?:KIA\s+)?([A-Za-z0-9\s]+)", model_text)
                if model_match:
                    model_name = model_match.group(1).strip()
                
                # Ищем цену
                price_match = re.search(r"(\d[\d\.,]+)(?:\s*€)?", model_text)
                if price_match:
                    model_price = self._extract_price(price_match.group(1))
                
                logger.debug(f"🚗 Найдена модель из HTML: {model_name}, Цена: {model_price}€")
                
                # Применяем фильтры
                if "model" in filters and filters["model"] and model_name.lower() != filters["model"].lower():
                    continue
                
                if "min_price" in filters and model_price < filters["min_price"]:
                    continue
                
                if "max_price" in filters and model_price > filters["max_price"]:
                    continue
                
                # Создаем запись автомобиля
                car_id = f"kia_{model_name.lower().replace(' ', '_')}_{idx}"
                
                car_data = {
                    "car_id": car_id,
                    "brand": "KIA",
                    "model": model_name,
                    "title": f"KIA {model_name}",
                    "price": model_price,
                    "dealer": "KIA Okasion",
                    "dealer_location": "España",
                    "url": f"{self.base_url}?modelo={model_name}",
                    "last_updated": datetime.now().isoformat()
                }
                
                cars_data.append(car_data)
                
                # Сохраняем в базу данных
                await self.db.save_car(car_data)
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке HTML-данных: {e}")
        
        return cars_data
    
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
    
    async def fetch_car_details(self, car_id):
        """
        Получение детальной информации об автомобиле по ID
        
        Args:
            car_id: ID автомобиля
            
        Returns:
            dict: Полные данные об автомобиле
        """
        # Проверяем наличие автомобиля в базе данных
        car = await self.db.cars_collection.find_one({"car_id": car_id})
        
        if car:
            # Если автомобиль уже есть в базе, удаляем _id для JSON-сериализации
            if "_id" in car:
                car["_id"] = str(car["_id"])
            return car
        
        # Если автомобиля нет в базе, пробуем получить с сайта
        model_name = None
        
        # Извлекаем название модели из ID
        model_match = re.search(r"kia_([a-z_]+)_\d+", car_id)
        if model_match:
            model_name = model_match.group(1).replace("_", " ").title()
        
        if not model_name:
            logger.error(f"❌ Не удалось определить модель из ID: {car_id}")
            return None
        
        # Ищем автомобили данной модели
        cars = await self.fetch_cars({"model": model_name})
        
        # Ищем конкретный автомобиль по ID
        for car in cars:
            if car["car_id"] == car_id:
                return car
        
        return None
