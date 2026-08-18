"""Utility functions for cloud deployment."""

import base64
import io
import re
import zipfile
from collections.abc import Callable
from pathlib import Path

import cloudpickle

from ..common import logger
from ..schedule import Calendar, Periodic, Schedule


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
        r"(?P<hours>\d{1,2}):(?P<minutes>\d{2})(?::\d{2})?"
        r"(?:\s+(?P<timezone>\S+))?",
        schedule_str,
    )
    if match is None:
        raise ValueError(f"Invalid calendar schedule format: {schedule_str}")

    day_of_week_str = match.group("days")
    hours = int(match.group("hours"))
    minutes = int(match.group("minutes"))
    timezone = match.group("timezone")
    if hours > 23 or minutes > 59:
        raise ValueError(f"Invalid calendar schedule time: {hours:02d}:{minutes:02d}")
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

    if timezone:
        logger.warning(
            f"Timezone '{timezone}' specified but EventBridge cron expressions use UTC. "
            f"Consider converting time to UTC or using EventBridge Scheduler instead."
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
) -> bytes:
    """Create a Lambda deployment package (zip file) containing the function and dependencies.

    Args:
        function: The Python function to package
        dependencies: List of pip package names to install (e.g., ["requests", "boto3"])
        include_files: Additional files to include in the package

    Returns:
        Bytes of the zip file ready for Lambda deployment

    Note:
        For production use, dependencies should be installed into a temp directory
        and included in the zip. This POC includes a simplified version.
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
                requirements.append("cloudpickle")
            dependency_package = DependencyManager().build_deployment_package(requirements)
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

    Note:
        In production, you would use `pip install -t python/lib/python3.11/site-packages`
        to install packages in the correct structure for Lambda layers.
    """
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        requirements = "\n".join(dependencies)
        # Lambda layers must have python/lib/python3.x/site-packages structure
        zip_file.writestr("python/requirements.txt", requirements)

    return zip_buffer.getvalue()


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

    # Filter out standard library modules (simplified)
    stdlib_modules = {
        "os",
        "sys",
        "re",
        "json",
        "time",
        "datetime",
        "pathlib",
        "typing",
        "dataclasses",
        "collections",
        "itertools",
        "functools",
        "io",
        "math",
        "random",
    }

    third_party = [m for m in imports if m not in stdlib_modules]

    return list(set(third_party))


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
