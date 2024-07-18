import json
import psycopg2
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, create_engine
from config import get_settings


def pydantic_serializer(value):
    if isinstance(value, BaseModel):
        # Pydantic модели имеют метод .json() для сериализации
        return value.model_dump_json()
    else:
        # Для всех других объектов используем стандартный json.dumps
        # с установкой default=str, чтобы не пропустить объекты несериализуемые json'ом по умолчанию
        return json.dumps(value, default=str)


settings = get_settings()

# Create a synchronous SQLAlchemy engine
sync_engine = create_engine(
    settings.DB_ASYNC_CONNECTION_STR,
    echo=settings.DEBUG,
    future=True,
    json_serializer=pydantic_serializer,
    connect_args={
        'timeout': 15,
    }
)


def get_db_connection():
    return psycopg2.connect(settings.DB_CONNECTION_STR)


def execute_query(query, params=None):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            if cursor.description:
                return cursor.fetchall()
            else:
                conn.commit()
                return None


def execute_query_single(query, params=None):
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(query, params)
            if cursor.description:
                return cursor.fetchone()
            else:
                conn.commit()
                return None


def execute_sqlmodel_query(query_func):
    with Session(sync_engine) as session:
        return query_func(session)


def execute_sqlmodel_query_single(query_func):
    with Session(sync_engine) as session:
        return query_func(session)


def get_sync_session():
    return Session(sync_engine)


# Create a configured "Session" class
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=sync_engine)


# Dependency to get DB session
def get_db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
