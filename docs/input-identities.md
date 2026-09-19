# 输入身份登记处（`sha16` ＋ 来源约定）

**为什么有这个文件**：2026-09-20 实测，`roster_max_modelled.json` 的**实物**随旁支检出废弃而消失
（它住在易失的 `out/`、且**从未入库**），而**基线只记了它的哈希** ⇒ 19 份读数当场不可复现。
同日 `data/skland/roster_*.json`（森空岛账号名册）也发现不在场。
⇒ **"丢了就再也量不出来"的输入，必须有身份登记**；实物要不要入库是另一件事（隐私口径）。

读它的判据：`tools/acceptance.py` 的 `roster_identity_item`（门内 `[1c]`）与
`skland_identity_item`（门内 `[1d]`）。下面那一块是**机器可读**的（`key = value`），
**判据读不到就报缺口，不猜**；改这一块要连同判据一起复核。

```identity
# 当前生效的满练度已建模名册：实物已入库 fixtures/（`_find` 是 fixtures 优先 ⇒ 重生成必须写这个落点）
roster_max_modelled_sha16 = 21d3045f119a5d04
roster_max_modelled_path = fixtures/roster_max_modelled.json
roster_max_modelled_source = python tools/max_roster.py --source data/operbox/Arknights_OperBox_Export.json --out fixtures/roster_max_modelled.json
roster_max_modelled_authority = tools/max_roster.py（源导出按 tools/operbox_path.py 的约定找；名单出处 docs/batch3-plan.md）

# 森空岛账号名册：**实物不入库**（博士自己的账号数据，隐私口径），只登记身份
# ⚠ 登记需要一个**在场值** ⇒ 实物不在场时这里只能是「未登记」，判据报缺口（不计红、也不许记成通过）
skland_roster_sha16 = 未登记
skland_roster_glob = data/skland/roster_*.json
skland_roster_source = python tools/skland.py login <手机号> <验证码> && python tools/skland.py fetch && python tools/roster.py
skland_roster_authority = tools/skland.py（森空岛账号导出；consumer 之一 tools/check_verify.py）
```

## 各输入的口径（人读部分，判据不解析）

| 输入 | 谁会用到 | 不在场时 | 换了会怎样 |
| --- | --- | --- | --- |
| `fixtures/roster_max_modelled.json` | 金标准 19 份、深水线、对拍台账 | **红**（门内 `[1c]`）——它是判据集的一部分，缺了就是缺陷 | 换名册＝换输入，基线数字不可比 |
| `data/skland/roster_*.json` | `tools/check_verify.py`（71 项的主体）等 | **未跑＋原因**（门内 `[1d]`）：账号导出，别人机器上不在场是常态 | **红**（sha16 ≠ 登记值），并给登记命令 |

## 登记/复核怎么做

* **首次登记（需要一个在场值）**：`python tools/acceptance.py --register-roster`
  —— 只写本文件里那一行，**不碰实物、不进 `fixtures/`**；实物不唯一时**拒绝登记**（登记值必须唯一）。
* **复核**：`python tools/acceptance.py`（门内 `[1c]`/`[1d]` 会打印实物路径、实物 sha16 与登记值）。
* **实物不在场时不许做的事**：不许凭空写一个哈希、不许把"不在场"记成"通过"。
