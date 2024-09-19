#!/bin/bash

# Функция для генерации случайного пароля
generate_password() {
  openssl rand -base64 12
}

# Получаем внешний IP адрес сервера
get_external_ip() {
  curl -4 -s ifconfig.me
}

echo "Шаг 1: Установка Docker..."
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh ./get-docker.sh
sudo usermod -aG docker ${USER}
sudo chmod 666 /var/run/docker.sock
sudo systemctl restart docker

echo "Docker установлен."

echo "Шаг 2: Авторизация в Docker Hub под пользователем 'isteit'..."
docker login -u isteit

echo "Шаг 3: Загрузка файла docker-compose.yml..."
curl -L -o docker-compose.yml "https://drive.google.com/uc?export=download&id=1M-Y5_wOE68wPV0w7bSdP0Pq-bfSBW1OW"

echo "Шаг 4: Настройка файла .env..."

# Запрашиваем ключи Binance и символы
read -p "Введите ваш BINANCE_API_KEY: " BINANCE_API_KEY
read -p "Введите ваш BINANCE_API_SECRET: " BINANCE_API_SECRET
read -p "Введите список символов (например: 1000FLOKIUSDT,FETUSDT): " SYMBOLS

# Генерируем пароль для PostgreSQL
POSTGRES_PASSWORD=$(generate_password)

# Получаем внешний IP сервера
EXTERNAL_IP=$(get_external_ip)

# Создаем файл .env
cat <<EOF > .env
BINANCE_API_KEY=${BINANCE_API_KEY}
BINANCE_API_SECRET=${BINANCE_API_SECRET}

POSTGRES_USER=postgres
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=tradebox

DB_ASYNC_CONNECTION_STR="postgresql+asyncpg://postgres:${POSTGRES_PASSWORD}@postgres:5432/tradebox"
DB_CONNECTION_STR="postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/tradebox"

SYMBOLS=${SYMBOLS}
PREFECT_API_URL=http://${EXTERNAL_IP}:4200/api
EOF

echo ".env файл создан и заполнен."

echo "Шаг 5: Запуск Docker Compose..."
docker compose up -d

echo "Шаг 6: Накатывание миграции базы данных..."
docker compose run backend alembic upgrade head

echo "Установка завершена."

