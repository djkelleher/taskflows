import random
from importlib import reload
from typing import Literal
from uuid import uuid4

import pytest
import sqlalchemy as sa
from taskflows.db import engine


async def create_task_logger(monkeypatch, request, db: Literal["sqlite", "postgres"]):
    if db == "sqlite":
        db_url = "sqlite:///services_test.sqlite"
    elif db == "postgres":
        db_url = request.config.getoption("--pg-url")
    monkeypatch.setenv("DL_SERVICES_DB_URL", db_url)
    from taskflows.tasks import TaskLogger

    return await TaskLogger.create(
        name=str(uuid4()),
        required=False,
        db_record=True,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("db", ["sqlite", "postgres"])
async def test_on_task_start(monkeypatch, request, db):
    task_logger = await create_task_logger(monkeypatch, request, db)
    await task_logger.on_task_start()
    # Get table from module instead of class
    from taskflows.db import task_runs_table

    table = task_runs_table
    query = sa.select(table.c.task_name, table.c.started).where(
        table.c.task_name == task_logger.name
    )
    async with engine.begin() as conn:
        tasks = list(await conn.execute(query))
    assert len(tasks) == 1
    # name and started columns should be not null.
    assert all(v is not None for v in tasks[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("db", ["sqlite", "postgres"])
async def test_on_task_error(monkeypatch, request, db):
    task_logger = await create_task_logger(monkeypatch, request, db)
    error = Exception(str(uuid4()))
    await task_logger.on_task_error(error)
    # Get table from module instead of class
    from taskflows.db import task_errors_table

    table = task_errors_table
    query = sa.select(table).where(table.c.task_name == task_logger.name)
    async with engine.begin() as conn:
        errors = list(await conn.execute(query))
    assert len(errors) == 1
    # no columns should be null.
    assert all(v is not None for v in errors[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("db", ["sqlite", "postgres"])
async def test_on_task_finish(monkeypatch, request, db):
    task_logger = await create_task_logger(monkeypatch, request, db)
    await task_logger.on_task_start()
    await task_logger.on_task_finish(
        success=random.choice([True, False]),
        retries=random.randint(0, 5),
        return_value=str(uuid4()),
    )
    # Get table from module instead of class
    from taskflows.db import task_runs_table

    table = task_runs_table
    query = sa.select(table).where(table.c.task_name == task_logger.name)
    async with engine.begin() as conn:
        tasks = list(await conn.execute(query))
    assert len(tasks) == 1
    # no columns should be null.
    assert all(v is not None for v in tasks[0])
