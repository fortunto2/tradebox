from datetime import datetime

from pydantic import validator, field_validator
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Field, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession


class BaseTable(SQLModel):
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
    )

    updated_at: datetime = Field(
        default_factory=datetime.utcnow,
        nullable=False,
    )

    @field_validator("updated_at", mode='before')
    def validate_updated_at(cls, v):
        if v is None:
            return v
        return v.replace(tzinfo=None)

    async def save(self, db_session: AsyncSession):
        db_session.add(self)
        await db_session.commit()
        await db_session.refresh(self)
        return self

    async def delete(self, db_session: AsyncSession):
        await db_session.delete(self)
        await db_session.commit()
        return True

    async def update(self, db_session: AsyncSession, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)
        db_session.add(self)
        await db_session.commit()
        await db_session.refresh(self)
        return self

    async def save_if_not_exist(self, db_session: AsyncSession):
        statement = pg_insert(self.__table__).values(**self.dict()).on_conflict_do_nothing()
        await db_session.exec(statement)
        await db_session.commit()
        return self
