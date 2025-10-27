"""
Тесты для проверки кэширования symbol precision
"""
import time
import pytest


def test_symbol_precision_cache_performance():
    """Проверка что кэширование действительно ускоряет работу"""
    from flows.tasks.binance_futures import get_symbol_quantity_and_precisions

    symbol = "BTCUSDT"

    # Первый вызов - может обратиться к БД или API
    start1 = time.perf_counter()
    precision1 = get_symbol_quantity_and_precisions(symbol)
    time1 = time.perf_counter() - start1

    # Второй вызов - из кэша
    start2 = time.perf_counter()
    precision2 = get_symbol_quantity_and_precisions(symbol)
    time2 = time.perf_counter() - start2

    # Третий вызов - тоже из кэша
    start3 = time.perf_counter()
    precision3 = get_symbol_quantity_and_precisions(symbol)
    time3 = time.perf_counter() - start3

    # Результаты должны быть одинаковые
    assert precision1 == precision2 == precision3

    # Второй и третий вызовы должны быть значительно быстрее
    # Кэшированные вызовы обычно в 100+ раз быстрее
    print(f"\n1st call (cold): {time1*1000:.4f}ms")
    print(f"2nd call (cached): {time2*1000:.4f}ms")
    print(f"3rd call (cached): {time3*1000:.4f}ms")
    print(f"Speedup: {time1/time2:.1f}x")

    # Кэш должен работать - второй вызов быстрее
    assert time2 < time1 * 0.5, "Cache should make it at least 2x faster"


def test_multiple_symbols_cached():
    """Проверка кэширования нескольких символов"""
    from flows.tasks.binance_futures import get_symbol_quantity_and_precisions

    symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
    precisions = {}

    # Первый проход - заполняем кэш
    for symbol in symbols:
        precisions[symbol] = get_symbol_quantity_and_precisions(symbol)

    # Второй проход - все из кэша, должно быть быстро
    start = time.perf_counter()
    for symbol in symbols:
        cached = get_symbol_quantity_and_precisions(symbol)
        assert cached == precisions[symbol]
    elapsed = time.perf_counter() - start

    print(f"\n{len(symbols)} symbols from cache: {elapsed*1000:.4f}ms")
    # Все 3 символа из кэша должны быть очень быстро (< 1ms)
    assert elapsed < 0.001, f"Cache access too slow: {elapsed*1000:.2f}ms"


def test_cache_info():
    """Проверка статистики кэша"""
    from flows.tasks.binance_futures import get_symbol_quantity_and_precisions

    # Очистим кэш перед тестом
    get_symbol_quantity_and_precisions.cache_clear()

    symbol = "BTCUSDT"

    # Первый вызов - cache miss
    get_symbol_quantity_and_precisions(symbol)
    info1 = get_symbol_quantity_and_precisions.cache_info()
    print(f"\nAfter 1st call: {info1}")
    assert info1.hits == 0
    assert info1.misses == 1

    # Второй вызов - cache hit
    get_symbol_quantity_and_precisions(symbol)
    info2 = get_symbol_quantity_and_precisions.cache_info()
    print(f"After 2nd call: {info2}")
    assert info2.hits == 1
    assert info2.misses == 1

    # Третий вызов - еще один hit
    get_symbol_quantity_and_precisions(symbol)
    info3 = get_symbol_quantity_and_precisions.cache_info()
    print(f"After 3rd call: {info3}")
    assert info3.hits == 2
    assert info3.misses == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
