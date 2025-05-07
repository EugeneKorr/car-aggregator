import os
import subprocess
import time

print("Запуск полного процесса обновления данных об автомобилях KIA...")

# Шаг 1: Создаем директорию scripts, если она не существует
os.makedirs("scripts", exist_ok=True)

# Шаг 2: Запускаем скрипт сбора ID автомобилей
print("\n--- Запуск сбора ID автомобилей ---\n")
subprocess.run(["python", "scripts/collect_car_ids.py"])

# Пауза между шагами
time.sleep(5)

# Шаг 3: Запускаем скрипт получения детальной информации
print("\n--- Запуск получения детальной информации ---\n")
subprocess.run(["python", "scripts/update_car_details.py"])

print("\n--- Процесс обновления завершен ---\n")
