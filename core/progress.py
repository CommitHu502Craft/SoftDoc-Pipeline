"""
进度回调机制
统一的任务进度管理
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, List, Any
from datetime import datetime


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"       # 等待执行
    RUNNING = "running"       # 执行中
    PAUSED = "paused"         # 已暂停
    COMPLETED = "completed"   # 已完成
    FAILED = "failed"         # 失败
    CANCELLED = "cancelled"   # 已取消


@dataclass
class ProgressInfo:
    """进度信息"""
    current: int                    # 当前进度
    total: int                      # 总进度
    message: str                    # 进度消息
    status: TaskStatus              # 任务状态
    task_name: str = ""             # 任务名称
    sub_task: str = ""              # 子任务名称
    timestamp: datetime = field(default_factory=datetime.now)
    extra: dict = field(default_factory=dict)  # 额外信息

    @property
    def percentage(self) -> float:
        """计算百分比"""
        if self.total <= 0:
            return 0.0
        return min(100.0, (self.current / self.total) * 100)

    @property
    def is_complete(self) -> bool:
        """是否完成"""
        return self.status == TaskStatus.COMPLETED

    @property
    def is_running(self) -> bool:
        """是否运行中"""
        return self.status == TaskStatus.RUNNING


# 进度回调类型
ProgressCallback = Callable[[ProgressInfo], None]


class ProgressTracker:
    """
    进度跟踪器
    用于跟踪任务执行进度并通知回调
    """

    def __init__(self, task_name: str, total: int = 100):
        self._task_name = task_name
        self._total = total
        self._current = 0
        self._status = TaskStatus.PENDING
        self._message = ""
        self._sub_task = ""
        self._callbacks: List[ProgressCallback] = []
        self._cancelled = False

    @property
    def task_name(self) -> str:
        return self._task_name

    @property
    def current(self) -> int:
        return self._current

    @property
    def total(self) -> int:
        return self._total

    @property
    def status(self) -> TaskStatus:
        return self._status

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def add_callback(self, callback: ProgressCallback):
        """添加进度回调"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: ProgressCallback):
        """移除进度回调"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify(self):
        """通知所有回调"""
        info = ProgressInfo(
            current=self._current,
            total=self._total,
            message=self._message,
            status=self._status,
            task_name=self._task_name,
            sub_task=self._sub_task
        )
        for callback in self._callbacks:
            try:
                callback(info)
            except Exception:
                pass

    def start(self, message: str = ""):
        """开始任务"""
        self._status = TaskStatus.RUNNING
        self._current = 0
        self._message = message or f"开始执行: {self._task_name}"
        self._notify()

    def update(self, current: int = None, message: str = None, sub_task: str = None):
        """更新进度"""
        if self._cancelled:
            return

        if current is not None:
            self._current = min(current, self._total)
        if message is not None:
            self._message = message
        if sub_task is not None:
            self._sub_task = sub_task
        self._notify()

    def increment(self, step: int = 1, message: str = None):
        """增加进度"""
        self.update(current=self._current + step, message=message)

    def set_sub_task(self, sub_task: str, progress: int = None):
        """设置子任务"""
        self._sub_task = sub_task
        if progress is not None:
            self._current = progress
        self._notify()

    def complete(self, message: str = None):
        """完成任务"""
        self._status = TaskStatus.COMPLETED
        self._current = self._total
        self._message = message or f"任务完成: {self._task_name}"
        self._notify()

    def fail(self, message: str = None, error: Exception = None):
        """任务失败"""
        self._status = TaskStatus.FAILED
        error_msg = str(error) if error else ""
        self._message = message or f"任务失败: {error_msg}"
        self._notify()

    def cancel(self):
        """取消任务"""
        self._cancelled = True
        self._status = TaskStatus.CANCELLED
        self._message = "任务已取消"
        self._notify()

    def pause(self, message: str = None):
        """暂停任务"""
        self._status = TaskStatus.PAUSED
        self._message = message or "任务已暂停"
        self._notify()

    def resume(self, message: str = None):
        """恢复任务"""
        if self._status == TaskStatus.PAUSED:
            self._status = TaskStatus.RUNNING
            self._message = message or "任务已恢复"
            self._notify()


class MultiStepProgressTracker(ProgressTracker):
    """
    多步骤进度跟踪器
    用于跟踪包含多个步骤的复杂任务
    """

    def __init__(self, task_name: str, steps: List[str]):
        super().__init__(task_name, total=len(steps))
        self._steps = steps
        self._current_step_index = -1

    @property
    def steps(self) -> List[str]:
        return self._steps

    @property
    def current_step(self) -> Optional[str]:
        if 0 <= self._current_step_index < len(self._steps):
            return self._steps[self._current_step_index]
        return None

    def next_step(self, message: str = None):
        """进入下一步骤"""
        if self._cancelled:
            return

        self._current_step_index += 1
        if self._current_step_index < len(self._steps):
            step_name = self._steps[self._current_step_index]
            self._sub_task = step_name
            self._current = self._current_step_index
            self._message = message or f"执行步骤: {step_name}"
            self._notify()

    def complete_step(self, message: str = None):
        """完成当前步骤"""
        if self._current_step_index >= 0:
            step_name = self._steps[self._current_step_index]
            self._message = message or f"完成步骤: {step_name}"
            self._notify()

    def skip_step(self, message: str = None):
        """跳过当前步骤"""
        if self._current_step_index < len(self._steps):
            step_name = self._steps[self._current_step_index]
            self._message = message or f"跳过步骤: {step_name}"
            self.next_step()


# 全局进度管理器
class ProgressManager:
    """
    进度管理器
    管理多个任务的进度跟踪
    """

    _instance: Optional['ProgressManager'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._trackers = {}
        return cls._instance

    def create_tracker(self, task_id: str, task_name: str, total: int = 100) -> ProgressTracker:
        """创建进度跟踪器"""
        tracker = ProgressTracker(task_name, total)
        self._trackers[task_id] = tracker
        return tracker

    def create_multi_step_tracker(self, task_id: str, task_name: str,
                                   steps: List[str]) -> MultiStepProgressTracker:
        """创建多步骤进度跟踪器"""
        tracker = MultiStepProgressTracker(task_name, steps)
        self._trackers[task_id] = tracker
        return tracker

    def get_tracker(self, task_id: str) -> Optional[ProgressTracker]:
        """获取进度跟踪器"""
        return self._trackers.get(task_id)

    def remove_tracker(self, task_id: str):
        """移除进度跟踪器"""
        if task_id in self._trackers:
            del self._trackers[task_id]

    def cancel_all(self):
        """取消所有任务"""
        for tracker in self._trackers.values():
            tracker.cancel()


def get_progress_manager() -> ProgressManager:
    """获取进度管理器单例"""
    return ProgressManager()
