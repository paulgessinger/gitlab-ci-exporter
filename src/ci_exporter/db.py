from pathlib import Path
from enum import Enum, auto

import peewee

database = peewee.SqliteDatabase(None)


class Status(Enum):
    created = auto()
    waiting_for_resource = auto()
    preparing = auto()
    pending = auto()
    manual = auto()
    scheduled = auto()
    running = auto()
    success = auto()
    failed = auto()
    canceled = auto()
    skipped = auto()

def prepare_database(dbfile: Path):
    database.init(dbfile)
    database.connect()
    database.create_tables([Job])


class Model(peewee.Model):
    class Meta:
        database = database




class Job(Model):
    id = peewee.IntegerField(primary_key=True, unique=True)
    commit_sha = peewee.CharField()
    created_at = peewee.DateTimeField()
    started_at = peewee.DateTimeField(null=True)
    finished_at = peewee.DateTimeField(null=True, index=True)
    name = peewee.CharField()
    ref = peewee.CharField()
    status = peewee.CharField()
    project = peewee.CharField()
