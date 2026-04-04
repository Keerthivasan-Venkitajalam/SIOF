"""Retry logic with exponential backoff for transient failures."""

import logging
import random
import time
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Classification of errors for retry logic.
    
    Attributes:
        TRANSIENT: Error is temporary and should be retried
        PERMANENT: Error is permanent and should fail immediately
    """

    TRANSIENT = "transient"
    PERMANENT = "permanent"


class RetryPolicy:
    """Exponential backoff retry policy for transient failures.
    
    This policy automatically retries operations that fail with transient
    errors (network timeouts, connection refused, etc.) using exponential
    backoff with jitter to prevent thundering herd.
    
    Attributes:
        base_delay_ms: Base delay in milliseconds for first retry
        max_retries: Maximum number of retry attempts
        jitter: Whether to add random jitter to delays
    """

    # Errors that are considered transient and should be retried
    TRANSIENT_ERRORS: tuple[type[Exception], ...] = (
        ConnectionError,
        TimeoutError,
        OSError,
        BrokenPipeError,
        ConnectionResetError,
        ConnectionAbortedError,
    )

    # Errors that are permanent and should fail immediately
    PERMANENT_ERRORS: tuple[type[Exception], ...] = (
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        NotImplementedError,
    )

    def __init__(
        self,
        base_delay_ms: int = 100,
        max_retries: int = 3,
        jitter: bool = True,
    ) -> None:
        """Initialize retry policy.
        
        Args:
            base_delay_ms: Base delay in milliseconds (default: 100)
            max_retries: Maximum retry attempts (default: 3)
            jitter: Add random jitter to delays (default: True)
            
        Raises:
            ValueError: If parameters are invalid
        """
        if base_delay_ms < 0:
            raise ValueError(f"base_delay_ms must be non-negative, got {base_delay_ms}")
        if max_retries < 0:
            raise ValueError(f"max_retries must be non-negative, got {max_retries}")

        self.base_delay_ms = base_delay_ms
        self.max_retries = max_retries
        self.jitter = jitter

    def classify_error(self, error: Exception) -> ErrorCategory:
        """Classify an error as transient or permanent.
        
        Args:
            error: The exception to classify
            
        Returns:
            ErrorCategory.TRANSIENT or ErrorCategory.PERMANENT
        """
        # Check permanent errors first (fail fast)
        if isinstance(error, self.PERMANENT_ERRORS):
            return ErrorCategory.PERMANENT

        # Check transient errors
        if isinstance(error, self.TRANSIENT_ERRORS):
            return ErrorCategory.TRANSIENT

        # Default to transient for unknown errors (safer to retry)
        return ErrorCategory.TRANSIENT

    def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with retry logic.
        
        This method will retry the function if it raises a transient error,
        using exponential backoff with optional jitter.
        
        Args:
            func: Callable to execute
            *args: Positional arguments to pass to func
            **kwargs: Keyword arguments to pass to func
            
        Returns:
            Return value of func
            
        Raises:
            The original exception if all retries are exhausted or
            a permanent error occurs
        """
        last_error: Exception | None = None
        func_name = getattr(func, "__name__", str(func))

        for attempt in range(self.max_retries + 1):
            try:
                if attempt > 0:
                    logger.debug(
                        f"Retry attempt {attempt}/{self.max_retries} for {func_name}"
                    )
                return func(*args, **kwargs)

            except Exception as e:
                last_error = e
                category = self.classify_error(e)

                # Fail immediately on permanent errors
                if category == ErrorCategory.PERMANENT:
                    logger.error(
                        f"Permanent error in {func_name}: {e}",
                        exc_info=True,
                    )
                    raise

                # Check if we have retries left
                if attempt < self.max_retries:
                    delay_ms = self._calculate_delay(attempt)
                    logger.warning(
                        f"Transient error in {func_name} (attempt {attempt + 1}/"
                        f"{self.max_retries + 1}): {e}. "
                        f"Retrying in {delay_ms:.0f}ms..."
                    )
                    time.sleep(delay_ms / 1000.0)  # Convert ms to seconds
                else:
                    logger.error(
                        f"All retries exhausted for {func_name}: {e}",
                        exc_info=True,
                    )

        # All retries exhausted
        if last_error:
            raise last_error
        raise RuntimeError(f"Unexpected error in retry logic for {func_name}")

    def _calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and optional jitter.
        
        The delay grows exponentially: base_delay * 2^attempt
        With jitter enabled, adds random variation (±25%) to prevent
        thundering herd when multiple clients retry simultaneously.
        
        Args:
            attempt: The retry attempt number (0-indexed)
            
        Returns:
            Delay in milliseconds
        """
        # Exponential backoff: base_delay * 2^attempt
        delay = self.base_delay_ms * (2 ** attempt)

        if self.jitter:
            # Add random jitter: ±25% of delay
            jitter_amount = delay * 0.25
            jitter = random.uniform(-jitter_amount, jitter_amount)
            delay += jitter

        # Ensure delay is non-negative
        return max(0, delay)
