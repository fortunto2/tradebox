# План улучшений производительности TradeBox

**Дата:** 2025-10-28
**Принцип:** Парето (20% усилий → 80% результата)

---

## Топ-5 критических улучшений

### 1. **Глобальный Binance Client как Singleton** ⚡

**Проблема:**
- Файл: `flows/tasks/binance_futures.py:28-31`
- Создается глобальный `UMFutures` client при импорте модуля
- Множественные API вызовы `client.time()` при каждом импорте
- Нет переиспользования HTTP connections
- Потенциальные проблемы с rate limits

**Решение:**
```python
# Создать singleton factory pattern для Binance client
class BinanceClientFactory:
    _instance = None
    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            cls._client = UMFutures(
                key=settings.BINANCE_API_KEY,
                secret=settings.BINANCE_API_SECRET
            )
        return cls._client
```

**Профит:**
- ↓ latency на 30-50%
- ↓ rate limit проблемы
- Переиспользование HTTP connections

**Время:** 2-3 часа
**Приоритет:** 2 (после кэширования)

---

### 2. **Кэширование данных о символах (BinanceSymbol)** 🚀

**Проблема:**
- Файлы: `flows/tasks/binance_futures.py:67-101`, `core/views/handle_positions.py:77`
- Каждый раз идет запрос в БД за `quantity_precision` и `price_precision`
- N+1 запросы при обработке множества ордеров
- Данные почти никогда не меняются
- Лишняя нагрузка на DB

**Решение:**
```python
# In-memory LRU cache для precision данных
from functools import lru_cache

@lru_cache(maxsize=128)
def get_symbol_precision_cached(symbol: str) -> tuple[int, int]:
    """Кэшируем precision данные в памяти"""
    return get_symbol_quantity_and_precisions(symbol)
```

**Профит:**
- ↓ DB queries на 70-80%
- ↓ latency на 40%
- Instant impact

**Время:** 1-2 часа
**Приоритет:** 1 (первым делом)

---

### 3. **Connection Pooling для Database** 💾

**Проблема:**
- Файл: `core/clients/db_sync.py:74`
- Каждый раз создается новая сессия через `SessionLocal()`
- Множественные `with SessionLocal() as session:` по всему коду
- Нет переиспользования соединений
- 15+ мест в коде где используется

**Решение:**
```python
# Настроить proper connection pooling в SQLAlchemy engine
sync_engine = create_engine(
    settings.DB_CONNECTION_STR,
    echo=False,
    future=True,
    json_serializer=pydantic_serializer,
    pool_size=10,           # Базовый размер пула
    max_overflow=20,        # Дополнительные соединения при нагрузке
    pool_pre_ping=True,     # Проверка соединения перед использованием
    pool_recycle=3600,      # Пересоздавать соединения каждый час
)
```

**Профит:**
- ↓ DB connection overhead на 60%
- ↑ throughput на 2-3x
- Лучше масштабируется

**Время:** 1 час
**Приоритет:** 3 (легкая настройка)

---

### 4. **Асинхронные DB операции везде** ⚡

**Проблема:**
- `ws_monitor_async.py` - async WebSocket, но вызывает sync DB функции
- `core/views/handle_positions.py:119, handle_orders.py:15-56` - все sync
- Блокирующие операции в async event loop
- Смешивание sync/async паттернов

**Решение:**
```python
# Переписать handle_positions.py на async
async def get_exist_position_async(
    symbol: str,
    webhook_id: int = None,
    position_side: OrderPositionSide = None,
    not_closed=True
) -> BinancePosition:
    async with get_async_session() as session:
        query = select(BinancePosition).options(...)
        result = await session.execute(query)
        return result.scalar_one_or_none()
```

**Файлы для рефакторинга:**
- `core/views/handle_positions.py` - все функции на async
- `core/views/handle_orders.py` - все функции на async
- Обновить вызовы в `ws_monitor_async.py`

**Профит:**
- ↑ WebSocket throughput на 5-10x
- ↓ latency на 70%
- Нет блокировок event loop

**Время:** 5-8 часов
**Приоритет:** 4 (требует рефакторинга)

---

### 5. **Batch Operations для Orders & Positions** 📦

**Проблема:**
- `flows/tasks/orders_processing.py` - создает ордера по одному в цикле
- `flows/order_filled_flow.py:92-103` - grid orders создаются последовательно
- При `order_quan=5` → 5 отдельных запросов к DB + Binance
- Критично для grid trading

**Решение:**
```python
# Batch insert в БД
orders = [Order(...) for _ in range(order_quan)]
session.bulk_save_objects(orders)
session.commit()

# Batch update
session.bulk_update_mappings(Order, [
    {'id': 1, 'status': OrderStatus.FILLED},
    {'id': 2, 'status': OrderStatus.FILLED},
])
```

**Профит:**
- ↓ DB roundtrips на 80%
- ↓ latency для grid на 5-10x
- Меньше транзакций

**Время:** 3-5 часов
**Приоритет:** 5 (требует изменений логики)

---

## Дополнительные быстрые wins (бонус)

### 6. Убрать `print()` и заменить на `logger`
**Места:**
- `flows/tasks/binance_futures.py:30, 90, 109`
- `core/views/handle_orders.py:184, 200`
- И другие (~10 мест)

**Время:** 30 минут

---

### 7. Удалить `time.sleep(0.5)`
**Место:** `flows/tasks/orders_processing.py:116`
**Комментарий в коде:** `#todo: нафига она тут`

**Время:** 5 минут

---

### 8. Вынести TODO из кода
**Найдено TODO:**
- `flows/tasks/binance_futures.py:134` - "надо вынести в базу данные по точности числа quantity"
- `ws_monitor_async_old.py:188` - "придумать чтоб каждый раз позицию из базы не дергал"
- `core/views/handle_positions.py:15` - "почемуто считает ее ассинхронной"

**Время:** 15 минут на документирование

---

## План тестирования

### Smoke тесты (обязательно перед каждым изменением)

```python
# tests/test_smoke.py

def test_binance_client_connection():
    """Проверка подключения к Binance API"""
    from flows.tasks.binance_futures import client
    result = client.time()
    assert 'serverTime' in result

def test_database_connection():
    """Проверка подключения к БД"""
    from core.clients.db_sync import SessionLocal
    with SessionLocal() as session:
        assert session is not None

def test_symbol_precision_cache():
    """Проверка кэша precision данных"""
    from flows.tasks.binance_futures import get_symbol_quantity_and_precisions

    # Первый вызов - из БД
    precision1 = get_symbol_quantity_and_precisions("BTCUSDT")

    # Второй вызов - из кэша
    precision2 = get_symbol_quantity_and_precisions("BTCUSDT")

    assert precision1 == precision2
    assert isinstance(precision1[0], int)  # quantity_precision
    assert isinstance(precision1[1], int)  # price_precision

def test_webhook_payload_validation():
    """Проверка валидации webhook payload"""
    from core.schemas.webhook import WebhookPayload

    payload_data = {
        "name": "test",
        "side": "BUY",
        "positionSide": "LONG",
        "symbol": "BTCUSDT",
        "open": {
            "enabled": True,
            "amountType": "quantity",
            "amount": 0.001,
            "leverage": 5
        },
        "settings": {
            "start": True,
            "deposit": 1000,
            "extramarg": 0.5,
            "tp": 2.5,
            "trail_1": 0.5,
            "trail_2": 0.3,
            "offset_short": 0.2,
            "offset_pluse": 0.1,
            "sl_short": -2.0,
            "grid_long": "0.5|1.0|1.5",
            "mg_long": "1|1.5|2",
            "trail_step": 0.1,
            "order_quan": 3
        }
    }

    payload = WebhookPayload(**payload_data)
    assert payload.symbol == "BTCUSDT"
    assert len(payload.settings.grid_long) == 3

def test_order_creation_dry_run():
    """Проверка создания ордера (без отправки на биржу)"""
    from core.models.orders import Order, OrderType, OrderPositionSide, OrderSide
    from decimal import Decimal

    order = Order(
        position_side=OrderPositionSide.LONG,
        side=OrderSide.BUY,
        type=OrderType.LONG_MARKET,
        symbol="BTCUSDT",
        quantity=Decimal("0.001"),
        order_number=0
    )

    assert order.symbol == "BTCUSDT"
    assert order.quantity == Decimal("0.001")

def test_websocket_import():
    """Проверка импорта WebSocket монитора"""
    from ws_monitor_async import TradeMonitor
    assert TradeMonitor is not None

def test_async_db_session():
    """Проверка async DB сессии"""
    import asyncio
    from core.clients.db_async import get_async_session

    async def check():
        async with get_async_session() as session:
            assert session is not None

    asyncio.run(check())
```

### Запуск тестов:

```bash
# Установить pytest если нет
uv add pytest pytest-asyncio --dev

# Запустить smoke тесты
uv run pytest tests/test_smoke.py -v

# Запустить все тесты
uv run pytest tests/ -v
```

---

## Порядок реализации

### Этап 1: Подготовка (30 минут)
1. ✅ Создать `tests/test_smoke.py` с базовыми тестами
2. ✅ Запустить smoke тесты - убедиться что всё работает
3. ✅ Зафиксировать baseline метрики

### Этап 2: Quick wins (1 час)
1. ✅ Убрать `time.sleep(0.5)` из orders_processing.py
2. ✅ Заменить все `print()` на `logger`
3. ✅ Запустить smoke тесты

### Этап 3: Кэширование символов (1-2 часа)
1. ✅ Добавить `@lru_cache` для `get_symbol_quantity_and_precisions()`
2. ✅ Добавить тест для кэша
3. ✅ Запустить все smoke тесты
4. ✅ Замерить улучшение производительности

### Этап 4: Binance Client Singleton (2-3 часа)
1. ✅ Создать `BinanceClientFactory`
2. ✅ Заменить все обращения к `client` на `BinanceClientFactory.get_client()`
3. ✅ Запустить smoke тесты
4. ✅ Проверить rate limits

### Этап 5: Connection Pooling (1 час)
1. ✅ Обновить `core/clients/db_sync.py` с pool параметрами
2. ✅ Запустить smoke тесты
3. ✅ Проверить количество активных соединений

### Этап 6: Async DB (5-8 часов)
1. ✅ Переписать `handle_positions.py` на async
2. ✅ Переписать `handle_orders.py` на async
3. ✅ Обновить вызовы в `ws_monitor_async.py`
4. ✅ Добавить async тесты
5. ✅ Запустить все тесты

### Этап 7: Batch Operations (3-5 часов)
1. ✅ Реализовать batch insert для orders
2. ✅ Реализовать batch update
3. ✅ Обновить grid creation логику
4. ✅ Запустить тесты

---

## Ожидаемые результаты

| Метрика | До | После | Улучшение |
|---------|-----|-------|-----------|
| DB queries (на 1 webhook) | ~50 | ~10 | **80% ↓** |
| Latency (создание grid) | ~500ms | ~50ms | **90% ↓** |
| WebSocket throughput | 100 msg/s | 500-1000 msg/s | **5-10x ↑** |
| Connection overhead | Высокий | Низкий | **60% ↓** |
| Memory usage | ~200MB | ~150MB | **25% ↓** |

---

## Итого

**Общее время:** 12-19 часов
**Ожидаемый прирост производительности:** 3-5x общий throughput
**Latency reduction:** 50-70%
**Стабильность:** Значительно выше (нет rate limits, нет блокировок)

---

## Примечания

- **Кэш в памяти:** Использовать `functools.lru_cache` для простоты
- **Smoke тесты:** Запускать после каждого изменения
- **Rollback план:** Git branch для каждого этапа
- **Мониторинг:** Добавить логи производительности для отслеживания улучшений
