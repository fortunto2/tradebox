@echo off
rem Запуск скрипта Python через Poetry
poetry lock
poetry install

rem Пауза перед закрытием окна командной строки (необязательно)
pause
