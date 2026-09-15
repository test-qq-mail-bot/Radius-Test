# -*- coding: utf-8 -*-
"""
测试会话快照模块。

职责：
    把 TestSession 的运行时状态组装为前端可直接消费的快照字典，
    供 WebSocket 实时推送与接口查询共用。

拆分原因：
    session.py 已接近单文件 20KB 上限（项目书 18.2），而快照组装是纯数据变换、
    与调度逻辑耦合度低，故独立成本模块。

掉线指标口径（需求2 / 需求3）：
    掉线率 = 累计掉线用户数 / 当前在线数 × 100%；
    平均掉线前在线时长 = 累计「掉线前在线时长」/ 掉线次数（需求2 新口径）。
    其中「累计掉线前在线时长」在每次判定掉线时按 start_time -> offline_start_time 结算，
    恢复后不再累加离线时长；因此表示用户掉线前平均保持了多久在线。
"""

from . import state as state_mod


def build(session) -> dict:
    """
    生成测试会话实时快照。

    参数：
        session: TestSession 实例（读取其统计字段与在线会话管理器状态）。
    """
    success_rate = (session.success_count / session.total * 100) if session.total else 0.0
    failed_rate = (session.failed_count / session.total * 100) if session.total else 0.0

    online_total = session.online_count
    dropped_users = session._online.dropped_user_count
    drop_rate = (dropped_users / online_total * 100) if online_total else 0.0
    drop_count = session._online.drop_count
    avg_drop_duration = (session._online.total_drop_duration / drop_count) if drop_count else 0.0
    current_offline = session._online.current_offline_count

    return {
        "task_id": session.task_id,
        "status": session.status,
        "status_text": state_mod.state_text(session.status),
        "stop_reason": session.stop_reason,
        "stop_reason_text": state_mod.stop_reason_text(session.stop_reason),
        "server": session.server_name,
        "protocol": session.protocol,
        "elapsed_seconds": session.elapsed_seconds,
        "total": session.total,
        "success": session.success_count,
        "failed": session.failed_count,
        "timeout": session.timeout_count,
        "cancelled": session.cancelled_count,
        "online": online_total,
        # 掉线指标：随快照一并暴露给前端实时指标
        "drop_rate": round(drop_rate, 2),
        "avg_drop_duration": round(avg_drop_duration, 3),
        "dropped_users": dropped_users,
        "current_offline": current_offline,
        "success_rate": round(success_rate, 2),
        "failed_rate": round(failed_rate, 2),
        "max_response_time": round(session.max_response_time, 3),
        "min_response_time": round(session.min_response_time, 3),
        "concurrency": session._controller.snapshot(),
        "rate": session._limiter.snapshot(),
    }
