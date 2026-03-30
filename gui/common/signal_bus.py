"""
全局信号总线
用于组件间通信，避免紧耦合
"""
from PyQt6.QtCore import QObject, pyqtSignal

class SignalBus(QObject):
    """全局信号总线"""
    
    # 项目相关信号
    project_created = pyqtSignal(str)  # 项目名称
    project_updated = pyqtSignal(str)  # 项目名称
    project_deleted = pyqtSignal(str)  # 项目名称
    projects_refresh = pyqtSignal()    # 刷新项目列表
    
    # 任务相关信号
    task_started = pyqtSignal(str, str)  # (任务类型, 项目名称)
    task_progress = pyqtSignal(str, int)  # (任务ID, 进度百分比)
    task_completed = pyqtSignal(str, bool, str)  # (任务ID, 成功与否, 消息)
    task_log = pyqtSignal(str, str)  # (任务ID, 日志文本)
    
    # 配置相关信号
    api_provider_changed = pyqtSignal(str)  # 新的provider名称
    theme_changed = pyqtSignal(str)  # 'light' or 'dark'
    
    # 提交相关信号
    submit_started = pyqtSignal(str)  # 项目名称
    submit_captcha_required = pyqtSignal(str)  # 提示信息
    submit_completed =pyqtSignal(str, bool)  # (项目名称, 是否成功)

# 全局信号总线实例
signal_bus = SignalBus()
