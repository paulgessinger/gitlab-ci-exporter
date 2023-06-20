from pathlib import Path

import peewee

database = peewee.SqliteDatabase(None)


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
    duration = peewee.FloatField(null=True)
    queued_duration = peewee.FloatField(null=True)
    name = peewee.CharField()
    ref = peewee.CharField()
    status = peewee.CharField()
