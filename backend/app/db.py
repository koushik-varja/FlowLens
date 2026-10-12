from __future__ import annotations
import os
import json
from datetime import datetime, timezone
from sqlalchemy import create_engine, String, Text, DateTime, Integer
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./flowlens.db")
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    events_json: Mapped[str] = mapped_column(Text)
    quality_json: Mapped[str] = mapped_column(Text)

    def events(self):
        rows = json.loads(self.events_json)
        for r in rows:
            r["timestamp"] = datetime.fromisoformat(r["timestamp"])
        return rows

    def quality(self):
        return json.loads(self.quality_json)


def init_db():
    Base.metadata.create_all(engine)
