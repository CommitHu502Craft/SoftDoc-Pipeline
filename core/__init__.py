"""
Core module for the automated software copyright application material generation system.
"""

from .deepseek_client import DeepSeekClient
from .logger import (
    LogManager, LogLevel, LogRecord, ModuleLogger,
    get_logger, create_logger,
    debug, info, warning, error, critical
)
from .progress import (
    TaskStatus, ProgressInfo, ProgressTracker,
    MultiStepProgressTracker, ProgressManager,
    get_progress_manager
)

__all__ = [
    # DeepSeek Client
    'DeepSeekClient',
    # Logger
    'LogManager', 'LogLevel', 'LogRecord', 'ModuleLogger',
    'get_logger', 'create_logger',
    'debug', 'info', 'warning', 'error', 'critical',
    # Progress
    'TaskStatus', 'ProgressInfo', 'ProgressTracker',
    'MultiStepProgressTracker', 'ProgressManager',
    'get_progress_manager'
]
