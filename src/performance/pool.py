# -*- coding: utf-8 -*-
"""
并发控制模块。

职责：
    1. 限制同时在途的任务数量（项目书 13.3）；
    2. 提供阻塞与非阻塞两种额度申请方式；
    3. 任务数量保护：达到上限时停止新增任务（项目书 14，本项目只保留这一项保护）。

说明：
    CPU、内存、Socket 数量、文件描述符监控已按用户要求取消，
    因此本模块不包含上述指标的采集逻辑。

实现说明：
    不使用 asyncio.Semaphore。
    asyncio.Semaphore 在不同 Python 小版本上的非阻塞 API 存在差异
    （3.12 无 acquire_nowait），且不支持运行时动态扩容，
    因此本模块自行维护计数器与等待队列，行为在所有受支持版本上一致。
"""

import asyncio
from typing import Optional


class ConcurrencyController:
    """
    并发控制器。

    参数：
        max_concurrency: 最大同时在途任务数量
    """

    def __init__(self, max_concurrency: int = 10000):
        self._max = max(1, int(max_concurrency))
        self._running = 0
        self._peak = 0
        self._blocked = False
        self._waiters: list = []

    @property
    def max_concurrency(self) -> int:
        """最大并发数。"""
        return self._max

    @property
    def running(self) -> int:
        """当前在途任务数量。"""
        return self._running

    @property
    def peak(self) -> int:
        """历史峰值并发数。"""
        return self._peak

    @property
    def blocked(self) -> bool:
        """是否因达到任务数量上限而阻塞新增。"""
        return self._blocked

    @property
    def available(self) -> int:
        """剩余可用额度。"""
        return max(0, self._max - self._running)

    def set_max_concurrency(self, value: int) -> None:
        """
        动态修改最大并发数。

        扩容后立即唤醒等待中的申请者，让排队任务尽快获得额度。
        """
        self._max = max(1, int(value))
        self._notify_waiters()

    def _notify_waiters(self) -> None:
        """唤醒全部等待中的申请者重新尝试。"""
        waiters = self._waiters
        self._waiters = []
        for future in waiters:
            if not future.done():
                future.set_result(True)

    async def acquire(self, timeout: Optional[float] = None) -> bool:
        """
        申请一个并发额度（阻塞）。

        参数：
            timeout: 最长等待时间，None 表示一直等待

        返回：
            True 表示获取成功，False 表示超时。
        """
        if self.try_acquire():
            return True
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        self._waiters.append(future)
        try:
            if timeout is None:
                while True:
                    await future
                    if self.try_acquire():
                        return True
                    future = loop.create_future()
                    self._waiters.append(future)
            else:
                await asyncio.wait_for(future, timeout)
                if self.try_acquire():
                    return True
                self._blocked = True
                return False
        except asyncio.TimeoutError:
            self._blocked = True
            return False
        finally:
            if future in self._waiters:
                self._waiters.remove(future)

    def try_acquire(self) -> bool:
        """
        非阻塞申请额度。

        返回：
            True 表示获取成功，False 表示已达上限。
        """
        if self._running >= self._max:
            self._blocked = True
            return False
        self._running += 1
        if self._running > self._peak:
            self._peak = self._running
        self._blocked = False
        return True

    def release(self) -> None:
        """释放一个并发额度并唤醒等待者。"""
        if self._running > 0:
            self._running -= 1
        self._notify_waiters()

    def snapshot(self) -> dict:
        """返回并发控制器状态。"""
        return {
            "max_concurrency": self._max,
            "running": self._running,
            "peak": self._peak,
            "available": self.available,
            "blocked": self._blocked,
        }
