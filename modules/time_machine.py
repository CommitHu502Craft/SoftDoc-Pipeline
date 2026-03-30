"""
时光机 (Time Machine)
用于伪造文件系统时间戳，模拟真实的项目开发周期
"""
import os
import random
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

class TimeMachine:
    def __init__(self, root_dir: str, months_back: int = 3):
        """
        初始化时光机

        Args:
            root_dir: 需要处理的根目录
            months_back: 模拟回溯的月份数 (默认3个月)
        """
        self.root_dir = Path(root_dir)
        self.end_time = datetime.now()
        # 设定项目开始时间
        self.start_time = self.end_time - timedelta(days=months_back * 30)

    def _random_date(self, start, end):
        """生成范围内的随机时间"""
        if start >= end:
            return start

        delta = end - start
        int_delta = (delta.days * 24 * 60 * 60) + delta.seconds
        random_second = random.randrange(int_delta)
        return start + timedelta(seconds=random_second)

    def travel(self):
        """执行时间旅行：修改目录下所有文件的时间戳"""
        if not self.root_dir.exists():
            logger.error(f"目录不存在: {self.root_dir}")
            return False

        logger.info(f"启动时光机: {self.root_dir}")
        logger.info(f"设定开发周期: {self.start_time.strftime('%Y-%m-%d')} ~ {self.end_time.strftime('%Y-%m-%d')}")

        count = 0
        for root, dirs, files in os.walk(self.root_dir):
            for file in files:
                file_path = Path(root) / file

                # 跳过某些不应修改的文件 (如 .git, __pycache__)
                if ".git" in str(file_path) or "__pycache__" in str(file_path):
                    continue

                # 生成随机时间策略：
                # 1. "热点"模式：大部分文件集中在最近 1 个月 (60%) - 模拟近期迭代
                # 2. "中期"模式：核心功能分布在 2-3 个月前 (30%) - 模拟基础开发
                # 3. "早期"模式：基础设施分布在 3 个月前 (10%) - 模拟项目启动

                rand_val = random.random()
                if rand_val < 0.6:
                    # 最近 1 个月 (冲刺阶段)
                    file_date = self._random_date(self.end_time - timedelta(days=30), self.end_time)
                elif rand_val < 0.9:
                    # 1-3 个月前 (开发阶段)
                    file_date = self._random_date(self.start_time, self.end_time - timedelta(days=30))
                else:
                    # 早期文件 (初始化阶段)
                    file_date = self._random_date(self.start_time, self.start_time + timedelta(days=15))

                # 转换为 timestamp
                ts = file_date.timestamp()

                try:
                    # 修改访问时间和修改时间 (atime, mtime)
                    # 注意：在 Windows 上 ctime (创建时间) 很难通过 os.utime 修改，
                    # 通常需要 pywin32 的 SetFileTime，这里主要处理 mtime
                    os.utime(file_path, (ts, ts))
                    count += 1
                except Exception as e:
                    logger.warning(f"无法修改时间戳 {file_path}: {e}")

        logger.info(f"时光机执行完毕，已篡改 {count} 个文件的时间维度")
        return True

def warp_directory(directory: str):
    """便捷调用函数"""
    tm = TimeMachine(directory)
    return tm.travel()
