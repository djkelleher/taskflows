import json

import pytest
from taskflows.loggers.structured import configure_loki_logging, get_struct_logger


def test_loki_configuration():
    """Test that Loki configuration produces expected output format"""
    configure_loki_logging(
        app_name="test-app",
        environment="test",
        extra_labels={"version": "1.0.0"},
        log_level="DEBUG",
    )

    logger = get_struct_logger("test_logger")

    # Capture log output
    import io
    import logging

    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    # Configure the logger that structlog will use
    test_logger = logging.getLogger("test_logger")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)

    # Log a test message
    logger.info("Test message", user_id=123, action="login")

    # Parse the JSON output
    log_output = log_capture.getvalue()
    if log_output.strip():
        log_data = json.loads(log_output.strip())
    else:
        raise AssertionError("No log output captured")

    # Verify Loki-specific fields at top level (indexed by Loki)
    assert log_data["app"] == "test-app"
    assert log_data["environment"] == "test"
    assert log_data["severity"] == "INFO"
    assert log_data["level_name"] == "info"
    assert "timestamp" in log_data
    assert log_data["event"] == "Test message"
    
    # Verify context fields (not indexed by Loki)
    assert "context" in log_data
    context = log_data["context"]
    assert context["version"] == "1.0.0"
    assert context["user_id"] == 123
    assert context["action"] == "login"

    # Verify source location fields (likely in context)
    if "filename" in log_data:
        assert log_data["filename"] == "test_loki_struct.py"
    elif "filename" in context:
        assert context["filename"] == "test_loki_struct.py"
    
    assert ("lineno" in log_data) or ("lineno" in context)
    assert ("func_name" in log_data) or ("func_name" in context)

    # Clean up
    test_logger.removeHandler(handler)


def test_bound_logger_context():
    """Test that bound logger maintains context"""
    configure_loki_logging(app_name="test-app")

    base_logger = get_struct_logger("test")
    bound_logger = base_logger.bind(request_id="req-123", session_id="sess-456")

    import io
    import logging

    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    # Configure the logger that structlog will use
    test_logger = logging.getLogger("test")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)

    bound_logger.info("Bound message")

    log_output = log_capture.getvalue()
    log_data = json.loads(log_output.strip())

    # Fields should be in context or top level
    context = log_data.get("context", {})
    assert log_data.get("request_id") == "req-123" or context.get("request_id") == "req-123"
    assert log_data.get("session_id") == "sess-456" or context.get("session_id") == "sess-456"

    test_logger.removeHandler(handler)


def test_exception_logging():
    """Test that exceptions are properly formatted for Loki"""
    configure_loki_logging(app_name="test-app")
    logger = get_struct_logger("test")

    import io
    import logging

    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    # Configure the logger that structlog will use
    test_logger = logging.getLogger("test")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)

    try:
        raise ValueError("Test error")
    except ValueError:
        logger.error("Error occurred", exc_info=True)

    log_output = log_capture.getvalue()
    log_data = json.loads(log_output.strip())

    assert log_data["severity"] == "ERROR"
    context = log_data.get("context", {})
    # Exception info could be in log_data or context
    exc_info = log_data.get("exc_info") or log_data.get("exception") or context.get("exc_info") or context.get("exception")
    assert exc_info is not None
    assert "ValueError: Test error" in str(exc_info)

    test_logger.removeHandler(handler)


def test_get_struct_logger_with_context():
    """Test get_struct_logger with context parameters"""
    configure_loki_logging(app_name="test-app")

    logger = get_struct_logger(
        "test", service="api", version="2.0.0", region="us-east-1"
    )

    import io
    import logging

    log_capture = io.StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    # Configure the logger that structlog will use
    test_logger = logging.getLogger("test")
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)

    logger.info("Context test")

    log_output = log_capture.getvalue()
    log_data = json.loads(log_output.strip())

    context = log_data.get("context", {})
    assert log_data.get("service") == "api" or context.get("service") == "api"
    assert log_data.get("version") == "2.0.0" or context.get("version") == "2.0.0"
    assert log_data.get("region") == "us-east-1" or context.get("region") == "us-east-1"

    test_logger.removeHandler(handler)
