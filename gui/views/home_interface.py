"""
首页 - 仪表盘
显示统计信息和快捷操作
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from qfluentwidgets import (ScrollArea, CardWidget, IconWidget, BodyLabel, 
                            CaptionLabel, PushButton, FluentIcon, InfoBadge,
                            InfoLevel)
from pathlib import Path
import sys

BASE_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(BASE_DIR))

from ..common.project_scanner import ProjectScanner
from ..common.signal_bus import signal_bus
from config import OUTPUT_DIR


class StatCard(CardWidget):
    """统计卡片"""
    
    def __init__(self, icon, title: str, value: str, color: str = "blue", parent=None):
        super().__init__(parent)
        self.setFixedHeight(120)
        
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 图标和数值
        top_layout = QHBoxLayout()
        icon_widget = IconWidget(icon, self)
        icon_widget.setFixedSize(48, 48)
        
        value_label = BodyLabel(value, self)
        value_label.setObjectName("value")
        font = value_label.font()
        font.setPointSize(24)
        font.setBold(True)
        value_label.setFont(font)
        
        top_layout.addWidget(icon_widget)
        top_layout.addStretch(1)
        top_layout.addWidget(value_label)
        
        # 标题
        title_label = CaptionLabel(title, self)
        title_label.setObjectName("title")
        
        layout.addLayout(top_layout)
        layout.addWidget(title_label)


class HomeInterface(ScrollArea):
    """首页界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.view = QWidget(self)
        self.vBoxLayout = QVBoxLayout(self.view)
        
        self.setObjectName("homeInterface")
        self.setWidget(self.view)
        self.setWidgetResizable(True)
        
        self.scanner = ProjectScanner(OUTPUT_DIR)
        
        self.init_ui()
        self.connect_signals()
        self.refresh_stats()
    
    def init_ui(self):
        """初始化UI"""
        # 标题
        title_label = BodyLabel("软著AI自动化生成系统", self.view)
        font = title_label.font()
        font.setPointSize(20)
        font.setBold(True)
        title_label.setFont(font)
        
        # 统计卡片
        self.stats_layout = QHBoxLayout()
        self.stats_layout.setSpacing(20)
        
        self.total_card = StatCard(
            FluentIcon.FOLDER, 
            "项目总数", 
            "0", 
            parent=self.view
        )
        
        self.completed_card = StatCard(
            FluentIcon.COMPLETED,
            "已完成",
            "0",
            parent=self.view
        )
        
        self.pending_card = StatCard(
            FluentIcon.CERTIFICATE,
            "待提交",
            "0",
            parent=self.view
        )
        
        self.stats_layout.addWidget(self.total_card)
        self.stats_layout.addWidget(self.completed_card)
        self.stats_layout.addWidget(self.pending_card)
        self.stats_layout.addStretch(1)
        
        # 快捷操作
        actions_label = BodyLabel("快捷操作", self.view)
        font = actions_label.font()
        font.setPointSize(16)
        font.setBold(True)
        actions_label.setFont(font)
        
        actions_layout = QHBoxLayout()
        actions_layout.setSpacing(15)
        
        new_project_btn = PushButton(FluentIcon.ADD, "新建项目", self.view)
        new_project_btn.clicked.connect(self.on_new_project)
        
        open_output_btn = PushButton(FluentIcon.FOLDER, "打开输出目录", self.view)
        open_output_btn.clicked.connect(self.on_open_output)
        
        refresh_btn = PushButton(FluentIcon.SYNC, "刷新", self.view)
        refresh_btn.clicked.connect(self.refresh_stats)
        
        actions_layout.addWidget(new_project_btn)
        actions_layout.addWidget(open_output_btn)
        actions_layout.addWidget(refresh_btn)
        actions_layout.addStretch(1)
        
        # 布局
        self.vBoxLayout.setSpacing(20)
        self.vBoxLayout.setContentsMargins(30, 30, 30, 30)
        self.vBoxLayout.addWidget(title_label)
        self.vBoxLayout.addLayout(self.stats_layout)
        self.vBoxLayout.addSpacing(20)
        self.vBoxLayout.addWidget(actions_label)
        self.vBoxLayout.addLayout(actions_layout)
        self.vBoxLayout.addStretch(1)
    
    def connect_signals(self):
        """连接信号"""
        signal_bus.projects_refresh.connect(self.refresh_stats)
        signal_bus.project_created.connect(lambda: self.refresh_stats())
        signal_bus.project_updated.connect(lambda: self.refresh_stats())
    
    def refresh_stats(self):
        """刷新统计"""
        projects = self.scanner.scan_all_projects()
        total = len(projects)
        
        # 统计完成项目（所有状态都为True）
        completed = sum(1 for p in projects if all(p['status'].values()))
        
        # 统计待提交（有文档但未提交）
        pending = sum(1 for p in projects if p['status'].get('document', False))
        
        self.total_card.findChild(BodyLabel, "value").setText(str(total))
        self.completed_card.findChild(BodyLabel, "value").setText(str(completed))
        self. pending_card.findChild(BodyLabel, "value").setText(str(pending))
    
    def on_new_project(self):
        """新建项目"""
        # TODO: 弹出对话框输入项目名称
        from qfluentwidgets import MessageBox
        MessageBox("提示", "此功能将在项目管理页实现", self).exec()
    
    def on_open_output(self):
        """打开输出目录"""
        import os
        os.startfile(str(OUTPUT_DIR))
