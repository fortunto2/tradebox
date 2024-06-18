import logging

from main import app
from fastapi import FastAPI, Request, HTTPException


@app.post("/webhook/test")
async def receive_webhook(request: Request):
    print(request.__dict__)

    headers = request.headers
    qparams = request.query_params
    pparams = request.path_params

    if 'text/plain' in request.headers['content-type']:
        print("text/plain")
        body = await request.body()
        body = body.decode('utf-8')
        logging.info(f"Received webhook text payload: {body}")

        return {"status": "success"}

    elif 'application/json' in request.headers['content-type']:
        print("application/json")
        payload = await request.json()
        logging.info(f"Received webhook JSON payload: {payload}")

    else:
        raise HTTPException(status_code=400, detail="Unsupported content type")

    return payload
