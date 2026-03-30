"""
主窗口
使用 PyQt-Fluent-Widgets 的 NavigationInterface 实现侧边导航
"""
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import (NavigationItemPosition, MessageBox, setTheme, Theme,
                            FluentIcon, NavigationInterface, qrouter)
from qfluentwidgets import FluentWindow

from .common.config_manager import config_manager
from .common.signal_bus import signal_bus

# 视图页面（稍后实现）
from .views.home_interface import HomeInterface
from .views.project_interface import ProjectInterface
from .views.submit_interface import SubmitInterface
from .views.signature_interface import SignatureInterface
from .views.setting_interface import SettingInterface
from .views.llm_monitor_interface import LlmMonitorInterface


class MainWindow(FluentWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.init_window()
        self.init_navigation()
        self.connect_signals()
    
    def init_window(self):
        """初始化窗口"""
        self.setWindowTitle("软著AI自动化生成系统")
        
        # 设置窗口尺寸
        geometry = config_manager.get('window_geometry', {})
        self.resize(geometry.get('width', 1200), geometry.get('height', 800))
        
        # 设置主题
        theme = config_manager.get('theme', 'dark')
        if theme == 'dark':
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
        
        # 移动到屏幕中心
        desktop = QApplication.primaryScreen().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w//2 - self.width()//2, h//2 - self.height()//2)
    
    def init_navigation(self):
        """初始化导航"""
        # 创建子界面
        self.home_interface = HomeInterface(self)
        self.project_interface = ProjectInterface(self)
        self.llm_monitor_interface = LlmMonitorInterface(self)
        self.submit_interface = SubmitInterface(self)
        self.signature_interface = SignatureInterface(self)
        self.setting_interface = SettingInterface(self)

        # 添加导航项
        self.addSubInterface(
            self.home_interface,
            FluentIcon.HOME,
            '仪表盘',
            NavigationItemPosition.TOP
        )

        self.addSubInterface(
            self.project_interface,
            FluentIcon.FOLDER,
            '项目管理',
            NavigationItemPosition.TOP
        )

        self.addSubInterface(
            self.llm_monitor_interface,
            FluentIcon.DEVELOPER_TOOLS,
            'LLM监控',
            NavigationItemPosition.TOP
        )

        self.addSubInterface(
            self.submit_interface,
            FluentIcon.SEND,
            '自动提交',
            NavigationItemPosition.TOP
        )

        self.addSubInterface(
            self.signature_interface,
            FluentIcon.PENCIL_INK,
            '签章管理',
            NavigationItemPosition.TOP
        )

        # 底部导航项
        self.addSubInterface(
            self.setting_interface,
            FluentIcon.SETTING,
            '系统设置',
            NavigationItemPosition.BOTTOM
        )
    
    def connect_signals(self):
        """连接信号"""
        # 主题切换
        signal_bus.theme_changed.connect(self.on_theme_changed)
        
        # 刷新请求
        signal_bus.projects_refresh.connect(self.project_interface.refresh_projects)
    
    def on_theme_changed(self, theme_name: str):
        """主题切换"""
        if theme_name == 'dark':
            setTheme(Theme.DARK)
        else:
            setTheme(Theme.LIGHT)
    
    def closeEvent(self, event):
        """关闭事件 - 保存配置"""
        # 保存窗口尺寸
        config_manager.set('window_geometry', {
            'width': self.width(),
            'height': self.height(),
            'x': self.x(),
            'y': self.y()
        })
        super().closeEvent(event)
