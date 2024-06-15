from pprint import pprint
import sys

sys.path.append('..')
sys.path.append('.')

import pytest
import requests
import json

from core.schema import WebhookPayload


def test_webhook():
    # Загрузка данных из файла example.json
    with open('tests/example2.json', 'r') as file:
        data = json.load(file)

    payload = WebhookPayload(**data)
    pprint(payload.model_dump())

    # Отправка данных на вебхук эндпоинт
    url = "http://127.0.0.1:8000/webhook"  # URL вашего вебхука
    headers = {"Content-Type": "application/json"}
    response = requests.post(url, json=data, headers=headers)
    print(response.json())

    # Проверка статуса ответа
    assert response.status_code == 200, f"Expected status code 200 but got {response.status_code}"

    # Дополнительные проверки ответа при необходимости
    response_data = response.json()
    assert response_data["status"] == "success", f"Expected status 'success' but got {response_data['status']}"
