# Анализ: Добавление поддержки OKX биржи

**Дата:** 2025-10-28
**Статус:** Анализ сложности

---

## TL;DR

**Сложность:** Средняя (3-5 дней работы)
**Рекомендация:** Реализовать через абстракцию Exchange Interface

---

## Текущая архитектура

### Binance-специфичный код найден в:

**Критичные файлы (требуют изменений):**
1. `flows/tasks/binance_futures.py` - все API вызовы к Binance
2. `core/models/binance_position.py` - модель позиций
3. `core/models/binance_symbol.py` - модель символов
4. `ws_monitor_async.py` - WebSocket для Binance User Data Stream
5. `main.py` - использует Binance API напрямую

**Файлы с зависимостями:**
- 23 файла упоминают "binance" или "Binance"
- Весь код завязан на Binance API

---

## Два подхода к интеграции

### ❌ Подход 1: Дублирование кода (плохо)

**Что нужно сделать:**
```
flows/tasks/binance_futures.py → flows/tasks/okx_futures.py
core/models/binance_position.py → core/models/okx_position.py
core/models/binance_symbol.py → core/models/okx_symbol.py
ws_monitor_async.py → ws_monitor_okx.py
```

**Проблемы:**
- ❌ Дублирование 2000+ строк кода
- ❌ Поддерживать 2 копии бизнес-логики
- ❌ Баги нужно фиксить в двух местах
- ❌ Добавление 3й биржи = еще одна копия

**Время:** 3-4 дня
**Качество:** Плохое (технический долг)

---

### ✅ Подход 2: Exchange Interface (правильно)

**Идея:** Создать абстракцию, которая работает с любой биржей

**Архитектура:**

```
core/exchanges/
├── base.py                    # Базовый класс ExchangeInterface
├── binance_exchange.py        # Binance реализация
├── okx_exchange.py            # OKX реализация
└── factory.py                 # Фабрика для создания exchange

core/models/
├── position.py                # Универсальная модель Position (вместо BinancePosition)
├── symbol.py                  # Универсальная модель Symbol (вместо BinanceSymbol)
└── ...

flows/tasks/
├── futures_trading.py         # Универсальные task (работает с любой биржей)
└── ...

ws_monitor/
├── base_monitor.py            # Базовый WebSocket монитор
├── binance_monitor.py         # Binance-specific
└── okx_monitor.py             # OKX-specific
```

**Пример интерфейса:**

```python
# core/exchanges/base.py
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Dict, List

class ExchangeInterface(ABC):
    """Базовый интерфейс для всех бирж"""

    @abstractmethod
    def create_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal] = None,
        **kwargs
    ) -> Dict:
        """Создать ордер на бирже"""
        pass

    @abstractmethod
    def cancel_order(self, symbol: str, order_id: str) -> Dict:
        """Отменить ордер"""
        pass

    @abstractmethod
    def get_position(self, symbol: str) -> Dict:
        """Получить позицию"""
        pass

    @abstractmethod
    def get_current_price(self, symbol: str) -> Decimal:
        """Получить текущую цену"""
        pass

    @abstractmethod
    def change_leverage(self, symbol: str, leverage: int) -> Dict:
        """Изменить плечо"""
        pass

    @abstractmethod
    def get_symbol_info(self, symbol: str) -> Dict:
        """Получить информацию о символе (precision и т.д.)"""
        pass

    @abstractmethod
    def normalize_symbol(self, symbol: str) -> str:
        """Нормализовать название символа (BTCUSDT vs BTC-USDT-SWAP)"""
        pass


# core/exchanges/binance_exchange.py
from binance.um_futures import UMFutures
from .base import ExchangeInterface

class BinanceExchange(ExchangeInterface):
    """Binance Futures реализация"""

    def __init__(self, api_key: str, api_secret: str):
        self.client = UMFutures(key=api_key, secret=api_secret)

    def create_order(self, symbol, side, order_type, quantity, price=None, **kwargs):
        # Адаптировать параметры для Binance API
        return self.client.new_order(
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            **kwargs
        )

    def get_position(self, symbol):
        positions = self.client.get_position_risk(symbol=symbol)
        # Нормализовать ответ в универсальный формат
        return self._normalize_position(positions)

    def normalize_symbol(self, symbol):
        # Binance: BTCUSDT
        return symbol.replace("-", "")


# core/exchanges/okx_exchange.py
import okx.Trade as Trade
from .base import ExchangeInterface

class OKXExchange(ExchangeInterface):
    """OKX Futures реализация"""

    def __init__(self, api_key: str, api_secret: str, passphrase: str):
        self.client = Trade.TradeAPI(
            api_key=api_key,
            api_secret_key=api_secret,
            passphrase=passphrase,
            flag="0"  # 0=live, 1=demo
        )

    def create_order(self, symbol, side, order_type, quantity, price=None, **kwargs):
        # Адаптировать параметры для OKX API
        return self.client.place_order(
            instId=symbol,
            tdMode="cross",  # cross margin
            side=side,
            ordType=order_type,
            sz=str(quantity),
            px=str(price) if price else None
        )

    def get_position(self, symbol):
        positions = self.client.get_positions(instId=symbol)
        # Нормализовать ответ в универсальный формат
        return self._normalize_position(positions)

    def normalize_symbol(self, symbol):
        # OKX: BTC-USDT-SWAP
        if "-" not in symbol:
            # BTCUSDT → BTC-USDT-SWAP
            base = symbol[:-4]  # BTC
            quote = symbol[-4:]  # USDT
            return f"{base}-{quote}-SWAP"
        return symbol


# core/exchanges/factory.py
from typing import Literal
from .base import ExchangeInterface
from .binance_exchange import BinanceExchange
from .okx_exchange import OKXExchange

class ExchangeFactory:
    """Фабрика для создания exchange клиентов"""

    _instances = {}  # Singleton для каждой биржи

    @classmethod
    def get_exchange(
        cls,
        exchange_name: Literal["binance", "okx"],
        api_key: str,
        api_secret: str,
        passphrase: str = None
    ) -> ExchangeInterface:
        """Получить exchange client (singleton)"""

        if exchange_name not in cls._instances:
            if exchange_name == "binance":
                cls._instances[exchange_name] = BinanceExchange(
                    api_key=api_key,
                    api_secret=api_secret
                )
            elif exchange_name == "okx":
                if not passphrase:
                    raise ValueError("OKX requires passphrase")
                cls._instances[exchange_name] = OKXExchange(
                    api_key=api_key,
                    api_secret=api_secret,
                    passphrase=passphrase
                )
            else:
                raise ValueError(f"Unknown exchange: {exchange_name}")

        return cls._instances[exchange_name]


# Использование в коде:
from core.exchanges.factory import ExchangeFactory
from config import settings

# В конфиге
# EXCHANGE_NAME = "binance"  # или "okx"
# OKX_PASSPHRASE = "your_passphrase"

exchange = ExchangeFactory.get_exchange(
    exchange_name=settings.EXCHANGE_NAME,
    api_key=settings.API_KEY,
    api_secret=settings.API_SECRET,
    passphrase=settings.OKX_PASSPHRASE if settings.EXCHANGE_NAME == "okx" else None
)

# Теперь код не зависит от конкретной биржи!
order = exchange.create_order(
    symbol="BTCUSDT",  # будет нормализовано внутри
    side="BUY",
    order_type="MARKET",
    quantity=0.001
)
```

---

## План реализации (Подход 2)

### Этап 1: Создание абстракции (8-12 часов)

1. **Создать `ExchangeInterface`** (2ч)
   - Определить все методы из `binance_futures.py`
   - Нормализовать параметры и возвращаемые значения

2. **Обернуть Binance в `BinanceExchange`** (4ч)
   - Реализовать все методы интерфейса
   - Сохранить текущее поведение

3. **Обновить модели БД** (2ч)
   - `BinancePosition` → `Position` с полем `exchange`
   - `BinanceSymbol` → `Symbol` с полем `exchange`
   - Миграции БД

4. **Создать `ExchangeFactory`** (2ч)
   - Singleton для каждой биржи
   - Конфигурация через settings

### Этап 2: Интеграция OKX (6-8 часов)

5. **Установить `python-okx`** (0.5ч)
   ```bash
   uv add python-okx
   ```

6. **Реализовать `OKXExchange`** (4ч)
   - Имплементировать все методы интерфейса
   - Маппинг Binance API → OKX API
   - Обработка различий в форматах

7. **WebSocket для OKX** (3ч)
   - Создать `OKXMonitor` на базе `BaseMonitor`
   - User Data Stream для OKX
   - Обработка событий ордеров/позиций

8. **Тестирование OKX** (1ч)
   - Smoke тесты для OKX
   - Проверка на testnet

### Этап 3: Рефакторинг существующего кода (8-12 часов)

9. **Обновить все flows/tasks** (4ч)
   - Заменить прямые вызовы `client.*` на `exchange.*`
   - Использовать `ExchangeFactory.get_exchange()`

10. **Обновить WebSocket монитор** (3ч)
    - Выбор монитора в зависимости от `EXCHANGE_NAME`
    - Унификация обработки событий

11. **Обновить API endpoints** (2ч)
    - `main.py` работает с любой биржей
    - Webhook payload одинаковый для всех бирж

12. **Обновить тесты** (3ч)
    - Параметризованные тесты для Binance и OKX
    - Mock для обеих бирж

### Этап 4: Документация и деплой (2-4 часа)

13. **Документация** (2ч)
    - Как добавить новую биржу
    - Настройка конфигурации
    - Различия между биржами

14. **Деплой и мониторинг** (2ч)
    - .env для разных бирж
    - Логирование exchange_name
    - Тестирование на production

---

## Ключевые различия Binance vs OKX

### 1. Названия символов
- **Binance:** `BTCUSDT`
- **OKX:** `BTC-USDT-SWAP` (для perpetual futures)

### 2. API параметры

**Create Order:**

| Параметр | Binance | OKX |
|----------|---------|-----|
| Symbol | `symbol="BTCUSDT"` | `instId="BTC-USDT-SWAP"` |
| Quantity | `quantity=0.001` | `sz="0.001"` |
| Price | `price=50000` | `px="50000"` |
| Side | `side="BUY"` | `side="buy"` (lowercase) |
| Type | `type="LIMIT"` | `ordType="limit"` |
| Position Side | `positionSide="LONG"` | `posSide="long"` |

**Get Position:**
- **Binance:** `get_position_risk(symbol="BTCUSDT")`
- **OKX:** `get_positions(instId="BTC-USDT-SWAP")`

### 3. WebSocket

**Binance:**
- User Data Stream: требует `listenKey`
- События: `ORDER_TRADE_UPDATE`, `ACCOUNT_UPDATE`

**OKX:**
- Private channel: требует login
- События: `orders`, `positions`, `account`

### 4. Аутентификация

**Binance:**
```python
client = UMFutures(key=api_key, secret=api_secret)
```

**OKX:**
```python
client = Trade.TradeAPI(
    api_key=api_key,
    api_secret_key=api_secret,
    passphrase=passphrase,  # Дополнительный параметр!
    flag="0"  # 0=live, 1=demo
)
```

---

## Оценка сложности

### Если делать правильно (Exchange Interface):

| Этап | Часы | Сложность |
|------|------|-----------|
| Создание абстракции | 8-12ч | Средняя |
| Интеграция OKX | 6-8ч | Низкая |
| Рефакторинг кода | 8-12ч | Средняя |
| Документация | 2-4ч | Низкая |
| **ИТОГО** | **24-36ч** | **Средняя** |

**3-5 рабочих дней** при полной занятости

### Если дублировать код (плохой подход):

| Этап | Часы | Сложность |
|------|------|-----------|
| Копировать и адаптировать | 20-24ч | Средняя |
| Тестирование | 4-6ч | Средняя |
| **ИТОГО** | **24-30ч** | **Средняя** |

**3-4 дня**, но технический долг высокий

---

## Риски и проблемы

### 1. Различия в API
- ⚠️ Не все функции Binance есть в OKX
- ⚠️ Форматы ответов разные
- ✅ Решение: адаптеры и нормализация

### 2. WebSocket различия
- ⚠️ Разные протоколы аутентификации
- ⚠️ Разные форматы событий
- ✅ Решение: базовый класс `BaseMonitor`

### 3. Precision и лимиты
- ⚠️ Разные минимальные размеры ордеров
- ⚠️ Разные precision для quantity/price
- ✅ Решение: кэшировать symbol info для каждой биржи

### 4. Миграция БД
- ⚠️ Нужно переименовать `BinancePosition` → `Position`
- ⚠️ Добавить поле `exchange` во все таблицы
- ✅ Решение: Alembic миграции

---

## Рекомендация

### ✅ Идти через Exchange Interface (Подход 2)

**Почему:**
1. Масштабируемость - легко добавить 3ю, 4ю биржу
2. Поддерживаемость - бизнес-логика в одном месте
3. Тестируемость - можно mock exchange
4. Качество кода - чистая архитектура

**Профит в будущем:**
- Добавить Bybit - 4-6 часов (только адаптер)
- Добавить Gate.io - 4-6 часов (только адаптер)
- Арбитраж между биржами - уже готовая база!

### План действий:

1. **Сначала рефакторинг** - создать abstraction для Binance
2. **Потом OKX** - добавить как вторую реализацию
3. **Тесты** - параметризованные для всех бирж
4. **Production** - постепенный rollout

**Время:** 3-5 дней полной работы

---

## Быстрая оценка усилий

Если нужно **очень быстро** (1-2 дня):
- ✅ Дублировать код для OKX
- ❌ Но потом придется рефакторить

Если делать **правильно** (3-5 дней):
- ✅ Exchange Interface
- ✅ Легко масштабировать
- ✅ Чистая архитектура

---

## Заключение

**Ответ на вопрос:** Не очень сложно, но требует правильного подхода.

**Рекомендация:** Потратить 3-5 дней, но сделать правильно через Exchange Interface. Это окупится при добавлении следующих бирж.

**Альтернатива:** Если нужно прямо сейчас - дублировать код, но планировать рефакторинг.
