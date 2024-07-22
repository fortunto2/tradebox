from fastapi import APIRouter
from starlette.responses import Response

router = APIRouter(tags=['ping'])


@router.get('/ping', response_class=Response)
async def ping():
    return Response(status_code=200)
