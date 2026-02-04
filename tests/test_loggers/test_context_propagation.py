import asyncio
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from io import StringIO

import pytest
from taskflows.loggers.structured import (
    clear_request_context,
    configure_loki_logging,
    generate_request_id,
    get_struct_logger,
    request_id_var,
    set_request_context,
    trace_id_var,
)


def setup_log_capture(logger_name):
    """Helper function to set up log capture for tests"""
    log_capture = StringIO()
    handler = logging.StreamHandler(log_capture)
    handler.setLevel(logging.DEBUG)
    
    test_logger = logging.getLogger(logger_name)
    test_logger.setLevel(logging.DEBUG)
    test_logger.addHandler(handler)
    
    return log_capture, handler, test_logger


class TestContextPropagation:
    """Test context propagation across threads and async operations"""

    def setup_method(self):
        """Setup for each test"""
        configure_loki_logging(app_name="context-test", log_level="DEBUG")
        clear_request_context()

    def teardown_method(self):
        """Cleanup after each test"""
        clear_request_context()

    def test_context_isolation_between_threads(self):
        """Test that context is isolated between different threads"""
        results = {}
        
        def thread_worker(thread_id):
            # Set unique context for this thread
            request_id = f"req-thread-{thread_id}"
            trace_id = f"trace-thread-{thread_id}"
            
            set_request_context(
                request_id=request_id,
                trace_id=trace_id,
                thread_id=thread_id
            )
            
            # Verify context is set correctly
            assert request_id_var.get() == request_id
            assert trace_id_var.get() == trace_id
            
            # Log something
            logger = get_struct_logger(f"thread.{thread_id}")
            
            log_capture, handler, test_logger = setup_log_capture(f"thread.{thread_id}")
            
            logger.info(f"message_from_thread_{thread_id}")
            
            log_output = log_capture.getvalue()
            log_data = json.loads(log_output.strip())
            
            # Store results - context might be nested
            context = log_data.get("context", {})
            results[thread_id] = {
                "request_id": log_data.get("request_id") or context.get("request_id"),
                "trace_id": log_data.get("trace_id") or context.get("trace_id"),
                "thread_id": log_data.get("thread_id") or context.get("thread_id")
            }
            
            test_logger.removeHandler(handler)
            clear_request_context()
        
        # Run multiple threads
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(thread_worker, i) for i in range(3)]
            for future in futures:
                future.result()
        
        # Verify each thread had its own isolated context
        for i in range(3):
            assert results[i]["request_id"] == f"req-thread-{i}"
            assert results[i]["trace_id"] == f"trace-thread-{i}"
            assert results[i]["thread_id"] == i

    def test_context_inheritance_in_child_loggers(self):
        """Test that child loggers inherit context from parent"""
        request_id = "req-parent-123"
        trace_id = "trace-parent-456"
        
        set_request_context(
            request_id=request_id,
            trace_id=trace_id,
            user_id="user-789"
        )
        
        # Test parent logger first
        parent_logger = get_struct_logger("parent")
        log_capture, handler, test_logger = setup_log_capture("parent")
        
        parent_logger.info("parent_message")
        
        parent_logs = log_capture.getvalue().strip()
        parent_log = json.loads(parent_logs) if parent_logs else {}
        
        test_logger.removeHandler(handler)
        
        # Test child logger with fresh capture
        child_logger = get_struct_logger("parent.child")
        child_log_capture, child_handler, child_test_logger = setup_log_capture("parent.child")
        
        child_logger.info("child_message")
        
        child_logs = child_log_capture.getvalue().strip()
        child_log = json.loads(child_logs) if child_logs else {}
        
        child_test_logger.removeHandler(child_handler)
        
        # Both should have the same context (might be nested)
        parent_context = parent_log.get("context", {})
        child_context = child_log.get("context", {})
        
        assert (parent_log.get("request_id") == request_id or parent_context.get("request_id") == request_id)
        assert (child_log.get("request_id") == request_id or child_context.get("request_id") == request_id)
        assert (parent_log.get("trace_id") == trace_id or parent_context.get("trace_id") == trace_id)
        assert (child_log.get("trace_id") == trace_id or child_context.get("trace_id") == trace_id)
        assert (parent_log.get("user_id") == "user-789" or parent_context.get("user_id") == "user-789")
        assert (child_log.get("user_id") == "user-789" or child_context.get("user_id") == "user-789")

    @pytest.mark.asyncio
    async def test_async_context_propagation(self):
        """Test context propagation in async operations"""
        results = []
        
        async def async_task(task_id):
            # Set context for this async task
            request_id = f"req-async-{task_id}"
            set_request_context(request_id=request_id, task_id=task_id)
            
            logger = get_struct_logger(f"async.{task_id}")
            
            log_capture, handler, test_logger = setup_log_capture(f"async.{task_id}")
            
            # Simulate some async work
            await asyncio.sleep(0.01)
            
            logger.info(f"async_task_{task_id}_completed")
            
            log_output = log_capture.getvalue()
            log_data = json.loads(log_output.strip())
            
            # Context might be nested
            context = log_data.get("context", {})
            results.append({
                "task_id": task_id,
                "request_id": log_data.get("request_id") or context.get("request_id"),
                "logged_task_id": log_data.get("task_id") or context.get("task_id")
            })
            
            test_logger.removeHandler(handler)
            clear_request_context()
        
        # Run multiple async tasks concurrently
        await asyncio.gather(
            async_task(1),
            async_task(2),
            async_task(3)
        )
        
        # Verify each task had its own context
        for result in results:
            task_id = result["task_id"]
            assert result["request_id"] == f"req-async-{task_id}"
            assert result["logged_task_id"] == task_id

    def test_context_clear_behavior(self):
        """Test that clear_request_context properly clears all context"""
        # Set some context
        set_request_context(
            request_id="req-clear-test",
            trace_id="trace-clear-test",
            custom_field="custom_value",
            another_field=123
        )
        
        logger = get_struct_logger("clear.test")
        
        log_capture, handler, test_logger = setup_log_capture("clear.test")
        
        # Log with context
        logger.info("with_context")
        
        # Clear context
        clear_request_context()
        
        # Log without context
        logger.info("without_context")
        
        logs = log_capture.getvalue().strip().split('\n')
        with_context = json.loads(logs[0])
        without_context = json.loads(logs[1])
        
        # First log should have context (might be nested)
        with_context_ctx = with_context.get("context", {})
        assert (with_context.get("request_id") == "req-clear-test" or 
                with_context_ctx.get("request_id") == "req-clear-test")
        assert (with_context.get("trace_id") == "trace-clear-test" or 
                with_context_ctx.get("trace_id") == "trace-clear-test")
        assert (with_context.get("custom_field") == "custom_value" or 
                with_context_ctx.get("custom_field") == "custom_value")
        assert (with_context.get("another_field") == 123 or 
                with_context_ctx.get("another_field") == 123)
        
        # Second log should not have context
        without_context_ctx = without_context.get("context", {})
        assert ("request_id" not in without_context and 
                "request_id" not in without_context_ctx)
        assert ("trace_id" not in without_context and 
                "trace_id" not in without_context_ctx)
        assert ("custom_field" not in without_context and 
                "custom_field" not in without_context_ctx)
        assert ("another_field" not in without_context and 
                "another_field" not in without_context_ctx)
        
        test_logger.removeHandler(handler)

    def test_nested_context_updates(self):
        """Test updating context multiple times"""
        logger = get_struct_logger("nested.test")
        
        log_capture, handler, test_logger = setup_log_capture("nested.test")
        
        # Initial context
        set_request_context(request_id="req-1", step="init")
        logger.info("step_1")
        
        # Add more context
        set_request_context(trace_id="trace-1", step="processing")
        logger.info("step_2")
        
        # Update existing field
        set_request_context(step="completed", result="success")
        logger.info("step_3")
        
        logs = log_capture.getvalue().strip().split('\n')
        log1 = json.loads(logs[0])
        log2 = json.loads(logs[1])
        log3 = json.loads(logs[2])
        
        # Check all logs (context might be nested)
        log1_ctx = log1.get("context", {})
        log2_ctx = log2.get("context", {})
        log3_ctx = log3.get("context", {})
        
        # First log
        assert (log1.get("request_id") == "req-1" or log1_ctx.get("request_id") == "req-1")
        assert (log1.get("step") == "init" or log1_ctx.get("step") == "init")
        assert ("trace_id" not in log1 and "trace_id" not in log1_ctx)
        
        # Second log (context accumulates)
        assert (log2.get("request_id") == "req-1" or log2_ctx.get("request_id") == "req-1")
        assert (log2.get("trace_id") == "trace-1" or log2_ctx.get("trace_id") == "trace-1")
        assert (log2.get("step") == "processing" or log2_ctx.get("step") == "processing")
        
        # Third log
        assert (log3.get("request_id") == "req-1" or log3_ctx.get("request_id") == "req-1")
        assert (log3.get("trace_id") == "trace-1" or log3_ctx.get("trace_id") == "trace-1")
        assert (log3.get("step") == "completed" or log3_ctx.get("step") == "completed")
        assert (log3.get("result") == "success" or log3_ctx.get("result") == "success")
        
        test_logger.removeHandler(handler)

    def test_context_with_bound_logger(self):
        """Test context interaction with bound logger"""
        # Set global context
        set_request_context(request_id="req-bound", global_field="global_value")
        
        # Create bound logger with additional context
        logger = get_struct_logger("bound.test").bind(
            bound_field="bound_value",
            service="test-service"
        )
        
        log_capture, handler, test_logger = setup_log_capture("bound.test")
        
        logger.info("test_message", inline_field="inline_value")
        
        log_output = log_capture.getvalue()
        log_data = json.loads(log_output.strip())
        
        # Should have all three types of context (might be nested)
        context = log_data.get("context", {})
        assert log_data.get("request_id") == "req-bound" or context.get("request_id") == "req-bound"
        assert log_data.get("global_field") == "global_value" or context.get("global_field") == "global_value"
        assert log_data.get("bound_field") == "bound_value" or context.get("bound_field") == "bound_value"
        assert log_data.get("service") == "test-service" or context.get("service") == "test-service"
        assert log_data.get("inline_field") == "inline_value" or context.get("inline_field") == "inline_value"
        
        test_logger.removeHandler(handler)


class TestRequestIdGeneration:
    """Test request ID generation functionality"""

    def test_generate_unique_request_ids(self):
        """Test that generated request IDs are unique"""
        ids = set()
        for _ in range(100):
            request_id = generate_request_id()
            assert request_id not in ids
            ids.add(request_id)
            # Should be a valid UUID format
            assert len(request_id) == 36
            assert request_id.count('-') == 4

    def test_request_id_format(self):
        """Test request ID format is consistent"""
        import re
        
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        )
        
        for _ in range(10):
            request_id = generate_request_id()
            assert uuid_pattern.match(request_id) is not None