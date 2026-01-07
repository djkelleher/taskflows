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


def gzip_file(file: Path, suffix: str = ".csv.gz", delete: bool = True):
    gz_file = file.with_suffix(suffix)
    with open(file, "rb") as tf:
        with gzip.open(gz_file, "wb") as gf:
            shutil.copyfileobj(tf, gf)
    logger.info(f"Saved file: {gz_file}")
    if delete:
        file.unlink()


def gzip_files(
    files: List[Path], suffix: str = ".csv.gz", delete: bool = True, n_proc: int = 4
):
    with Pool(n_proc) as p:
        p.map(partial(gzip_file, suffix=suffix, delete=delete), files)


def with_parquet_extension(file: Path) -> Path:
    """Return a file with a Parquet extension."""
    stem = file.stem.split(".")[0]
    return file.with_name(f"{stem}.parquet")


def csv_to_parquet(
    file: Path, save_path_generator: Callable[[Path], Path] = with_parquet_extension
):
    """Convert a CSV file to Parquet."""
    if not file.exists():
        logger.info(f"File not found: {file}. Can not convert.")
        return
    save_path = save_path_generator(file)
    if not save_path.exists():
        logger.info(f"Converting {file} -> {save_path}")
        duckdb.execute(
            f"COPY (SELECT * FROM '{file}') TO '{save_path}' (FORMAT PARQUET);"
        )
    else:
        logger.info(f"Skipping {file} -> {save_path}")


def csvs_to_parquet(
    files: Path | Sequence[Path],
    save_path_generator: Callable[[Path], Path] = with_parquet_extension,
):
    """Convert CSV files to Parquet."""
    # convert csv file to parquet.
    if isinstance(files, Path) and files.is_dir():
        files = list(files.glob("*.csv.gz"))
    logger.info(f"Converting {len(files)} CSV files to Parquet: {files[:10]}")
    if not files:
        return
    if len(files) == 1:
        csv_to_parquet(file=files[0], save_path_generator=save_path_generator)
    else:
        func = partial(csv_to_parquet, save_path_generator=save_path_generator)
        max_workers = max(1, min(len(files), int(os.cpu_count() * 0.4)))
        with ProcessPoolExecutor(max_workers=max_workers) as pool:
            results = pool.map(func, files)
        for result in results:
            logger.info(f"File conversion result: {result}")
    # remove csv files
    for file in files:
        logger.info(f"Removing: {file}")
        os.remove(file)


def pprint_bytes(n_bytes: int) -> str:
    """Convert a number of bytes to a human readable string."""
    n_digits = len(str(n_bytes))
    if n_digits > 12:
        return f"{n_bytes / 10 ** 12:.3f} TB"
    if n_digits > 9:
        return f"{n_bytes / 10 ** 9:.3f} GB"
    if n_digits > 6:
        return f"{n_bytes / 10 ** 6:.3f} MB"
    return f"{n_bytes / 10 ** 3:.3f} KB"
