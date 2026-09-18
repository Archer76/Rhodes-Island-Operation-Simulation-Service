"""终端界面（TUI）的自检。

    python tools/check_tui.py

分九类：

1. **惰性导入**——`import ak_tactic`、建 CLI parser、跑别的子命令，**都不许**
   把 `textual` 拉进来。它是本项目唯一的重依赖，没装它也必须能跑 `db`/`formula`；
2. **命令注册**——`tui` 子命令在，`--no-login` / `--stage` / `--squad` 都在；
3. **数据访问层**——名册的三个来源、把关卡表读出来的路径、配置写在仓库**外**；
4. **界面无头冒烟**——用 `App.run_test()` 真挂一遍：选关卡屏有行、回车能推进、
   模式能切、勾选能读回。这一类比断言签名有用得多，`Selection(initial=…)`
   那种参数不存在的问题是它抓出来的；
5. **边界**——关卡表为空时给出的是「关卡名获取失败」加一句能照做的事，
   而不是一句"没有数据"。
6. **终端二维码**——惰性导入、矩阵方正、纯文本与 ANSI 两路都能解回原矩阵、
   字符在 cp936 下可编码（`▀` 不行、`▄` 行）；
7. **选人界面的按键**——空格勾选、回车推进，用 `pilot.press()` 真按；
8. **MAA 导出**——模组编号表（含 D 型）、`stage_name` 用 levelId、不写协议里
   不存在的 `time` 键、编队要写进 `doc.details`、落盘按序号追加。
9. **回主界面**——结果屏按 H 把屏幕栈弹回「基屏 + [0]」，并把上一轮的
   stage/squad/result 清空（不清就会带着上次的关卡从半路开始，而屏幕写着「准备」）。

`textual` 装不上时第 4 类整节跳过并**如实报出来**，不假装通过。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.db import DEFAULT_DB_PATH                                  # noqa: E402

_FAILED: list[str] = []
_PASSED = 0
_SKIPPED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def skip(label: str, why: str) -> None:
    _SKIPPED.append(label)
    print(f"  [skip] {label}   {why}")


# ---------------------------------------------------------------- 名册夹具
#
# **界面自检不能依赖「这台机器当前登录的是哪个号」。**
#
# `load_roster()` 是**按当前账号**取名册的（有意的，见 [16] 节），而名册缓存
# 要跑过 `skland fetch` + `roster.py` 才有：换过账号、或者从没拉过的机器上真名册
# 根本不存在。此时界面自检若还用真名册，红的是「这台机器没拉过名册」——
# 一条与本项目代码无关的环境状态，而不是被测的那段界面逻辑。
#
# 夹具只喂给**界面**。判据本身（名册必须按当前账号取、不许拿别人号的名册顶上）
# 在 [16] 节用临时凭据 + 临时名册文件单独验，那里会把夹具摘掉。

_FIXTURE_OPS = (
    # (charId, 名字, 主职业, 子职业, 精英, 等级, 潜能)
    # 八个主职业各 4 个**不同子职业**（组合数够多，"切主-子分类组数变多"才咬得动），
    # 练度按序号铺开，好让三档门槛都咬得动。charId 与子职业名都取自本地库。
    ("char_180_amgoat", "艾雅法拉", "CASTER", "中坚术师", 2, 90, 6),
    ("char_450_necras", "死芒", "CASTER", "塑灵术师", 2, 80, 3),
    ("char_2015_dusk", "夕", "CASTER", "扩散术师", 2, 60, 1),
    ("char_1040_blaze2", "烛煌", "CASTER", "本源术师", 1, 55, 1),
    ("char_003_kalts", "凯尔希", "MEDIC", "医师", 2, 90, 6),
    ("char_1020_reed2", "焰影苇草", "MEDIC", "咒愈师", 2, 80, 3),
    ("char_1052_kalts2", "凯尔希·思衡托", "MEDIC", "守望者", 2, 60, 1),
    ("char_4042_lumen", "流明", "MEDIC", "疗养师", 1, 55, 1),
    ("char_222_bpipe", "风笛", "PIONEER", "冲锋手", 2, 90, 6),
    ("char_112_siege", "推进之王", "PIONEER", "尖兵", 2, 80, 3),
    ("char_4087_ines", "伊内丝", "PIONEER", "情报官", 2, 60, 1),
    ("char_249_mlyss", "缪尔赛思", "PIONEER", "战术家", 1, 55, 1),
    ("char_4138_narant", "娜仁图亚", "SNIPER", "回环射手", 2, 90, 6),
    ("char_1035_wisdel", "维什戴尔", "SNIPER", "投掷手", 2, 80, 3),
    ("char_197_poca", "早露", "SNIPER", "攻城手", 2, 60, 1),
    ("char_1013_chen2", "假日威龙陈", "SNIPER", "散射手", 1, 55, 1),
    ("char_4132_ascln", "阿斯卡纶", "SPECIAL", "伏击客", 2, 90, 6),
    ("char_1023_ghost2", "归溟幽灵鲨", "SPECIAL", "傀儡师", 2, 80, 3),
    ("char_1028_texas2", "缄默德克萨斯", "SPECIAL", "处决者", 2, 60, 1),
    ("char_1015_aglna2", "予愿安洁莉娜", "SPECIAL", "巡空者", 1, 55, 1),
    ("char_1047_halo2", "溯光星源", "SUPPORT", "凝滞师", 2, 90, 6),
    ("char_206_gnosis", "灵知", "SUPPORT", "削弱者", 2, 80, 3),
    ("char_2023_ling", "令", "SUPPORT", "召唤师", 2, 60, 1),
    ("char_1012_skadi2", "浊心斯卡蒂", "SUPPORT", "吟游者", 1, 55, 1),
    ("char_311_mudrok", "泥岩", "TANK", "不屈者", 2, 90, 6),
    ("char_416_zumama", "森蚺", "TANK", "决战者", 2, 80, 3),
    ("char_1034_jesca2", "涤火杰西卡", "TANK", "哨戒铁卫", 2, 60, 1),
    ("char_2025_shu", "黍", "TANK", "守护者", 1, 55, 1),
    ("char_1049_catap2", "雷狼龙S空爆", "WARRIOR", "佣兵", 2, 90, 6),
    ("char_010_chen", "陈", "WARRIOR", "剑豪", 2, 80, 3),
    ("char_017_huang", "煌", "WARRIOR", "强攻手", 2, 60, 1),
    ("char_1051_headb2", "怒潮凛冬", "WARRIOR", "撼地者", 1, 55, 1),
)


def fixture_roster():
    """一份造出来的名册。**不是**本机登录那个号的名册。

    `note` 与真森空岛名册**同款措辞**：那条判据（"森空岛来的名册要说清含专精"）
    验的是"这份名册是什么口径"，夹具既然代表一份完整的森空岛名册，
    就该说同样的话，否则界面自检会因为"夹具没写专精"而红。
    """
    from ak_tactic.tui import data as _D
    ops = [_D.Operator(char_id=cid, name=n, profession=p, sub_profession=sp,
                       elite=e, level=lv, potential=pot, trust=100.0,
                       module="uniequip_002_x" if i == 0 else None,
                       module_level=3 if i == 0 else 0,
                       equipped_status="ok" if i == 0 else "")
           for i, (cid, n, p, sp, e, lv, pot) in enumerate(_FIXTURE_OPS)]
    return _D.Roster(source="skland", operators=ops, uid="fixture",
                     nick="自检夹具", path="(自检夹具，不是真名册)",
                     note="含专精与模组等级（森空岛口径，最准）"
                          "〔自检夹具，不是本机那个号的名册〕")


def install_fixture_roster():
    """把 `data.load_roster` 换成夹具，返回复原用的旧函数。

    `RiosApp.on_mount` 调的就是 `data.load_roster()`，所以换掉模块属性即可。
    """
    from ak_tactic.tui import data as _D
    old = _D.load_roster
    _D.load_roster = fixture_roster
    return old


def restore_roster(old) -> None:
    from ak_tactic.tui import data as _D
    _D.load_roster = old


# ---------------------------------------------------------------- [1] 惰性导入

def check_lazy_import() -> None:
    print("\n[1] 惰性导入（textual 只能被 tui 子命令拉进来）")
    import subprocess

    code = (
        "import sys;"
        "import ak_tactic.cli as c;"
        "c.build_parser();"
        "bad=[m for m in sys.modules if m=='textual' or m.startswith('textual.')];"
        "print('IMPORTED' if bad else 'CLEAN')"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, cwd=str(Path(__file__).resolve().parent.parent))
    out = (r.stdout or "").strip().splitlines()
    last = out[-1] if out else ""
    check("import ak_tactic + 建 parser 不会导入 textual", last == "CLEAN",
          last or (r.stderr or "").strip()[-200:])

    pkg = Path(__file__).resolve().parent.parent / "ak_tactic" / "tui" / "__init__.py"
    src = pkg.read_text(encoding="utf-8")
    check("ak_tactic/tui/__init__.py 自己不 import textual 与 app",
          "textual" not in src.split('"""')[-1] and "from .app" not in src,
          "只在 cli 的 cmd_tui 里惰性导入")


# ---------------------------------------------------------------- [2] 命令注册

def check_registration() -> None:
    print("\n[2] 命令注册")
    from ak_tactic.cli import build_parser

    p = build_parser()
    acts = {a.dest for a in p._actions}
    check("有 tui 子命令", "tui" in _subcommands(p), "、".join(sorted(_subcommands(p))))

    tu = _subparser(p, "tui")
    opts = {a.dest for a in tu._actions} if tu else set()
    check("tui 认 --no-login（测试全新启动的流程用）", "no_login" in opts)
    check("tui 认 --stage / --squad（预填）",
          {"stage", "squad"} <= opts, "、".join(sorted(opts)))
    check("--no-login 的 dest 没被 argparse 吃掉", tu is not None
          and tu.get_default("no_login") is False)
    del acts


def _subcommands(parser):
    for a in parser._actions:
        if hasattr(a, "choices") and isinstance(a.choices, dict):
            return set(a.choices)
    return set()


def _subparser(parser, name):
    for a in parser._actions:
        if hasattr(a, "choices") and isinstance(a.choices, dict):
            return a.choices.get(name)
    return None


# ---------------------------------------------------------------- [3] 数据层

def check_data_layer() -> None:
    print("\n[3] 数据访问层")
    from ak_tactic import tui

    # 包整体导入不该带出 textual（`__init__` 只有 docstring）。
    # **必须开子进程测**：本进程后面要真导入 textual 跑界面冒烟，同进程测不出来。
    import subprocess

    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; import ak_tactic.tui;"
         "bad=[m for m in sys.modules if m=='textual' or m.startswith('textual.')];"
         "print('IMPORTED' if bad else 'CLEAN')"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parent.parent))
    last = (r.stdout or "").strip().splitlines()
    check("单独 import ak_tactic.tui 不会带出 textual",
          (last[-1] if last else "") == "CLEAN",
          (last[-1] if last else (r.stderr or "").strip()[-160:]))

    from ak_tactic.tui import data as D

    # 默认目录 = **工具根目录**下的 Guides/（不是 ~/Guides）：
    # 一份克隆自包含，换机器/换用户都跟着走。
    root = Path(__file__).resolve().parent.parent
    check("默认数据目录是工具根目录下的 Guides/",
          D.default_guides_dir() == root / "Guides",
          str(D.default_guides_dir()))
    check("Guides/ 已进 .gitignore（作业文件含玩家自己的编队）",
          "Guides/" in (root / ".gitignore").read_text(encoding="utf-8"))

    cfg = D.config_path()
    check("配置写在仓库外（~/.rios/），不往仓库里落本机路径",
          root not in cfg.parents and cfg.parent.parent == Path.home(),
          str(cfg))

    r = D.load_roster()
    if r is None:
        skip("名册三来源", "本机一个都没有（既无森空岛缓存也无 OperBox）")
    else:
        check("名册读到了", bool(r.operators), f"{r.source}，{len(r.operators)} 名")
        check("名册标注了来源与完整度（森空岛=完整，OperBox=降级）",
              (r.source == "skland") == r.complete, f"complete={r.complete}")
        if r.source == "operbox":
            check("降级来源必须写明缺了什么", "降级" in r.note, r.note[:60])
        else:
            check("森空岛名册带专精/模组口径", "专精" in r.note, r.note)
        top = r.top(1)
        check("按练度排序有结果", bool(top), top[0].name if top else "")

    del tui


def check_stage_access() -> None:
    print("\n[3b] 关卡表的读取路径")
    from ak_tactic.tui import data as D

    if not Path(DEFAULT_DB_PATH).exists():
        skip("关卡表", "库还不存在，先跑 db build")
        return
    rows = D.stage_rows(limit=5)
    if not rows:
        skip("关卡表", "stage 表是空的（要联网建，见 db stage-fetch）")
        return
    check("能读出关卡行", len(rows) > 0, f"{len(rows)} 行")
    # 排序：普通难度在四星限定版之前，且 `2-7` 要排在 `2-10` 前
    allrows = D.stage_rows(keyword="SR-EX", limit=0)
    ids = [r["level_id"] for r in allrows]
    normal = [i for i in ids if not i.endswith("#f#")]
    four = [i for i in ids if i.endswith("#f#")]
    check("普通难度排在四星限定版之前",
          bool(normal) and bool(four) and ids.index(normal[0]) < ids.index(four[0]),
          f"{ids[:3]} …")
    check("关键词筛选生效（SR-EX 只出 SR-EX）",
          all("SR-EX" in r["code"] for r in allrows), f"{len(allrows)} 行")


# ---------------------------------------------------------------- [4] 界面冒烟

def check_ui() -> None:
    print("\n[4] 界面无头冒烟（App.run_test）")
    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("界面冒烟", f"textual 没装（{exc}）——第 4 类整节跳过")
        return

    from ak_tactic.tui.app import RiosApp, _resolve_stage

    if Path(DEFAULT_DB_PATH).exists() and not _resolve_stage("SR-EX-8"):
        skip("界面冒烟", "关卡表空，选关卡屏没有行可测")
        return

    async def flow() -> dict:
        got: dict = {}
        app = RiosApp(skip_login=True)
        async with app.run_test(size=(120, 34)) as pilot:
            await pilot.pause()
            got["first"] = type(app.screen).__name__
            got["roster"] = app.state.roster
            from textual.widgets import DataTable, SelectionList

            # [1a] 章节屏：搜「月行水上」→ 唯一结果，回车直接选定
            app.screen.query_one("#kw").value = "月行水上"
            await pilot.pause()
            got["chapter_hits"] = len(app.screen._shown)
            # 全角关键词（中文输入法全角模式）要能筛出同样的结果：NFKC 归一
            app.screen.query_one("#kw").value = "ＡＣＴ５４ＳＩＤＥ"
            await pilot.pause()
            got["fw_hits"] = [c["key"] for c in app.screen._shown]
            app.screen.query_one("#kw").value = "月行水上"
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            got["after_chapter"] = type(app.screen).__name__

            # [1b] 分部屏：通学路 / 殡仪堂
            part_screen = app.screen
            got["parts"] = [p["title"] for p in part_screen.parts]
            part_screen.dismiss(next(p for p in part_screen.parts
                                     if p["zone_id"] == "act54side_zone2"))
            await pilot.pause()

            # [1c] 关卡屏
            got["after_part"] = type(app.screen).__name__
            got["stage_heading"] = getattr(app.screen, "heading", "")
            # **先读未筛的第一行**：它才是「这个分部的自然顺序」。
            # 先设关键词再读，读到的是筛剩的那一行，测的就不是列表格式了。
            tbl = app.screen.query_one("#stages", DataTable)
            got["table_rows"] = tbl.row_count
            try:
                got["first_label"] = str(tbl.get_row_at(0)[0])
            except Exception:                                       # noqa: BLE001
                got["first_label"] = ""
            app.screen.query_one("#kw").value = "SR-EX-8"
            await pilot.pause()
            rows = app.screen._rows
            got["row_names"] = [r.get("name") or "" for r in rows]
            target = next(r for r in rows if r["level_id"] == "act54side_ex08")
            app.screen.dismiss(target)
            await pilot.pause()

            # [2a] 先问「要不要手动加人」（需求第 9 条），再进选人界面
            got["after_stage_pick"] = type(app.screen).__name__
            if got["after_stage_pick"] == "SquadAskScreen":
                got["ask_rows"] = len(app.screen._choices)
                app.screen.dismiss(app.screen._choices[1])      # 我自己选
                await pilot.pause()
            got["after_ask"] = type(app.screen).__name__

            sl = app.screen.query_one("#squad", SelectionList)
            got["options"] = len(sl.options)
            got["mode0"] = app.state.mode
            await pilot.press("m")
            await pilot.pause()
            got["mode1"] = app.state.mode
            got["stage"] = app.state.stage
            if got["options"]:
                sl.select(sl.options[0].value)
                await pilot.pause()
                got["selected"] = list(sl.selected)
            del DataTable
        return got

    got = asyncio.run(flow())
    check("skip_login 时直接进**章节**屏（选关是第一层，不再是平铺列表）",
          got["first"] == "ChapterPickScreen", got["first"])
    check("搜「月行水上」能筛到唯一一条（活动名可搜）",
          got["chapter_hits"] == 1, f"{got['chapter_hits']} 条")
    check("**全角关键词**也能筛到（ＡＣＴ５４ＳＩＤＥ → act54side，NFKC 归一）",
          got["fw_hits"] == ["act54side"], str(got["fw_hits"]))
    check("选定一个多分部的活动后进「选哪一部分」屏",
          got["after_chapter"] == "PartPickScreen", got["after_chapter"])
    check("「月行水上」的分部正是通学路与殡仪堂",
          got["parts"] == ["通学路", "殡仪堂"], str(got["parts"]))
    check("选定分部后进关卡屏，标题带分部名",
          got["after_part"] == "StagePickScreen" and "殡仪堂" in got["stage_heading"],
          f"{got['after_part']} / {got['stage_heading']}")
    check("关卡行的中文名取到了（不是只有代号）",
          any(got["row_names"]) and "虚无之顶" in got["row_names"],
          str(got["row_names"]))
    check("列表第一行是「代号　中文名」两段式",
          "SR-EX-1" in got["first_label"]
          and "欲求之础" in got["first_label"],
          got["first_label"])
    check("选定关卡后**先问要不要手动加人**（需求第 9 条）",
          got["after_stage_pick"] == "SquadAskScreen", got["after_stage_pick"])
    check("「要不要手动加人」正好两个选项",
          got.get("ask_rows") == 2, str(got.get("ask_rows")))
    check("答「我自己选」之后才进选人屏",
          got["after_ask"] == "SquadPickScreen", got["after_ask"])
    check("编队屏列出了名册里的人", got["options"] > 0, f"{got['options']} 人")
    check("模式默认是「允许程序补充」", got["mode0"] == "auto", got["mode0"])
    check("按 M 能切换成「只用我选的」（搜索层零改动）",
          got["mode1"] == "only", got["mode1"])
    check("选中的关卡带着 levelId（不是只带显示名）",
          bool(got["stage"]) and bool(got["stage"].get("level_id")),
          str(got["stage"].get("level_id")) if got["stage"] else "无")
    check("勾选能读回来（SelectionList 的取值路径通）",
          len(got.get("selected") or []) == 1, str(got.get("selected")))


def check_empty_stage_guard() -> None:
    print("\n[5] 边界与纪律")
    from ak_tactic.tui import app as A

    src = Path(A.__file__).read_text(encoding="utf-8")
    check("有专门的空表屏幕，且标题是「关卡名获取失败」",
          "关卡名获取失败" in src and "NoStageScreen" in src)
    check("空表屏幕给的是能照做的命令（db stage-fetch）", "db stage-fetch" in src)
    check("空表屏幕说明了「保留上一版表」", "保留上一版" in src)

    # 解算的进度反馈**不许**动核心搜索代码：靠轮询 Searcher.evaluated 实现。
    # 这里断的是"那个计数器真的存在且从 0 起"，以及 TUI 只用了公开入口。
    from ak_tactic.search import Searcher
    s = Searcher(verbose=False)
    check("Searcher 自带 evaluated 计数器（TUI 靠它给真实进度）",
          getattr(s, "evaluated", None) == 0, f"evaluated={s.evaluated}")
    check("TUI 只用 Searcher 的公开入口，没碰私有实现",
          "from ..search import Searcher" in src
          and "_eval_many" not in src and "_plan(" not in src,
          "未引用 _eval_many / _plan")

    # 进度条不许假装有精确分母
    check("进度条是「还在动」的脉动而非匀速假进度（有上限钳制）",
          "min(95.0" in src, "封顶在 95%，不假装能到 100%")


def check_qrterm() -> None:
    """[6] 终端二维码渲染（`ak_tactic/qrterm.py`）。

    一个画出来的二维码**看一眼是看不出对错的**——极性反了、错半格、
    静默区少一行，肉眼都是"一片黑白格子"。所以这里做**往返解码**：
    把自己画出来的字符流反解回布尔矩阵，与库给的矩阵逐格比对。
    这抓的是渲染器的错（那是我们写的），不是二维码编码的错（那是库的事）。
    """
    print("\n[6] 终端二维码渲染（ak_tactic/qrterm.py）")

    import subprocess

    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys; import ak_tactic.qrterm;"
         "bad=[m for m in sys.modules if m=='qrcode' or m.startswith('qrcode.')];"
         "print('IMPORTED' if bad else 'CLEAN')"],
        capture_output=True, text=True, cwd=str(root))
    last = (r.stdout or "").strip().splitlines()
    check("import ak_tactic.qrterm 不会带出 qrcode（惰性导入）",
          (last[-1] if last else "") == "CLEAN",
          (last[-1] if last else (r.stderr or "").strip()[-160:]))

    try:
        from ak_tactic.qrterm import matrix, render, render_plain
    except Exception as exc:                                    # noqa: BLE001
        skip("终端二维码", f"qrcode 不可用（{exc}）")
        return

    link = "hypergryph://scan_login?scanId=f14db1023a18b1fc63756f3f7393b9c3"
    m = matrix(link)
    check("矩阵是方的且边长合理（21..177，QR 版本 1..40）",
          len(m) > 0 and len(m) == len(m[0]) and 21 <= len(m) <= 177,
          f"{len(m)}x{len(m[0])}")
    check("静默区是白的（四条边全 False）",
          not any(m[0]) and not any(m[-1])
          and not any(row[0] or row[-1] for row in m), "border=2")

    # --- 纯文本版往返 ---
    art = render_plain(link)
    body = [ln for ln in art.splitlines() if not ln.startswith("（")]
    got = []
    for ln in body:
        # 每个模块两格：██ 暗 / 两空格 亮
        got.append([ln[i:i + 2] == "██" for i in range(0, len(m[0]) * 2, 2)])
    check("纯文本版能反解回原矩阵（逐格一致）", got == m,
          f"反解 {len(got)}x{len(got[0]) if got else 0}")
    check("纯文本版行数等于矩阵边长（一行一格）", len(body) == len(m))

    # --- ANSI 版往返 ---
    from ak_tactic.qrterm import _render_ansi
    ansi = _render_ansi(m)
    rows = ansi.splitlines()
    check("ANSI 版行数是矩阵的一半（▄ 一行压两格）",
          len(rows) == (len(m) + 1) // 2, f"{len(rows)} 行 / {len(m)} 格")
    back_top, back_bottom = [], []
    import re
    pat = re.compile(r"\x1b\[38;5;(\d+);48;5;(\d+)m\u2584")
    ok_shape = True
    for ln in rows:
        hits = pat.findall(ln)
        if len(hits) != len(m[0]):
            ok_shape = False
            break
        # ▄ 画下半格：前景 = 下格、背景 = 上格；16 黑(暗) / 231 白(亮)
        back_bottom.append([fg == "16" for fg, _bg in hits])
        back_top.append([bg == "16" for _fg, bg in hits])
    check("ANSI 版每行都恰好覆盖矩阵宽度", ok_shape,
          f"期望每行 {len(m[0])} 个半块")
    if ok_shape:
        merged = []
        for i in range(len(back_top)):
            merged.append(back_top[i])
            if i < len(back_bottom):
                merged.append(back_bottom[i])
        # **矩阵边长可能是奇数**（本例 41）：最后一行上半格是第 40 格，
        # 下半格是补出来的。故反解结果比矩阵多一行，要截断再比。
        check("ANSI 版能反解回原矩阵（前景=下格、背景=上格没错位）",
              merged[:len(m)] == m, "逐格一致（已按奇数边长截断）")
        if len(m) % 2 == 1:
            check("奇数边长时，最后一行的下半格是补出来的亮格",
                  not back_bottom[-1][0] and all(not v for v in back_bottom[-1]),
                  f"补出 {len(back_bottom[-1])} 格")

    # --- 编码安全：控制台代码页是 cp936 ---
    check("纯文本版结果 cp936 可编码（GBK 控制台不会崩）",
          _cp936_ok(art), "用户没设 PYTHONIOENCODING=utf-8 时也安全")
    check("ANSI 版结果 cp936 可编码", _cp936_ok(ansi),
          "用的是 U+2584 而不是 GBK 里没有的 U+2580")
    check("渲染器不用 U+2580（上半块，GBK 编不出来）",
          "\u2580" not in art and "\u2580" not in ansi)


def _cp936_ok(s: str) -> bool:
    try:
        s.encode("cp936")
        return True
    except UnicodeEncodeError:
        return False


def check_squad_keys() -> None:
    """[7] 选人界面的按键（博士 2026-09-17 实测报的 bug）。

    报的现象是「回车与空格都是选人，无法进入解算阶段」。根因有**两条**，
    都藏在 Textual 的默认行为里，而且**都不报错**：

    1. `space → select` 绑在 `SelectionList` 自己身上，`enter → select` 绑在
       父类 `OptionList` 上——**两个键都是"勾选"**，屏幕上没有任何一个键能推进；
    2. `SelectionList` 初始 `highlighted=None`，此时按空格连勾选都不会发生
       （`action_select` 找不到落点），于是"按了没反应"与"按了在勾选"
       两种症状混在一起，更难判断。

    修法：Screen 上的 `enter` 绑定加 `priority=True`（先于聚焦控件截获），
    并在 `on_mount` 里 `action_first()` 把光标落到第一项。
    """
    print("\n[7] 选人界面的按键（回车推进 / 空格勾选）")

    import asyncio

    from textual.widgets import SelectionList

    from ak_tactic.tui.app import RiosApp, SquadList, SquadPickScreen

    check("选人列表是 SquadList（把「空格 勾选」露给 Footer）",
          issubclass(SquadList, SelectionList),
          "Textual 默认把它设成 show=False，底部就看不出空格能勾人")
    shown = [b.key for b in SquadList.BINDINGS if getattr(b, "show", True)]
    check("SquadList 显式把 space 的提示亮出来", "space" in shown, str(shown))
    enter_b = [b for b in SquadPickScreen.BINDINGS if b.key == "enter"]
    check("选人屏的 enter 绑定带 priority=True（否则被控件吃掉）",
          bool(enter_b) and getattr(enter_b[0], "priority", False),
          "不带这个参数时回车只会反复勾选、永远推不动")

    async def run() -> dict:
        out: dict = {}
        app = RiosApp(skip_login=True)
        async with app.run_test(size=(100, 30)) as pilot:
            got: dict = {}
            app.push_screen(SquadPickScreen(), lambda r: got.update(r=r))
            await pilot.pause()
            lst = app.screen.query_one("#squad", SelectionList)
            out["highlighted_on_mount"] = lst.highlighted

            await pilot.press("space")
            await pilot.pause()
            out["after_space"] = list(lst.selected)
            out["still_there_after_space"] = isinstance(app.screen, SquadPickScreen)

            await pilot.press("down")
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            out["after_two"] = list(lst.selected)

            await pilot.press("enter")
            await pilot.pause()
            out["left_after_enter"] = not isinstance(app.screen, SquadPickScreen)
            out["passed"] = got.get("r")
        return out

    r = asyncio.run(run())
    check("上车时光标已落在第一项（不是 None）",
          r["highlighted_on_mount"] is not None, f"highlighted={r['highlighted_on_mount']}")
    check("按空格能勾上人（此前 highlighted=None 时静默无效）",
          len(r["after_space"]) == 1, str(r["after_space"]))
    check("勾选后仍停在选人屏（空格不是「开始解算」）",
          r["still_there_after_space"], "空格只勾选")
    check("可以多选（↓ 再空格得到两个人）", len(r["after_two"]) == 2,
          str(r["after_two"]))
    check("按回车能推进到解算屏（这就是博士报的那条）",
          r["left_after_enter"], "priority=True 生效")
    check("推进时把勾选的人带了过去",
          r["passed"] is not None and len(r["passed"]) == 2, str(r["passed"]))


# ---------------------------------------------------------------- [8] 导出

def check_maa_export() -> None:
    """导出成 MAA 作业：模组编号、stage_name、不写 time、编队要写明白。

    本节钉的都是**协议层面的事实**，不是实现细节——`module` 编号漏了 D 型
    曾让 6 个干员的模组要求被静默丢掉，`time` 字段则是协议里根本不存在的键。
    """
    print("\n[8] MAA 导出（ak_tactic/maa_export.py）")
    import json
    import subprocess
    import tempfile

    from ak_tactic import maa_export as maa
    from ak_tactic.plan import DeployOrder, Plan

    # ---- ① 模组编号表
    check("模组编号表覆盖 X/Y/A/D/B 五个（MAA 文档的 1-5 对应 χ γ α Δ β）",
          maa.MODULE_SLOT == {"X": 1, "Y": 2, "A": 3, "D": 4, "B": 5},
          str(maa.MODULE_SLOT))
    check("编号表里没有 Z（905 条模组里 Z 一次都没出现过，曾是占着 3 号位的死项）",
          "Z" not in maa.MODULE_SLOT)

    # ---- ② 逐条编号：已知四条回归 + D 型修复
    known = {"uniequip_002_chen3": 1, "uniequip_002_sbell2": 2,
             "uniequip_002_ascln": 1, "uniequip_002_wang": 1,
             "uniequip_002_logos": 4, "uniequip_002_ela": 4,
             "uniequip_004_ebnhlz": 4, "uniequip_003_thorns": 4,
             "uniequip_003_ifrit": 4, "uniequip_002_vvana": 4}
    got = {k: maa.module_slot(k) for k in known}
    check("模组编号逐条正确（含 D 型六条，此前一律被丢成 None）",
          got == known, str(got))
    check("基础证章没有 typeName2 → 判为无模组",
          maa.module_slot("uniequip_001_angel") is None, "能天使的基础证章")
    check("无模组时返回 None（调用方必须整个省略该键；写 0 会让整份作业不被 MAA 识别）",
          maa.module_slot(None) is None and maa.module_slot("") is None)

    # ---- ③ 组装
    plan = Plan(stage="act54side_ex08", deploys=[
        DeployOrder("赤刃明霄陈", (4, 2), "Left", skill=3, mastery=3, elite=2,
                    level=90, potential=2, module="uniequip_002_chen3", time=10.0),
        DeployOrder("予愿安洁莉娜", (1, 4), "Right", skill=3, mastery=3, elite=2,
                    level=60, potential=1, time=28.0),
        DeployOrder("圣聆初雪", (10, 4), "Right", skill=2, mastery=3, elite=2,
                    level=90, potential=1, module="uniequip_002_sbell2", time=71.0),
    ])
    data = maa.to_maa(plan, None, difficulty="NORMAL", title="测试", details="详情")
    check("stage_name 缺省用 levelId（code 不唯一：774 条突袭变体共用同一个 code）",
          data["stage_name"] == "act54side_ex08", str(data["stage_name"]))
    check("difficulty 按关卡索引填（NORMAL → 1，即普通/三星）",
          data.get("difficulty") == 1, str(data.get("difficulty")))
    check("Deploy 动作里没有 time 字段（协议根本没这个键）",
          not any("time" in a for a in data["actions"]),
          "计时只有条件与 pre_delay/post_delay")
    check("没有生效模组的干员整个省略 module 键",
          "module" not in data["opers"][1]["requirements"],
          str(data["opers"][1]["requirements"]))
    check("有生效模组的写对编号",
          data["opers"][0]["requirements"].get("module") == 1)
    check("skill_level = 7 + 专精（专三即 10）",
          data["opers"][0]["requirements"].get("skill_level") == 10)
    check("键序是 elite → level → skill_level → module → potential",
          list(data["opers"][0]["requirements"]) ==
          ["elite", "level", "skill_level", "module", "potential"],
          str(list(data["opers"][0]["requirements"])))
    det = data["doc"]["details"]
    check("编队写进了 doc.details（博士要求「导出结果写明使用了哪些干员」）",
          "【编队】" in det and "赤刃明霄陈" in det)
    check("三个干员一个不漏地写在 doc.details 里",
          all(o["name"] in det for o in data["opers"]), "逐名核对")
    check("opers 的顺序与部署顺序一致",
          [o["name"] for o in data["opers"]] ==
          ["赤刃明霄陈", "予愿安洁莉娜", "圣聆初雪"])
    check("每个 Deploy 的 doc 里写着技能与练度",
          "技能3" in data["actions"][0]["doc"] and "精2 90" in data["actions"][0]["doc"],
          data["actions"][0]["doc"])
    check("minimum_required 在", bool(data.get("minimum_required")),
          str(data.get("minimum_required")))

    # ---- ③b 人读清单里的模组写法：**模组名 + 类型字母 + 等级**（博士 2026-09-18 定）
    #
    # 原先印的是模组 id 加括号（`uniequip_002_chen3(X→1)`）：id 与 MAA 的编号都
    # 不是游戏里看得见的东西，照着抄不下去。名字与字母才是。
    mplan = Plan(stage="main_01-07", deploys=[
        DeployOrder("甲", (1, 1), "Right", skill=0, time=0.0),
        DeployOrder("乙", (2, 1), "Right", skill=0, time=1.0),
        DeployOrder("丙", (3, 1), "Right", skill=0, time=2.0),
        DeployOrder("丁", (4, 1), "Right", skill=0, time=3.0),
    ])
    mroster = {
        "甲": {"module": "uniequip_002_chen3", "module_level": 3},      # X 型，Lv3
        "乙": {"module": "uniequip_001_chen3", "module_level": 1},      # 基础证章
        "丙": {"module": "uniequip_002_sbell2"},                        # 名册没记等级
        "丁": {},                                                       # 没有模组
    }
    mlines = maa.operators_lines(mplan, mroster)
    check("模组写法 = 「模组名 类型字母 等级」（不再印 uniequip id 与 MAA 编号）",
          "模组 记忆残页 X 3" in mlines[0] and "uniequip" not in mlines[0],
          mlines[0])
    check("换个模组/换个等级照实写（千分之一的心 Y → 1）",
          "模组 千分之一的心 Y " in mlines[2], mlines[2])
    check("基础证章（typeName2 为空）**不算模组**，写「无」",
          "模组 无" in mlines[1] and "证章" not in mlines[1], mlines[1])
    check("没有模组的写「无」", "模组 无" in mlines[3], mlines[3])
    check("名册没记模组等级时写 `-`（不编一个数）",
          "模组 千分之一的心 Y -" in mlines[2], mlines[2])
    check("模组名取自 uniequip 表（module_name 已公开）",
          maa.module_name("uniequip_002_chen3") == "记忆残页"
          and maa.module_name("uniequip_001_chen3") == "赤刃明霄陈证章",
          str(maa.module_name("uniequip_002_chen3")))
    check("查不到的模组 id 返回 None（调用方不许编名字）",
          maa.module_name("uniequip_999_nope") is None
          and maa.module_name(None) is None)
    check("doc.details 里的模组一格与新写法一致（同一份 _mod_text，两处不会漂）",
          "记忆残页 X " in det, det.splitlines()[0] if det else "")

    # ---- ④ detail 的等待秒要累加成绝对时刻
    rows = [("A", (1, 1), "Right", 3), ("B", (2, 2), "Left", 2), ("C", (3, 3), "Right", 0)]
    detail = [(10.0, "A", (1, 1), "Right", 3, 3, 20),
              (18.0, "B", (2, 2), "Left", 2, 3, 18),
              (19.0, "C", (3, 3), "Right", 0, 0, 19)]
    q = maa.plan_from_rows("s", rows, detail)
    check("detail 的「等待秒」累加成绝对时刻（不是原样当时刻用）",
          [d.time for d in q.deploys] == [10.0, 28.0, 47.0],
          str([d.time for d in q.deploys]))
    check("专精从 detail 带过来了", [d.mastery for d in q.deploys] == [3, 3, 0])

    # ---- ⑤ 落盘命名与追加
    with tempfile.TemporaryDirectory() as td:
        p1 = maa.write_job(data, td, "SR-EX-8")
        p2 = maa.write_job(data, td, "SR-EX-8")
        check("落盘路径是 <guides>/<关卡名>/<关卡名>-<序号>.json",
              p1.parent.name == "SR-EX-8" and p1.name == "SR-EX-8-1.json", str(p1))
        check("再导出一次是 -2，不覆盖已有作业", p2.name == "SR-EX-8-2.json", str(p2))
        check("写出来的是合法 JSON，opers 原样",
              json.loads(p1.read_text(encoding="utf-8"))["opers"] == data["opers"])

    # ---- ⑥ 导出模块不许拉进重依赖
    r = subprocess.run(
        [sys.executable, "-c",
         "import sys, ak_tactic.maa_export as m; "
         "print('|'.join(sorted(x for x in ('textual', 'qrcode') if x in sys.modules)))"],
        capture_output=True, text=True, encoding="utf-8", cwd=str(Path(__file__).resolve().parent.parent))
    check("导入 maa_export 不会拉进 textual / qrcode（惰性）",
          r.stdout.strip() == "", r.stdout.strip() or r.stderr.strip()[:80])


# ---------------------------------------------------------------- [9] 回主界面

def check_home() -> None:
    """结果屏按 H 回 [0] 准备屏，且把上一轮的状态清干净。

    不清状态的后果不是报错，是下一轮**从半路开始**：屏幕上写着「准备」，
    底下却还压着上一次的 stage/squad。这类"看着对"的错误比崩溃难查得多。
    """
    print("\n[9] 结果屏回主界面")
    import types
    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("回主界面", f"textual 没装（{exc}）")
        return

    from textual.app import ComposeResult
    from textual.containers import Vertical
    from textual.screen import Screen
    from textual.widgets import Footer, Header, Static

    from ak_tactic.tui.app import ResultScreen, RiosApp, WelcomeScreen

    class _Fake(Screen):
        """只占住屏幕栈的一层，模拟 [1]/[2]/[3]。"""

        def compose(self) -> ComposeResult:
            yield Header()
            with Vertical():
                yield Static("fake")
            yield Footer()

    # 绑定与动作名先静态核对：按键写对了但动作没接上，按下去是静默无反应
    binds = {(b.key, b.action) for b in ResultScreen.BINDINGS}
    check("结果屏挂了 H → home（不是只写了按键没接动作）",
          ("h", "home") in binds, str(sorted(binds)))
    check("结果屏挂了 R → stage_list（回选关页，博士 2026-09-18 要的）",
          ("r", "stage_list") in binds, str(sorted(binds)))
    check("出口是退出程序 / 回主界面 / 回选关页：Q、H、R 三个都在",
          ("q", "quit") in binds and ("h", "home") in binds
          and ("r", "stage_list") in binds, str(sorted(binds)))
    check("结果屏**不挂** Esc（博士 2026-09-17 裁定：这两屏不给 esc）",
          not any(k == "escape" for k, _ in binds), str(sorted(binds)))
    check("结果屏真的有 action_home / action_quit / action_stage_list 三个方法",
          callable(getattr(ResultScreen, "action_home", None))
          and callable(getattr(ResultScreen, "action_quit", None))
          and callable(getattr(ResultScreen, "action_stage_list", None)))
    check("结果屏不残留 action_finish（它只会退出程序，已由 action_quit 取代）",
          not any(n == "action_finish" for n in vars(ResultScreen)))

    async def flow() -> dict:
        got: dict = {}
        app = RiosApp()                       # 真实路径：on_mount 自己压 [0]
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            st = app.state
            got["fresh_stack"] = [type(s).__name__ for s in app.screen_stack]
            st.stage = {"code": "SR-EX-8", "level_id": "act54side_ex08",
                        "difficulty": "NORMAL", "zone_id": "act54side_zone2"}
            st.squad = ["赤刃明霄陈", "圣聆初雪"]
            # 故意给一个「解算失败」的结果：回主界面在没解出方案时也必须可用
            st.result = types.SimpleNamespace(plan=None, verdict=None,
                                              evaluated=3, depth=2)
            st.error = "上一轮的错误"
            st.export_path = Path("X:/nope.json")
            st.searcher = object()
            got["roster_before"] = len(st.roster.operators) if st.roster else 0

            app.push_screen(_Fake(), app._stage_picked)
            app.push_screen(_Fake(), app._squad_picked)
            app.push_screen(_Fake())
            app.push_screen(ResultScreen())
            await pilot.pause()
            got["at_result"] = isinstance(app.screen, ResultScreen)

            # **按大写 H**：Footer 上印的就是 H，博士照着按 Shift+H 曾经毫无反应
            # ——`Binding("h", …)` 只匹配小写，而 Textual 的键匹配区分大小写。
            # 这条原先用 press("h") 测，所以"全绿"却根本没测到博士按的那个键。
            await pilot.press("H")
            await pilot.pause()
            got["stack"] = [type(s).__name__ for s in app.screen_stack]
            got["at_home"] = isinstance(app.screen, WelcomeScreen)
            got["stage"] = st.stage
            got["squad"] = st.squad
            got["result"] = st.result
            got["error"] = st.error
            got["export_path"] = st.export_path
            got["roster_after"] = st.roster is not None
        return got

    got = asyncio.run(flow())
    check("按 H 之前确实停在结果屏（不然下面几条测的不是这件事）",
          got["at_result"], "从结果屏出发")
    check("按 H 后停在 [0] 准备屏", got["at_home"], "WelcomeScreen")
    check("屏幕栈弹回「基屏 + [0]」，与全新启动一致",
          got["stack"] == ["Screen", "WelcomeScreen"], str(got["stack"]))
    check("上一轮的关卡被清掉（否则下一轮从半路开始）",
          got["stage"] is None, str(got["stage"]))
    check("上一轮的编队被清掉", got["squad"] == [], str(got["squad"]))
    check("上一轮的结果被清掉", got["result"] is None, str(got["result"]))
    check("上一轮的错误被清掉", got["error"] == "", repr(got["error"]))
    check("上一轮的导出路径被清掉", got["export_path"] is None,
          str(got["export_path"]))
    check("名册留着（它和算哪一关无关，重读是白费）",
          got["roster_after"] and got["roster_before"] > 0,
          f"{got['roster_before']} 人")
    check("解算失败（没有结果）时也能回主界面",
          got["at_home"], "这条用的是没解出方案的假结果")


def check_welcome() -> None:
    """[0b] 主界面两栏（博士 2026-09-18 的三条要求）。

    一条要求一条判据：数据目录栏要写出**当前正在用的路径**（初次启动即默认目录，
    改过之后要标出来）；登录账号栏要写出**玩家账号用户名**；名册那一栏删掉，
    名册与干员库的「获取没有」并进账号栏。

    另有一条是**兜底**：任何一栏取数抛了，必须在那一栏写下原因——博士报过
    「主界面什么都看不见，只有四行标题」，而空白说不出是哪一栏坏了。
    """
    print("\n[0b] 主界面两栏")

    from textual.widgets import Static

    from ak_tactic.tui import app as A
    from ak_tactic.tui import data as D

    src = Path(A.__file__).read_text(encoding="utf-8")
    check("「名册」那一栏已经删掉（compose 里不再有 roster-line）",
          'id="roster-line"' not in src, "还有 roster-line")
    check("两个栏的 id 还在（数据目录 / 登录账号）",
          'id="dir-line"' in src and 'id="account-line"' in src)

    # ---- 干员库状态：真库数与「库不在」两条路
    st = D.operator_db_status()
    check("operator_db_status() 拿得到真库的干员数",
          st["exists"] and (st["operators"] or 0) > 100,
          f"{st['operators']} 名 / {st['path']}")
    import ak_tactic.db as _db
    old_path = _db.DEFAULT_DB_PATH
    _db.DEFAULT_DB_PATH = Path(str(old_path) + ".not-exists")
    try:
        gone = D.operator_db_status()
    finally:
        _db.DEFAULT_DB_PATH = old_path
    check("库文件不在时如实说不在，而且**不抛**（这一屏不该被一个坏库拖垮）",
          gone["exists"] is False and gone["operators"] is None
          and not gone["error"], str(gone))

    # ---- 账号行：用户名还在，名册那句挪到 _data_line
    line = D.describe_account("0f0f0f")
    check("默认还是带「（无）名册缓存」那半句（登录屏那几处照旧）",
          "无名册缓存" in line, line[:60])
    lean = D.describe_account("0f0f0f", roster_flag=False)
    check("给主界面用的那一版**不带**那半句（同一栏里不重复说两遍）",
          "名册缓存" not in lean, lean[:60])

    root = Path(D.__file__).resolve().parents[2]              # 仓库根

    async def flow() -> dict:
        got: dict = {}
        app = A.RiosApp()
        async with app.run_test(size=(110, 44)) as pilot:
            await pilot.pause()
            got["screen"] = type(app.screen).__name__
            got["dir"] = str(app.screen.query_one("#dir-line", Static).render())
            got["acct"] = str(app.screen.query_one("#account-line", Static).render())
            try:
                app.screen.query_one("#roster-line", Static)
                got["roster_widget"] = True
            except Exception:                                  # noqa: BLE001
                got["roster_widget"] = False

        # 配置里有 guides_dir → 标「当前设置」；没有 → 标「默认目录」
        old_cfg = D.load_config
        D.load_config = lambda: {"guides_dir": str(root / "Guides")}
        try:
            app2 = A.RiosApp()
            async with app2.run_test(size=(110, 44)) as pilot:
                await pilot.pause()
                got["dir_set"] = str(
                    app2.screen.query_one("#dir-line", Static).render())
        finally:
            D.load_config = old_cfg

        # 取数抛错 → 那一栏必须写出原因，账号栏照常
        def boom():
            raise RuntimeError("模拟：路径取不到")

        old_dir = D.guides_dir
        D.guides_dir = boom
        try:
            app3 = A.RiosApp()
            async with app3.run_test(size=(110, 44)) as pilot:
                await pilot.pause()
                got["dir_err"] = str(
                    app3.screen.query_one("#dir-line", Static).render())
                got["acct_err"] = str(
                    app3.screen.query_one("#account-line", Static).render())
        finally:
            D.guides_dir = old_dir
        return got

    got = asyncio.run(flow())
    check("开机进的是主界面", got["screen"] == "WelcomeScreen", got["screen"])
    check("#roster-line 在真界面里也查不到（不只是源码里删了）",
          not got["roster_widget"])
    check("数据目录栏写着当前路径",
          str(D.guides_dir()) in got["dir"], got["dir"][:80])
    check("初次启动（配置里没有 guides_dir）标的是「默认目录」",
          "默认目录" in got["dir"], got["dir"][:80])
    check("改过目录之后标的是「当前设置」，两种状态分得开",
          "当前设置" in got["dir_set"], got["dir_set"][:80])
    check("数据目录栏把作业的实际落点也写出来（不再是 <数据目录> 这种占位）",
          "<关卡名>" in got["dir"] and "<数据目录>" not in got["dir"],
          got["dir"][:80])
    uid = D.skland_uid()
    if uid:
        # 用户名本身来自 `account_info`（`describe_account` 用的也是它），
        # 所以这里比的是**用户名在不在那一栏里**，不是某个写死的名字。
        nick = (D.account_info(uid) or {}).get("nick") or ""
        check("登录账号栏写着玩家账号用户名（还没问过时如实写「未知」）",
              (bool(nick) and nick in got["acct"])
              or "游戏用户名未知" in got["acct"],
              got["acct"].splitlines()[0][:70])
    else:
        check("没登录时账号栏如实说没有账号，并指向补救键 L",
              "当前没有登录的账号" in got["acct"],
              got["acct"].splitlines()[0][:70])
    check("账号栏里名册与干员库各一句「已获取没有」",
          "名册：已获取" in got["acct"] and "干员库：已获取" in got["acct"],
          got["acct"].splitlines()[-1][:80])
    check("某一栏取数抛错时写出原因（**不留空白**）",
          "这一栏取不到" in got["dir_err"] and "RuntimeError" in got["dir_err"],
          got["dir_err"][:70])
    check("一栏坏了不连累另一栏",
          "干员库" in got["acct_err"], got["acct_err"][:60])


def check_result_back_to_stage() -> None:
    """[9b] 结果屏按 `R` 回**选关页**（关卡列表），章/分部/环境的选择留着。

    与「回主界面」的区别全在**退到哪一层**，所以这一节必须走真向导：从 [1] 一路
    点到关卡列表、再点一关、进解算屏、压一张结果屏，然后按 `R`，逐条量：

    * 落点是不是 `StagePickScreen`（不是 [0]、也不是它上面的编队屏）；
    * 路径有没有被截到关卡列表那一格（再按 `Esc` 应当回到**分部/环境**那一层，
      而不是掉回主界面）；
    * 这一轮的关卡/结果/错误清没清，**编队有没有留着**（换一关通常还是同一队）。
    """
    print("\n[9b] 结果屏回选关页（R）")
    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("回选关页", f"textual 没装（{exc}）")
        return

    from ak_tactic.tui import app as A
    from ak_tactic.tui import data as D

    rows = D.chapter_rows()
    if not rows:
        skip("回选关页", "本地库没有章节数据（`db stage-fetch` 之后才有）")
        return

    real_run = A.SolveScreen._run

    async def flow() -> dict:
        got: dict = {}
        app = A.RiosApp(skip_login=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            # 挑一个**有分部**的章/活动，才走得出「分部」那一层
            row = next((r for r in rows if len(r["parts"]) > 1), rows[0])
            app.screen.dismiss(row)
            await pilot.pause()
            if type(app.screen).__name__ == "PartPickScreen":
                app.screen.dismiss(row["parts"][0])
                await pilot.pause()
            if type(app.screen).__name__ == "EnvPickScreen":
                app.screen.dismiss(D.zone_envs(row["parts"][0]["zone_id"])[0])
                await pilot.pause()
            got["at_stage"] = type(app.screen).__name__
            got["path_at_stage"] = len(app._path)
            stage_row = next(iter(app.screen._rows), None)
            if stage_row is None:
                return got
            got["stage_code"] = stage_row["code"]
            app.screen.dismiss(stage_row)
            await pilot.pause()
            if type(app.screen).__name__ == "SquadAskScreen":
                app.screen.dismiss({"manual": True})
                await pilot.pause()
            if type(app.screen).__name__ == "SquadPickScreen":
                names = [o.name for o in app.state.roster.top(2)]
                app.screen._picked = set(names)
                app.screen.dismiss(names)
                await pilot.pause()
            got["at_solve"] = type(app.screen).__name__
            got["squad_used"] = list(app.state.squad)
            # 结果屏照原样压上去（真实路径里由 `_done` 推）；解算不真跑
            app.push_screen(A.ResultScreen())
            await pilot.pause()
            got["before"] = type(app.screen).__name__
            await pilot.press("R")                    # 按 Footer 上印的那个键
            await pilot.pause()
            got["after"] = type(app.screen).__name__
            got["path_after"] = len(app._path)
            got["stack_after"] = [type(s).__name__ for s in app.screen_stack]
            got["stage_cleared"] = app.state.stage is None
            got["result_cleared"] = app.state.result is None
            got["error_cleared"] = app.state.error == ""
            got["squad_after"] = list(app.state.squad)
            got["roster_kept"] = app.state.roster is not None
            # 从选关页再按 Esc：应当回**上一层（分部/环境/章）**，不是回主界面
            await pilot.press("escape")
            await pilot.pause()
            got["after_esc"] = type(app.screen).__name__
        return got

    A.SolveScreen._run = lambda self: None
    try:
        got = asyncio.run(flow())
    finally:
        A.SolveScreen._run = real_run

    if got.get("at_stage") != "StagePickScreen":
        check("回选关页：能走到关卡列表", False, str(got))
        return
    check("按 R 之前停在结果屏（不然下面几条测的不是这件事）",
          got.get("before") == "ResultScreen", str(got.get("before")))
    check("**按 R 落到关卡列表**（不是 [0]、也不是编队屏）",
          got.get("after") == "StagePickScreen", str(got.get("after")))
    check("路径被截到关卡列表那一格（同一层的屏数不变）",
          got.get("path_after") == got.get("path_at_stage"),
          f"{got.get('path_at_stage')} → {got.get('path_after')}")
    check("解算屏与结果屏都被弹掉（屏幕栈里不留旧屏）",
          "SolveScreen" not in (got.get("stack_after") or [])
          and "ResultScreen" not in (got.get("stack_after") or []),
          str(got.get("stack_after")))
    check("这一轮的关卡被清掉（下一次点的那一关才算数）",
          got.get("stage_cleared") is True, str(got.get("stage_cleared")))
    check("这一轮的结果与错误被清掉",
          got.get("result_cleared") is True and got.get("error_cleared") is True,
          f"result={got.get('result_cleared')} error={got.get('error_cleared')}")
    check("**编队留着**（换一关通常还是同一队，不必重勾）",
          got.get("squad_after") == got.get("squad_used")
          and bool(got.get("squad_used")), str(got.get("squad_after")))
    check("名册留着（它和算哪一关无关）", got.get("roster_kept") is True)
    check("从选关页按 Esc 退回**上一层**（分部/环境/章），不是回主界面",
          got.get("after_esc") in ("PartPickScreen", "EnvPickScreen",
                                   "ChapterPickScreen"),
          str(got.get("after_esc")))


def check_stage_layers() -> None:
    """[10] 选关的三层与它依赖的数据层。

    这一节钉的是**需求第 5/6/7 条**。它们全都建立在「akdb 里有章节名与关卡
    中文名」之上，而那份数据要联网取——所以先断数据层，再断界面层。
    数据层缺了就整节跳过（联网的东西不该让离线自检变红）。
    """
    print("\n[10] 选关的三层（章／活动 → 分部或环境 → 关卡）")
    from ak_tactic.tui import data as D

    chapters = D.chapter_rows()
    if not chapters:
        skip("选关三层", "章表是空的——先跑 `db stage-fetch`（要联网）")
        return

    by_key = {c["key"]: c for c in chapters}
    check("第一层是章/活动，不是 477 条 zone 平铺",
          20 < len(chapters) < 400, f"{len(chapters)} 条")

    # --- 需求 6：sidestory 分部分 ---
    srx = by_key.get("act54side")
    check("「月行水上」在第一层（活动名来自 activity_table，zone_table 里没有它）",
          srx is not None and srx["title"] == "月行水上",
          srx["title"] if srx else "没有 act54side")
    check("它含两个分部：通学路 与 殡仪堂",
          srx is not None and [p["title"] for p in srx["parts"]]
          == ["通学路", "殡仪堂"],
          str([p["title"] for p in srx["parts"]]) if srx else "")
    check("没有第三部分（act54side_zone3 不存在）",
          srx is not None and len(srx["parts"]) == 2,
          f"{len(srx['parts'])} 个" if srx else "")

    # --- 需求 7：环境分层 ---
    nine = by_key.get("main_9")
    if nine:
        envs = D.zone_envs(nine["parts"][0]["zone_id"])
        names = [e["label"] for e in envs]
        check("第九章有环境层，且含剧情体验与标准实战",
              "剧情体验" in names and "标准实战" in names, str(names))
        check("第九章**没有**磨难险地（那是第 10-14 章才有）",
              "磨难险地" not in names, str(names))
        # 博士 2026-09-17 裁定：第九章的「通用」保留。
        # 需求原文只列了两条（剧情体验/标准实战），但第 9 章实际有第三档
        # diff_group=ALL 的 4 关；藏起来它们就没有第二个入口了。
        check("第九章的「通用」保留（博士裁定：那些就放在通用）",
              "通用" in names, str(names))
        check("第九章环境菜单是**三条**", len(names) == 3, str(names))
        tot = sum(len(D.stage_rows(zone_id=nine["parts"][0]["zone_id"],
                                   env=e["env"])) for e in envs)
        allrows = len(D.stage_rows(zone_id=nine["parts"][0]["zone_id"]))
        check("各环境的关数之和 == 直接列出的关数（不然有关卡被菜单吞掉）",
              tot == allrows, f"{tot} vs {allrows}")
    five = by_key.get("main_5")
    if five:
        check("第五章没有环境层（全 NONE，不该多一层菜单）",
              D.zone_envs(five["parts"][0]["zone_id"]) == [], "空")
    fifteen = by_key.get("act2mainss")
    if fifteen:
        check("第十五章标题是【第十五章 ‘离解复合’】（章号要自己拼，"
              "它的 name_first 是英文）",
              fifteen["title"] == "【第十五章 ‘离解复合’】", fifteen["title"])

    # --- 主线标题的写法：【第X章 ‘章节标题’】（博士 2026-09-18）---
    import re as _re

    from ak_tactic.db import DEFAULT_DB_PATH as _DB_PATH
    from ak_tactic.db import connect as _connect
    from ak_tactic.db.stages import chapter_label, load_zones, zone_title
    pat = _re.compile(r"^【(第[一二三四五六七八九十]+章|序章) ‘.+’】$")
    conn = _connect()
    try:
        zones = load_zones(conn)
    finally:
        conn.close()
    main_keys = {zid for zid, v in zones.items()
                 if (v.get("type") or "") in ("MAINLINE", "MAINLINE_ACTIVITY")}
    main_rows = [c["title"] for c in chapters
                 if any(p["zone_id"] in main_keys for p in c["parts"])]
    other_rows = [c["title"] for c in chapters
                  if not any(p["zone_id"] in main_keys for p in c["parts"])]
    check("主线每一章的标题都是【第X章 ‘章节标题’】",
          bool(main_rows) and all(pat.match(t) for t in main_rows),
          str([t for t in main_rows if not pat.match(t)][:3]))
    check("序章也带上了章节标题（它没有章号，写【序章 ‘黑暗时代·上’】）",
          "【序章 ‘黑暗时代·上’】" in main_rows,
          str(main_rows[:2]))
    check("活动那些标题**不套**这个格式（引号与书名号只给主线）",
          not any(t.startswith("【") for t in other_rows),
          str([t for t in other_rows if t.startswith("【")][:3]))
    check("章号与副标题都取自 zone 表（不是拼死的字符串）",
          chapter_label(zones["main_7"]) == "【第七章 ‘苦难摇篮’】"
          and chapter_label(zones["act4mainss_zone1"]) == "【第十七章 ‘相变临界’】",
          f"{chapter_label(zones['main_7'])} / "
          f"{chapter_label(zones.get('act4mainss_zone1'))}")
    check("非主线 zone 上 chapter_label 返回空串（调用方好退回 zone_title）",
          chapter_label(zones["act54side_zone1"]) == ""
          and chapter_label(zones["camp_zone_1"]) == ""
          and chapter_label(None) == "")
    check("zone_title 的旧口径没被改坏（分部名还在用它，第十五章仍带副标题）",
          zone_title(zones["act3mainss_zone1"]) == "第十六章　反常光谱"
          and zone_title(zones["main_1"]) == "第一章",
          f"{zone_title(zones['act3mainss_zone1'])} / {zone_title(zones['main_1'])}")

    # --- 分部那一列不许横到屏幕外（剿灭作战 15 个分部）---
    from ak_tactic.tui import app as A
    cell = A.ChapterPickScreen._parts_cell(by_key["act54side"])
    check("两个分部照实写全（通学路、殡仪堂）", cell == "通学路、殡仪堂", cell)
    camp_cell = A.ChapterPickScreen._parts_cell(by_key["剿灭作战"])
    check("15 个分部的那一格只写前几个 + 「共 N 个分部」",
          "共 15 个分部" in camp_cell and len(camp_cell) < 80, camp_cell[:70])
    check("单分部那一列留空（没有第二层可点）",
          A.ChapterPickScreen._parts_cell(by_key["main_5"]) == "",
          A.ChapterPickScreen._parts_cell(by_key["main_5"]))

    # --- 条数一致：菜单报几关，下一层就得给几行 ---
    mismatched = []
    for key in ("act54side", "main_9", "main_5"):
        c = by_key.get(key)
        if c is None:
            continue
        total = sum(len(D.stage_rows(zone_id=p["zone_id"]))
                    for p in c["parts"])
        if total != c["levels"]:
            mismatched.append(f"{c['title']} 菜单 {c['levels']} / 列表 {total}")
    check("章节菜单报的关数 = 下一层列表的行数（含四星限定版）",
          not mismatched, "；".join(mismatched) or "三章都一致")

    # --- 需求 5：关卡行只给「代号　中文名」 ---
    rows = D.stage_rows(zone_id="act54side_zone2", limit=999)
    check("关卡记录带中文名", rows and all(r.get("name") for r in rows),
          f"{sum(1 for r in rows if not r.get('name'))} 条缺名")
    check("SR-EX-8 的中文名是「虚无之顶」",
          any(r["level_id"] == "act54side_ex08" and r["name"] == "虚无之顶"
              for r in rows), "")
    check("难度不止两档：四星限定版与普通版并存",
          {r["difficulty"] for r in rows} >= {"NORMAL", "FOUR_STAR"},
          str(sorted({r["difficulty"] for r in rows})))

    from ak_tactic.db.stages import DIFFICULTY_LABELS
    check("难度标签是「普通（三星）」这类人话",
          DIFFICULTY_LABELS["NORMAL"] == "普通（三星）"
          and DIFFICULTY_LABELS["FOUR_STAR"] == "突袭（四星）",
          DIFFICULTY_LABELS["NORMAL"])

    # --- 界面纪律：不显示 levelId 与区域 ---
    from ak_tactic.tui import app as A
    src = Path(A.__file__).read_text(encoding="utf-8")
    head = src[src.index("class StagePickScreen"):]
    cols = ""
    if "add_columns" in head:
        cols = head.split("add_columns", 1)[1].split(")", 1)[0] + ")"
    check("关卡屏的表头不含 levelId 与区域（博士明确要求不展示）",
          '"levelId"' not in head and '"区域"' not in head
          and "level_id" not in cols,
          f"add_columns{cols}")


def check_stage_categories() -> None:
    """[10b] 库里只留这五类 zone，活动名去掉「复刻」（博士 2026-09-18）。

    两件事都落在**数据层**，不是界面层：肉鸽关卡留在库里而界面不显示，下一个人
    打开 sqlite 就会以为「这游戏有这些关」。所以这一节既断白名单与清洗函数，
    也断真库里的实际内容（真库空了就跳过——它要联网取数）。
    """
    print("\n[10b] 只取这五类 zone / 活动名去「复刻」")
    import sqlite3

    from ak_tactic.db import DEFAULT_DB_PATH, connect
    from ak_tactic.db import stages as S
    from ak_tactic.db.schema import SCHEMA_SQL
    from ak_tactic.tui import data as D

    # ---- ① 白名单与菜单顺序
    check("白名单正好是这五类（口径 = theresa.wiki/map 的分类）",
          S.CHAPTER_TYPES == ("MAINLINE", "BRANCHLINE", "CAMPAIGN",
                              "MAINLINE_ACTIVITY", "ACTIVITY"),
          str(S.CHAPTER_TYPES))
    check("肉鸽/爬塔/周常/导览/SIDESTORY/MAINLINE_RETRO 一个都不在白名单里",
          not ({"ROGUELIKE", "CLIMB_TOWER", "WEEKLY", "GUIDE", "SIDESTORY",
                "MAINLINE_RETRO"} & set(S.CHAPTER_TYPES)),
          str(S.CHAPTER_TYPES))
    check("菜单顺序：主线 → 第 15–17 章 → 剿灭作战 → 插曲·别传 → 活动",
          S.CHAPTER_ORDER == ("MAINLINE", "MAINLINE_ACTIVITY", "CAMPAIGN",
                              "BRANCHLINE", "ACTIVITY"), str(S.CHAPTER_ORDER))
    check("剿灭作战有固定的显示名（它的 15 个 zone 名字全是空的）",
          S.CAMPAIGN_TITLE == "剿灭作战")

    # ---- ② 名字清洗：判据是**后缀**，不是「有没有间隔符」
    cases = [("墟·复刻", "墟"), ("不义之财 复刻", "不义之财"),
             ("众生行记·复刻", "众生行记"), ("玛莉娅·临光", "玛莉娅·临光"),
             ("复刻", "复刻"), ("", ""), (None, "")]
    bad = [(a, S.clean_activity_name(a), b) for a, b in cases
           if S.clean_activity_name(a) != b]
    check("活动名去「复刻」：·复刻与空格两种写法都认，带·但不带复刻的**不动**",
          not bad, str(bad))

    # ---- ③ 清库逻辑：拿一个内存库断，不碰真库
    mem = sqlite3.connect(":memory:")
    mem.executescript(SCHEMA_SQL)
    mem.execute("INSERT INTO zone (zone_id, type) VALUES ('keep_zone', 'MAINLINE')")
    mem.execute("INSERT INTO zone (zone_id, type) VALUES ('gone_zone', 'ROGUELIKE')")
    mem.execute("INSERT INTO zone (zone_id, type) VALUES ('odd_zone', 'SIDESTORY')")
    for lid, zid in (("keep_1", "keep_zone"), ("rogue_1", "gone_zone"),
                     ("story_1", "odd_zone"), ("mem_1", "nowhere")):
        mem.execute("INSERT INTO stage (level_id, code, zone_id) VALUES (?, ?, ?)",
                    (lid, lid, zid))
    gone = S.prune_foreign_rows(mem)
    left_z = {r[0] for r in mem.execute("SELECT zone_id FROM zone")}
    left_s = {r[0] for r in mem.execute("SELECT level_id FROM stage")}
    mem.close()
    check("清库：被剔除类型的 zone 清掉，白名单那类不动",
          left_z == {"keep_zone"}, str(left_z))
    check("清库：被剔除类型下的关卡、以及 zone 表里查不到的关卡都清掉",
          left_s == {"keep_1"}, str(left_s))
    check("清库返回的条数如实（2 个 zone / 3 个关卡）", gone == (2, 3), str(gone))

    # 读侧也过口径：库是旧口径时菜单不许把肉鸽摆出来（`db build` 的 carry_over
    # 会把自己旧库里的两张表整表搬过来，而 build 不联网、不清库）
    mem = sqlite3.connect(":memory:")
    mem.executescript(SCHEMA_SQL)
    mem.execute("INSERT INTO zone (zone_id, type, name_first) "
                "VALUES ('rogue_zone', 'ROGUELIKE', '肉鸽')")
    mem.execute("INSERT INTO stage (level_id, code, zone_id, name) "
                "VALUES ('rogue_1', 'R-1', 'rogue_zone', '肉鸽关')")
    mem.execute("INSERT INTO zone (zone_id, type, name_first) "
                "VALUES ('main_1', 'MAINLINE', '第一章')")
    mem.execute("INSERT INTO stage (level_id, code, zone_id, name) "
                "VALUES ('main_01-01', '1-1', 'main_1', '坍塌')")
    keys = [e["key"] for e in S.list_chapters(mem)]
    mem.close()
    check("读侧也过口径：库里留着肉鸽时，菜单里也不显示它",
          keys == ["main_1"], str(keys))

    # ---- ④ 真库：类型、孤儿关卡、还带「复刻」的名字
    if not Path(DEFAULT_DB_PATH).exists():
        skip("只取这五类（真库）", "本地没有 akdb.sqlite")
        return
    conn = connect()
    try:
        types = {r[0] for r in conn.execute("SELECT DISTINCT type FROM zone")}
        keep_ids = {r[0] for r in conn.execute(
            "SELECT zone_id FROM zone WHERE type IN (%s)"
            % ", ".join("?" * len(S.CHAPTER_TYPES)), S.CHAPTER_TYPES)}
        orphans = conn.execute(
            "SELECT count(*) FROM stage WHERE zone_id IS NULL OR zone_id = '' "
            "OR zone_id NOT IN (SELECT zone_id FROM zone)").fetchone()[0]
        rerun = [r[0] for r in conn.execute(
            "SELECT activity_name FROM zone WHERE activity_name LIKE '%复刻%'")]
    finally:
        conn.close()
    check("真库里只有这五类 zone（少一类可以，多了不行）",
          bool(types) and types <= set(S.CHAPTER_TYPES), str(sorted(types)))
    check("真库里没有归属不明的关卡（清库那一步真跑过）",
          orphans == 0, f"{orphans} 条")
    check("真库里没有还带「复刻」的活动名", not rerun, str(rerun[:5]))

    # ---- ⑤ 菜单：剿灭作战那一条与它的分部
    ch = D.chapter_rows()
    if not ch:
        skip("剿灭作战进菜单", "章表是空的——先跑 `db stage-fetch`")
        return
    check("第一层没有空标题（单 zone 活动没有活动名时曾显示成空白行）",
          all(e["title"].strip() for e in ch),
          str([e["key"] for e in ch if not e["title"].strip()]))
    check("第一层没有带「复刻」的标题",
          not [e for e in ch if "复刻" in e["title"]],
          str([e["title"] for e in ch if "复刻" in e["title"]][:3]))
    bad_zids = [p["zone_id"] for e in ch for p in e["parts"]
                if p["zone_id"] not in keep_ids]
    check("第一层里每一个分部都落在白名单类型上（界面与库同一口径）",
          not bad_zids, str(bad_zids[:5]))

    camp = [e for e in ch if e["key"] == S.CAMPAIGN_TITLE]
    check("菜单里有「剿灭作战」，且只有一条（整类归成一条）",
          len(camp) == 1, f"{len(camp)} 条")
    if camp:
        parts = camp[0]["parts"]
        check("剿灭作战 15 个分部（15 个 camp zone 一个不漏）",
              len(parts) == 15, f"{len(parts)} 个")
        check("分部名用的是关卡名（不是空白、也不是 camp_zone_N）",
              all(p["title"] and not p["title"].startswith("camp_") for p in parts),
              str([p["title"] for p in parts[:2]]))
        ids = [p["zone_id"] for p in parts]
        check("分部按 zone_id 尾号排（它们的 zone_index 全是 0，只按它会排成 "
              "1、10、11…2）",
              ids == sorted(ids, key=lambda z: int(z.rsplit("_", 1)[-1])), str(ids))
        # 分部名必须与那一分部的关卡名逐字一致——两处各算一遍就会漂
        got = {}
        for p in parts:
            names = []
            for r in D.stage_rows(zone_id=p["zone_id"]):
                nm = (r.get("name") or "").strip()
                if nm and nm not in names:
                    names.append(nm)
            got[p["zone_id"]] = "、".join(names)
        off = {z: (got[z], p["title"]) for p in parts for z in [p["zone_id"]]
               if got[z] != p["title"]}
        check("分部名与那一分部的关卡名逐字一致", not off, str(list(off.items())[:2]))
        check("剿灭作战的关数与分部关数之和相等",
              camp[0]["levels"] == sum(p["levels"] for p in parts),
              f"{camp[0]['levels']} vs {sum(p['levels'] for p in parts)}")

    # BRANCHLINE（插曲·别传）那 20 个 zone 是 `permanent_sub_N_zoneM`——永久开放
    # 入口，分部名与活动本体一一对应（格兰法洛 / 失落旗舰 / 阵中往事…）。关卡索引
    # 把那些关挂在**活动**那一侧的 zone 上，所以这 20 个 zone 自己一条关卡都没有。
    # 内容没丢：它们在活动名（愚人号、遗尘漫步、生于黑夜…）底下照常进菜单。
    # 守的是「那 20 个分部名在菜单里都找得到」——哪天对不上了，就是真丢了内容。
    conn = connect()
    try:
        bl = [r[0] for r in conn.execute(
            "SELECT name_second FROM zone WHERE type = 'BRANCHLINE' "
            "AND name_second <> ''")]
        bl_stages = conn.execute(
            "SELECT COUNT(*) FROM stage WHERE zone_id IN "
            "(SELECT zone_id FROM zone WHERE type = 'BRANCHLINE')").fetchone()[0]
    finally:
        conn.close()
    titles = {p["title"] for e in ch for p in e["parts"]}
    missing = [n for n in bl if n not in titles]
    check("BRANCHLINE 那 20 个 zone 自己不挂关卡（关卡在活动那一侧）",
          bl_stages == 0, f"{bl_stages} 关")
    check("但它们的分部名在菜单里都找得到（内容没丢，只是走活动那条门）",
          bool(bl) and not missing, f"缺 {missing[:3]}" if missing else f"{len(bl)} 个分部")


def check_completion() -> None:
    """[11] Guides 目录输入框的 Tab 补全（需求第 3 条）。"""
    print("\n[11] 路径 Tab 补全")
    from ak_tactic.tui import data as D
    from ak_tactic.tui import app as A

    bindings = [(b.key, b.action) for b in A.PathInput.BINDINGS]
    check("PathInput 挂了 tab → complete",
          ("tab", "complete") in bindings, str(bindings))
    check("tab 绑定是 priority（否则会被屏幕的焦点切换抢走）",
          any(b.key == "tab" and b.priority for b in A.PathInput.BINDINGS),
          str([(b.key, b.priority) for b in A.PathInput.BINDINGS]))
    check("GuidesDirScreen 用的就是这个输入框（不是裸 Input）",
          "PathInput(" in Path(A.__file__).read_text(encoding="utf-8"),
          "PathInput(")

    here = Path(D.__file__).resolve().parents[2]          # 仓库根
    stem = here.name[:4]                                  # ak-t…

    # 空输入：补成默认目录，且带分隔符
    new, cands = D.complete_dir("")
    check("空输入补成默认 Guides 目录",
          new.rstrip("/\\") == str(D.default_guides_dir()).rstrip("/\\"),
          new)
    check("补出来带分隔符（好接着往下打）", new.endswith(("/", "\\")), new)

    # 唯一匹配：补到真实存在的目录
    new, cands = D.complete_dir(str(here.parent / stem))
    check("唯一匹配补到真目录", Path(new.rstrip("/\\")).is_dir(), new)
    check("补的是目录就带分隔符", new.endswith(("/", "\\")), new)
    check("唯一匹配时不返回候选（没什么可挑的）", cands == [], str(cands))

    # 分隔符风格：用户打 / 就全用 /，不混
    new, _ = D.complete_dir(str(here.parent).replace("\\", "/") + "/" + stem)
    check("正斜杠输入补出来仍是正斜杠（不在一个路径里混两种）",
          "\\" not in new and new.startswith("D:/"), new)

    # 多匹配：**自造一个确定的场景**，不依赖本机目录长什么样。
    # （早先拿 `D:\home\DSH` 里前两个目录的首字母当前缀，结果选到了 `.`——
    # 而 `Path` 会把 `/.` 规范化掉，测的就不是补全逻辑了。）
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        for name in ("alpha-1", "alpha-2", "beta"):
            (base / name).mkdir()
        new, cands = D.complete_dir(str(base) + "/al")
        check("多个匹配时只补到公共前缀，并把候选交回",
              len(cands) == 2 and new.replace("\\", "/").endswith("alpha-"),
              f"{len(cands)} 个候选 → {new}")
        check("补到前缀之后**不**擅自加分隔符（还没定是哪一个）",
              not new.endswith(("/", "\\")), new)
        listed = D.complete_dir(str(base) + "/")[1]
        check("以分隔符结尾时列出该目录下全部条目",
              len(listed) == 3, str(listed))

        # 大小写：Windows 路径不区分大小写，公共前缀也必须不区分。
        # `os.path.commonprefix` 本身是区分大小写的，直接用它会把
        # `Alpha-1` 与 `alpha-2` 的前缀算成空串——补完等于没补。
        (base / "Alpha-3").mkdir()
        new, cands = D.complete_dir(str(base) + "/a")
        check("大小写不同的兄弟目录也能补出公共前缀（不能被大小写噎住）",
              len(cands) == 3 and len(new) > len(str(base)) + 1,
              f"{new} / 候选 {cands}")

    # 不存在的路径：原样退回，不猜
    new, cands = D.complete_dir("D:/__rios_no_such_dir__/x")
    check("不存在的路径原样退回、不给候选",
          new == "D:/__rios_no_such_dir__/x" and cands == [], new)


def check_squad_grouping() -> None:
    """[12] 选人屏的职业分类与练度门槛（需求第 10 条）。"""
    print("\n[12] 选人屏：主职业分类 / 主-子职业 / 练度三档")
    from textual.widgets import Select, SelectionList

    from ak_tactic.tui import app as A
    from ak_tactic.tui import data as D

    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("选人分类", f"textual 没装（{exc}）")
        return

    # --- 常量与判据（不依赖界面） ---
    binds = [(b.key, b.action) for b in A.SquadPickScreen.BINDINGS]
    check("G 键切分类、M 键切模式、回车进解算",
          ("g", "toggle_group") in binds and ("m", "toggle_mode") in binds
          and any(k == "enter" and a == "go" for k, a in binds), str(binds))
    check("回车仍是 priority（需求第 8 条不能被这次改动弄坏）",
          any(b.key == "enter" and b.priority for b in A.SquadPickScreen.BINDINGS),
          str([(b.key, b.priority) for b in A.SquadPickScreen.BINDINGS]))

    labels = [t[0] for t in D.TRAINED_FILTERS]
    check("练度门槛是博士定的三档",
          labels == ["不限", "≥ 精英二 60 级", "精英二 90 级"], str(labels))
    check("门槛用 (精英段, 段内等级) 元组比，不是只看等级",
          D.meets_trained(D.Operator("x", "x", elite=2, level=90), 2, 90)
          and not D.meets_trained(D.Operator("x", "x", elite=2, level=59), 2, 60)
          and not D.meets_trained(D.Operator("x", "x", elite=1, level=80), 2, 60),
          "E1 80 级不该过「≥精英二60」")

    check("八个主职业都有中文名",
          all(p in D.PROFESSION_CN for p in
              ("PIONEER", "WARRIOR", "TANK", "SNIPER", "CASTER", "MEDIC",
               "SUPPORT", "SPECIAL")),
          str(len(D.PROFESSION_CN)))
    op = D.Operator("c", "赤刃明霄陈", profession="WARRIOR",
                    sub_profession="术战者")
    check("分组表头：主职业视图是「近卫」、主-子视图是「近卫·术战者」",
          D.group_label(op, "prof") == "近卫"
          and D.group_label(op, "sub") == "近卫·术战者",
          f"{D.group_label(op, 'prof')} / {D.group_label(op, 'sub')}")
    check("子职业缺失时不留一个孤零零的分隔点",
          D.group_label(D.Operator("c", "n", profession="MEDIC"), "sub") == "医疗",
          D.group_label(D.Operator("c", "n", profession="MEDIC"), "sub"))

    roster = D.load_roster()
    if roster is None or not roster.top():
        skip("选人分类的界面部分", "没有名册，跳过（逻辑部分已断）")
        return

    async def flow() -> dict:
        got: dict = {}
        app = A.RiosApp(skip_login=True, stage="SR-EX-8")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            got["screen"] = type(app.screen).__name__
            # [2a] 答「我自己选」
            app.screen.dismiss(app.screen._choices[1])
            await pilot.pause()
            got["at_pick"] = type(app.screen).__name__
            sl = app.screen.query_one("#squad", SelectionList)

            def heads() -> list[str]:
                return [o.prompt.plain.strip("─ ")
                        for o in sl._options if o.prompt.plain.startswith("──")]

            def people() -> int:
                return len([o for o in sl._options
                            if not o.prompt.plain.startswith("──")])

            got["groups_prof"] = len(heads())
            got["people0"] = people()
            # 勾一个再切分类：勾选必须活下来
            sl.action_first()
            await pilot.press("space")
            await pilot.pause()
            got["picked_before"] = sorted(sl.selected)
            await pilot.press("g")
            await pilot.pause()
            got["groups_sub"] = len(heads())
            got["picked_after_group"] = sorted(sl.selected)
            got["head_options_disabled"] = all(
                o.disabled for o in sl._options
                if o.prompt.plain.startswith("──"))

            # 练度门槛
            counts = []
            for label, e, lv in D.TRAINED_FILTERS:
                app.screen._min = (e, lv)
                app.screen._fill()
                await pilot.pause()
                counts.append(people())
            got["counts"] = counts
            got["picked_after_filter"] = sorted(sl.selected)
            got["has_select"] = app.screen.query_one("#f-trained", Select) is not None
        return got

    got = asyncio.run(flow())
    check("[2a] 答「我自己选」才进选人屏",
          got["at_pick"] == "SquadPickScreen", f"{got['screen']} → {got['at_pick']}")
    check("默认按**主职业**分类（正好八组，不是每人一组）",
          got["groups_prof"] == 8, f"{got['groups_prof']} 组")
    check("按 G 切成「主职业-子职业」，组数明显变多",
          got["groups_sub"] > got["groups_prof"] * 3,
          f"{got['groups_prof']} → {got['groups_sub']} 组")
    check("分组表头是**不可选**的哑行（否则会混进编队）",
          got["head_options_disabled"], str(got["head_options_disabled"]))
    check("切分类不丢已勾的人",
          got["picked_before"] and got["picked_after_group"] == got["picked_before"],
          f"{got['picked_before']} → {got['picked_after_group']}")
    check("换练度门槛也不丢已勾的人",
          got["picked_after_filter"] == got["picked_before"],
          f"{got['picked_before']} → {got['picked_after_filter']}")
    check("三档门槛的人数单调递减（不限 ≥ 精英二60 ≥ 精英二90）",
          got["counts"][0] >= got["counts"][1] >= got["counts"][2]
          and got["counts"][0] == got["people0"],
          str(got["counts"]))
    check("界面上真有那个练度下拉框", got["has_select"], "f-trained")


def check_key_cases() -> None:
    """[14] **单字母绑定必须大小写都收**。

    博士实测「按 H 无法返回主界面」：Footer 上印着 `H`（`key_display` 只管显示），
    而 `Binding("h", …)` 只注册了小写——Textual 的键匹配区分大小写，按 Shift+H
    送过来的是大写 `H`，一个绑定都不匹配。**提示写着能用、按下去没反应。**

    这一节是全局守卫：任何 Screen 上凡有单字母绑定，就必须有大写孪生。
    """
    print("\n[14] 字母键大小写：Footer 印大写，按键也必须收大写")
    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("字母键", f"textual 没装（{exc}）")
        return

    from ak_tactic.tui import app as A

    missing: list[str] = []
    screens = 0
    for name in dir(A):
        obj = getattr(A, name)
        if not (isinstance(obj, type) and issubclass(obj, A.Screen)) or obj is A.Screen:
            continue
        bs = list(obj.__dict__.get("BINDINGS") or [])
        if not bs:
            continue
        screens += 1
        keys = {b.key for b in bs}
        for k in sorted(k for k in keys if len(k) == 1 and k.isalpha()):
            if k.islower() and k.upper() not in keys:
                missing.append(f"{name}.{k!r}")
            if k.isupper() and k.lower() not in keys:
                missing.append(f"{name}.{k!r}")
        shown = [b.key for b in bs if b.show]
        check(f"{name} 的显示键不重复（孪生必须 show=False）",
              len(shown) == len(set(shown)), str(shown))
    check("扫到了若干屏（不然这一节是空转）", screens >= 8, f"{screens} 屏")
    check("**每个单字母绑定都有大小写两份**", not missing, str(missing) or "无缺口")

    # 真按一次大写键：这是博士按的那个
    async def press_upper() -> dict:
        got: dict = {}
        app = A.RiosApp(skip_login=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            app.push_screen(A.ResultScreen())
            await pilot.pause()
            got["before"] = type(app.screen).__name__
            await pilot.press("H")
            await pilot.pause()
            got["after"] = type(app.screen).__name__
        return got

    got = asyncio.run(press_upper())
    check("结果屏上按大写 H 能回主界面",
          got["before"] == "ResultScreen" and got["after"] == "WelcomeScreen",
          f"{got['before']} -> {got['after']}")


def check_login_screen() -> None:
    """[13] 登录屏真的能扫码（需求第 11 条：这次测试加上登录测试）。

    **不联网**：只断「接线对不对、二维码画法对不对」。真去申请二维码会消耗
    一次上游配额，而且码 2 分钟就废——那属于人工实跑，不该进自检。
    """
    print("\n[13] 登录屏：扫码链路接线与二维码画法")
    from ak_tactic import qrterm
    from ak_tactic.tui import app as A

    QR_CONTENT = "hypergryph://scan_login?scanId=0123456789abcdef0123456789abcdef"

    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("登录屏", f"textual 没装（{exc}）")
        return

    binds = [(b.key, b.action) for b in A.LoginScreen.BINDINGS]
    check("登录屏挂了 L → 扫码登录", ("l", "login") in binds, str(binds))
    check("Esc 仍是返回", ("escape", "close") in binds, str(binds))
    for name in ("on_login_screen_qr_ready", "on_login_screen_qr_status",
                 "on_login_screen_login_done"):
        check(f"{name} 在（回调只 post，真正改界面的是它）",
              hasattr(A.LoginScreen, name), name)

    # 库已经搬进包里，TUI 才能正经 import（不再反向依赖 tools/）
    try:
        from ak_tactic import skland
        check("森空岛实现已进包（ak_tactic.skland），TUI 不必反向依赖 tools/",
              hasattr(skland, "login_by_qr"), "login_by_qr")
    except ImportError as exc:
        check("森空岛实现已进包（ak_tactic.skland）", False, str(exc))
        return
    def _tail(src: str, head: str) -> str:
        """从 `class <head>` 起到下一个顶层类为止。"""
        i = src.index(f"class {head}")
        rest = src[i + 10:]
        j = rest.find("\nclass ")
        return rest[:j] if j >= 0 else rest

    check("tools/skland.py 仍是可用入口（文档里写的就是它）",
          (Path(__file__).resolve().parent / "skland.py").exists(),
          "tools/skland.py")

    # 画法：绝不能把 ANSI 串塞进 Static
    src = Path(A.__file__).read_text(encoding="utf-8")
    seg = _tail(src, "LoginScreen")
    check("登录屏**不**调用 _render_ansi（会把 ANSI 串当标记解析）",
          "_render_ansi(" not in seg,
          "文档里提到它是可以的，调用它不行")
    check("登录屏走 qrterm.matrix 自己上色", "matrix(" in seg, "matrix(")

    # 真算一遍矩阵，断画法与编码
    m = qrterm.matrix("hypergryph://scan_login?scanId=0" * 1)
    check("矩阵是方的", len(m) == len(m[0]), f"{len(m)}x{len(m[0])}")
    check("U+2584 编得进 cp936（本机控制台是 GBK，U+2580 编不进）",
          len("\u2584".encode("cp936")) == 2, "2 字节")

    async def flow() -> dict:
        got: dict = {}
        app = A.RiosApp(skip_login=True)
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app.push_screen(A.LoginScreen())
            await pilot.pause()
            scr = app.screen
            got["screen"] = type(scr).__name__
            got["has_abort"] = hasattr(scr, "_abort")
            # 二维码另开一屏，全屏居中
            app.push_screen(A.QrScreen(QR_CONTENT))
            await pilot.pause()
            q = app.screen
            got["qr_screen"] = type(q).__name__
            got["border"] = q._pick_border()
            from textual.widgets import Static as _S
            qr_w = q.query_one("#qr", _S)
            box = q.query_one("#qr-box")
            got["qr_size"] = (qr_w.size.width, qr_w.size.height)
            got["box_size"] = (box.size.width, box.size.height)
            got["screen_size"] = (q.size.width, q.size.height)
            from ak_tactic.qrterm import matrix as _m
            m = _m(QR_CONTENT, border=got["border"])
            got["side"] = len(m)
            got["square"] = len(m) == len(m[0])
            got["quiet"] = (not any(m[0]) and not any(m[-1])
                            and not any(r[0] or r[-1] for r in m))
        return got

    got = asyncio.run(flow())
    check("登录屏能无头加载", got["screen"] == "LoginScreen", got["screen"])
    check("按 L 弹的是**独立的全屏二维码屏**", got["qr_screen"] == "QrScreen",
          got["qr_screen"])
    check("静默区给足 4 格（二维码四周必须留白，缺了识别率骤降）",
          got["border"] == 4, f"border={got['border']}")
    check("矩阵是方的", got["square"], f"{got['side']}x{got['side']}")
    check("静默区整圈为白（真画出来了，不只是算了算）", got["quiet"], "四周全白")
    check("二维码在屏内**不被裁**（控件宽 ≤ 屏宽、高 ≤ 屏高）",
          got["qr_size"][0] <= got["screen_size"][0]
          and got["qr_size"][1] <= got["screen_size"][1],
          f"控件 {got['qr_size']} / 屏 {got['screen_size']}")
    bx, by = got["box_size"]
    sx, sy = got["screen_size"]
    check("居中：左右留白对称（差 ≤1 列）",
          abs((sx - bx) // 2 - (sx - bx - (sx - bx) // 2)) <= 1,
          f"框 {got['box_size']} / 屏 {got['screen_size']}")
    check("居中：上下留白对称（差 ≤1 行，底部另有贴底状态行）",
          abs((sy - by) // 2 - (sy - by - (sy - by) // 2)) <= 2,
          f"框 {got['box_size']} / 屏 {got['screen_size']}")
    check("有 _abort，Esc 能把后台轮询叫停（不然它跑满 180 秒）",
          got["has_abort"], "_abort")


def check_esc_steps() -> None:
    """[15] Esc 逐层返回，以及 [3]/[4] 两屏不给 Esc（博士 2026-09-17 裁定）。

    原话：「这两屏不给 esc,结算中止退回上一步，结果屏只留退出程序和回主界面」。

    ## 为什么这一节必须真跑向导，而不是只看 BINDINGS

    向导里各屏选完是 `dismiss(值)` 把**自己**弹掉的，所以栈里只剩当前屏。
    曾经因此出现「Esc 不是返回上一步、而是一路掉回主界面」——**看绑定表
    完全看不出来**（每一屏都规规矩矩挂着 `escape → back`）。
    唯一能测出来的是真的走一遍、真的按 Esc、再看落在哪一屏。
    """
    print("\n[15] Esc：逐层返回，且 [3]/[4] 不给 Esc")
    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("Esc 逐层返回", f"textual 没装（{exc}）")
        return

    import asyncio

    from ak_tactic.tui import app as A

    # ---- 静态部分：这两屏不许有 escape ----
    for name in ("SolveScreen", "ResultScreen"):
        cls = getattr(A, name)
        keys = [b.key for b in cls.BINDINGS]
        check(f"{name} 不挂 Esc", "escape" not in keys, str(keys))
    solve_binds = {b.action for b in A.SolveScreen.BINDINGS}
    check("解算屏的中止键接在 action_cancel 上", "cancel" in solve_binds,
          str(sorted(solve_binds)))

    src = Path(A.__file__).read_text(encoding="utf-8")
    i = src.index("class SolveScreen")
    j = src.index("\nclass ", i + 10)
    seg = src[i:j]
    # 只找**语句**，不找散文：文档字符串里正解释着「原先这里是 self.app.exit()」，
    # 用 `in seg` 判会把我自己写的说明当成代码（上一版就这么误报了一次）。
    exits = [ln.strip() for ln in seg.splitlines()
             if ln.strip().startswith("self.app.exit(")]
    check("解算屏的中止**不再是** app.exit()（那是把「中止」当「退出程序」）",
          not exits, str(exits) or "没有 exit 语句")
    check("解算屏的中止走 app.back_to_step()（退回上一步）",
          "self.app.back_to_step()" in seg, "back_to_step()")
    check("解算屏有 _aborted 闸门（挡住后台线程回来后推结果屏）",
          "_aborted" in seg, "_aborted")

    check("App 有 push_step / step_back / back_to_step 三个方法",
          callable(getattr(A.RiosApp, "push_step", None))
          and callable(getattr(A.RiosApp, "step_back", None))
          and callable(getattr(A.RiosApp, "back_to_step", None)))

    # ---- 动态部分：真走一遍向导，逐层按 Esc ----
    async def flow() -> dict:
        got: dict = {}
        app = A.RiosApp(skip_login=True)          # 直接进 [1a]，省掉登录
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()

            def where() -> str:
                return type(app.screen).__name__

            got["start"] = where()
            # 选一个**有分部**的章/活动，才会出现 [1b] 那一层
            row = next((r for r in A.D.chapter_rows() if len(r["parts"]) > 1), None)
            if row is None:
                return got
            got["chapter"] = row["title"]
            # **必须走 dismiss**：各屏选完是自己弹掉的。直接调 app._chapter_picked
            # 会绕过这一弹，屏幕栈就假地累积起来，测出来的「返回」是假的。
            app.screen.dismiss(row)
            await pilot.pause()
            got["after_chapter"] = where()         # 期望 PartPickScreen

            part = row["parts"][0]
            app.screen.dismiss(part)
            await pilot.pause()
            # 有环境分层（第 9-14 章）时会先过环境层
            if where() == "EnvPickScreen":
                app.screen.dismiss(A.D.zone_envs(part["zone_id"])[0])
                await pilot.pause()
            got["at_stage"] = where()              # 期望 StagePickScreen
            got["path_len"] = len(app._path)

            # **关键一击**：在关卡层按 Esc，必须回到上一层，而不是掉回主界面
            # ——这正是博士报的毛病。
            await pilot.press("escape")
            await pilot.pause()
            got["after_esc1"] = where()

            # 再退一步，应当落在 [1a]
            await pilot.press("escape")
            await pilot.pause()
            got["after_esc2"] = where()

            # 退到最初一步后再按，才回 [0]
            await pilot.press("escape")
            await pilot.pause()
            got["after_esc3"] = where()
        return got

    got = asyncio.run(flow())
    if "at_stage" not in got:
        check("Esc 逐层返回：能走到关卡层", False, "找不到有多分部的章节，跳过")
    else:
        check("向导真跑到了关卡层", got["at_stage"] == "StagePickScreen",
              got["at_stage"])
        check("关卡层按 Esc **退回上一层**（不是掉回主界面）",
              got["after_esc1"] == "PartPickScreen",
              f"{got['at_stage']} -> {got['after_esc1']}")
        check("再按一次 Esc 落在 [1a] 选章/活动",
              got["after_esc2"] == "ChapterPickScreen", got["after_esc2"])
        check("退到最初一步后按 Esc 才回 [0]",
              got["after_esc3"] == "WelcomeScreen", got["after_esc3"])
        check("路径记全了三层（章/活动 → 分部 → 关卡）",
              got["path_len"] >= 3, str(got.get("path_len")))

    # ---- 中止的语义：不退出程序，只退回上一步 ----
    #
    # 这一节只测「中止之后落在哪一屏」，**不测搜索本身**。所以把后台搜索换成
    # 空操作——不换的话它会真去解一遍 SR-EX-8（分钟级），而这一节一个字都
    # 用不到它的结果。
    real_run = A.SolveScreen._run

    async def cancel_flow() -> dict:
        got: dict = {}
        app = A.RiosApp(skip_login=True)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            st = app.state
            row = A.D.chapter_rows()[0]
            # 一律走 dismiss：跟上一条一样，绕开它屏幕栈就不真实
            app.screen.dismiss(row)
            await pilot.pause()
            if type(app.screen).__name__ == "PartPickScreen":
                app.screen.dismiss(row["parts"][0])
                await pilot.pause()
            if type(app.screen).__name__ == "EnvPickScreen":
                st_zone = row["parts"][0]["zone_id"] if len(row["parts"]) == 1 \
                    else None
                if st_zone:
                    app.screen.dismiss(A.D.zone_envs(st_zone)[0])
                    await pilot.pause()
            if isinstance(app.screen, A.StagePickScreen):
                st.stage = {"code": "SR-EX-8", "level_id": "act54side_ex08",
                            "difficulty": "NORMAL", "zone_id": "act54side_zone2"}
                app.screen.dismiss(st.stage)
                await pilot.pause()
            if isinstance(app.screen, A.SquadAskScreen):
                app.screen.dismiss({"manual": False})
                await pilot.pause()
            got["at_solve"] = type(app.screen).__name__
            if isinstance(app.screen, A.SolveScreen):
                # 按 Footer 上印的那个键，不是直接调 action
                await pilot.press("Q")
                await pilot.pause()
                got["after_cancel"] = type(app.screen).__name__
                got["still_running"] = app.is_running
        return got

    A.SolveScreen._run = lambda self: None
    try:
        got2 = asyncio.run(cancel_flow())
    finally:
        A.SolveScreen._run = real_run

    if got2.get("at_solve") != "SolveScreen":
        check("解算屏的中止：能走到解算屏", False, str(got2))
    else:
        check("解算屏按中止**不退出程序**（程序还在跑）",
              got2.get("still_running") is True, str(got2.get("still_running")))
        check("解算屏按中止退回上一步（不是停在解算屏、也不是回主界面）",
              got2.get("after_cancel") in ("SquadPickScreen", "SquadAskScreen"),
              str(got2.get("after_cancel")))


def check_solve_pool() -> None:
    """[3] 解算的**人选池**：勾的人 + （auto 时）名册按练度补的人。

    这一节的存在理由是一条真 bug：`[2a]` 那一屏的默认项是「不用，让程序自己挑」，
    它把 `st.squad` 留成空表，而解算屏又把这张空表**原样**交给搜索——
    `candidates_for` 是按名单遍历的，空名单一个候选都不产生。于是默认这条路
    对任何关卡都当场返回「没有结果」，界面上还把原因写成"几何剪枝"。
    """
    from ak_tactic.plan import Roster as PlanRoster
    from ak_tactic.tui import app as A
    from ak_tactic.tui import data as D

    tui = D.load_roster()
    # **直接从夹具名册造一份 `plan.Roster`**，不去读文件：夹具的 `path` 是句
    # 说明（"自检夹具，不是真名册"），`PlanRoster.from_json` 会当场 FileNotFound。
    roster = PlanRoster({op.name: {"char_id": op.char_id, "elite": op.elite,
                                   "level": op.level, "potential": op.potential,
                                   "module": op.module,
                                   "module_level": op.module_level}
                         for op in tui.operators})
    top = [o.name for o in tui.top() if roster.get(o.name)]

    def pool_of(squad: list[str], mode: str) -> tuple[list[str], str]:
        st = SimpleNamespace(squad=squad, mode=mode, roster=tui)
        cls = type("FakeSolve", (A.SolveScreen,),
                   {"app": SimpleNamespace(state=st)})
        return cls()._pool(roster)

    check("解算屏真的有 _pool（人选池不再等于 st.squad）",
          callable(getattr(A.SolveScreen, "_pool", None)))

    pool, note = pool_of([], "auto")
    check("**不勾人也要有池子**（[2a] 默认那条路）", len(pool) > 0, note)
    check("不勾人时池子 = 名册按练度前 AUTO_POOL 人或全部",
          pool == top[:A.AUTO_POOL], f"{len(pool)} 人 / 名册 {len(top)} 人")
    check("池子说明写清「补了多少人」（界面上要看得见）",
          "名册按练度补" in note, note)

    picked = top[:3]
    pool, note = pool_of(picked, "auto")
    check("auto 模式：勾的人**排在池子最前**（先按你选的试）",
          pool[:len(picked)] == picked, str(pool[:5]))
    check("auto 模式池子上限是 AUTO_POOL（不是把 211 人全丢进去）",
          len(pool) == min(A.AUTO_POOL, len(top)), f"{len(pool)} 人")

    pool, note = pool_of(picked, "only")
    check("only 模式：池子**正好**是勾的那些人", pool == picked, str(pool))
    check("only 模式的说明只提勾的人", "只用勾的" in note, note)

    pool, note = pool_of([], "only")
    check("only 模式一个都没勾：池子为空", pool == [], str(pool))
    check("**并如实说「池子是空的」**，不再甩一句「几何剪枝」",
          "池子是空的" in note and "几何剪枝" not in note, note)
    check("空池子时告诉人怎么补救（回去勾人 / 按 M 换模式）",
          "勾人" in note and "M" in note, note)

    pool, note = pool_of([top[0], "名册里没有的人"], "only")
    check("名册里没有的人被剔掉，并在说明里点名",
          pool == [top[0]] and "名册里没有" in note, f"{pool} / {note}")

    # 搜索侧：空名单的措辞必须与"剪枝剪没了"分开——两者补救办法完全不同。
    from ak_tactic.search import Searcher
    row = next((r for r in D.stage_rows(limit=5) if r["level_id"]), None)
    if row is None:
        check("空名单的措辞（需要关卡表，跳过）", False, "关卡表是空的")
    else:
        r = Searcher(verbose=False).search(row["level_id"], roster, [])
        check("搜索：空名单 → 说「候选名单是空的」，不赖坐标口径",
              "名单是空的" in r.note and "几何剪枝" not in r.note, r.note)
        check("搜索：空名单不产生任何评估（当场返回）",
              r.evaluated == 0 and r.plan is None,
              f"evaluated={r.evaluated}")

    # 接线：解算屏交给搜索的必须是**池子**，不是 st.squad
    src = Path(A.__file__).read_text(encoding="utf-8")
    i = src.index("class SolveScreen")
    seg = src[i:src.index("\nclass ", i + 10)]
    check("解算屏把 _pool 的结果交给搜索（不是 st.squad）",
          "searcher.search(st.stage[\"level_id\"], roster, pool)" in seg
          and "self._pool(roster)" in seg, "_pool(roster) → search(..., pool)")
    check("解算屏把池子规模显示出来（st.pool_note）",
          "pool_note" in seg and "人选池" in seg, "pool_note")


def check_login_wizard() -> None:
    """[16] 初次干净启动的登录向导 / 本次或以后不登录 / 退出账号 / 切账号。

    博士 2026-09-17 的裁定：**初次干净启动先进入登录向导**；在登录屏按 Esc
    等于"不登录"，此时要补问一句是"本次"还是"以后都不"；[0] 屏加一个退出账号
    的键，方便换号。

    ## 夹子（不碰跑自检那个人的真实配置与真实 ~/.skland）

    ① `skland.DEFAULT_HOME` 换到临时目录。**不能用环境变量 `SKLAND_HOME`**
       ——`DEFAULT_HOME` 是模块级算出来的，而 `ak_tactic.skland` 在本文件
       前面的 [13] 节早就 import 过了，那时设的环境变量已经不起作用。
       （`cred_dir()` 写的是 `home or DEFAULT_HOME`，所以改模块属性有效。）
    ② `A.D.load_config` / `A.D.save_config` 换成走临时文件——配置路径在
       `data.py` 里写死成 `~/.rios/tui.json`，自检不能去动它。

    探针 `_proto/login_wizard_probe.py` 先跑通的就是这套夹子；这里是同一套。
    """
    print("\n[16] 初次启动登录向导 · 本次/以后不登录 · 退出账号 · 切账号")
    try:
        import textual                                              # noqa: F401
    except ImportError as exc:
        skip("登录向导", f"textual 没装（{exc}）")
        return
    from ak_tactic import skland
    from ak_tactic.tui import app as A

    old_home = skland.DEFAULT_HOME
    old_load, old_save = A.D.load_config, A.D.save_config
    tmp = Path(tempfile.mkdtemp(prefix="rios-check-tui-"))
    conf = tmp / "tui.json"

    def _load() -> dict:
        try:
            return json.loads(conf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save(**kw) -> None:
        cfg = _load()
        cfg.update(kw)
        conf.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    skland.DEFAULT_HOME = tmp
    A.D.load_config = _load
    A.D.save_config = _save
    try:
        _check_login_wizard_body(A, skland, tmp, conf, _load)
    finally:
        skland.DEFAULT_HOME = old_home
        A.D.load_config, A.D.save_config = old_load, old_save


def _check_login_wizard_body(A, skland, tmp: Path, conf: Path, read_cfg) -> None:
    # ---- 静态：按键挂对了没有
    wb = A.WelcomeScreen.BINDINGS
    check("[0] 准备屏挂了 O → 退出账号",
          any(b.key == "o" and b.action == "logout" for b in wb),
          str([(b.key, b.action) for b in wb]))
    descs = {b.action: b.description for b in wb}
    check("退出账号（O）与退出程序（Q）的文案分得开，不都印「退出」",
          descs.get("logout") == "退出账号" and descs.get("quit") == "退出程序",
          str(descs))
    lb = [(b.key, b.action) for b in A.LoginScreen.BINDINGS]
    check("登录屏挂了 S → 切换账号", ("s", "switch") in lb, str(lb))
    check("登录屏挂了 U → 补全账号信息（联网问一次绑定列表）",
          ("u", "fill") in lb, str(lb))
    check("登录屏的 Esc 还在（它仍是「回主界面」，只是已登录时不再补问）",
          ("escape", "close") in lb, str(lb))
    check("AskScreen 的选项键是数字 1–9 与 Esc（另补**全角数字**孪生，不上 Footer）",
          sorted(b.key for b in A.AskScreen.BINDINGS if b.key.isascii())
          == sorted(["escape"] + [str(i) for i in range(1, 10)]),
          str([(b.key, b.show) for b in A.AskScreen.BINDINGS]))
    check("AskScreen 补了全角数字（中文输入法全角模式下 1 送来的是 １）",
          all(any(b.key == chr(ord(str(i)) + 0xFEE0) for b in A.AskScreen.BINDINGS)
              for i in range(1, 10)),
          str([b.key for b in A.AskScreen.BINDINGS]))
    check("AskScreen 的 Esc 文案是「返回」（博士：类似提示都简化成一个词）",
          [b.description for b in A.AskScreen.BINDINGS if b.key == "escape"]
          == ["返回"],
          str([b.description for b in A.AskScreen.BINDINGS]))

    # ---- 凭据按 uid 分文件：退出账号不删任何文件
    skland.save_cred({"hgToken": "hg-x", "userId": None, "stage": "hg_token"})
    check("userId 未知时落 pending.json，不占账号位",
          skland.load_pending() is not None and skland.current_uid() is None,
          f"pending={skland.load_pending() is not None}")
    skland.save_cred({"hgToken": "hg-x", "cred": "cr-x", "token": "tk-x",
                      "userId": "9d1", "stage": "ready"})
    check("拿到 userId 后写进 cred_<uid>.json 并把当前账号指过去",
          skland.cred_path_for("9d1").exists() and skland.current_uid() == "9d1",
          str(skland.current_uid()))
    check("票据兑现后 pending.json 被清掉（留着会拿过期 hgToken 重试）",
          skland.load_pending() is None, "pending")
    skland.logout()
    check("退出账号后当前账号为空", skland.current_uid() is None,
          str(skland.current_uid()))
    check("退出账号**一个文件都不删**（否则切回旧号要重扫）",
          skland.cred_path_for("9d1").exists()
          and len(skland.known_accounts()) == 1,
          str([a["uid"] for a in skland.known_accounts()]))
    try:
        skland.load_cred()
        check("退出账号后读凭据要报「当前没有登录的账号」", False, "居然读出来了")
    except skland.SklandError as exc:
        check("退出账号后读凭据报的是「当前没有登录的账号」（不是别的错）",
              "当前没有登录的账号" in str(exc), str(exc))
    skland.activate("9d1")
    check("activate 能切回旧号且读到的就是它的凭据",
          skland.current_uid() == "9d1"
          and skland.load_cred().get("hgToken") == "hg-x",
          str(skland.current_uid()))

    # ---- 名册按**当前账号**取：取错账号的名册是这一类里最坏的错
    data_dir = Path(A.__file__).resolve().parents[3] / "data" / "skland"
    made: list[Path] = []
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        for uid, nick, mtime in (("9d1", "甲", 1_000_000.0),
                                 ("8c2", "乙", 2_000_000.0)):
            p = A.D.roster_file(uid)
            p.write_text(json.dumps(
                {"uid": uid, "nickName": nick,
                 "opers": [{"charId": "char_002_amiya", "name": "阿米娅",
                            "profession": "CASTER", "elite": 2, "level": 80,
                            "potential": 6, "trust": 100.0}]},
                ensure_ascii=False), encoding="utf-8")
            os.utime(p, (mtime, mtime))
            made.append(p)
        skland.set_current_uid("9d1")
        r = A.D.load_roster()
        check("名册按**当前账号**取，不是按文件 mtime 取最新的那份"
              "（取错账号不会报错，界面看着完全正常）",
              r is not None and r.uid == "9d1", f"uid={getattr(r, 'uid', None)}")
        check("cached_roster_uids 列出本机真有缓存的号",
              {"9d1", "8c2"} <= set(A.D.cached_roster_uids()),
              str(A.D.cached_roster_uids()))
        skland.set_current_uid("8c2")
        r2 = A.D.load_roster()
        check("切换账号后名册跟着换", r2 is not None and r2.uid == "8c2",
              f"uid={getattr(r2, 'uid', None)}")
        skland.logout()
        r3 = A.D.load_roster()
        check("退出账号后不冒用任何一个号的名册",
              r3 is None or r3.source != "skland",
              f"source={getattr(r3, 'source', None)}")
    finally:
        for p in made:
            try:
                p.unlink()
            except OSError:
                pass

    # ---- 「没名册」这一句要说清是哪一种（换号之后最先看到的就是它）
    _ou, _oc, _og = A.D.skland_uid, A.D.cached_roster_uids, A.D.skland_game_uid
    try:
        def _hint(uid, game, cached):
            A.D.skland_uid = lambda: uid
            A.D.skland_game_uid = lambda: game
            A.D.cached_roster_uids = lambda: cached
            return A.WelcomeScreen._no_roster_hint(object())

        h_uid = _hint("1000000000001", None, ["10000001"])
        h_game = _hint("1000000000001", "10000001", ["999"])
        h_fresh = _hint("1000000000001", "10000001", [])
        h_none = _hint(None, None, ["10000001"])
    finally:
        A.D.skland_uid, A.D.cached_roster_uids = _ou, _oc
        A.D.skland_game_uid = _og
    check("还不知道游戏 uid → 说的是「登录账号 ≠ 游戏 uid」并指向 U",
          "游戏 uid" in h_uid and "按 U" in h_uid and "10000001" in h_uid,
          h_uid.replace("\n", " / "))
    check("知道游戏 uid、但那个号没缓存 → 报的是游戏 uid，不是登录 uid",
          "10000001" in h_game and "1000000000001" not in h_game,
          h_game.replace("\n", " / "))
    check("知道游戏 uid、本机也没有任何缓存 → 又另一句",
          "还没有名册缓存" in h_fresh and "本机拉过" not in h_fresh,
          h_fresh.replace("\n", " / "))
    check("本来就没登 → 说的是「没有登录的账号」，不是「没拉过」",
          "没有登录的账号" in h_none and "缓存" not in h_none,
          h_none.replace("\n", " / "))

    # ---- 登录 uid 与游戏 uid 是两个量，映射要能记能读
    check("映射表默认是空的（自检用的是临时 home，不该有真数据）",
          isinstance(skland.accounts_map(), dict) and not skland.accounts_map(),
          str(skland.accounts_map()))
    skland.set_game_uid("9999", "7777", nick="夹具", channel="官服")
    rec = skland.accounts_map().get("9999") or {}
    check("记下「通行证账号 → 游戏 uid」后读得回来",
          rec.get("gameUid") == "7777" and rec.get("nickName") == "夹具",
          str(rec))
    check("accounts.json 的键是**登录账号**，不是游戏 uid",
          "9999" in skland.accounts_map() and "7777" not in skland.accounts_map(),
          str(sorted(skland.accounts_map())))
    _cur0 = skland.current_uid()
    skland.set_current_uid("9999")
    check("映射存在、且当前账号就是它 → game_uid() 取得到",
          skland.game_uid() == "7777", f"game={skland.game_uid()}")
    skland.set_current_uid(_cur0 or "")
    check("当前账号没有映射时 game_uid() 是 None（不是拿别人的顶上）",
          skland.game_uid() is None or skland.current_uid() == "9999",
          f"current={skland.current_uid()} game={skland.game_uid()}")

    # ---- 凭据过期时先补一次再问：`10000` 这个码字面看不出是过期
    _bl, _fl = skland.binding_list, skland.finish_login
    _cur_b = skland.current_uid()
    stale = "取绑定列表失败（sign 若错也会报同码）：{'code': 10000}"
    try:
        skland.set_current_uid("9d1")          # 它的夹具凭据是 stage=ready
        skland.finish_login = lambda home=None: {
            "userId": "9d1", "cred": "cr-new", "token": "tk-new",
            "stage": "ready"}
        seen = {"n": 0}

        def once_bad(cred, token):
            seen["n"] += 1
            if seen["n"] == 1:
                raise skland.SklandError(stale)
            return [{"uid": "10000001", "nickName": "补完后的",
                     "channelName": "官服"}]

        skland.binding_list = once_bad
        got_retry = skland.resolve_game_uid()
        n_retry = seen["n"]

        def always_bad(cred, token):
            seen["n"] += 1
            raise skland.SklandError(stale)

        seen["n"] = 0
        skland.binding_list = always_bad
        try:
            skland.resolve_game_uid()
            second = None
        except skland.SklandError as exc:
            second = str(exc)
        n_fail = seen["n"]
    finally:
        skland.binding_list, skland.finish_login = _bl, _fl
        skland.set_current_uid(_cur_b or "")
    check("凭据过期（code 10000）→ 先补一次 cred 再重问，不是当场失败",
          got_retry.get("gameUid") == "10000001" and n_retry == 2,
          f"问了 {n_retry} 次，拿到 {got_retry.get('gameUid')}")
    check("补完成功就把游戏 uid 记下来",
          (skland.accounts_map().get("9d1") or {}).get("gameUid") == "10000001",
          str(skland.accounts_map().get("9d1")))
    check("补完仍失败 → 抛的是**原来那个**错，且只补一次（不反复刷）",
          second == stale and n_fail == 2, f"n={n_fail} err={second}")

    # ---- `resolve_game_uid_for`：给**指定**账号补，不碰当前账号指向
    #
    # 登录屏按 U 要一次补好几个号，而 `resolve_game_uid` 只认当前账号。
    # 两条真判据：① 读的是那一个号自己的凭据文件；② 非当前账号失败**不许**
    # 拿当前账号的 hgToken 去补 cred（那是"静默换错号"的入口）。
    _bl2 = skland.binding_list
    _fl2 = skland.finish_login
    _cur_c = skland.current_uid()
    try:
        skland.save_cred({"hgToken": "hg-9d1", "cred": "cr-9d1", "token": "tk-9d1",
                          "userId": "9d1", "stage": "ready"})
        skland.save_cred({"hgToken": "hg-8f8", "cred": "cr-8f8", "token": "tk-8f8",
                          "userId": "8f8", "stage": "ready"})
        skland.set_current_uid("9d1")
        used: list[tuple[str, str]] = []

        def seen_cred(cred, token):
            used.append((cred, token))
            return [{"uid": "50000002", "nickName": "另一个号", "channelName": "B服"}]

        skland.binding_list = seen_cred
        got_for = skland.resolve_game_uid_for("8f8")
        check("resolve_game_uid_for 读的是**指定账号**的凭据（8f8，不是当前 9d1）",
              used == [("cr-8f8", "tk-8f8")], str(used))
        check("补完记在**那个账号**名下，当前账号的映射不受影响",
              (skland.accounts_map().get("8f8") or {}).get("gameUid") == "50000002"
              and (skland.accounts_map().get("9d1") or {}).get("gameUid")
              != "50000002",
              str(skland.accounts_map().get("8f8")))

        called = {"n": 0}

        def counting_finish(home=None):
            called["n"] += 1
            return {"userId": "8f8", "cred": "cr-nope", "token": "tk-nope",
                    "stage": "ready"}

        skland.finish_login = counting_finish

        def bad(cred, token):
            raise skland.SklandError(stale)

        skland.binding_list = bad
        try:
            skland.resolve_game_uid_for("8f8")
            err_noncur = None
        except skland.SklandError as exc:
            err_noncur = str(exc)
        check("非当前账号失败 → **不补 cred**（补 cred 只认当前账号的 hgToken，"
              "拿去救别的号会换错号）",
              called["n"] == 0 and err_noncur == stale,
              f"finish_login 调了 {called['n']} 次，err={err_noncur}")

        # 当前账号自己失败时才补一次（与 resolve_game_uid 同一条路）
        skland.finish_login = lambda home=None: {
            "userId": "9d1", "cred": "cr-fresh", "token": "tk-fresh",
            "stage": "ready"}

        def bad_then_ok(cred, token):
            if cred == "cr-fresh":
                return [{"uid": "50000001", "nickName": "补来的", "channelName": "官服"}]
            raise skland.SklandError(stale)

        skland.binding_list = bad_then_ok
        got_cur = skland.resolve_game_uid_for("9d1")
        check("当前账号自己失败 → 补一次 cred 再问（与 resolve_game_uid 同一条路）",
              got_cur.get("gameUid") == "50000001", str(got_cur))
    finally:
        skland.binding_list, skland.finish_login = _bl2, _fl2
        skland.set_current_uid(_cur_c or "")

    bl = [{"uid": "1"}, {"uid": "2", "isDefault": True}]
    check("pick_binding：没指定就取**默认角色**",
          skland.pick_binding(bl)["uid"] == "2", "isDefault 优先")
    check("pick_binding：指定 uid 就精确命中",
          skland.pick_binding(bl, "1")["uid"] == "1", "指定 1 → 拿到 1")
    try:
        skland.pick_binding(bl, "404")
        ok_missing = False
    except skland.SklandError:
        ok_missing = True
    check("要的 uid 不在绑定列表里 → 报错，**不静默挑一个顶上**",
          ok_missing, "不在列表里就抛 SklandError")
    try:
        skland.pick_binding([], None)
        ok_empty = False
    except skland.SklandError:
        ok_empty = True
    check("绑定列表为空 → 报「没有绑定任何明日方舟角色」", ok_empty, "")

    # ---- 真跑 TUI：初次启动 → Esc 补问 → 本次/以后 → 退出账号
    from textual.widgets import Static as _Static

    async def flow() -> dict:
        got: dict = {}
        conf.unlink(missing_ok=True)
        skland.logout()

        app = A.RiosApp(skip_login=False)
        async with app.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            got["first"] = type(app.screen).__name__
            await pilot.press("escape")
            await pilot.pause()
            got["esc_screen"] = type(app.screen).__name__
            got["esc_rows"] = [v for v, _ in getattr(app.screen, "_rows", [])]
            got["running"] = app.is_running
            await pilot.press("escape")             # 取消这一问
            await pilot.pause()
            got["cancel_screen"] = type(app.screen).__name__
            got["cancel_cfg"] = read_cfg()
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("1")                  # 本次不登录
            await pilot.pause()
            got["once_screen"] = type(app.screen).__name__
            got["once_cfg"] = read_cfg()

        conf.unlink(missing_ok=True)
        app2 = A.RiosApp(skip_login=False)
        async with app2.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            got["second"] = type(app2.screen).__name__
            await pilot.press("escape")
            await pilot.pause()
            await pilot.press("2")                  # 以后都不登录
            await pilot.pause()
            got["never_cfg"] = read_cfg()

        app3 = A.RiosApp(skip_login=False)
        async with app3.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            got["third"] = type(app3.screen).__name__
            await pilot.press("o")                  # 此刻没账号
            await pilot.pause()
            got["no_acct_title"] = getattr(app3.screen, "_title", "")

        skland.save_cred({"hgToken": "hg-y", "cred": "cr-y", "token": "tk-y",
                          "userId": "7b3", "stage": "ready"})
        app4 = A.RiosApp(skip_login=False)
        async with app4.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            await pilot.press("o")
            await pilot.pause()
            got["logout_title"] = getattr(app4.screen, "_title", "")
            got["logout_rows"] = [v for v, _ in getattr(app4.screen, "_rows", [])]
            await pilot.press("2")                  # 不退出
            await pilot.pause()
            got["kept"] = skland.current_uid()
            await pilot.press("o")
            await pilot.pause()
            got["cred_before_logout"] = sorted(p.name for p in tmp.glob("cred_*.json"))
            await pilot.press("1")                  # 退出账号
            await pilot.pause()
            got["after_logout"] = skland.current_uid()
            got["after_logout_cfg"] = read_cfg()
            got["cred_left"] = sorted(p.name for p in tmp.glob("cred_*.json"))

        # ---- 已登录时：Esc 直接回主界面；登录成功**自动**回主界面（博士 2026-09-18）
        skland.save_cred({"hgToken": "hg-x", "cred": "cr-x", "token": "tk-x",
                          "userId": "9d1", "stage": "ready"})
        skland.set_game_uid("9d1", "90000001", nick="测试博士", channel="官服")
        app5 = A.RiosApp(skip_login=False)
        async with app5.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            got["logged_start"] = type(app5.screen).__name__
            app5.push_screen(A.LoginScreen())
            await pilot.pause()
            got["login_list"] = str(
                app5.screen.query_one("#login-accounts", _Static).render())
            await pilot.press("escape")
            await pilot.pause()
            got["esc_logged"] = type(app5.screen).__name__
            got["welcome_acct"] = str(
                app5.screen.query_one("#account-line", _Static).render())
            # 扫码成功：LoginDone(ok=True) 一进来就该弹回 [0]
            app5.push_screen(A.LoginScreen())
            await pilot.pause()
            app5.screen.post_message(
                A.LoginScreen.LoginDone(True, "登录成功，凭据已保存。"))
            await pilot.pause()
            got["after_done"] = type(app5.screen).__name__
            got["after_done_note"] = str(
                app5.screen.query_one("#account-line", _Static).render())

        # ---- 全角按键（中文输入法全角模式）：ｌ 进登录屏、ｓ 弹切号
        app6 = A.RiosApp(skip_login=True)
        async with app6.run_test(size=(120, 44)) as pilot:
            await pilot.pause()
            app6.push_screen(A.WelcomeScreen())
            await pilot.pause()
            got["fw_before"] = type(app6.screen).__name__
            await pilot.press("\uff4c")             # 全角 ｌ
            await pilot.pause()
            got["fw_l"] = type(app6.screen).__name__
            await pilot.press("\uff33")             # 全角 ｓ
            await pilot.pause()
            got["fw_s"] = type(app6.screen).__name__
        return got

    got = asyncio.run(flow())

    check("初次干净启动**先落在登录屏**（不是 [0]）",
          got["first"] == "LoginScreen", got["first"])
    check("登录屏按 Esc 弹出「本次 / 以后都不」的补问",
          got["esc_screen"] == "AskScreen", got["esc_screen"])
    check("补问的两行就是本次与以后都不",
          got["esc_rows"] == ["once", "never"], str(got["esc_rows"]))
    check("按 Esc 到这里**没有把程序关掉**", got["running"] is True,
          str(got["running"]))
    check("补问屏上再按 Esc ＝ 取消这一问、回登录屏",
          got["cancel_screen"] == "LoginScreen", got["cancel_screen"])
    check("取消不写配置（他可能只是按错了）", not got["cancel_cfg"],
          str(got["cancel_cfg"]))
    check("选「本次不登录」落到 [0] 准备屏",
          got["once_screen"] == "WelcomeScreen", got["once_screen"])
    check("选「本次」**不写**配置", not got["once_cfg"], str(got["once_cfg"]))
    check("问过「本次」之后下一次干净启动**仍然**进向导（「本次」就是这个意思）",
          got["second"] == "LoginScreen", got["second"])
    check("选「以后都不登录」写进配置",
          got["never_cfg"].get("login_prompt") == "never",
          str(got["never_cfg"]))
    check("记着「以后都不」之后下次启动**直接进 [0]**、L 键仍留着",
          got["third"] == "WelcomeScreen", got["third"])
    check("没有账号时按 O 给一句说明，不当场报错",
          got["no_acct_title"] == "没有可退出的账号", got["no_acct_title"])
    check("有账号时按 O 先弹确认", got["logout_title"] == "退出账号",
          got["logout_title"])
    check("确认是二选一：退出 / 不退出",
          got["logout_rows"] == ["yes", "no"], str(got["logout_rows"]))
    check("选「不退出」账号原样留着", got["kept"] == "7b3", str(got["kept"]))
    check("选「退出账号」后当前账号为空", got["after_logout"] is None,
          str(got["after_logout"]))
    check("退出账号**不删凭据文件**（退出前后一份都没少）",
          got["cred_left"] == got["cred_before_logout"]
          and {"cred_9d1.json", "cred_7b3.json"} <= set(got["cred_left"]),
          f"{got['cred_before_logout']} → {got['cred_left']}")
    check("退出账号顺手清掉「以后都不登录」（他要换号，那条不该再拦他）",
          not got["after_logout_cfg"].get("login_prompt"),
          str(got["after_logout_cfg"]))

    # ---- 博士 2026-09-18 那一组：登已有账号要说话 · 账号列表口径 · Esc/登录成功直接回车
    check("已有账号时启动**不拦登录向导**（直接落在 [0]）",
          got["logged_start"] == "WelcomeScreen", got["logged_start"])
    check("**已登录时按 Esc 直接回主界面**，不再弹「是否不登录」",
          got["esc_logged"] == "WelcomeScreen", got["esc_logged"])
    check("扫码成功 → **自动回主界面**（不再等用户按 Esc）",
          got["after_done"] == "WelcomeScreen", got["after_done"])
    check("回主界面时把「登的是哪个号」写在账号行上",
          "测试博士" in got["after_done_note"], got["after_done_note"][:120])
    check("账号列表显示**游戏用户名**（不是空白）",
          "测试博士" in got["login_list"], got["login_list"][:120])
    check("账号列表显示**游戏uid**",
          "游戏uid=90000001" in got["login_list"], got["login_list"][:120])
    check("[0] 屏账号行同样是「游戏用户名 + 游戏uid」",
          "测试博士" in got["welcome_acct"] and "游戏uid=90000001" in got["welcome_acct"],
          got["welcome_acct"][:120])
    check("通行证账号 id 退成附注（不再冒充 uid）",
          "uid=9d1" not in got["welcome_acct"] and "登录账号 9d1" in got["welcome_acct"],
          got["welcome_acct"][:160])

    # ---- 输入法全角：按键匹配表补了全角孪生，真按下也走通
    check("全角 ｌ（U+FF4C）也能进登录屏——中文输入法全角模式的产物",
          got["fw_before"] == "WelcomeScreen" and got["fw_l"] == "LoginScreen",
          f"{got['fw_before']} → {got['fw_l']}")
    check("全角 ｓ（U+FF53）也能弹切号屏",
          got["fw_s"] == "AskScreen", got["fw_s"])

    # ---- `_back_note` 三种情形（登回当前号 / 登回已有别的号 / 新号）
    def _note(cur_before, known) -> str:
        scr = A.LoginScreen()
        scr._cur_before = cur_before
        scr._known_before = set(known)
        return scr._back_note()

    skland.activate("9d1")
    n_same = _note("9d1", ("9d1",))
    n_known = _note("7b3", ("9d1", "7b3"))
    n_new = _note("7b3", ("7b3",))
    check("登录成功：登回**当前这个号** → 明说「本来就登录着」（账号没变多）",
          "本来就登录着" in n_same, n_same)
    check("登录成功：登到本机**已有的另一个号** → 明说「本机已经登录过」",
          "本机已经登录过" in n_known, n_known)
    check("登录成功：**新号** → 明说这是新账号",
          "新账号" in n_new, n_new)
    check("这三种话都带上游戏用户名与游戏uid",
          all("游戏uid=" in x for x in (n_same, n_known, n_new)),
          str([n_same, n_known, n_new])[:160])

    # ---- 账号行排版：未知时如实说未知并给出补救键
    unknown = A.D.describe_account("0f0f0f")
    check("映射还没建立的账号如实写「游戏用户名未知」并指向 U 键",
          "游戏用户名未知" in unknown and "按 U" in unknown, unknown)
    check("未知账号不假装有名册缓存", "无名册缓存" in unknown, unknown)


def main() -> int:
    print("检查终端界面（ak_tactic/tui/）")
    # 界面各节用**夹具名册**跑：真名册要 `skland fetch` 之后才有，
    # 而换过账号（或从没拉过）的机器上它根本不存在。判据本身在 [16] 节单验。
    old_loader = install_fixture_roster()
    try:
        check_lazy_import()
        check_registration()
        check_data_layer()
        check_stage_access()
        check_ui()
        check_empty_stage_guard()
        check_qrterm()
        check_squad_keys()
        check_maa_export()
        check_home()
        check_welcome()
        check_result_back_to_stage()
        check_stage_categories()
        check_stage_layers()
        check_completion()
        check_squad_grouping()
        check_key_cases()
        check_login_screen()
        check_esc_steps()
        check_solve_pool()
    finally:
        restore_roster(old_loader)
    # [16] 要真的读本机凭据与名册文件（只是换到临时目录），必须用真函数
    check_login_wizard()

    print(f"\n通过 {_PASSED} 项", end="")
    if _SKIPPED:
        print(f"，跳过 {len(_SKIPPED)} 项", end="")
    if _FAILED:
        print(f"，失败 {len(_FAILED)} 项：")
        for f in _FAILED:
            print(f"  - {f}")
        return 1
    print("，无失败。")
    if _SKIPPED:
        for s in _SKIPPED:
            print(f"  （跳过：{s}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


