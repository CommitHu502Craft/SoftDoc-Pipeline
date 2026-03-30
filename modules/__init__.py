"""
Modules for the automated software copyright application material generation system.
"""

from .project_planner import generate_project_plan
from .html_generator import generate_html_pages

# 尝试导入依赖 Playwright 的模块
# 如果环境缺失 Playwright，不会导致整个包导入失败，只有在调用相关函数时才会报错
try:
    from .screenshot_engine import capture_screenshots_sync
except ImportError as e:
    import sys
    err_msg = str(e)
    print(f"[WARNING] 导入截图引擎失败: {err_msg}", file=sys.stderr)
    def capture_screenshots_sync(*args, **kwargs):
        raise ImportError(f"无法使用截图功能，导入错误: {err_msg}")

try:
    from .auto_submitter import auto_submit
except ImportError as e:
    err_msg = str(e)
    def auto_submit(*args, **kwargs):
        raise ImportError(f"无法使用自动提交功能，导入错误: {err_msg}")

__all__ = ['generate_project_plan', 'generate_html_pages', 'capture_screenshots_sync', 'auto_submit']
