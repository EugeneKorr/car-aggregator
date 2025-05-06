cat > main.py << 'EOF'
import asyncio
import argparse
from datetime import datetime

from config import Config
from utils.logger import logger
from database.mongo_client import MongoDB
from scrapers.kia_scraper import KiaScraper

class CarAggregator:
    def __init__(self):
        self.db = MongoDB()
        self.scrapers = []
    
    async def initialize(self):
        """Инициализация базы данных и скраперов"""
        # Подключение к базе данных
        connected = await self.db.connect()
        if not connected:
            logger.error("❌ Не удалось подключиться к MongoDB")
            return False
        
        # Инициализация скраперов
        self.scrapers = [
            KiaScraper(self.db)
        ]
        
        return True
    
    async def run_scrapers(self, filters=None):
        """
        Запуск всех скраперов для сбора данных
        
        Args:
            filters: Словарь с фильтрами для применения ко всем скраперам
        """
        if not self.scrapers:
            logger.error("❌ Скраперы не инициализированы")
            return
        
        logger.info(f"🚀 Запуск скраперов с фильтрами: {filters}")
        
        results = {}
        
        # Запускаем скраперы последовательно, чтобы не перегружать систему
        for scraper in self.scrapers:
            scraper_name = scraper.__class__.__name__
            try:
                cars = await scraper.fetch_cars(filters)
                results[scraper_name] = len(cars)
                logger.info(f"✅ Скрапер {scraper_name} собрал {len(cars)} автомобилей")
            except Exception as e:
                logger.error(f"❌ Ошибка в скрапере {scraper_name}: {e}")
                results[scraper_name] = 0
            finally:
                # Закрываем сессию скрапера
                await scraper.close_session()
        
        return results
    
    async def get_cars_by_budget(self, min_price, max_price, limit=100):
        """
        Получение автомобилей в заданном ценовом диапазоне
        
        Args:
            min_price: Минимальная цена
            max_price: Максимальная цена
            limit: Максимальное количество результатов
            
        Returns:
            list: Список автомобилей
        """
        return await self.db.get_cars_by_price_range(min_price, max_price, limit)
    
    async def run_continuous(self, interval=None):
        """
        Непрерывный запуск скраперов с интервалом
        
        Args:
            interval: Интервал между запусками в секундах
        """
        if interval is None:
            interval = Config.CHECK_INTERVAL
        
        logger.info(f"⏱️ Запуск непрерывного режима с интервалом {interval} секунд")
        
        while True:
            try:
                start_time = datetime.now()
                logger.info(f"🔄 Запуск цикла сбора данных: {start_time}")
                
                # Запускаем скраперы без фильтров для сбора всех данных
                results = await self.run_scrapers()
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                
                logger.info(f"✅ Цикл завершен за {duration:.2f} секунд. Результаты: {results}")
                
                # Ожидаем до следующего запуска
                logger.info(f"💤 Ожидание {interval} секунд до следующего запуска")
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле: {e}")
                # Ожидаем немного меньше при ошибке
                await asyncio.sleep(60)
    
    async def shutdown(self):
        """Закрытие всех ресурсов"""
        for scraper in self.scrapers:
            await scraper.close_session()
        
        await self.db.disconnect()
        logger.info("👋 Работа агрегатора завершена")

async def main():
    parser = argparse.ArgumentParser(description="Car Aggregator CLI")
    parser.add_argument("--continuous", action="store_true", help="Запуск в непрерывном режиме")
    parser.add_argument("--interval", type=int, help="Интервал между запусками в секундах")
    parser.add_argument("--min-price", type=int, help="Минимальная цена")
    parser.add_argument("--max-price", type=int, help="Максимальная цена")
    
    args = parser.parse_args()
    
    aggregator = CarAggregator()
    initialized = await aggregator.initialize()
    
    if not initialized:
        logger.error("❌ Не удалось инициализировать агрегатор")
        return
    
    try:
        if args.continuous:
            interval = args.interval if args.interval else Config.CHECK_INTERVAL
            await aggregator.run_continuous(interval)
        elif args.min_price is not None and args.max_price is not None:
            # Режим запроса по бюджету
            cars = await aggregator.get_cars_by_budget(args.min_price, args.max_price)
            logger.info(f"📊 Найдено {len(cars)} автомобилей в диапазоне {args.min_price}-{args.max_price}€")
            for car in cars:
                logger.info(f"🚗 {car['brand']} {car['model']} ({car['year']}) - {car['price']}€")
        else:
            # Разовый запуск всех скраперов
            results = await aggregator.run_scrapers()
            logger.info(f"📊 Результаты сбора данных: {results}")
    except KeyboardInterrupt:
        logger.info("👋 Прерывание пользователем")
    finally:
        await aggregator.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
EOF
