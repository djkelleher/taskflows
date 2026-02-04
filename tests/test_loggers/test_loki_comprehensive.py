import json
import logging
import os
import time
from io import StringIO
from unittest.mock import patch

import pytest
from taskflows.loggers.structured import (
    add_event_fingerprint,
    add_loki_labels,
    add_nano_timestamp,
    clear_request_context,
    configure_loki_logging,
    generate_request_id,
    get_struct_logger,
    normalize_log_level,
    organize_fields_for_loki,
    request_id_var,
    set_request_context,
    trace_id_var,
)


def setup_log_capture(logger_name="test"):
    """Helper function to set up log capture for tests"""
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    test_logger = logging.getLogger(logger_name)
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)
    
    return log_capture, handler, test_logger


class TestLokiProcessors:
    """Test individual Loki processors"""

    def test_add_loki_labels(self):
        """Test that Loki labels are properly added"""
        with patch.dict(os.environ, {
            "APP_NAME": "test-app",
            "ENVIRONMENT": "staging",
            "HOSTNAME": "test-host-123"
        }):
            event_dict = {"event": "test"}
            result = add_loki_labels(None, None, event_dict)
            
            assert result["app"] == "test-app"
            assert result["environment"] == "staging"
            assert result["hostname"] == "test-host-123"

    def test_add_loki_labels_with_context_vars(self):
        """Test Loki labels with request/trace IDs"""
        request_id = "req-123"
        trace_id = "trace-456"
        
        request_id_var.set(request_id)
        trace_id_var.set(trace_id)
        
        try:
            event_dict = {"event": "test"}
            result = add_loki_labels(None, None, event_dict)
            
            assert result["request_id"] == request_id
            assert result["trace_id"] == trace_id
        finally:
            request_id_var.set(None)
            trace_id_var.set(None)

    def test_normalize_log_level(self):
        """Test log level normalization for Loki"""
        test_cases = [
            ("debug", "DEBUG", "debug"),
            ("info", "INFO", "info"),
            ("warning", "WARNING", "warning"),
            ("error", "ERROR", "error"),
            ("critical", "CRITICAL", "critical"),
        ]
        
        for level, expected_severity, expected_level_name in test_cases:
            event_dict = {"level": level}
            result = normalize_log_level(None, None, event_dict)
            
            assert result["severity"] == expected_severity
            assert result["level_name"] == expected_level_name

    def test_add_nano_timestamp(self):
        """Test nanosecond timestamp addition"""
        event_dict = {"event": "test"}
        before_ns = time.time_ns()
        result = add_nano_timestamp(None, None, event_dict)
        after_ns = time.time_ns()
        
        assert "timestamp_ns" in result
        assert before_ns <= result["timestamp_ns"] <= after_ns

    def test_add_event_fingerprint(self):
        """Test event fingerprint generation"""
        event_dict = {
            "event": "test_event",
            "logger": "test.logger",
            "filename": "test.py",
            "func_name": "test_func",
            "lineno": 42
        }
        
        result = add_event_fingerprint(None, None, event_dict)
        assert "event_fingerprint" in result
        assert len(result["event_fingerprint"]) == 8
        
        # Same event should generate same fingerprint
        result2 = add_event_fingerprint(None, None, event_dict.copy())
        assert result["event_fingerprint"] == result2["event_fingerprint"]
        
        # Different event should generate different fingerprint
        different_event_dict = event_dict.copy()
        different_event_dict["event"] = "different_event"
        result3 = add_event_fingerprint(None, None, different_event_dict)
        assert result["event_fingerprint"] != result3["event_fingerprint"]

    def test_organize_fields_for_loki(self):
        """Test field organization to minimize Loki cardinality"""
        event_dict = {
            # Indexed fields (should remain at top level)
            "app": "test-app",
            "environment": "prod",
            "severity": "INFO",
            "logger": "test.logger",
            
            # Non-indexed fields (should move to context)
            "user_id": 123,
            "session_id": "sess-456",
            "custom_field": "value",
            
            # Special fields (should remain at top level)
            "timestamp": "2023-01-01T00:00:00",
            "event": "test_event",
            "message": "Test message",
        }
        
        result = organize_fields_for_loki(None, None, event_dict)
        
        # Check indexed fields remain at top level
        assert result["app"] == "test-app"
        assert result["environment"] == "prod"
        
        # Check non-indexed fields moved to context
        assert "context" in result
        assert result["context"]["user_id"] == 123
        assert result["context"]["session_id"] == "sess-456"
        assert result["context"]["custom_field"] == "value"
        
        # Check these fields are removed from top level
        assert "user_id" not in result
        assert "session_id" not in result
        
        # Check special fields remain at top level
        assert result["timestamp"] == "2023-01-01T00:00:00"
        assert result["event"] == "test_event"


class TestRequestContext:
    """Test request context management"""

    def test_set_and_clear_request_context(self):
        """Test setting and clearing request context"""
        request_id = "req-789"
        trace_id = "trace-012"
        
        set_request_context(
            request_id=request_id,
            trace_id=trace_id,
            user_id="user-123",
            endpoint="/api/test"
        )
        
        # Check context variables are set
        assert request_id_var.get() == request_id
        assert trace_id_var.get() == trace_id
        
        # Create logger and check context is included
        logger = get_struct_logger("test")
        
        log_capture, handler, test_logger = setup_log_capture("test")
        
        logger.info("test_with_context")
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Context should be in the log or nested in context
        context = log_data.get("context", {})
        assert log_data.get("request_id") == request_id or context.get("request_id") == request_id
        assert log_data.get("trace_id") == trace_id or context.get("trace_id") == trace_id
        assert log_data.get("user_id") == "user-123" or context.get("user_id") == "user-123"
        assert log_data.get("endpoint") == "/api/test" or context.get("endpoint") == "/api/test"
        
        # Clear context
        clear_request_context()
        
        # Check context variables are cleared
        assert request_id_var.get() is None
        assert trace_id_var.get() is None
        
        test_logger.removeHandler(handler)

    def test_generate_request_id(self):
        """Test request ID generation"""
        id1 = generate_request_id()
        id2 = generate_request_id()
        
        # Should be valid UUIDs
        assert len(id1) == 36
        assert len(id2) == 36
        
        # Should be unique
        assert id1 != id2


class TestConfigurationOptions:
    """Test various configuration options"""

    def test_configure_with_all_options(self):
        """Test configuration with all options enabled"""
        configure_loki_logging(
            app_name="full-test-app",
            environment="testing",
            extra_labels={"version": "2.0.0", "region": "us-west"},
            log_level="DEBUG",
            enable_console_renderer=False,
            max_string_length=500,
            include_hostname=True,
            include_process_info=True
        )
        
        logger = get_struct_logger("test")
        
        log_capture, handler, test_logger = setup_log_capture("test")
        
        # Test string truncation
        long_string = "A" * 1000
        logger.info("truncation_test", data=long_string)
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Check configuration was applied
        assert log_data["app"] == "full-test-app"
        assert log_data["environment"] == "testing"
        
        # Extra labels should be in context or top level
        context = log_data.get("context", {})
        assert log_data.get("version") == "2.0.0" or context.get("version") == "2.0.0"
        assert log_data.get("region") == "us-west" or context.get("region") == "us-west"
        
        # Check string was truncated
        if "context" in log_data and "data" in log_data["context"]:
            assert log_data["context"]["data"].endswith("... (truncated)")
            assert len(log_data["context"]["data"]) < 600
        elif "data" in log_data:
            assert log_data["data"].endswith("... (truncated)")
            assert len(log_data["data"]) < 600
        
        test_logger.removeHandler(handler)

    def test_configure_without_hostname(self):
        """Test configuration without hostname"""
        configure_loki_logging(
            app_name="no-host-app",
            include_hostname=False
        )
        
        logger = get_struct_logger("test")
        
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logging.root.addHandler(handler)
        
        logger.info("test_no_hostname")
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Hostname should not be included
        assert "hostname" not in log_data
        
        logging.root.removeHandler(handler)


class TestLokiIntegration:
    """Test full Loki integration scenarios"""

    def test_concurrent_logging(self):
        """Test concurrent logging from multiple loggers"""
        configure_loki_logging(app_name="concurrent-test")
        
        logger1 = get_struct_logger("test.logger1")
        logger2 = get_struct_logger("test.logger2")
        
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logging.root.addHandler(handler)
        
        # Log from both loggers
        logger1.info("message_from_logger1", source="logger1")
        logger2.info("message_from_logger2", source="logger2")
        
        logs = log_capture.getvalue().strip().split('\n')
        assert len(logs) == 2
        
        log1 = json.loads(logs[0])
        log2 = json.loads(logs[1])
        
        # Check both logs have correct logger names
        assert log1["logger"] == "test.logger1"
        assert log2["logger"] == "test.logger2"
        
        logging.root.removeHandler(handler)

    def test_exception_with_loki_formatting(self):
        """Test exception logging with Loki formatting"""
        configure_loki_logging(app_name="exception-test")
        logger = get_struct_logger("test.exceptions")
        
        log_capture, handler, test_logger = setup_log_capture("test.exceptions")
        
        try:
            raise ValueError("Test error for Loki")
        except ValueError:
            logger.error("exception_occurred", exc_info=True)
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Check exception is properly formatted
        assert log_data["severity"] == "ERROR"
        context = log_data.get("context", {})
        exc_info = log_data.get("exc_info") or log_data.get("exception") or context.get("exc_info") or context.get("exception")
        assert exc_info is not None
        assert "ValueError: Test error for Loki" in str(exc_info)
        
        test_logger.removeHandler(handler)

    def test_nested_context_data(self):
        """Test logging with nested context data"""
        configure_loki_logging(app_name="nested-test")
        logger = get_struct_logger("test.nested")
        
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logging.root.addHandler(handler)
        
        # Log with complex nested data
        logger.info(
            "complex_event",
            user={
                "id": 123,
                "name": "Test User",
                "preferences": {
                    "theme": "dark",
                    "notifications": True
                }
            },
            metrics={
                "cpu": 45.2,
                "memory": 1024,
                "connections": [1, 2, 3, 4, 5]
            }
        )
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Check nested data is preserved in context
        assert "context" in log_data
        assert log_data["context"]["user"]["preferences"]["theme"] == "dark"
        assert log_data["context"]["metrics"]["connections"] == [1, 2, 3, 4, 5]
        
        logging.root.removeHandler(handler)


class TestGetStructLogger:
    """Test get_struct_logger function variations"""

    def test_get_struct_logger_with_all_params(self):
        """Test get_struct_logger with all parameters"""
        configure_loki_logging(app_name="struct-test")
        
        request_id = "req-999"
        trace_id = "trace-888"
        
        logger = get_struct_logger(
            "test.full",
            request_id=request_id,
            trace_id=trace_id,
            service="api",
            version="1.2.3",
            custom_field="custom_value"
        )
        
        log_capture = StringIO()
        handler = logging.StreamHandler(log_capture)
        logging.root.addHandler(handler)
        
        logger.info("test_message")
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Check all parameters are included
        assert log_data["logger"] == "test.full"
        assert log_data.get("request_id") == request_id
        assert log_data.get("trace_id") == trace_id
        
        # Check additional context
        if "context" in log_data:
            assert log_data["context"].get("service") == "api"
            assert log_data["context"].get("version") == "1.2.3"
            assert log_data["context"].get("custom_field") == "custom_value"
        else:
            assert log_data.get("service") == "api"
            assert log_data.get("version") == "1.2.3"
            assert log_data.get("custom_field") == "custom_value"
        
        # Clean up context
        request_id_var.set(None)
        trace_id_var.set(None)
        
        logging.root.removeHandler(handler)