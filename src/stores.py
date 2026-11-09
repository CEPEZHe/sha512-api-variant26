"""File-based storage and SQLite/SQLAlchemy implementations of one API."""

import json
import threading
import time
from pathlib import Path

from sqlalchemy import ForeignKey, Integer, String, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

FIELDS = {
    "profile": ("key", "created", "ip", "locale", "platform", "user_agent"),
    "query": (
        "key",
        "created",
        "parameter",
        "profile",
        "description",
        "tags",
        "status",
    ),
    "feedback": (
        "key",
        "created",
        "response",
        "status",
        "exception",
        "query",
        "cache_hit",
    ),
}
EDITABLE = {
    "profile": ("ip", "locale", "platform", "user_agent"),
    "query": ("parameter", "description", "tags", "status"),
}


class MissingRecord(KeyError):
    """A requested record does not exist."""


class StorageError(ValueError):
    """A submitted record is invalid."""


def validated_fields(kind, changes, editing=False):
    """Check allowed fields and convert required foreign keys."""
    allowed = EDITABLE[kind] if editing else FIELDS[kind]
    allowed = set(allowed) - {"key", "created"}
    unknown = set(changes) - allowed
    if unknown:
        raise StorageError("Unknown fields: " + ", ".join(sorted(unknown)))
    result = dict(changes)
    if "profile" in result:
        result["profile"] = int(result["profile"])
    if "query" in result:
        result["query"] = int(result["query"])
    return result


def default_record(kind, values, key):
    """Create one record with fields matching the ER diagram."""
    result = {field: "" for field in FIELDS[kind]}
    result.update(values)
    result["key"] = key
    result["created"] = int(time.time())
    if kind == "feedback":
        result["cache_hit"] = int(result["cache_hit"] or 0)
    return result


def select_records(records, filters):
    """Return records whose filter values match exactly."""
    return [
        row
        for row in records
        if all(str(row.get(name, "")) == str(value) for name, value in filters.items())
    ]


class FileStore:
    """Persist the three ER relations to a human-readable JSON file."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write({kind: [] for kind in FIELDS})

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, data):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporary.replace(self.path)

    def get(self, kind, key):
        with self.lock:
            for record in self._read()[kind]:
                if record["key"] == int(key):
                    return record.copy()
        raise MissingRecord(f"{kind} {key} was not found")

    def scan(self, kind, filters=None):
        filters = filters or {}
        if set(filters) - set(FIELDS[kind]):
            raise StorageError("Invalid filter field")
        with self.lock:
            records = self._read()[kind]
        return select_records(records, filters)

    def add(self, kind, values):
        values = validated_fields(kind, values)
        with self.lock:
            data = self._read()
            self._validate_foreign_key(kind, values, data)
            key = max((r["key"] for r in data[kind]), default=0) + 1
            record = default_record(kind, values, key)
            data[kind].append(record)
            self._write(data)
        return record

    @staticmethod
    def _validate_foreign_key(kind, values, data):
        field = "profile" if kind == "query" else "query"
        if kind == "profile":
            return
        if field not in values:
            raise StorageError(f"{field} is required")
        parent = "profile" if kind == "query" else "query"
        if not any(r["key"] == values[field] for r in data[parent]):
            raise StorageError(f"{parent} {values[field]} was not found")

    def update(self, kind, key, values):
        values = validated_fields(kind, values, editing=True)
        with self.lock:
            data = self._read()
            for record in data[kind]:
                if record["key"] == int(key):
                    record.update(values)
                    self._write(data)
                    return record.copy()
        raise MissingRecord(f"{kind} {key} was not found")

    def close(self):
        """Keep the same lifecycle interface as SQLAlchemyStore."""


class Base(DeclarativeBase):
    """Base for SQLAlchemy models."""


class Profile(Base):
    """A client profile from figure 26."""

    __tablename__ = "profile"
    key: Mapped[int] = mapped_column(Integer, primary_key=True)
    created: Mapped[int] = mapped_column(Integer)
    ip: Mapped[str] = mapped_column(String, default="")
    locale: Mapped[str] = mapped_column(String, default="")
    platform: Mapped[str] = mapped_column(String, default="")
    user_agent: Mapped[str] = mapped_column(String, default="")


class Query(Base):
    """A calculation request from figure 26."""

    __tablename__ = "query"
    key: Mapped[int] = mapped_column(Integer, primary_key=True)
    created: Mapped[int] = mapped_column(Integer)
    parameter: Mapped[str] = mapped_column(String, default="")
    profile: Mapped[int] = mapped_column(ForeignKey("profile.key"))
    description: Mapped[str] = mapped_column(String, default="")
    tags: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="")


class Feedback(Base):
    """A request result from figure 26."""

    __tablename__ = "feedback"
    key: Mapped[int] = mapped_column(Integer, primary_key=True)
    created: Mapped[int] = mapped_column(Integer)
    response: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="")
    exception: Mapped[str] = mapped_column(String, default="")
    query: Mapped[int] = mapped_column(ForeignKey("query.key"))
    cache_hit: Mapped[int] = mapped_column(Integer, default=0)


MODELS = {"profile": Profile, "query": Query, "feedback": Feedback}


class SQLAlchemyStore:
    """SQLite storage via SQLAlchemy ORM, with the same external behavior."""

    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}")
        Base.metadata.create_all(self.engine)

    @staticmethod
    def _dict(kind, entity):
        return {name: getattr(entity, name) for name in FIELDS[kind]}

    def get(self, kind, key):
        with Session(self.engine) as session:
            entity = session.get(MODELS[kind], int(key))
            if entity is None:
                raise MissingRecord(f"{kind} {key} was not found")
            return self._dict(kind, entity)

    def scan(self, kind, filters=None):
        filters = filters or {}
        with Session(self.engine) as session:
            query = select(MODELS[kind])
            if set(filters) - set(FIELDS[kind]):
                raise StorageError("Invalid filter field")
            for name, value in filters.items():
                query = query.where(getattr(MODELS[kind], name) == value)
            return [self._dict(kind, r) for r in session.scalars(query)]

    def add(self, kind, values):
        values = validated_fields(kind, values)
        required = "profile" if kind == "query" else "query"
        if kind != "profile" and required not in values:
            raise StorageError(f"{required} is required")
        if kind == "query":
            self.get("profile", values["profile"])
        if kind == "feedback":
            self.get("query", values["query"])
        record = default_record(kind, values, None)
        record.pop("key")
        with Session(self.engine) as session:
            entity = MODELS[kind](**record)
            session.add(entity)
            session.commit()
            session.refresh(entity)
            return self._dict(kind, entity)

    def update(self, kind, key, values):
        values = validated_fields(kind, values, editing=True)
        with Session(self.engine) as session:
            entity = session.get(MODELS[kind], int(key))
            if entity is None:
                raise MissingRecord(f"{kind} {key} was not found")
            for name, value in values.items():
                setattr(entity, name, value)
            session.commit()
            session.refresh(entity)
            return self._dict(kind, entity)

    def close(self):
        self.engine.dispose()
