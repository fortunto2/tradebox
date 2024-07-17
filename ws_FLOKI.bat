@echo off
rem Запуск скрипта Python через Poetry
poetry run python ws_monitor.py --symbol=FLOKIUSDT

rem Пауза перед закрытием окна командной строки (необязательно)
pause
