from fastapi import FastAPI, Request

from tg_client import TelegramClient

app = FastAPI()


@app.post("/webhook")
async def receive_webhook(request: Request):
    result = await request.json()
    print(result)

    tg = TelegramClient()
    tg.send_message(message=result)

    return result
