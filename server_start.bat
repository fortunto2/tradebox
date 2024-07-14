@echo off
rem Запуск скрипта Python через Poetry
@REM poetry run python main.py
poetry run uvicorn main:app --host 45.32.253.11 --port 8000 --log-level info --reload

rem Пауза перед закрытием окна командной строки (необязательно)
pause
