# -*- coding: utf-8 -*-
"""敌人数值的**取法**：从库里取、关卡本地覆盖、换形态技能的黑板。

两个原本是 `BattleSimulator` 的方法（`sim.py:1556` / `sim.py:1467`），本模块把
**纯的那部分**搬出来。

## 搬的时候要分清楚的一件事

`_enemy_stats` 是**纯**的——它只读两个外接钩子（`enemy_at` 取数器、`stage`），
不碰模拟器状态 ⇒ 整体搬走，一点不改。

⚠ 但 `_note_mode_skill` **不是纯的**：它写 `self.mode_skill` / `self._mode_next`，
即"造一个敌人"会**顺手改模拟器状态**。`spec.py` 现在靠 `copy.copy(sim)` 绕开它
（`spec.py:1005-1007` 有说明）。

所以这里只搬它的**纯部分**——`mode_skill_from_stats(stats)` 只管**算出**那张黑板，
**不写任何地方**。落不落、落到谁身上，由调用方决定：

* 模拟器那边：`_note_mode_skill` 拿它算完再写自己的实例字段（行为一字不改）；
* 规格那边：直接把它算出来的值放进规格，不需要一个"要写状态的模拟器"。

⚠ **别把副作用一起搬过来**。原版那个写法之所以要 `copy.copy(sim)`，
就是因为"造模板"和"要跑的那一份"是同一个对象；副作用一旦跟着搬，
就会提前改掉要跑的那一份，而且**看不出来**。
"""
from __future__ import annotations

from typing import Any, Callable

__all__ = ["enemy_stats", "mode_skill_from_stats", "MODE_SKILL_KEY"]


#: 换形态技能的 `prefabKey`。写死它是原样搬——原版 `_note_mode_skill` 就是按它挑的。
MODE_SKILL_KEY = "Skill_Revelation"


def enemy_stats(enemy_at: Callable[[str, int], Any], stage: Any,
                enemy_id: str, level: int) -> Any:
    """取敌人数值，**支持关卡自带的敌人定义**（``enemyDbRefs`` 里 ``useDb: false``）。

    那些 id（怀黍离的 ``enemy_1398_dhdcr_b`` / ``enemy_1399_dhtb_b``）不在
    属性库里，整份数据写在关卡文件里，只有 ``prefabKey`` 指向的那个在库里。
    库那一步取不到时，才走本地覆盖；本地也没有就**照原样把异常抛出去**——
    静默返回一个空数值会让召唤链"看起来跑了、其实什么都没算"。
    """
    try:
        return enemy_at(enemy_id, level)
    except Exception:                                            # noqa: BLE001
        local = stage.local_enemies().get(enemy_id)
        if not local:
            raise
        owner = getattr(enemy_at, "__self__", None)
        if owner is None or not hasattr(owner, "with_overwrite"):
            raise
        return owner.with_overwrite(enemy_id, local, level)


def mode_skill_from_stats(stats: Any) -> dict[str, float] | None:
    """从 `stats` 的 `skills_raw` 里读换形态技能的黑板；没有就返回 None。

    ⚠ **纯函数**：只算不写。原版是边算边写 `sim.mode_skill` / `sim._mode_next`，
    那个副作用留在 `BattleSimulator._note_mode_skill` 里，**不在这里**。

    不写死数字：cd 30 / init 25 / idle 5 / disarmed 7 都是这一关的实际取值，
    换关卡换数值也不会失准。

    `trigger` 的语义是从同类敌人反推出来的：`enemy_10190_pppham`（几点了钟）的
    `PowerAttackTrigger.trigger_cnt = 2`，对应描述「**数次攻击后**使目标晕眩」
    ——即"条件满足几次才触发"。`Mode_A/trigger_cnt` 与 `Mode_B/trigger_cnt`
    都写着 2，两个取到哪个都一样。
    """
    for sk in (getattr(stats, "skills_raw", None) or ()):
        if str(sk.get("prefabKey") or "") != MODE_SKILL_KEY:
            continue
        bb = {b.get("key"): b.get("value") for b in (sk.get("blackboard") or [])}
        tbb = getattr(stats, "talent_blackboard", None) or {}
        return {
            "cd": float(sk.get("cooldown") or 0.0),
            "init": float(sk.get("initCooldown") or 0.0),
            "idle": float(bb.get("idle_duration") or 0.0),
            "disarm": float(bb.get("disarmed_duration") or 0.0),
            "trigger": float(tbb.get("Mode_A.trigger_cnt")
                             or tbb.get("Mode_B.trigger_cnt") or 0.0),
        }
    return None
