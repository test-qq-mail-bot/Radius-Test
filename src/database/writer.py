# -*- coding: utf-8 -*-
"""
异步批量写入模块。

存在原因：
    高并发测试下每秒可能产生数万条写入，
    若在事件循环中同步写 SQLite 会阻塞事件循环，
    导致 WebSocket 心跳发不出去，进而触发 6 秒自动停止保护。

设计：
    1. 业务协程只做非阻塞入队；
    2. 后台单写线程批量取出任务并放在一个事务中提交；
    3. 批量大小与最大等待时间均可调节，兼顾吞吐与实时性。
"""

import queue
import sqlite3
import threading
import time
from typing import List, Tuple

from ..logging import logger

# 单批次最大写入条数
DEFAULT_BATCH_SIZE = 500
# 单批次最大等待时间（秒）
DEFAULT_FLUSH_INTERVAL = 0.2
# 队列上限，超过后丢弃最旧的任务以保护内存
DEFAULT_QUEUE_SIZE = 200000


class AsyncDatabaseWriter:
    """
    异步批量写入器。

    参数：
        db_path: SQLite 文件路径
        batch_size: 单批次最大条数
        flush_interval: 单批次最大等待时间
        queue_size: 队列容量
    """

    def __init__(self, db_path: str, batch_size: int = DEFAULT_BATCH_SIZE,
                 flush_interval: float = DEFAULT_FLUSH_INTERVAL,
                 queue_size: int = DEFAULT_QUEUE_SIZE):
        self._db_path = db_path
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.01, flush_interval)
        self._queue: "queue.Queue" = queue.Queue(maxsize=queue_size)
        self._connection: sqlite3.Connection = sqlite3.connect(
            db_path, check_same_thread=False
        )
        self._stop_event = threading.Event()
        self._thread: threading.Thread = None
        self._dropped = 0
        self._written = 0
        self._lock = threading.Lock()

    # ---------------- 生命周期 ----------------

    def start(self) -> None:
        """启动后台写线程。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="radius-db-writer", daemon=True)
        self._thread.start()
        logger.debug("database", "异步写入线程已启动", {"path": self._db_path})

    def stop(self, timeout: float = 5.0) -> None:
        """停止后台写线程并冲刷剩余数据。"""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None
        self._flush_once(force=True)
        try:
            self._connection.close()
        except Exception:
            pass

    # ---------------- 写入接口 ----------------

    def submit(self, sql: str, params: tuple) -> bool:
        """
        提交一条写入任务。

        返回：
            True 表示入队成功，False 表示队列已满被丢弃。
        """
        try:
            self._queue.put_nowait((sql, params))
            return True
        except queue.Full:
            with self._lock:
                self._dropped += 1
            return False

    def submit_many(self, tasks: List[Tuple[str, tuple]]) -> int:
        """
        批量提交写入任务。

        返回：
            实际入队条数。
        """
        accepted = 0
        for sql, params in tasks:
            if self.submit(sql, params):
                accepted += 1
        return accepted

    @property
    def pending(self) -> int:
        """待写入任务数量。"""
        return self._queue.qsize()

    @property
    def written(self) -> int:
        """已写入任务数量。"""
        with self._lock:
            return self._written

    @property
    def dropped(self) -> int:
        """被丢弃的任务数量。"""
        with self._lock:
            return self._dropped

    # ---------------- 内部实现 ----------------

    def _run(self) -> None:
        """后台写线程主循环。"""
        while not self._stop_event.is_set():
            self._flush_once(force=False)
        # 退出前冲刷剩余数据
        self._flush_once(force=True)

    def _flush_once(self, force: bool = False) -> None:
        """
        执行一次批量冲刷。

        参数：
            force: True 时把队列中全部任务写完再返回
        """
        if self._queue.empty():
            if not force:
                time.sleep(self._flush_interval)
            return
        batch = []
        deadline = time.time() + self._flush_interval
        while len(batch) < self._batch_size:
            try:
                if force:
                    batch.append(self._queue.get_nowait())
                else:
                    remaining = deadline - time.time()
                    if remaining <= 0 and batch:
                        break
                    batch.append(self._queue.get(timeout=max(0.001, remaining)))
            except queue.Empty:
                break
        if not batch:
            return
        try:
            cursor = self._connection.cursor()
            cursor.execute("BEGIN")
            for sql, params in batch:
                cursor.execute(sql, params)
            self._connection.commit()
            cursor.close()
            with self._lock:
                self._written += len(batch)
        except Exception as exc:
            try:
                self._connection.rollback()
            except Exception:
                pass
            logger.error("database", "批量写入失败，已回滚", {
                "count": len(batch),
                "error": str(exc),
            }, exc_info=True)
        if not force and self._queue.empty():
            time.sleep(self._flush_interval)
