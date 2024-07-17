@echo off
rem Запуск скрипта Python через Poetry
poetry run python ws_monitor.py --symbol=1000FLOKIUSDT

rem Пауза перед закрытием окна командной строки (необязательно)
pause
