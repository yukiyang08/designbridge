"""Stage-timing helper for diagnosing pipeline latency.

Usage:
    with log_stage("renderer.hf_inference", task_id=task_id):
        ...

Prints ``[timing][task_id] label: X.XXs`` to stdout when the block exits
(including on exception, so failed/skipped attempts still show how long
they took before failing).
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import TypeVar

T = TypeVar("T")


@contextmanager
def log_stage(label: str, task_id: str | None = None):
    prefix = f"[timing][{task_id}]" if task_id else "[timing]"
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        print(f"{prefix} {label}: {elapsed:.2f}s")


def timed_call(label: str, task_id: str | None, fn, *args, **kwargs) -> T:
    """Call ``fn(*args, **kwargs)`` wrapped in :func:`log_stage`; returns fn's result."""
    with log_stage(label, task_id=task_id):
        return fn(*args, **kwargs)


def fal_subscribe(label: str, application: str, arguments: dict, **kwargs):
    """``fal_client.subscribe`` 包一層：記錄總時間、排隊時間與 fal 回報的純推論時間。

    用來判斷慢在排隊/傳輸還是去噪本身（決定是否值得自架 FLUX）。
    """
    import fal_client

    start = time.perf_counter()
    started_at: list[float] = []  # 第一次收到 InProgress 的時間點
    user_cb = kwargs.pop("on_queue_update", None)

    def _on_update(status):
        if not started_at and isinstance(status, fal_client.InProgress):
            started_at.append(time.perf_counter())
        if user_cb:
            user_cb(status)

    result = None
    try:
        result = fal_client.subscribe(application, arguments=arguments, on_queue_update=_on_update, **kwargs)
        return result
    finally:
        total = time.perf_counter() - start
        parts = []
        if started_at:
            parts.append(f"queue {started_at[0] - start:.2f}s")
        timings = result.get("timings") if isinstance(result, dict) else None
        inference = (timings or {}).get("inference")
        if isinstance(inference, (int, float)):
            parts.append(f"fal inference {inference:.2f}s")
        detail = f" ({', '.join(parts)})" if parts else ""
        status = "" if result is not None else " [failed]"
        print(f"[timing] fal.{label} {application}: total {total:.2f}s{detail}{status}")
