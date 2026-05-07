import gzip
import os
import shutil
from concurrent.futures import ProcessPoolExecutor
from functools import partial
from multiprocessing import Pool
from pathlib import Path
from typing import Callable, List, Sequence

import duckdb
from taskflows.loggers import get_logger

logger = get_logger("files")


def _normalize_csv_files(files: str | Path | Sequence[str | Path]) -> list[Path]:
    """Normalize a file, directory, or sequence of files to a concrete list."""
    if isinstance(files, (str, Path)):
        path = Path(files)
        if path.is_dir():
            return list(path.glob("*.csv.gz"))
        return [path]
    return [Path(file) for file in files]


def _duckdb_sql_literal(value: Path | str) -> str:
    """Return a safely quoted DuckDB string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def gzip_file(file: Path, suffix: str = ".csv.gz", delete: bool = True) -> None:
    gz_file = file.with_suffix(suffix)
    with open(file, "rb") as tf:
        with gzip.open(gz_file, "wb") as gf:
            shutil.copyfileobj(tf, gf)
    logger.info(f"Saved file: {gz_file}")
    if delete:
        file.unlink()


def gzip_files(
    files: List[Path], suffix: str = ".csv.gz", delete: bool = True, n_proc: int = 4
) -> None:
    with Pool(n_proc) as p:
        p.map(partial(gzip_file, suffix=suffix, delete=delete), files)


def with_parquet_extension(file: Path) -> Path:
    """Return a file path with CSV/compression suffixes replaced by .parquet."""
    suffixes = file.suffixes
    if suffixes[-2:] == [".csv", ".gz"]:
        return file.with_suffix("").with_suffix(".parquet")
    if file.suffix == ".csv":
        return file.with_suffix(".parquet")
    return file.with_suffix(".parquet")


def csv_to_parquet(
    file: Path, save_path_generator: Callable[[Path], Path] = with_parquet_extension
) -> None:
    """Convert a CSV file to Parquet."""
    if not file.exists():
        logger.info(f"File not found: {file}. Can not convert.")
        return
    save_path = save_path_generator(file)
    if not save_path.exists():
        logger.info(f"Converting {file} -> {save_path}")
        duckdb.execute(
            "COPY "
            f"(SELECT * FROM {_duckdb_sql_literal(file)}) "
            f"TO {_duckdb_sql_literal(save_path)} "
            "(FORMAT PARQUET);"
        )
    else:
        logger.info(f"Skipping {file} -> {save_path}")


def csvs_to_parquet(
    files: str | Path | Sequence[str | Path],
    save_path_generator: Callable[[Path], Path] = with_parquet_extension,
) -> None:
    """Convert CSV files to Parquet."""
    files = _normalize_csv_files(files)
    logger.info(f"Converting {len(files)} CSV files to Parquet: {files[:10]}")
    if not files:
        return
    if len(files) == 1:
        csv_to_parquet(file=files[0], save_path_generator=save_path_generator)
    else:
        func = partial(csv_to_parquet, save_path_generator=save_path_generator)
        cpu_count = os.cpu_count() or 1
        max_workers = max(1, min(len(files), int(cpu_count * 0.4)))
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            list(pool.map(func, files))
    # remove csv files
    for file in files:
        if not file.exists():
            logger.info(f"File already removed or missing: {file}")
            continue
        logger.info(f"Removing: {file}")
        os.remove(file)


def pprint_bytes(n_bytes: int) -> str:
    """Convert a number of bytes to a human readable string."""
    if n_bytes < 0:
        raise ValueError("n_bytes must be non-negative")
    if n_bytes < 1024:
        return f"{n_bytes} B"
    size = float(n_bytes)
    for unit in ("KB", "MB", "GB"):
        size /= 1024
        if size < 1024:
            return f"{size:.3f} {unit}"
    return f"{size / 1024:.3f} TB"
