"""
memprobe.py — OOM 定位打点（临时诊断工具）

在 BM25 / 活跃缓存重建、衰减周期结束时，把当前进程的内存相关计数
追加一行到持久盘上的 memprobe.csv。目的：找出哪个计数随 RSS 一起
单调增长。定位完成后本文件与各调用点应整体移除。

设计约束：
- 绝不抛异常：打点失败只丢一行数据，不能影响主流程。
- 只用标准库；RSS 读 /proc/self/status 的 VmRSS（Linux）。
"""
from __future__ import annotations

import csv
import gc
import os
import threading
from datetime import datetime, timezone

_LOCK = threading.Lock()

_HEADER = [
    "ts", "source", "rss_mb",
    "gc_gen0", "gc_gen1", "gc_gen2", "gc_objects",
    "active_cache_len", "bm25_docs", "bm25_tokens", "buckets_total",
]


def _rss_mb() -> float | None:
    try:
        with open("/proc/self/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return round(int(line.split()[1]) / 1024, 1)
    except Exception:
        pass
    return None


def probe(
    path: str,
    source: str,
    *,
    active_cache_len: int | None = None,
    bm25_docs: int | None = None,
    bm25_tokens: int | None = None,
    buckets_total: int | None = None,
) -> None:
    """追加一行打点数据到 path 指向的 csv。任何失败静默吞掉。"""
    try:
        counts = gc.get_count()
        row = [
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source,
            _rss_mb(),
            counts[0], counts[1], counts[2],
            len(gc.get_objects()),
            active_cache_len, bm25_docs, bm25_tokens, buckets_total,
        ]
        with _LOCK:
            new_file = not os.path.exists(path)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(_HEADER)
                w.writerow(["" if v is None else v for v in row])
    except Exception:
        pass
