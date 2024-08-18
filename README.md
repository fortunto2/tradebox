# tradebox
https://www.tradingview.com/chart/XZ6jyBi4/

https://docs.google.com/spreadsheets/d/1g1U8zsxZvC6TDC3TF3Krb2pm9n2MaENUmvOtpRWRloE/edit?gid=0#gid=0


prefect config set PREFECT_API_URL=http://127.0.0.1:4200/api
prefect config set PREFECT_UI_URL=http://20.243.22.4:4200/api
prefect server start
prefect config set PREFECT_API_DATABASE_CONNECTION_URL="postgresql+asyncpg://postgres:rust_admin@localhost:6432/prefect"
prefect config set PREFECT_API_DATABASE_CONNECTION_URL="sqlite+aiosqlite:///./prefect.db"


1. Приходит вебхук
2. Проверка позиции
3. Создание ордера по маркету
4. Создание сетки ордеров
5. Создание первого лимитного ордера
6. Ожидание ордера


Всегда ордера в позиции Усредняющий(LONG-BUY) усредняют, но не закрывают. 
И мы ставим вместе с ним Тайк-профит(LONG-SELL) он закрывает позицию. 
После позиции закрытия проверяются какие лимитные ордера остались, и закрываю все ордера кроме SHORT SELL(страховку оставить)


Backtesting

https://kernc.github.io/backtesting.py/
https://github.com/Gunthersuper/Binance-Futures-Backtesting/
https://www.youtube.com/watch?v=HWG4gKH2kMY

