"""
Common package initialization
"""
from .config_manager import config_manager

try:
    from .signal_bus import signal_bus
except Exception:
    # 允许在无 PyQt6 的测试环境中导入 common 包。
    signal_bus = None

__all__ = ['config_manager', 'signal_bus']
