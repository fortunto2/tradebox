from fastapi import APIRouter
from starlette.responses import JSONResponse, Response
from starlette import status

from core.logger.logging import log_error
from core.exceptions import DatabaseError

router = APIRouter(tags=['healthcheck'], prefix='/healthcheck')


@router.get('/')
async def healthcheck_handler():
    return Response(status_code=status.HTTP_200_OK)


@router.get('/db')
async def db_handler():
    from main import app
    db_engine = app.ping_db_engine
    try:
        async with db_engine.acquire() as conn:
            await conn.execute('SELECT 1;')
    except Exception as e:
        log_error(e)
        raise DatabaseError
    return JSONResponse(
        content={
            'status': 'success'
        }
    )
