"""把仪表盘要用的头像按"前一条是谁"逐条算出来。

`_avatar_for` 需要知道上一条的状态才能判断"是不是刚回到正轨"，
所以不能在列表推导里单条调用。这里统一处理，避免各处写法不一致。
"""
from __future__ import annotations

from typing import Any, Iterable


def with_avatars(records: Iterable[dict], avatar_for) -> list[dict]:
    """给每条记录补上 avatar 字段。

    avatar_for(rec, prev) -> 头像 key。prev 是同一条序列里的前一条（可能为 None）。
    """
    out: list[dict] = []
    prev: dict | None = None
    for r in records:
        out.append({**r, "avatar": avatar_for(r, prev)})
        prev = r
    return out
