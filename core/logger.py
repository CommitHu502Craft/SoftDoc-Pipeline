"""
统一日志管理器
支持控制台输出、文件日志和GUI回调
"""
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, List
from enum import Enum
from dataclasses import dataclass


class LogLevel(Enum):
    """日志级别"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


@dataclass
class LogRecord:
    """日志记录"""
    timestamp: datetime
    level: LogLevel
    message: str
    module: str


class LogManager:
    """
    统一日志管理器
    支持多种输出方式：控制台、文件、GUI回调
    """

    _instance: Optional['LogManager'] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if LogManager._initialized:
            return

        self._callbacks: List[Callable[[LogRecord], None]] = []
        self._console_enabled: bool = True
        self._file_enabled: bool = False
        self._log_file: Optional[Path] = None
        self._min_level: LogLevel = LogLevel.INFO

        # 配置标准 logging
        self._setup_logging()
        LogManager._initialized = True

    def _setup_logging(self):
        """配置标准 logging 模块"""
        # 创建根 logger
        self._root_logger = logging.getLogger("软著AI生成系统")
        self._root_logger.setLevel(logging.DEBUG)

        # 控制台 handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s",
            datefmt="%H:%M:%S"
        )
        console_handler.setFormatter(console_format)
        self._root_logger.addHandler(console_handler)
        self._console_handler = console_handler

    def enable_file_logging(self, log_dir: Path = None):
        """启用文件日志"""
        if log_dir is None:
            log_dir = Path(__file__).parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)

        log_file = log_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        self._log_file = log_file

        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
        )
        file_handler.setFormatter(file_format)
        self._root_logger.addHandler(file_handler)
        self._file_enabled = True

    def add_callback(self, callback: Callable[[LogRecord], None]):
        """添加日志回调（用于GUI显示）"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[LogRecord], None]):
        """移除日志回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def set_console_enabled(self, enabled: bool):
        """启用/禁用控制台输出"""
        self._console_enabled = enabled
        if enabled:
            self._console_handler.setLevel(logging.INFO)
        else:
            self._console_handler.setLevel(logging.CRITICAL + 1)

    def set_min_level(self, level: LogLevel):
        """设置最低日志级别"""
        self._min_level = level
        self._console_handler.setLevel(level.value)

    def _notify_callbacks(self, record: LogRecord):
        """通知所有回调"""
        for callback in self._callbacks:
            try:
                callback(record)
            except Exception:
                pass  # 忽略回调错误

    def _log(self, level: LogLevel, message: str, module: str = ""):
        """内部日志方法"""
        if level.value < self._min_level.value:
            return

        record = LogRecord(
            timestamp=datetime.now(),
            level=level,
            message=message,
            module=module
        )

        # 标准 logging
        logger = logging.getLogger(f"软著AI生成系统.{module}" if module else "软著AI生成系统")
        logger.log(level.value, message)

        # 回调通知
        self._notify_callbacks(record)

    def debug(self, message: str, module: str = ""):
        """调试日志"""
        self._log(LogLevel.DEBUG, message, module)

    def info(self, message: str, module: str = ""):
        """信息日志"""
        self._log(LogLevel.INFO, message, module)

    def warning(self, message: str, module: str = ""):
        """警告日志"""
        self._log(LogLevel.WARNING, message, module)

    def error(self, message: str, module: str = ""):
        """错误日志"""
        self._log(LogLevel.ERROR, message, module)

    def critical(self, message: str, module: str = ""):
        """严重错误日志"""
        self._log(LogLevel.CRITICAL, message, module)


# 全局单例
_log_manager: Optional[LogManager] = None


def get_logger() -> LogManager:
    """获取日志管理器单例"""
    global _log_manager
    if _log_manager is None:
        _log_manager = LogManager()
    return _log_manager


class ModuleLogger:
    """
    模块级日志器
    为每个模块提供独立的日志器，自动记录模块名
    """

    def __init__(self, module_name: str):
        self._module = module_name
        self._manager = get_logger()

    def debug(self, message: str):
        self._manager.debug(message, self._module)

    def info(self, message: str):
        self._manager.info(message, self._module)

    def warning(self, message: str):
        self._manager.warning(message, self._module)

    def error(self, message: str):
        self._manager.error(message, self._module)

    def critical(self, message: str):
        self._manager.critical(message, self._module)


def create_logger(module_name: str) -> ModuleLogger:
    """创建模块日志器"""
    return ModuleLogger(module_name)


# 便捷函数
def debug(message: str, module: str = ""):
    get_logger().debug(message, module)


def info(message: str, module: str = ""):
    get_logger().info(message, module)


def warning(message: str, module: str = ""):
    get_logger().warning(message, module)


def error(message: str, module: str = ""):
    get_logger().error(message, module)


def critical(message: str, module: str = ""):
    get_logger().critical(message, module)
