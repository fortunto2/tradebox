@echo off
rem Запуск скрипта Python через Poetry
poetry run python trade/ws_monitor.py

rem Пауза перед закрытием окна командной строки (необязательно)
pause
