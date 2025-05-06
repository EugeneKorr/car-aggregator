import json
import re
from datetime import datetime
from bs4 import BeautifulSoup
from config import Config
from scrapers.base_scraper import BaseScraper
from utils.logger import logger

class KiaScraper(BaseScraper):
    def __init__(self, db):
        super().__init__(db)
        self.base_url = Config.KIA_BASE_URL
        
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
        
        # Заголовки для имитации браузера
        headers = self.get_headers()
        headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": "https://www.kia.com/es/",
            "Origin": "https://www.kia.com"
        })
        
        # Получаем HTML-страницу
        success, html_content = await self.fetch_with_retry(
            self.base_url,
            method="GET",
            headers=headers
        )
        
        if not success or not html_content:
            logger.error("❌ Не удалось получить данные с сайта KIA Outlet")
            return []
        
        # Обработка результатов
        cars_data = []
        try:
            # Парсим HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Ищем контейнеры с автомобилями на странице
            car_containers = soup.select('.vehicle-card, .car-item, .vehicle-list-item')
            
            if not car_containers:
                # Если не нашли по стандартным классам, пробуем другие селекторы
                car_containers = soup.select('.product-item, .listing-item, .vehicle')
            
            logger.info(f"✅ Найдено {len(car_containers)} контейнеров с автомобилями KIA")
            
            # Если элементы всё равно не найдены, ищем скрипты с данными
            if not car_containers:
                logger.info("⚠️ Контейнеры с автомобилями не найдены, пробуем извлечь данные из скриптов")
                
                # Поиск JSON-данных в скриптах
                script_data = self._extract_script_data(soup)
                if script_data:
                    cars_data = await self._process_script_data(script_data, filters)
                    return cars_data
            
            # Обрабатываем каждый найденный контейнер
            for idx, container in enumerate(car_containers):
                car_data = await self._extract_car_data_from_html(container, idx)
                if car_data:
                    # Применяем фильтры
                    if self._apply_filters(car_data, filters):
                        cars_data.append(car_data)
                        # Сохраняем в базу данных
                        await self.db.save_car(car_data)
            
            logger.info(f"✅ Обработано {len(cars_data)} автомобилей KIA")
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных KIA: {e}")
        
        return cars_data
    
    def _extract_script_data(self, soup):
        """
        Извлекает данные из скриптов на странице
        
        Args:
            soup: BeautifulSoup объект
            
        Returns:
            dict: Данные об автомобилях из скриптов или None
        """
        # Ищем скрипты, которые могут содержать данные
        scripts = soup.find_all('script')
        for script in scripts:
            script_text = script.string
            if not script_text:
                continue
                
            # Ищем JSON-блоки с данными автомобилей
            json_pattern = r'var\s+vehicleData\s*=\s*({.*?});'
            matches = re.search(json_pattern, script_text, re.DOTALL)
            if matches:
                try:
                    return json.loads(matches.group(1))
                except json.JSONDecodeError:
                    continue
                    
            # Альтернативные варианты JSON-блоков
            alt_patterns = [
                r'window\.initialData\s*=\s*({.*?});',
                r'var\s+cars\s*=\s*(\[.*?\]);',
                r'data-vehicles\s*=\s*\'({.*?})\'',
            ]
            
            for pattern in alt_patterns:
                matches = re.search(pattern, script_text, re.DOTALL)
                if matches:
                    try:
                        return json.loads(matches.group(1))
                    except json.JSONDecodeError:
                        continue
        
        return None
    
    async def _process_script_data(self, script_data, filters):
        """
        Обрабатывает данные об автомобилях из скриптов
        
        Args:
            script_data: Данные из скриптов
            filters: Фильтры для автомобилей
            
        Returns:
            list: Список обработанных данных об автомобилях
        """
        cars_data = []
        
        # Обрабатываем разные форматы данных
        if isinstance(script_data, dict):
            if "vehicles" in script_data:
                vehicles = script_data["vehicles"]
            elif "cars" in script_data:
                vehicles = script_data["cars"]
            else:
                vehicles = [script_data]
        elif isinstance(script_data, list):
            vehicles = script_data
        else:
            vehicles = []
        
        for idx, vehicle in enumerate(vehicles):
            car_data = await self.process_car_data(vehicle)
            if car_data and self._apply_filters(car_data, filters):
                cars_data.append(car_data)
                await self.db.save_car(car_data)
        
        return cars_data
    
    async def _extract_car_data_from_html(self, container, idx):
        """
        Извлекает данные об автомобиле из HTML-контейнера
        
        Args:
            container: HTML-элемент с данными об автомобиле
            idx: Индекс автомобиля
            
        Returns:
            dict: Данные об автомобиле
        """
        try:
            # Генерируем ID на основе текста контейнера или индекса
            car_id = f"kia_{idx}_{hash(container.text) % 10000}"
            
            # Извлекаем заголовок
            title_elem = container.select_one('.vehicle-title, .car-title, .model-name, h2, h3')
            title = title_elem.text.strip() if title_elem else "KIA Unknown Model"
            
            # Извлекаем модель
            model = None
            model_elem = container.select_one('.model, .car-model')
            if model_elem:
                model = model_elem.text.strip()
            else:
                # Пытаемся извлечь модель из заголовка
                model_match = re.search(r'KIA\s+([A-Za-z0-9\s]+)', title)
                if model_match:
                    model = model_match.group(1).strip()
                else:
                    model = "Unknown Model"
            
            # Извлекаем цену
            price = 0
            price_elem = container.select_one('.price, .vehicle-price, .car-price')
            if price_elem:
                price_text = price_elem.text.strip()
                # Извлекаем числа из текста
                price_match = re.search(r'(\d[\d\.,]+)', price_text)
                if price_match:
                    price_str = price_match.group(1).replace('.', '').replace(',', '.')
                    try:
                        price = float(price_str)
                    except ValueError:
                        pass
            
            # Извлекаем год
            year = None
            year_elem = container.select_one('.year, .vehicle-year')
            if year_elem:
                year_text = year_elem.text.strip()
                year_match = re.search(r'(\d{4})', year_text)
                if year_match:
                    year = int(year_match.group(1))
            
            # Извлекаем изображение
            images = []
            img_elem = container.select_one('img')
            if img_elem and 'src' in img_elem.attrs:
                image_url = img_elem['src']
                if not image_url.startswith('http'):
                    image_url = f"https://www.kia.com{image_url}"
                images.append(image_url)
            
            # Извлекаем URL детальной страницы
            url = self.base_url
            link_elem = container.select_one('a')
            if link_elem and 'href' in link_elem.attrs:
                url_path = link_elem['href']
                if not url_path.startswith('http'):
                    url = f"https://www.kia.com{url_path}"
                else:
                    url = url_path
            
            # Создаем структуру данных об автомобиле
            car_data = {
                "car_id": car_id,
                "brand": "KIA",
                "model": model,
                "title": title,
                "year": year,
                "mileage": 0,  # Новые автомобили без пробега
                "fuel_type": "Unknown",
                "transmission": "Unknown",
                "color": "Unknown",
                "power": 0,
                "price": price,
                "images": images,
                "features": [],
                "description": title,
                "dealer": "KIA Outlet",
                "dealer_location": "España",
                "url": url,
                "warranty": "7 años",
                "last_updated": datetime.now().isoformat()
            }
            
            return car_data
            
        except Exception as e:
            logger.error(f"❌ Ошибка при извлечении данных из HTML: {e}")
            return None
    
    def _apply_filters(self, car_data, filters):
        """
        Применяет фильтры к данным об автомобиле
        
        Args:
            car_data: Данные об автомобиле
            filters: Фильтры
            
        Returns:
            bool: True если автомобиль соответствует фильтрам
        """
        # Фильтр по цене
        if "min_price" in filters and car_data["price"] < filters["min_price"]:
            return False
        if "max_price" in filters and car_data["price"] > filters["max_price"]:
            return False
        
        # Фильтр по моделям
        if "models" in filters and filters["models"]:
            if car_data["model"] not in filters["models"]:
                return False
        
        # Фильтр по пробегу
        if "min_mileage" in filters and car_data["mileage"] < filters["min_mileage"]:
            return False
        if "max_mileage" in filters and car_data["mileage"] > filters["max_mileage"]:
            return False
        
        return True
    
    async def process_car_data(self, car_data):
        """
        Обработка и нормализация данных об автомобиле KIA
        
        Args:
            car_data: Словарь с сырыми данными об автомобиле
            
        Returns:
            dict: Обработанные данные об автомобиле
        """
        try:
            # Генерируем ID если его нет
            car_id = car_data.get("id", f"kia_{hash(str(car_data)) % 10000}")
            
            # Извлекаем модель
            model = car_data.get("modelDisplayName", car_data.get("model", "Unknown"))
            
            # Извлекаем год
            year = car_data.get("year", None)
            if isinstance(year, str):
                year_match = re.search(r'(\d{4})', year)
                if year_match:
                    year = int(year_match.group(1))
            
            # Обработка цены
            price = car_data.get("price", 0)
            if isinstance(price, str):
                price = price.replace(".", "").replace(",", ".").replace("€", "").strip()
                try:
                    price = float(price)
                except ValueError:
                    price = 0
            
            # Извлечение изображений
            images = []
            if "thumbnailImages" in car_data and car_data["thumbnailImages"]:
                images = [img for img in car_data["thumbnailImages"] if img]
            elif "images" in car_data and car_data["images"]:
                images = [img for img in car_data["images"] if img]
            elif "image" in car_data and car_data["image"]:
                images = [car_data["image"]]
            
            # Формирование URL страницы автомобиля
            car_url = car_data.get("url", self.base_url)
            if not car_url.startswith("http"):
                car_url = f"{self.base_url}?id={car_id}"
            
            # Нормализованные данные об автомобиле
            normalized_car = {
                "car_id": str(car_id),
                "brand": "KIA",
                "model": model,
                "title": f"KIA {model} {year or ''}".strip(),
                "year": year,
                "mileage": car_data.get("mileage", 0),
                "fuel_type": car_data.get("fuelType", "Unknown"),
                "transmission": car_data.get("transmissionType", "Unknown"),
                "color": car_data.get("exteriorColorName", car_data.get("color", "Unknown")),
                "power": car_data.get("power", 0),
                "price": price,
                "images": images,
                "features": car_data.get("features", []),
                "description": car_data.get("description", ""),
                "dealer": "KIA Outlet",
                "dealer_location": car_data.get("dealerCity", "España"),
                "url": car_url,
                "warranty": car_data.get("warranty", "7 años"),
                "last_updated": datetime.now().isoformat()
            }
            
            return normalized_car
            
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке данных автомобиля KIA: {e}")
            return None
    
    async def fetch_car_details(self, car_id):
        """
        Получение детальной информации об автомобиле
        
        Args:
            car_id: ID автомобиля
            
        Returns:
            dict: Полные данные об автомобиле
        """
        # Вместо обращения к API, получаем данные из HTML-страницы
        details_url = f"{self.base_url}?id={car_id}"
        
        success, html_content = await self.fetch_with_retry(details_url)
        
        if not success or not html_content:
            logger.error(f"❌ Не удалось получить детали автомобиля KIA {car_id}")
            return None
        
        try:
            # Парсим HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Пытаемся найти контейнер с детальной информацией
            detail_container = soup.select_one('.vehicle-detail, .car-detail, .product-detail')
            
            if not detail_container:
                # Пробуем извлечь данные из скриптов
                script_data = self._extract_script_data(soup)
                if script_data:
                    vehicle_data = None
                    
                    # Ищем данные конкретного автомобиля в скрипте
                    if isinstance(script_data, dict):
                        if "vehicles" in script_data:
                            for vehicle in script_data["vehicles"]:
                                if str(vehicle.get("id", "")) == str(car_id):
                                    vehicle_data = vehicle
                                    break
                        else:
                            vehicle_data = script_data
                    
                    if vehicle_data:
                        car_details = await self.process_car_data(vehicle_data)
                        if car_details:
                            await self.db.save_car(car_details)
                        return car_details
            else:
                # Если нашли контейнер, извлекаем данные
                car_data = await self._extract_car_data_from_html(detail_container, car_id)
                if car_data:
                    await self.db.save_car(car_data)
                return car_data
        
        except Exception as e:
            logger.error(f"❌ Ошибка при обработке деталей автомобиля KIA: {e}")
        
        return None
