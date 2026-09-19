# -*- coding: utf-8 -*-
"""`frontend/talent_finders.py` 与 `battle/talents.py` 的**逐字 A/B**。

## 判据分两层

1. **源码层**：把两边的同名定义各自取出来，去掉注释与空行后**逐字比较**。
   这是最强的一层——搬运本该是"原样搬"，源码不同就说明我手滑了。
2. **行为层**：拿真的 `Talent` 对象（从名册的天赋库里取）把每个 `find_*`
   在两边各跑一遍，比返回值。

⚠ 只做第 2 层不够：六个 `find_*` 的**形状完全一样**（遍历、判据、返回），
随便填一个判据进去都可能在这批样本上给出同样结果。
⇒ 源码层是主判据，行为层是配菜。

跑法：`python tools\\check_talent_finders.py`
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

OLD = ROOT / "ak_tactic" / "battle" / "talents.py"
NEW = ROOT / "ak_tactic" / "frontend" / "talent_finders.py"


def baseline_source() -> str:
    """**搬走之前**的 `talents.py`。

    ⚠ 搬完之后 `talents.py` 里已经**没有那些定义**了（只剩转出导入），
    所以"拿它跟新家逐字比"必然报"原件里找不到"——第一次搬完跑这个 A/B
    就是这么红了 35 项，看起来像搬坏了，其实只是基线选错了地方。

    真正的基线是 **HEAD 里那一版**：`git show HEAD:ak_tactic/battle/talents.py`。
    这样这个检查在搬运前后都成立，而且搬完之后它才真正开始有用
    （它比的是"生成的副本"与"当初那份原件"）。
    """
    import subprocess
    rel = "ak_tactic/battle/talents.py"
    for rev in ("HEAD", ""):
        cmd = ["git", "show", "%s:%s" % (rev, rel)] if rev else None
        if cmd is None:
            break
        try:
            out = subprocess.run(cmd, cwd=str(ROOT), capture_output=True,
                                 check=True)
            text = out.stdout.decode("utf-8")
            if "def find_snow" in text:
                return text
        except Exception:                                         # noqa: BLE001
            continue
    #: 退路：真取不到就用工作树里那份（并说清楚，别让人以为比过了）
    print("⚠ 取不到 HEAD 版本，退回用工作树里的 talents.py —— "
          "搬完之后这样比会报「原件里找不到」，**不构成结论**")
    return OLD.read_text(encoding="utf-8")

#: ⚠ 清单**必须**取自生成器的自动推导（`AUTO_*`）。
#: 第一版这里是手写的，漏了 `find_class_aura` 等三个名字，
#: 于是"逐字一致"这条结论**覆盖面本身就是错的**——
#: 一份漏项的 A/B 报告全绿，比不报还危险。
sys.path.insert(0, str(ROOT))
from tools.gen_talent_finders import AUTO_CONSTS, AUTO_FUNCS         # noqa: E402

CONSTS, FUNCS = list(AUTO_CONSTS), list(AUTO_FUNCS)


def _norm(src: str, name: str, drop_first: bool) -> str | None:
    """同名定义的**规范化正文**：去掉注释、空行、文档串之后的 `unparse`。

    `drop_first=True` 时丢掉第一句语句——`frontend` 那份的 `is_*` 前面
    多了一句 `Talent` Protocol 的说明吗？不是；这里留着是为了将来需要。
    """
    tree = ast.parse(src)
    for node in tree.body:
        hit = (isinstance(node, ast.FunctionDef) and node.name == name)
        if not hit and isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgt = (node.targets[0] if isinstance(node, ast.Assign)
                   else node.target)
            hit = isinstance(tgt, ast.Name) and tgt.id == name
        if not hit:
            continue
        body = list(node.body) if isinstance(node, ast.FunctionDef) else [node]
        if isinstance(node, ast.FunctionDef) and body \
                and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant):
            body = body[1:]              # 文档串不比（两边本就允许不同）
        if isinstance(node, ast.FunctionDef):
            head = ast.arguments(
                posonlyargs=[], args=node.args.args, vararg=None,
                kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[])
            node2 = ast.FunctionDef(name=name, args=head,
                                    body=body or [ast.Pass()],
                                    decorator_list=[], returns=None)
        else:
            node2 = node
        return ast.unparse(ast.fix_missing_locations(node2))
    return None


def main() -> int:
    old, new = baseline_source(), NEW.read_text(encoding="utf-8")
    bad = 0
    for group, names in (("常量", CONSTS), ("函数", FUNCS)):
        print("=== %s ===" % group)
        for name in names:
            a = _norm(old, name, False)
            b = _norm(new, name, False)
            if a is None:
                print("  ❓ %-26s 原件里找不到" % name)
                bad += 1
            elif b is None:
                print("  ❓ %-26s 新文件里找不到" % name)
                bad += 1
            elif a != b:
                print("  ❌ %-26s 不一致" % name)
                print("      原件：%s" % a[:110])
                print("      新家：%s" % b[:110])
                bad += 1
            else:
                print("  ✅ %-26s 逐字一致" % name)
        print()

    #: 行为层：拿真的天赋对象两边各跑一遍
    print("=== 行为层（真天赋对象）===")
    from ak_tactic.battle import talents as t_old
    from ak_tactic.frontend import talent_finders as t_new
    behav = "未跑"
    try:
        from ak_tactic.operator import TalentBook
        book = TalentBook()
        tried = 0
        for cid in ("char_103_angel", "char_002_amiya", "char_1001_amiya2",
                    "char_4064_mlynar", "char_1046_sbell2"):
            for row in book.for_operator(cid):
                #: ⚠ `for_operator` 给的是**一列候选**（每个天赋一条），
                #: 直接当 Talent 用会 `'list' object has no attribute 'has'`
                #: ——第一版就是这么炸的。两种形状都接住。
                cands = row if isinstance(row, (list, tuple)) else [row]
                tried += 1
                for fn in FUNCS:
                    #: ⚠ **两种签名**：`is_*` 收单个天赋、`find_*` 收一列。
                    #: 一律传列表会炸在 `is_regen_talent` 的 `t.has(...)` 上
                    #: （第一版就是这么错的，而且看起来像代码坏了）。
                    arg = cands if fn.startswith("find_") else cands[0]
                    r1 = getattr(t_old, fn)(arg) is not None
                    r2 = getattr(t_new, fn)(arg) is not None
                    if r1 != r2:
                        print("  ❌ %s(%s)：原件 %s / 新家 %s"
                              % (fn, cid, r1, r2))
                        bad += 1
        print("  比了 %d 条天赋记录" % tried)
        if tried == 0:
            print("  ⚠ 一条都没取到——**判据跑空了**，不能当成通过")
            bad += 1
            behav = "跑空"
        else:
            behav = "%d 条" % tried
    except Exception as exc:                                      # noqa: BLE001
        import traceback
        print("  ⚠ 行为层跑不动：%s" % exc)
        print("  ⚠ 回溯（末 6 行）：")
        for line in traceback.format_exc().strip().splitlines()[-6:]:
            print("      " + line)
        #: ⚠ **不能把它说成"无一例外"**：仪器没跑起来与仪器说没问题
        #: 是两件事。第一版就印了"行为层无一例外"，而那时它刚抛过异常。
        behav = "**没跑起来**（不影响上面的源码层结论）"

    print()
    if bad:
        print("❌ %d 处有问题" % bad)
        return 1
    print("✅ 常量 %d 项 + 函数 %d 项，源码逐字一致" % (len(CONSTS), len(FUNCS)))
    print("   行为层：%s" % behav)
    return 0


if __name__ == "__main__":
    sys.exit(main())
