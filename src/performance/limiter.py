# -*- coding: utf-8 -*-
"""
速率限制模块。

职责：
    限制每秒启动的完整认证会话数量（项目书 13.2，默认 10 次/秒）。

设计：
    采用令牌桶算法，支持运行中动态修改速率。
    速率按「完整认证会话」计数，而非单个 RADIUS 报文，
    因此 EAP-MD5 的多轮交互只消耗一个令牌。
"""

import asyncio
import time
from typing import Optional


class RateLimiter:
    """
    令牌桶速率限制器。

    参数：
        rate_per_second: 每秒允许通过的数量，0 或负数表示不限速
    """

    def __init__(self, rate_per_second: float = 10.0):
        self._rate = float(rate_per_second or 0)
        self._tokens = 0.0
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()
        self._capacity = 0.0

    @property
    def rate(self) -> float:
        """当前速率。"""
        return self._rate

    def set_rate(self, rate_per_second: float) -> None:
        """
        动态修改速率。

        参数：
            rate_per_second: 新的每秒数量，0 或负数表示不限速
        """
        self._rate = float(rate_per_second or 0)
        if self._rate > 0:
            # 桶容量取 2 倍速率，允许短时突发，避免测试启动过慢
            self._capacity = max(1.0, self._rate * 2)
            self._tokens = min(self._tokens, self._capacity)
        else:
            self._capacity = 0.0
            self._tokens = 0.0

    async def acquire(self) -> float:
        """
        获取一个令牌。

        返回：
            实际等待时间（秒）。
        """
        if self._rate <= 0:
            return 0.0
        started = time.monotonic()
        async with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return time.monotonic() - started
            # 需要等待的时间
            deficit = 1.0 - self._tokens
            wait_time = deficit / self._rate
            self._tokens = 0.0
        await asyncio.sleep(wait_time)
        return time.monotonic() - started

    def _refill(self) -> None:
        """按经过时间补充令牌。"""
        if self._rate <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._updated
        self._updated = now
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)

    def snapshot(self) -> dict:
        """返回限流器状态。"""
        return {
            "rate": self._rate,
            "tokens": round(self._tokens, 3),
            "capacity": self._capacity,
        }


class AdaptiveRateLimiter(RateLimiter):
    """
    自适应速率限制器。

    说明：
        当前实现与 RateLimiter 完全一致，保留该类型用于后续扩展
        （例如根据服务器响应时间自动调整速率）。
    """
