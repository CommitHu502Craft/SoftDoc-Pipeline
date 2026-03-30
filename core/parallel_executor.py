"""
通用并行执行器 (Parallel Executor)
基于 asyncio 和 ThreadPoolExecutor 实现并发任务处理
用于加速 LLM API 调用 (IO密集型) 和 本地处理 (CPU密集型)

兼容 Python 3.8+
"""
import asyncio
import logging
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import List, Callable, Any, TypeVar, Optional, Tuple

from core.llm_budget import llm_budget

# 尝试导入 tqdm，如果不存在则使用静默模式
try:
    from tqdm.asyncio import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Python 3.8 兼容性：检查是否有 asyncio.to_thread
HAS_TO_THREAD = hasattr(asyncio, 'to_thread')


async def _run_in_thread(func: Callable[[], T]) -> T:
    """
    兼容 Python 3.8 的线程执行器
    Python 3.9+ 使用 asyncio.to_thread
    Python 3.8 使用 loop.run_in_executor
    """
    run_id = llm_budget.current_run_id()
    stage = llm_budget.current_stage()

    def _wrapped() -> T:
        with llm_budget.run_scope(run_id):
            with llm_budget.stage_scope(stage):
                return func()

    if HAS_TO_THREAD:
        return await asyncio.to_thread(_wrapped)
    else:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _wrapped)


class ParallelExecutor:
    """
    并行执行器
    """

    def __init__(self, max_workers: int = None):
        """
        初始化
        Args:
            max_workers: 线程池最大线程数，默认为 None (自动调整)
        """
        self.max_workers = max_workers

    async def run_llm_tasks(
        self,
        tasks: List[Callable[[], T]],
        concurrency: int = 5,
        delay: float = 0.2,
        desc: str = "Processing LLM tasks",
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[T]:
        """
        并发执行 LLM 任务 (IO 密集型)

        Args:
            tasks: 待执行的函数列表 (无参，返回结果)
            concurrency: 并发数控制 (Rate Limit)
            delay: 任务间启动延迟 (秒)，防止瞬间触发 API 限制
            desc: 进度条描述
            progress_callback: 进度回调 (current, total)

        Returns:
            结果列表 (与输入 tasks 顺序一致)
        """
        if not tasks:
            return []

        semaphore = asyncio.Semaphore(concurrency)
        total = len(tasks)
        results = [None] * total

        # 包装单个任务
        async def worker(index: int, task_func: Callable[[], T]):
            async with semaphore:
                # 简单的速率控制
                if delay > 0:
                    await asyncio.sleep(delay)

                try:
                    # 在线程池中执行同步的 LLM 调用，避免阻塞 Event Loop
                    # 使用兼容函数替代 asyncio.to_thread
                    result = await _run_in_thread(task_func)
                    return index, result, None
                except Exception as e:
                    logger.error(f"Task {index} failed: {e}")
                    return index, None, e

        # 创建所有协程
        coroutines = [worker(i, task) for i, task in enumerate(tasks)]

        # 执行并追踪进度
        completed_count = 0

        # 根据是否有 tqdm 决定迭代器
        iterator = asyncio.as_completed(coroutines)
        if HAS_TQDM:
            iterator = tqdm(iterator, total=total, desc=desc)

        for coro in iterator:
            index, result, error = await coro
            results[index] = result

            # 记录错误但不中断整体流程
            if error:
                logger.warning(f"Task {index} execution error: {error}")

            completed_count += 1
            if progress_callback:
                try:
                    progress_callback(completed_count, total)
                except Exception as cb_err:
                    logger.error(f"Progress callback error: {cb_err}")

        return results

    async def run_cpu_tasks(
        self,
        tasks: List[Callable[[], T]],
        desc: str = "Processing CPU tasks",
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[T]:
        """
        并发执行 CPU 密集型任务
        注意：Python GIL 限制了多线程纯 Python 代码的并行效率。
        如果任务主要是 I/O 或 调用了 C 扩展 (如 numpy, hash)，多线程有效。

        Args:
            tasks: 任务列表
            desc: 进度条描述
            progress_callback: 进度回调

        Returns:
            结果列表
        """
        if not tasks:
            return []

        loop = asyncio.get_event_loop()
        total = len(tasks)
        results = [None] * total

        # 使用 ThreadPoolExecutor
        # 如果需要真并行 (多核 CPU)，这里应该用 ProcessPoolExecutor，
        # 但考虑到序列化(Pickle)的复杂性和上下文传递，先使用 Thread

        async def worker(index: int, task_func: Callable[[], T], executor):
            try:
                result = await loop.run_in_executor(executor, task_func)
                return index, result, None
            except Exception as e:
                return index, None, e

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            coroutines = [worker(i, task, executor) for i, task in enumerate(tasks)]

            completed_count = 0
            iterator = asyncio.as_completed(coroutines)
            if HAS_TQDM:
                iterator = tqdm(iterator, total=total, desc=desc)

            for coro in iterator:
                index, result, error = await coro
                results[index] = result

                if error:
                    logger.error(f"CPU Task {index} failed: {error}")

                completed_count += 1
                if progress_callback:
                    try:
                        progress_callback(completed_count, total)
                    except Exception:
                        pass

        return results

    def run_sync(self, coroutine):
        """
        同步环境下的辅助运行方法
        检测是否已有事件循环，避免嵌套调用
        """
        try:
            # 尝试获取当前运行中的事件循环：若不存在会抛 RuntimeError。
            asyncio.get_running_loop()
        except RuntimeError:
            # 没有运行中的事件循环，可以安全使用 asyncio.run()。
            return asyncio.run(coroutine)
        logger.warning("检测到已有运行的事件循环，无法使用 run_sync，请直接使用 await")
        raise RuntimeError("Cannot use run_sync within an existing event loop. Use 'await' instead.")
