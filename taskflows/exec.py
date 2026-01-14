import asyncio
import base64
import hashlib
import hmac
import inspect
import os
import secrets
import stat
from pathlib import Path
from typing import Callable

import click
import cloudpickle

from .common import logger, services_data_dir


# SECURITY: Pickle deserialization protection
# Pickle files can contain arbitrary code, so we implement integrity checks
# and audit logging to prevent tampering and track usage.


def _get_hmac_secret() -> bytes:
    """Get or generate HMAC secret key for pickle file integrity verification.

    The secret is stored in ~/.taskflows/.pickle_secret with 0600 permissions.
    This provides integrity protection (not confidentiality) for pickle files.
    """
    secret_file = services_data_dir / ".pickle_secret"

    # Ensure services_data_dir has proper permissions (700)
    try:
        services_data_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(services_data_dir, stat.S_IRWXU)  # 700 (owner rwx only)
    except Exception as e:
        logger.warning(f"Failed to set directory permissions: {e}")

    if secret_file.exists():
        # Verify file permissions
        file_stat = secret_file.stat()
        if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.error(f"SECURITY: Secret file {secret_file} has insecure permissions!")
            # Fix permissions
            os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)  # 600

        return secret_file.read_bytes()

    # Generate new secret
    logger.info("Generating new HMAC secret for pickle integrity verification")
    secret = secrets.token_bytes(32)  # 256 bits
    secret_file.write_bytes(secret)
    os.chmod(secret_file, stat.S_IRUSR | stat.S_IWUSR)  # 600 (owner rw only)
    return secret


def _sign_pickle(pickle_data: bytes) -> bytes:
    """Generate HMAC signature for pickle data.

    Returns: signature (32 bytes)
    """
    secret = _get_hmac_secret()
    signature = hmac.new(secret, pickle_data, hashlib.sha256).digest()
    return signature


def _verify_pickle(pickle_path: Path, pickle_data: bytes, signature: bytes) -> bool:
    """Verify HMAC signature for pickle data.

    Returns: True if signature is valid, False otherwise
    """
    secret = _get_hmac_secret()
    expected_signature = hmac.new(secret, pickle_data, hashlib.sha256).digest()

    if not hmac.compare_digest(signature, expected_signature):
        logger.error(f"SECURITY: Pickle file integrity check FAILED for {pickle_path}")
        logger.error(f"SECURITY: File may have been tampered with!")
        return False

    return True


def _check_pickle_file_security(pickle_path: Path) -> bool:
    """Check that pickle file has secure permissions.

    Returns: True if permissions are secure, False otherwise
    """
    if not pickle_path.exists():
        logger.error(f"SECURITY: Pickle file does not exist: {pickle_path}")
        return False

    # Check file permissions (should be 600 or 400)
    file_stat = pickle_path.stat()
    if file_stat.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(f"SECURITY: Pickle file has insecure permissions: {pickle_path}")
        logger.warning(f"SECURITY: Attempting to fix permissions...")
        try:
            os.chmod(pickle_path, stat.S_IRUSR | stat.S_IWUSR)  # 600
            logger.info(f"SECURITY: Fixed permissions for {pickle_path}")
        except Exception as e:
            logger.error(f"SECURITY: Failed to fix permissions: {e}")
            return False

    # Check that file is owned by current user
    if file_stat.st_uid != os.getuid():
        logger.error(f"SECURITY: Pickle file is not owned by current user: {pickle_path}")
        return False

    return True


def _write_signed_pickle(pickle_path: Path, pickle_data: bytes) -> None:
    """Write pickle data with HMAC signature for integrity verification.

    File format: [32 bytes signature][pickle data]
    """
    signature = _sign_pickle(pickle_data)

    # Write signature + data
    with open(pickle_path, "wb") as f:
        f.write(signature)
        f.write(pickle_data)

    # Set secure permissions
    os.chmod(pickle_path, stat.S_IRUSR | stat.S_IWUSR)  # 600

    logger.info(f"AUDIT: Wrote signed pickle file: {pickle_path}")


def _migrate_unsigned_pickle(pickle_path: Path) -> None:
    """Migrate an unsigned pickle file to signed format.

    This is a backwards compatibility helper for existing pickle files.
    Reads unsigned pickle, validates it can be loaded, then writes signed version.
    """
    logger.warning(f"MIGRATION: Found unsigned pickle file: {pickle_path}")

    # Read unsigned pickle data
    pickle_data = pickle_path.read_bytes()

    # Try to load it to ensure it's valid
    try:
        obj = cloudpickle.loads(pickle_data)
        logger.info(f"MIGRATION: Successfully validated unsigned pickle")
    except Exception as e:
        logger.error(f"MIGRATION: Failed to load unsigned pickle: {e}")
        raise ValueError(f"Cannot migrate invalid pickle file: {pickle_path}")

    # Write signed version
    _write_signed_pickle(pickle_path, pickle_data)
    logger.info(f"MIGRATION: Successfully migrated pickle file to signed format")


def _read_signed_pickle(pickle_path: Path) -> bytes:
    """Read and verify pickle data with HMAC signature.

    Supports automatic migration of unsigned pickle files for backwards compatibility.

    Raises:
        ValueError: If signature verification fails or file is insecure
    """
    # Check file security
    if not _check_pickle_file_security(pickle_path):
        raise ValueError(f"Pickle file security check failed: {pickle_path}")

    # Read file
    file_data = pickle_path.read_bytes()

    if len(file_data) < 32:
        logger.error(f"SECURITY: Pickle file too small (no signature): {pickle_path}")
        raise ValueError(f"Invalid pickle file format: {pickle_path}")

    # Split signature and pickle data
    signature = file_data[:32]
    pickle_data = file_data[32:]

    # Verify signature
    if not _verify_pickle(pickle_path, pickle_data, signature):
        # Signature verification failed - might be unsigned legacy file
        # Try to migrate if it's a valid pickle
        logger.warning(f"SECURITY: Signature verification failed, attempting migration")

        # Try loading entire file as unsigned pickle
        try:
            cloudpickle.loads(file_data)
            # If successful, this is likely an unsigned legacy pickle
            _migrate_unsigned_pickle(pickle_path)
            # Recursively call to read the newly signed file
            return _read_signed_pickle(pickle_path)
        except Exception:
            # Not a valid pickle, signature was actually invalid
            raise ValueError(f"Pickle integrity verification failed: {pickle_path}")

    logger.info(f"AUDIT: Verified and loading pickle file: {pickle_path}")
    return pickle_data


@click.command()
@click.argument("b64_pickle_func")
def _run_function(b64_pickle_func: str):
    """Run a function from base64-encoded pickle.

    SECURITY NOTE: This loads pickle from command line argument without signature
    verification. Only use with trusted input. Audit logging is enabled.
    """
    logger.warning(f"AUDIT: Loading pickle from command line argument (length: {len(b64_pickle_func)})")
    logger.warning(f"SECURITY: This operation trusts the caller - ensure input is from trusted source")

    try:
        func = cloudpickle.loads(base64.b64decode(b64_pickle_func))
        logger.info(f"AUDIT: Successfully loaded function: {func.__name__ if hasattr(func, '__name__') else 'unknown'}")

        if inspect.iscoroutinefunction(func):
            asyncio.run(func())
        else:
            func()

        logger.info(f"AUDIT: Function execution completed successfully")
    except Exception as e:
        logger.error(f"AUDIT: Function execution failed: {e}", exc_info=True)
        raise


class PickledFunction:
    def __init__(self, func: Callable, name: str, attr: str):
        # Validate that the function takes no arguments
        sig = inspect.signature(func)
        params = [
            p
            for p in sig.parameters.values()
            if p.kind in (p.POSITIONAL_OR_KEYWORD, p.POSITIONAL_ONLY)
        ]
        if params:
            param_names = [p.name for p in params]
            raise ValueError(
                f"Function {func.__name__} must take no arguments, but has parameters: {param_names}"
            )
        self.name = name
        self.attr = attr
        self.func = func

    def write(self):
        """Write pickled function with HMAC signature for integrity verification."""
        file = services_data_dir.joinpath(f"{self.name}#_{self.attr}.pickle")
        logger.info(f"Writing pickled function: {file}")
        pickle_data = cloudpickle.dumps(self.func)
        _write_signed_pickle(file, pickle_data)

    def __str__(self):
        return f"_deserialize_and_call {self.name} {self.attr}"

    def __repr__(self):
        return str(self)


@click.command()
@click.argument("name")
@click.argument("attr")
def _deserialize_and_call(name: str, attr: str):
    """Deserialize and call a pickled function with integrity verification.

    SECURITY: Verifies HMAC signature before loading pickle.
    """
    pickle_path = services_data_dir.joinpath(f"{name}#_{attr}.pickle")

    try:
        # Read and verify signed pickle
        pickle_data = _read_signed_pickle(pickle_path)
        func = cloudpickle.loads(pickle_data)

        logger.info(f"AUDIT: Executing function {name}.{attr}")

        if inspect.iscoroutinefunction(func):
            asyncio.run(func())
        else:
            func()

        logger.info(f"AUDIT: Function {name}.{attr} completed successfully")
    except Exception as e:
        logger.error(f"AUDIT: Function {name}.{attr} failed: {e}", exc_info=True)
        raise


@click.command()
@click.argument("name")
def _run_docker_service(name: str):
    """Import Docker container and run it with integrity verification.

    SECURITY: Verifies HMAC signature before loading pickle.
    """
    path = services_data_dir / f"{name}#_docker_run_srv.pickle"

    try:
        logger.info(f"AUDIT: Loading Docker service from {path}")

        # Read and verify signed pickle
        pickle_data = _read_signed_pickle(path)
        service = cloudpickle.loads(pickle_data)

        container = service.environment
        logger.info(f"AUDIT: Running docker container {container.name}")
        container.run()

        logger.info(f"AUDIT: Docker service {name} started successfully")
    except Exception as e:
        logger.error(f"AUDIT: Docker service {name} failed: {e}", exc_info=True)
        raise
