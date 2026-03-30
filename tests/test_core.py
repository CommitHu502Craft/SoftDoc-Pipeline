"""
核心模块测试
"""
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestLogger:
    """日志模块测试"""

    def test_get_logger_singleton(self):
        """测试日志管理器单例"""
        from core.logger import get_logger

        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2

    def test_create_module_logger(self):
        """测试创建模块日志器"""
        from core.logger import create_logger

        logger = create_logger("test_module")
        assert logger._module == "test_module"

    def test_log_levels(self):
        """测试日志级别"""
        from core.logger import LogLevel

        assert LogLevel.DEBUG.value < LogLevel.INFO.value
        assert LogLevel.INFO.value < LogLevel.WARNING.value
        assert LogLevel.WARNING.value < LogLevel.ERROR.value

    def test_log_callback(self):
        """测试日志回调"""
        from core.logger import get_logger, LogRecord

        received_records = []

        def callback(record: LogRecord):
            received_records.append(record)

        logger = get_logger()
        logger.add_callback(callback)
        logger.info("Test message")

        assert len(received_records) > 0
        logger.remove_callback(callback)


class TestProgress:
    """进度模块测试"""

    def test_progress_tracker_creation(self):
        """测试创建进度跟踪器"""
        from core.progress import ProgressTracker, TaskStatus

        tracker = ProgressTracker("test_task", total=100)
        assert tracker.task_name == "test_task"
        assert tracker.total == 100
        assert tracker.status == TaskStatus.PENDING

    def test_progress_tracker_update(self):
        """测试更新进度"""
        from core.progress import ProgressTracker

        tracker = ProgressTracker("test_task", total=100)
        tracker.start()
        tracker.update(current=50, message="进行中")

        assert tracker.current == 50

    def test_progress_percentage(self):
        """测试进度百分比计算"""
        from core.progress import ProgressInfo, TaskStatus

        info = ProgressInfo(
            current=50,
            total=100,
            message="test",
            status=TaskStatus.RUNNING
        )
        assert info.percentage == 50.0

    def test_progress_manager_singleton(self):
        """测试进度管理器单例"""
        from core.progress import get_progress_manager

        manager1 = get_progress_manager()
        manager2 = get_progress_manager()
        assert manager1 is manager2

    def test_multi_step_tracker(self):
        """测试多步骤跟踪器"""
        from core.progress import MultiStepProgressTracker

        steps = ["step1", "step2", "step3"]
        tracker = MultiStepProgressTracker("multi_task", steps)

        assert len(tracker.steps) == 3
        tracker.start()
        tracker.next_step()
        assert tracker.current_step == "step1"


class TestTaskCancellation:
    """任务取消测试"""

    def test_task_cancelled_exception(self):
        """测试任务取消异常"""
        from gui.common.worker import TaskCancelledException

        with pytest.raises(TaskCancelledException):
            raise TaskCancelledException("Test cancellation")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
