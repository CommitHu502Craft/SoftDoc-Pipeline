"""
GUI Application Entry Point
软著AI自动化生成系统 - 桌面客户端
"""
import sys
import os
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import setTheme, Theme

# 添加项目根目录到路径
from pathlib import Path
BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from gui.main_window import MainWindow
from gui.common.config_manager import config_manager


def _setup_qt_font_dir():
    """
    在部分 Windows + venv 环境下，Qt 会提示内置字体目录不存在。
    显式指定系统字体目录，减少启动警告且不影响核心功能。
    """
    if os.name != "nt":
        return
    if os.environ.get("QT_QPA_FONTDIR"):
        return
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    candidates = [windir / "Fonts", Path(r"C:\Windows\Fonts")]
    for path in candidates:
        if path.exists() and path.is_dir():
            os.environ["QT_QPA_FONTDIR"] = str(path)
            break


def main():
    """主函数"""
    # PyQt6 中高DPI默认启用，无需手动设置
    # QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling)  # PyQt6已移除
    # QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps)  # PyQt6已移除
    
    _setup_qt_font_dir()
    app = QApplication(sys.argv)
    app.setApplicationName("软著AI生成系统")
    app.setOrganizationName("SoftwareCopyrightAI")
    
    # 设置主题
    theme = config_manager.get("theme", "dark")
    setTheme(Theme.DARK if theme == "dark" else Theme.LIGHT)
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
