"""Utility functions for cloud deployment."""

import base64
import io
import re
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

import cloudpickle

from ..common import logger
from ..schedule import Calendar, Periodic, Schedule
from .base import CloudFunctionConfig

AWS_LOG_RETENTION_DAYS = {
    0,
    1,
    3,
    5,
    7,
    14,
    30,
    60,
    90,
    120,
    150,
    180,
    365,
    400,
    545,
    731,
    1096,
    1827,
    2192,
    2557,
    2922,
    3288,
    3653,
}


def validate_aws_lambda_config(config: CloudFunctionConfig) -> None:
    """Validate configuration shared by both AWS Lambda backends."""
    validate_lambda_constraints(config.timeout_seconds, config.memory_mb, config.function_name)
    if not config.runtime.startswith("python"):
        raise ValueError("callable packaging currently supports only Python Lambda runtimes")
    if config.handler != "index.handler":
        raise ValueError("callable packaging requires handler='index.handler'")
    if config.secrets:
        raise ValueError(
            "secrets cannot be injected as Lambda environment variables; pass secret ARNs "
            "as environment variables and load values from Secrets Manager at runtime"
        )
    if config.create_alias and not config.enable_versioning:
        raise ValueError("create_alias requires enable_versioning=True")
    if config.create_alias and (
        len(config.create_alias) > 128
        or config.create_alias.isdigit()
        or not re.fullmatch(r"[A-Za-z0-9-_]+", config.create_alias)
    ):
        raise ValueError("create_alias is not a valid Lambda alias name")
    if config.log_retention_days not in AWS_LOG_RETENTION_DAYS:
        raise ValueError("log_retention_days is not supported by CloudWatch Logs")
    if bool(config.security_group_ids) != bool(config.subnet_ids):
        raise ValueError("both security_group_ids and subnet_ids are required for a VPC")
    if config.vpc_config:
        if not isinstance(config.vpc_config, dict):
            raise ValueError("vpc_config must be a mapping")
        required = {"SubnetIds", "SecurityGroupIds"}
        if not required <= set(config.vpc_config):
            raise ValueError("vpc_config must contain SubnetIds and SecurityGroupIds")
        if not all(config.vpc_config[key] for key in required):
            raise ValueError("vpc_config subnet and security-group lists cannot be empty")
    if config.monitoring:
        threshold = config.monitoring.error_rate_threshold
        if threshold is not None and not 0 <= threshold <= 1:
            raise ValueError("error_rate_threshold must be between 0 and 1")
        if (
            config.monitoring.duration_threshold_ms is not None
            and config.monitoring.duration_threshold_ms <= 0
        ):
            raise ValueError("duration_threshold_ms must be positive")
    dlq = config.dead_letter_config
    if dlq and dlq.target_arn:
        match = re.fullmatch(
            r"arn:[^:]+:(?P<service>sqs|sns):[^:]*:[^:]+:(?P<name>.+)",
            dlq.target_arn,
        )
        if match is None:
            raise ValueError("dead-letter target_arn must be an SQS or SNS ARN")
        if match.group("name").endswith(".fifo"):
            raise ValueError("Lambda dead-letter targets must be standard SQS queues or SNS topics")


def schedule_to_eventbridge_expression(schedule: Schedule) -> str:
    """Convert a taskflows Schedule to an AWS EventBridge schedule expression.

    Args:
        schedule: Calendar or Periodic schedule

    Returns:
        EventBridge cron() or rate() expression

    Examples:
        Calendar("Mon-Fri 09:00") -> "cron(0 9 ? * MON-FRI *)"
        Periodic(start_on="boot", period=3600, relative_to="finish") -> "rate(1 hour)"
    """
    if isinstance(schedule, Calendar):
        return _calendar_to_cron(schedule)
    if isinstance(schedule, Periodic):
        return _periodic_to_rate(schedule)
    raise ValueError(f"Unknown schedule type: {type(schedule)}")


def _calendar_to_cron(calendar: Calendar) -> str:
    """Convert Calendar schedule to EventBridge cron expression.

    EventBridge cron format: cron(Minutes Hours Day-of-month Month Day-of-week Year)
    All fields are required. Use ? for "no specific value" in day-of-month or day-of-week.

    Args:
        calendar: Calendar schedule with format like "Mon-Fri 14:00"

    Returns:
        EventBridge cron expression
    """
    schedule_str = calendar.schedule.strip()

    # Parse the schedule string
    # Expected formats:
    # "Mon-Fri 14:00"
    # "Mon,Wed,Fri 16:30:30"
    # "Sun 17:00 America/New_York"
    # "Mon-Sun 14:00"

    # Remove timezone if present (EventBridge cron is UTC-based)
    # In production, you'd want to convert the time to UTC based on the timezone
    match = re.fullmatch(
        r"(?P<days>[A-Za-z]{3}(?:-[A-Za-z]{3})?(?:,[A-Za-z]{3})*)\s+"
        r"(?P<hours>\d{1,2}):(?P<minutes>\d{2})(?::(?P<seconds>\d{2}))?"
        r"(?:\s+(?P<timezone>\S+))?",
        schedule_str,
    )
    if match is None:
        raise ValueError(f"Invalid calendar schedule format: {schedule_str}")

    day_of_week_str = match.group("days")
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    timezone = match.group("timezone")
    seconds = int(match.group("seconds") or 0)
    if hours > 23 or minutes > 59:
        raise ValueError(f"Invalid calendar schedule time: {hours:02d}:{minutes:02d}")
    if seconds > 59:
        raise ValueError(f"Invalid calendar schedule seconds: {seconds:02d}")
    if seconds:
        raise ValueError("EventBridge scheduled rules do not support non-zero seconds")
    valid_days = {"MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"}
    supplied_days = {day.upper() for day in re.split(r"[-,]", day_of_week_str)}
    if not supplied_days <= valid_days:
        invalid_days = ", ".join(sorted(supplied_days - valid_days))
        raise ValueError(f"Invalid day of week in calendar schedule: {invalid_days}")

    # Convert day of week format
    # systemd: Mon-Fri, Mon,Wed,Fri
    # EventBridge: MON-FRI, MON,WED,FRI (uppercase)
    day_of_week = day_of_week_str.upper()

    # Replace full week range
    if day_of_week == "MON-SUN" or day_of_week == "SUN-SAT":
        day_of_week = "*"

    # Build cron expression
    # Format: cron(Minutes Hours Day-of-month Month Day-of-week Year)
    cron_expr = f"cron({minutes:02d} {hours:02d} ? * {day_of_week} *)"

    if timezone and timezone.upper() not in {"UTC", "ETC/UTC"}:
        raise ValueError(
            f"Timezone {timezone!r} cannot be represented by EventBridge scheduled rules; "
            "convert the schedule to UTC or use EventBridge Scheduler"
        )

    return cron_expr


def _periodic_to_rate(periodic: Periodic) -> str:
    """Convert Periodic schedule to EventBridge rate expression.

    EventBridge rate format: rate(value unit)
    Units: minute, minutes, hour, hours, day, days

    Args:
        periodic: Periodic schedule with period in seconds

    Returns:
        EventBridge rate expression

    Note:
        EventBridge rate expressions don't distinguish between "start" and "finish" relative timing.
        This is a limitation of the EventBridge rate syntax compared to systemd timers.
    """
    period_seconds = periodic.period

    # Convert to most appropriate unit
    if period_seconds < 60:
        raise ValueError(
            f"EventBridge rate expressions require at least 1 minute, got {period_seconds}s"
        )
    if period_seconds % 60:
        raise ValueError(
            "EventBridge rate expressions only support whole-minute intervals, "
            f"got {period_seconds}s"
        )

    if period_seconds % 86400 == 0:  # Days
        value = period_seconds // 86400
        unit = "day" if value == 1 else "days"
    elif period_seconds % 3600 == 0:  # Hours
        value = period_seconds // 3600
        unit = "hour" if value == 1 else "hours"
    else:  # Minutes
        value = period_seconds // 60
        unit = "minute" if value == 1 else "minutes"

    if periodic.relative_to == "start":
        logger.warning(
            "Periodic schedule with relative_to='start' cannot be exactly replicated in EventBridge. "
            "EventBridge will trigger at fixed intervals, not relative to task start time."
        )

    return f"rate({value} {unit})"


def create_lambda_deployment_package(
    function: Callable[[], None],
    dependencies: list[str] | None = None,
    include_files: list[Path] | None = None,
    *,
    runtime: str | None = None,
    architecture: str = "x86_64",
    use_docker: bool = False,
) -> bytes:
    """Create a Lambda deployment package (zip file) containing the function and dependencies.

    Args:
        function: The Python function to package
        dependencies: List of pip package names to install (e.g., ["requests", "boto3"])
        include_files: Additional files to include in the package

    Returns:
        Bytes of the zip file ready for Lambda deployment

    Dependencies are installed at the archive root, as required by Lambda.
    Docker builds should be used for packages with native extensions.
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        # Serialize the function using cloudpickle
        pickled_func = cloudpickle.dumps(function)

        # Create handler that deserializes and calls the function
        handler_code = f'''
import base64
import cloudpickle

# Pickled function (base64-encoded)
PICKLED_FUNCTION = {base64.b64encode(pickled_func).decode("utf-8")!r}

def handler(event, context):
    """Lambda handler that deserializes and executes the pickled function."""
    func = cloudpickle.loads(base64.b64decode(PICKLED_FUNCTION))
    result = func()

    return {{
        'statusCode': 200,
        'body': 'Function executed successfully',
        'result': str(result) if result is not None else None
    }}
'''

        # Add handler to zip
        zip_file.writestr("index.py", handler_code)

        # Bundle requested dependencies at the archive root; Lambda does not
        # install a requirements.txt file when a function is uploaded.
        if dependencies:
            from .dependencies import DependencyManager

            requirements = list(dependencies)
            if not any(
                re.match(r"^cloudpickle(?:\W|$)", item, re.IGNORECASE) for item in requirements
            ):
                requirements.append(f"cloudpickle=={cloudpickle.__version__}")
            python_version = (
                runtime or f"python{sys.version_info.major}.{sys.version_info.minor}"
            ).removeprefix("python")
            dependency_package = DependencyManager(
                python_version=python_version,
                architecture=architecture,
            ).build_deployment_package(requirements, use_docker=use_docker)
            with zipfile.ZipFile(io.BytesIO(dependency_package)) as dependency_zip:
                for member in dependency_zip.infolist():
                    if not member.is_dir():
                        zip_file.writestr(member, dependency_zip.read(member.filename))
        else:
            # cloudpickle is always needed by index.py. Copy the installed,
            # pure-Python package without invoking a package manager.
            package_dir = Path(cloudpickle.__file__).parent
            for package_file in package_dir.rglob("*"):
                if package_file.is_file() and "__pycache__" not in package_file.parts:
                    archive_path = Path(package_dir.name) / package_file.relative_to(package_dir)
                    zip_file.write(package_file, archive_path.as_posix())

        # Add any additional files
        if include_files:
            for file_path in include_files:
                if file_path.exists():
                    zip_file.write(file_path, arcname=file_path.name)

    return zip_buffer.getvalue()


def create_lambda_layer_package(dependencies: list[str]) -> bytes:
    """Create a Lambda layer containing Python dependencies.

    This is useful for sharing dependencies across multiple Lambda functions.

    Args:
        dependencies: List of pip package names

    Returns:
        Bytes of the layer zip file

    This convenience function builds locally for the current interpreter.
    Provider deployments use :class:`LayerConfig` and default to Docker builds
    that match the configured runtime and architecture.
    """
    from .dependencies import DependencyManager

    return DependencyManager().create_layer_package(dependencies)


def validate_lambda_package(package: bytes) -> tuple[int, int]:
    """Validate Lambda's compressed and extracted zip size limits.

    Returns the compressed and extracted sizes in bytes. Packages above the
    direct-upload limit can still be deployed through S3.
    """
    compressed_size = len(package)
    try:
        with zipfile.ZipFile(io.BytesIO(package)) as archive:
            extracted_size = sum(member.file_size for member in archive.infolist())
    except zipfile.BadZipFile as exc:
        raise ValueError("deployment package is not a valid zip archive") from exc
    if extracted_size > 250 * 1024 * 1024:
        raise ValueError(
            "Lambda deployment package exceeds the 250 MB extracted-size limit "
            f"({extracted_size / 1024 / 1024:.2f} MB)"
        )
    return compressed_size, extracted_size


def extract_dependencies_from_function(function: Callable) -> list[str]:
    """Attempt to extract import dependencies from a function's source code.

    Args:
        function: Python function to analyze

    Returns:
        List of potential package dependencies

    Note:
        This is a best-effort extraction and may not be complete.
        Users should explicitly specify dependencies when possible.
    """
    import inspect

    try:
        source = inspect.getsource(function)
    except (OSError, TypeError):
        logger.warning(f"Could not extract source for function {function.__name__}")
        return []

    # Simple regex to find import statements
    import_pattern = r"^\s*(?:import|from)\s+([a-zA-Z0-9_]+)"
    imports = re.findall(import_pattern, source, re.MULTILINE)

    third_party = set(imports) - sys.stdlib_module_names
    return sorted(third_party)


def validate_lambda_constraints(
    timeout: int,
    memory_mb: int,
    function_name: str,
) -> None:
    """Validate that configuration meets Lambda constraints.

    Args:
        timeout: Timeout in seconds
        memory_mb: Memory in megabytes
        function_name: Function name for validation

    Raises:
        ValueError: If constraints are violated
    """
    # Lambda limits (as of 2024)
    if timeout < 1 or timeout > 900:
        raise ValueError(f"Lambda timeout must be between 1 and 900 seconds, got {timeout}")

    if memory_mb < 128 or memory_mb > 10240:
        raise ValueError(f"Lambda memory must be between 128 and 10240 MB, got {memory_mb}")

    # Memory must be in 1 MB increments (Lambda requirement)
    if memory_mb % 1 != 0:
        raise ValueError(f"Lambda memory must be in whole MB increments, got {memory_mb}")

    # Function name validation
    if not re.match(r"^[a-zA-Z0-9-_]{1,64}$", function_name):
        raise ValueError(
            f"Lambda function name must be 1-64 characters and contain only "
            f"alphanumeric characters, hyphens, and underscores. Got: {function_name}"
        )
