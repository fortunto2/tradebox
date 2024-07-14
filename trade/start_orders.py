import asyncio
import json
import sys
from random import randint
from typing import List

from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

sys.path.append('..')
sys.path.append('../core')

from core.db_async import async_engine

from core.schemas.webhook import WebhookPayload
from trade.orders.orders_processing import open_long_position


async def main(payload: WebhookPayload):
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    async with AsyncSession(async_engine) as session:
        # webhook = await save_webhook(payload, session)

        wh_id = randint(1, 1000)

        await open_long_position(payload, 1, session)
        # await get_position_closed_pnl('JOEUSDT')


if __name__ == "__main__":
    import sys
    from core.models.webhook import WebHook

    sys.path.append('..')
    sys.path.append('../core')

    with open('tests/joe.json', 'r') as file:
        data = json.load(file)

    payload = WebhookPayload(**data)

    # from core.db_async import async_session
    asyncio.run(main(payload))
