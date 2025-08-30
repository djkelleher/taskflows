import os
import re
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from .common import config, logger

schema_name = config.db_schema

db_url = config.db_url
if not db_url:
    db_dir = os.path.expanduser("~/.taskflows")
    db_url = f"sqlite+aiosqlite:///{db_dir}/services.sqlite"
    dialect = "sqlite"
else:
    dialect = re.search(r"^[a-z]+", db_url).group()

if dialect == "postgresql":
    from sqlalchemy.dialects.postgresql import insert
elif dialect == "sqlite":
    # schemas are not supported by SQLite. Will not use any provided schema.
    schema_name = None
    from sqlalchemy.dialects.sqlite import insert

    # TODO swich this replace to re.sub and make sure it works with any driver
    db_dir = Path(db_url.replace("sqlite+aiosqlite:///", "")).parent
    os.makedirs(db_dir, exist_ok=True, mode=0o755)

sa_meta = sa.MetaData(schema=schema_name)

# Define the tables
task_runs_table = sa.Table(
    "task_runs",
    sa_meta,
    sa.Column("task_name", sa.Text, primary_key=True),
    sa.Column(
        "started",
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        primary_key=True,
    ),
    sa.Column("finished", sa.DateTime(timezone=True)),
    sa.Column("retries", sa.Integer, default=0),
    sa.Column("status", sa.Text),
)

task_errors_table = sa.Table(
    "task_errors",
    sa_meta,
    sa.Column("task_name", sa.Text, primary_key=True),
    sa.Column(
        "time",
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        primary_key=True,
    ),
    sa.Column("type", sa.Text),
    sa.Column("message", sa.Text),
)

servers_table = sa.Table(
    "servers",
    sa_meta,
    sa.Column("hostname", sa.Text, primary_key=True),
    sa.Column("public_ipv4", sa.Text, nullable=False),
    sa.Column(
        "last_updated",
        sa.DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    ),
)

# Create async engine
# TODO limit connection pool size.
engine: AsyncEngine = create_async_engine(db_url)


class TasksDB:
    @classmethod
    async def create(cls):
        """
        Initialize the async database connection.

        This will create the database schema and tables if they do not
        exist.

        The database dialect is determined by the value of the DL_SERVICES_DB_URL
        environment variable. If this variable is empty, the default database
        is a SQLite file in the user's home directory.

        The database schema is determined by the value of the DL_SERVICES_DB_SCHEMA
        environment variable. If this variable is empty, the default schema is
        the "public" schema.

        :param self: The AsyncTasksDB instance.
        """
        self = cls()
        self.task_runs_table = task_runs_table
        self.task_errors_table = task_errors_table
        self.servers_table = servers_table
        # Create the database schema if it does not exist
        if schema_name:
            async with engine.begin() as conn:
                # Check if schema exists
                result = await conn.run_sync(
                    lambda sync_conn: sync_conn.dialect.has_schema(
                        sync_conn, schema_name
                    )
                )
                if not result:
                    logger.info("Creating schema '%s'", schema_name)
                    await conn.execute(sa.schema.CreateSchema(schema_name))

        # Create the tables if they do not exist
        async with engine.begin() as conn:
            await conn.run_sync(sa_meta.create_all)
        # Return the initialized instance so callers receive a usable object (fixes NoneType errors)
        return self

    async def upsert(self, table: sa.Table, **values):
        """
        Insert or update a record in the given table.

        If the given record already exists (i.e., it matches the primary key of
        an existing record in the table), then update the existing record with
        the given values.  Otherwise, insert a new record with the given values.

        :param table: A SQLAlchemy :class:`Table` object.
        :param values: A mapping of column names to values to be inserted or
            updated.
        """
        statement = insert(table).values(**values)
        on_conf_set = {c.name: c for c in statement.excluded}
        statement = statement.on_conflict_do_update(
            index_elements=table.primary_key.columns, set_=on_conf_set
        )
        async with engine.begin() as conn:
            await conn.execute(statement)


_tasks_db = None


async def get_tasks_db():
    """
    Get a synchronous TasksDB instance (compatibility wrapper).

    This is a synchronous wrapper that can be used in contexts where
    async/await is not available. Note that this requires the async
    database to have been initialized already.

    :return: A TasksDB instance.
    """
    global _tasks_db
    if _tasks_db is None:
        _tasks_db = await TasksDB.create()
    return _tasks_db
