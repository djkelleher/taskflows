#!/usr/bin/env python3
"""
Test script to demonstrate the improved structlog configuration for Loki.
"""

import random
import time

from quicklogs import (
    clear_request_context,
    configure_loki_logging,
    generate_request_id,
    get_struct_logger,
    set_request_context,
)


def test_basic_logging():
    """Test basic logging functionality."""
    logger = get_struct_logger("test.basic")

    logger.info("test_started", test_name="basic_logging")
    logger.debug("debug_message", details="This is a debug message")
    logger.warning("warning_example", threshold_exceeded=True, value=150, threshold=100)
    logger.error("error_example", error_code="ERR_001", module="database")


def test_exception_logging():
    """Test exception logging with traceback."""
    logger = get_struct_logger("test.exceptions")

    try:
        # Simulate an error
        result = 1 / 0
    except ZeroDivisionError:
        logger.error("division_by_zero", operation="test_calculation", exc_info=True)


def test_request_context():
    """Test request context propagation."""
    logger = get_struct_logger("test.requests")

    # Simulate handling multiple requests
    for i in range(3):
        request_id = generate_request_id()
        trace_id = f"trace-{request_id[:8]}"

        set_request_context(
            request_id=request_id,
            trace_id=trace_id,
            user_id=f"user_{i}",
            endpoint="/api/test",
        )

        logger.info("request_received", method="GET", path="/api/test")

        # Simulate some processing
        time.sleep(0.1)
        processing_time = random.uniform(10, 100)

        logger.info(
            "request_processed", status_code=200, response_time_ms=processing_time
        )

        clear_request_context()


def test_structured_data():
    """Test logging with complex structured data."""
    logger = get_struct_logger("test.structured")

    # Log with nested data
    logger.info(
        "complex_event",
        user={"id": 123, "name": "Test User", "roles": ["admin", "user"]},
        metrics={"cpu_usage": 45.2, "memory_mb": 1024, "active_connections": 42},
        tags=["important", "performance", "monitoring"],
    )


def test_long_strings():
    """Test string truncation."""
    logger = get_struct_logger("test.truncation")

    # Create a very long string
    long_string = "A" * 2000

    logger.info(
        "long_string_test",
        description="Testing string truncation",
        long_data=long_string,
    )


def test_high_cardinality():
    """Test handling of high cardinality fields."""
    logger = get_struct_logger("test.cardinality")

    # These fields will be moved to context (not indexed by Loki)
    for i in range(5):
        logger.info(
            "high_cardinality_event",
            unique_id=f"id_{i}_{time.time_ns()}",
            random_value=random.random(),
            timestamp_ns=time.time_ns(),
            iteration=i,
        )


def main():
    """Run all tests."""
    # Configure logging for testing
    configure_loki_logging(
        app_name="dl-logging-test",
        environment="testing",
        extra_labels={"test_run": "structlog_demo"},
        log_level="DEBUG",
        enable_console_renderer=False,  # Use JSON output
        max_string_length=1000,
        include_hostname=True,
    )

    print("Starting structlog tests for Loki...")
    print("-" * 50)

    tests = [
        ("Basic Logging", test_basic_logging),
        ("Exception Logging", test_exception_logging),
        ("Request Context", test_request_context),
        ("Structured Data", test_structured_data),
        ("Long Strings", test_long_strings),
        ("High Cardinality", test_high_cardinality),
    ]

    for test_name, test_func in tests:
        print(f"\nRunning: {test_name}")
        test_func()
        time.sleep(0.5)  # Small delay between tests

    print("\n" + "-" * 50)
    print("Tests completed. Check logs in Loki/Grafana or local files.")
    print("\nTo view logs locally:")
    print("  cat /var/log/fluent-bit/services-logs")
    print("\nTo query in Loki:")
    print('  {app="dl-logging-test"} |= "test_started"')


if __name__ == "__main__":
    main()
