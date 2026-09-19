# -*- coding: utf-8 -*-
"""runes 黑板的**取值原语**。

## 为什么单独一个模块

这三个（四个）函数原本住在 `ak_tactic/battle/environment.py` 里，是那 626 行中的
**纯函数**部分：只吃 `(runes / entries, key, difficulty)`，**不碰任何引擎状态**。

而 `battle/stage_mul.py` 用它们（关卡级生命点改写、费用回复倍率），
`stage_mul` 又要被搬到 `battle/` 之外去（见 `docs/spec-extraction-surface.md`）。
两条路只能选一条：

* 让新家 import `battle.environment` —— **新家反过来依赖要删的东西**，白搬；
* 把它们搬到这里，`battle/environment.py` 改成从这里 import —— 一份实现、两个消费者。

选后者。⚠ 搬迁口径是**原样搬（move）**，不是重写：这些函数的行为没有任何判据
能完整覆盖（见下），重写等于把它们悄悄改掉。

## 判据的边界（搬之前先问过"看不见会怎样"）

`mask_applies` / `find_rune` 的行为只在**同一关有多条同名 rune** 时才分叉
（`act31side_ex08` 的 `env_system_new` 有 NORMAL 与 FOUR_STAR 两条，黑板数值相同但
`init_pollut_value` 不同——`1,1:0` vs `4,4:100`）。而**当前流水线恒为 NORMAL**
（`Verifier` 不传 `environment_difficulty`），所以 FOUR_STAR 那条是**沉默区**。
⇒ 一旦重写出错，没有任何判据会响。这就是"原样搬"的理由。

## 所属

这里的东西**不依赖 `battle/`，也不依赖 `simgo/`** —— 所以放在 `ak_tactic/frontend/`
而不是 `ak_tactic/simgo/frontend/`：后者会踩到
`simgo/__init__` → `spec` → `battle.talents` 的循环导入。
"""
from __future__ import annotations

from typing import Iterable

__all__ = ["mask_applies", "find_rune", "bb_number", "bb_text"]


# ================================================================ 一、runes 黑板

def mask_applies(mask: str | None, difficulty: str) -> bool:
    """这条 rune 在当前难度下生效吗。

    `ALL` 必须认——`act31side_08` 用的就是它，不认则整条环境系统静默消失。
    """
    return mask in ("ALL", "", None) or mask == difficulty


def find_rune(runes: Iterable[dict], key: str,
              difficulty: str = "NORMAL") -> dict | None:
    """按 `difficultyMask` **消歧**后取 rune，取不到返回 None。

    ⚠ **禁止取第一条**：同一关常有多条同名 rune（`act31side_ex08` 的
    `env_system_new` 有 NORMAL 与 FOUR_STAR 两条，黑板数值相同但
    `init_pollut_value` 不同——`1,1:0` vs `4,4:100`）。取错了不会报错，
    只是污染点画在了别处。
    """
    hit = None
    for r in runes:
        if r.get("key") == key and mask_applies(r.get("difficultyMask"), difficulty):
            hit = r                      # 同键同难度若仍有多条，取最后一条
    return hit


def bb_number(entries: Iterable[dict] | None, key: str) -> float | None:
    """从黑板上取**数值**——值住 `value`，不是 `valueStr`。

    这是本项目记录在案的一次真错：只读 `valueStr` 会得出「五个参数全是 None」，
    进而误判「环境系统不在 gamedata 里」。
    """
    for e in entries or ():
        if e.get("key") == key:
            v = e.get("value")
            if isinstance(v, (int, float)):
                return float(v)
            return None
    return None


def bb_text(entries: Iterable[dict] | None, key: str) -> str | None:
    """从黑板上取**字符串**——值住 `valueStr`（`key` / `init_pollut_value` 走这条）。"""
    for e in entries or ():
        if e.get("key") == key:
            v = e.get("valueStr")
            if isinstance(v, str) and v.strip():
                return v.strip()
            return None
    return None
