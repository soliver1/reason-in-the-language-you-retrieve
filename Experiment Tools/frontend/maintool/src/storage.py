from dataclasses import dataclass, field
import asyncio
import sqlite3
from .config import settings

from .connection_manager import ConnectionManager


def dict_factory(cursor, row):
    fields = [column[0] for column in cursor.description]
    return {key: value for key, value in zip(fields, row)}


@dataclass
class Storage:
    client_cnt: int = 0
    connection_manager: ConnectionManager = None
    sse_queues: list[asyncio.Queue] = field(default_factory=list)
    client_caches: dict = field(default_factory=dict)
    _update_counter = 0
    fighter_cache = None

    db = None

    @property
    def next_update_id(self):
        self._update_counter += 1
        return self._update_counter

    @staticmethod
    def get_db():
        db = sqlite3.connect(settings.database_path)
        db.row_factory = dict_factory
        return db

storage = Storage()