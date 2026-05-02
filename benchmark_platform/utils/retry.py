"""Retry utilities for API client requests."""
from pathlib import Path

import requests.exceptions
from tenacity import RetryCallState

from benchmark_platform.utils.logger import get_logger

# Initialize logger for retry callbacks
_logger = get_logger(Path('logs/competition-platform-mcp-client.jsonl'))


def should_retry(exception: BaseException) -> bool:
    """
    Determine whether an exception should be retried.
    Only retry network errors and 5xx server errors, do not retry 4xx client errors.
    """
    # Network connection errors - should retry
    if isinstance(
        exception, (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RequestException,
        ),
    ):
        return True

    # HTTP errors - only retry 5xx server errors
    if isinstance(exception, requests.exceptions.HTTPError):
        if exception.response is not None:
            status_code = exception.response.status_code
            # Only retry 5xx server errors, do not retry 4xx client errors
            return 500 <= status_code < 600

    # Other exceptions should not be retried
    return False


def before_sleep_retry_callback(retry_state: RetryCallState) -> None:
    """Callback before retry sleep, logs retry attempt"""
    fn = retry_state.fn
    exception = retry_state.outcome.exception() if retry_state.outcome else None
    wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
    fn_name = fn.__name__ if fn is not None and hasattr(
        fn, '__name__',
    ) else 'unknown'
    _logger.warning(
        f'Retrying {fn_name} after {wait_time:.2f}s',
        action='retry',
        attempt_number=retry_state.attempt_number,
        exception_type=type(exception).__name__ if exception else 'Unknown',
        exception_message=str(exception) if exception else '',
    )


def after_retry_callback(retry_state: RetryCallState) -> None:
    """Callback after retry, logs final result"""
    if retry_state.outcome and retry_state.outcome.failed:
        fn = retry_state.fn
        exception = retry_state.outcome.exception()
        fn_name = fn.__name__ if fn is not None and hasattr(
            fn, '__name__',
        ) else 'unknown'
        _logger.error(
            f'All retry attempts exhausted for {fn_name}',
            action='retry_exhausted',
            total_attempts=retry_state.attempt_number,
            exception_type=type(
                exception,
            ).__name__ if exception else 'Unknown',
            exception_message=str(exception) if exception else '',
        )
