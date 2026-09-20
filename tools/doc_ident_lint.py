# -*- coding: utf-8 -*-
"""标识命名空间检查（验收会话自用）。

由来（PM 2026-09-20 第三件）：**任何标识都必须在产生它的那次动作之后才能被引用；
写不出「它是从哪儿读出来的」，就只能写「待取」。**
本仓里最容易犯的形态：**同一个形状承载两种命名空间**——8 位十六进制既是提交前缀
（`git cat-file -e` 能解析），又是记忆条目 id（不能解析）。★ 实测我的文档里有 54 个
反引号内的十六进制，其中 40 余个是**记忆 id**；一个按 sha 去 `git show` 的人会扑空，
而它们在形状上与真 sha 毫无区别（同族 `18f53299`）。

判据（三态，全部只用文档自身，不依赖外部文件 —— `bd07345f`）：
  · 能被 `git cat-file -e <tok>^{commit}` 解析   ⇒ 命名空间＝提交，首次出现处须贴「提交」；
  · 不能解析且长度 16                        ⇒ 命名空间＝sha16（文件哈希），须贴「sha16」；
  · 不能解析且长度 8                         ⇒ 命名空间＝记忆（条目 id），须贴「记忆」；
  · 其它（长度 9~15 / 17~40 且不是提交）      ⇒ **判红**：说不出它是从哪儿读出来的。
标签必须**紧贴反引号**，且**与命名空间一致** —— 只查「有没有标签」会被这条挡住：
★ 实测（本检查的反向守卫 B）：把真提交错标成「记忆」时，只查有没有标签的版本报 rc=0；
  而「贴错标签」的危害与「不贴标签」不同：它会让读者**去错的地方找**（去记忆轨里找一个提交）。

★ 本检查盖到哪为止（`3ee39185`）：它证明的是「**每个标识都声明了自己属于哪套命名空间**」，
  **不证明**「那个记忆 id 真的存在」（要证得去读记忆轨 ⇒ 外部依赖，按 `bd07345f` 拒）。
  这一层写在这里，免得下游把它读成「所有引用都核过了」。

★ 自检（防恒真）：本检查内置一个**合成反例**（8 位十六进制、非提交、不带标签），
  若它没被判红，就说明检查恒真 ⇒ 自己判 rc=2 并明说。
★ 反向守卫矩阵（`out/acceptance/identguard/`，本检查真跑过）：control rc=0、
  A 未贴标签 rc=1、**B 贴错命名空间 rc=1**、C 12 位非提交 rc=1。

用法：python tools/doc_ident_lint.py <文档路径> [...]
退出码：0 = 全部标识的命名空间已声明且正确；1 = 有未声明／未归类／贴错的；2 = 检查本身恒真。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

TOKEN = re.compile(r"`([0-9a-fA-F]{7,64})`")
LONG = re.compile(r"`([0-9a-fA-F]{65,})`")          # ★ 长度>64 ⇒ 仍然逃逸，必须自己会红（不许静默）
# ★ 第三面（后端2 送回）：**段内含非十六进制字符** ⇒ 整段不匹配 TOKEN。按装饰**语义**分两级：
REV = re.compile(r"`([0-9a-fA-F]{7,64})[\^~]`")     # 修订算符 ⇒ 十六进制部分**就是提交引用** ⇒ 进判定
TRUNC = re.compile(r"`([0-9a-fA-F]{7,64})…`")        # 省略号＝截断 ⇒ **推不出命名空间**（8 位截断会按形状误判成记忆）⇒ 只报不判
MIXED = re.compile(r"`[^`\n]*?[0-9a-fA-F]{7,64}[^`\n]*?`")
TRUNCATED: list = []
MIXED_HITS: list = []
SPELLING_UPPER: list = []
TOO_LONG: list = []


def resolves_as_commit(tok: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", tok + "^{commit}"],
                          capture_output=True).returncode == 0


def classify(tok: str) -> str:
    if resolves_as_commit(tok):
        return "提交"
    if len(tok) == 16:
        return "sha16"
    if len(tok) == 8:
        return "记忆"
    if len(tok) == 64:
        return "sha256"      # ★ 整份 sha256（两侧原文哈希常按这个长度写）
    return "未归类"          # 9~15／17~39／41~63 且不是提交 ⇒ 说不出从哪儿读出来的


def ident(path: Path) -> str:
    """印出**被测对象自己的身份**：工作区形态 sha16／入库 blob sha16／行数。

    ★ 由来（PM 2026-09-20）：我报「61 种」，PM 现算是「66 种」。61 是**测出来的**，
      但我**测完又改了文档**（§21.5 加了 5 个标识）⇒ 那个数测的是**已被取代的对象**。
      ⇒ **一个计数不许脱离「它测的是哪一版」单独旅行**。判据落在这里：**每次运行都把身份与数印在同一行**，
      于是报数只需贴这一行，人手算不进来（`df24ee6a`：漂移/清单要自带身份）。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return "  被测对象：**读不到** ⇒ 拒跑"
    import hashlib as _h, subprocess as _sp
    ws = _h.sha256(data).hexdigest()[:16]
    norm = _h.sha256(data.replace(b"\r\n", b"\n")).hexdigest()[:16]
    rel = path.as_posix()
    blob = _sp.run(["git", "cat-file", "blob", "HEAD:" + rel], capture_output=True)
    b16 = _h.sha256(blob.stdout).hexdigest()[:16] if blob.returncode == 0 else None
    lines = data.decode("utf-8", "replace").count(chr(10))
    if b16 is None:
        return (f"  被测对象：工作区形态 sha16={ws}／行数={lines}／归一(CRLF→LF) sha16={norm}"
                f"\n  ⊘ 与入库 blob 的可比性：**不适用**（`{rel}` 不在 HEAD 的树里 ⇒ 无入库形态可对）")
    side = f"工作区形态 sha16={ws}／入库 blob(HEAD) sha16={b16}"
    tip = f"  被测对象：{side}／行数={lines}／归一(CRLF→LF) sha16={norm}"
    if norm != b16:
        tip += (f"\n  ⚠ **工作区与入库 blob 归一后仍不同 ⇒ 有未提交改动**：这个读数可能测到\n"
                f"     **一个正在被写的中间态**（实测：别人正在改的那份文档被我读成 rc=1 判 5 处，\n"
                f"     重测 rc=0、且 diff 显示 38 行未提交 ⇒ 那不是缺陷，是**撕裂读**）。\n"
                f"     ⇒ **要下结论先冻住**：从 `git show <sha>:{rel}` 取只读副本再量（`5558b5a0`）。\n"
                f"     ★ **⚠ 与 rc 是两条轴**：⚠ 只提示「这个读数可能是中间态」，**它本身不参与 rc** ——\n"
                f"     构造态（内容本身不含违规）实测 **rc=0**；不要把 ⚠ 读成失败（后端2 实测并回送）。")
    else:
        tip += "\n  ✓ 工作区与入库 blob 归一后相同（差异仅行尾或有未提交改动时另报）"
    return tip


def label_before(ln: str, pos: int) -> str | None:
    """取**该出现处自己**紧邻前面的标签（按位置回看，不是按行取第一个）。

    ★ 这里踩过一次：先用 `re.search(标签 + 反引号)` 取整行第一个匹配 ⇒ 一行里出现两次时，
      第二次永远看到第一次的标签，于是「首处贴对、后面贴错」被判成绿（反向守卫 B 当场抓到）。
      ⇒ 粒度必须是**出现处**，不是行。
    """
    head = ln[max(0, pos - 10):pos]
    for w in ("sha256", "提交", "sha16", "记忆"):
        if not (head.endswith(w) or (head.rstrip().endswith(w) and head[len(head.rstrip()):].strip() == "")):
            continue
        # ★ 散文与标签在这把尺子里无法区分：`不是提交 X` / `非 sha16 X` 里的词紧邻反引号，
        #   会被读成「贴了标签」。语义反了也照样绿 ⇒ 加一条否定词窗口：紧邻的否定词使该词**不构成标签**。
        j = head.rstrip().rfind(w)
        win = head[max(0, j - 2):j]
        if any(c in win for c in ("不", "非", "未", "别")):
            return None
        return w
    return None


def collisions(info: dict, ids: set[str]) -> tuple[list[str], int]:
    """与**形状无关的第二来源**求交（可选）：记忆轨里真实存在的条目 id 清单。

    ★ 为什么需要它：`classify` 按**形状/可解析性**给命名空间。若某个 8 位值**既能解析为提交、
      又恰好是一条记忆条目 id**，按形状只会归「提交」，而那一处文档可能实际在指记忆条目
      ⇒ 检查会绿着放过一个**语义贴错**的标签（后端2 提出的洞，量级见 §21.5）。
    ★ 它盖到哪为止：只能查出**数值在两套命名空间里都存在**（那时值本身不再唯一确定语义，
      必须由人确认），**查不出**「值只在一套里存在、却被当成另一套用」——那种情况在文档里
      **没有第二个语义来源**，唯一来源就是标签本身（这正是本纪律要求贴标签的原因）。
    """
    bad: list[str] = []
    ghost = sorted(tok for tok, (ns, _, _) in info.items() if ns == "记忆" and tok not in ids)
    for tok in ghost:
        bad.append(f"`{tok}` 是「8 位非提交」而**不在记忆 id 清单里** ⇒ **一个不属于任何命名空间的标识**："
                   f"本检查按形状把它推定为「记忆」并要求贴标签，而第二来源否证了这个推定 ⇒ "
                   f"**不要给它贴假标签**（要么它是别的东西、要么清单不全）")
    hit = sorted(tok for tok, (ns, _, _) in info.items() if ns == "提交" and tok in ids)
    for tok in hit:
        bad.append(f"`{tok}` 既能解析为提交、又在记忆 id 清单里 ⇒ **值本身不再唯一确定语义**，"
                   f"请人工确认文档里那一处指的是哪一个（形状判不了）")
    return bad, len(hit)


def scan(path: Path) -> tuple[list[str], dict[str, tuple[str, int, str | None]]]:
    """返回 (判红理由, {token: (命名空间, 首次出现行号, 首次处贴的标签或 None)})。

    ★ 两条判据合起来才盖住这类错：
      ① **首次出现**处必须贴着**正确**的标签（读者第一次遇到它就得知道它是谁）；
      ② **任何一处**只要贴了标签，就必须贴对——贴错比不贴更坏，它让读者去错的地方找。
    """
    bad: list[str] = []
    info: dict[str, tuple[str, int, str | None]] = {}
    mislabel: list[str] = []
    _too_long_here: list[str] = []
    SPELLING_UPPER.clear()
    TOO_LONG.clear()
    TRUNCATED.clear()
    MIXED_HITS.clear()
    for i, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for m in LONG.finditer(ln):
            TOO_LONG.append(f"{path.name}:{i}  长度 {len(m.group(1))} 的十六进制串"
                            f"**超出尺子上限 64 ⇒ 它对判定完全不可见**，请缩短或改口径后再引用")
        for m in REV.finditer(ln):
            raw = m.group(1)
            label = label_before(ln, m.start())
            ns = classify(raw.lower())
            if label is None:
                bad.append(f"{path.name}:{i}  `{raw}[修订算符]` 的十六进制部分是**{ns}**"
                           f"（本仓约定：提交前缀 + ^ / ~）但**没有贴着标签** ⇒ 读者会把「前缀+算符」当成别的东西")
            elif label != ns:
                bad.append(f"{path.name}:{i}  `{raw}[修订算符]` 是**{ns}**却贴成了「{label}」")
        for m in TRUNC.finditer(ln):
            TRUNCATED.append(f"{path.name}:{i}  `{m.group(1)}…`")
        for m in MIXED.finditer(ln):
            seg = m.group(0)
            if TOKEN.fullmatch(seg) or REV.fullmatch(seg) or TRUNC.fullmatch(seg):
                continue
            MIXED_HITS.append(f"{path.name}:{i}  {seg[:70]}")
            break
        for m in TOKEN.finditer(ln):
            raw = m.group(1)
            tok = raw.lower()          # ★ 大写拼法也要被抓到；判定归一小写（git 的 sha 解析本就不分大小写）
            if raw != tok:
                SPELLING_UPPER.append(raw)
            label = label_before(ln, m.start())
            ns_here = classify(tok)
            if tok not in info:                       # ① 首次出现
                info[tok] = (ns_here, i, label)
            elif label is not None and label != ns_here:   # ② 后面任何一处贴错
                mislabel.append(f"{path.name}:{i}  `{tok}`（{ns_here}）在这里贴成了「{label}」")
    bad.extend(TOO_LONG)
    for tok, (ns, line, label) in sorted(info.items(), key=lambda kv: kv[1][1]):
        if ns == "未归类":
            bad.append(f"{path.name}:{line}  `{tok}` 既不是提交、也不是 sha16／记忆 id "
                       f"⇒ **说不出它是从哪儿读出来的**（长度 {len(tok)}）")
        elif label is None:
            bad.append(f"{path.name}:{line}  `{tok}` 是**{ns}**但首次出现处没有贴着标签 "
                       f"⇒ 读者会拿它去当另一种标识用（本仓最常见的是拿记忆 id 去 git show）")
        elif label != ns:
            bad.append(f"{path.name}:{line}  `{tok}` 是**{ns}**却贴成了「{label}」 "
                       f"⇒ 贴错标签比不贴更坏：它让读者**去错的地方找**")
    bad += [x + "  ⇒ 贴错标签比不贴更坏：它让读者**去错的地方找**" for x in mislabel]
    return bad, info


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[0])
        print("用法：python tools/doc_ident_lint.py <文档路径> [...]")
        return 1
    print("== 检查自身是否恒真（合成反例 `deadbeef`：8 位、非提交、无标签）==")
    ns = classify("deadbeef")
    if ns not in ("记忆", "未归类") or resolves_as_commit("deadbeef"):
        print(f"   ★ 合成反例没被判红（分类＝{ns}）⇒ 本检查恒真 ⇒ rc=2")
        return 2
    print(f"   ✓ 合成反例被归到「{ns}」且不能被当成提交 ⇒ 检查有分辨力\n")

    argv = sys.argv[1:]
    ids: set[str] | None = None
    if "--memory-ids" in argv:
        k = argv.index("--memory-ids")
        mf = Path(argv[k + 1]); del argv[k:k + 2]
        if not mf.exists():
            print(f"★ 记忆 id 清单不存在：{mf} ⇒ 拒跑（不把「找不到」读成通过）")
            return 1
        ids: set[str] = set()
        junk: list[str] = []
        for k2, raw in enumerate(mf.read_text(encoding="utf-8").splitlines(), 1):
            s = raw.strip()
            if not s:
                continue
            m2 = re.fullmatch(r"[0-9a-f]{7,40}", s)
            if m2:
                ids.add(s)
            else:
                junk.append(f"{mf.name}:{k2}  `{s[:24]}` 不是十六进制标识 ⇒ 清单本身不可用")
        if junk:
            print("★ 第二来源清单里有无法解析的行 ⇒ 拒跑（清单被静默丢空会让「碰撞 0 个」变成假绿）：")
            for j in junk[:6]:
                print("   ✗ " + j)
            return 1
        print(f"== 第二来源（记忆 id 清单）：{mf.name}，**解析出 {len(ids)} 个**（7~40 位十六进制）⇒ 碰撞检测已行使 ==")
    else:
        print("== 第二来源（记忆 id 清单）**未提供** ⇒ 碰撞检测**未行使**（第三态，不参与判定）==")

    total_bad: list[str] = []
    for arg in argv:
        path = Path(arg)
        if not path.exists():
            print(f"★ 文件不存在：{path} ⇒ 拒跑（不把「找不到」读成通过）")
            return 1
        print(f"== {path} ==")
        print(ident(path))
        bad, info = scan(path)
        head = sorted(info.items(), key=lambda kv: kv[1][1])[:8]
        if TRUNCATED:
            print(f"   ⚠ 另报（**不进 rc**）：**截断形式** {len(TRUNCATED)} 段 —— 装饰集＝`…`；"
                  f"**截断推不出命名空间**（8 位截断按形状会被误判成「记忆」）⇒ 只报不判，例：{TRUNCATED[:3]}")
        if MIXED_HITS:
            print(f"   ⚠ 另报（**不进 rc**）：段内含十六进制串但**不属标识形状** {len(MIXED_HITS)} 段"
                  f"（如 `source_sig=<8位>`、`<名>-<8位>.exe`）⇒ 按形状判会**贴错命名空间** ⇒ 只报不判，例：{MIXED_HITS[:3]}")
        if SPELLING_UPPER:
            print(f"   ★ 其中以**大写拼法**出现的 {len(SPELLING_UPPER)} 处（判定时**归一到小写**；"
                  f"两个拼法视为**同一个标识** —— git 的 sha 解析本就不分大小写）：{sorted(set(SPELLING_UPPER))[:6]}")
        print(f"   反引号内的十六进制标识共 {len(info)} 种："
              + "、".join(f"{k}({v[0]})" for k, v in head) + ("…" if len(info) > 8 else ""))
        if ids is None:
            print("   ⊘ 与形状无关的碰撞检测：**未行使**（未提供记忆 id 清单）")
        else:
            cb, nhit = collisions(info, ids)
            print(f"   · 碰撞检测：**已行使**（{len(info)} 个标识 × {len(ids)} 个记忆 id）⇒ 碰撞 {nhit} 个、"
                  f"推定被否证 {sum(1 for x in cb if '不在记忆 id 清单里' in x)} 个")
            print("     ★ 本层只在**清单完整**时才有意义；清单不全 ⇒ 真 id 会被判成「不属于」＝假红（宁可假红，`7bd9ca65`）。")
            bad += cb
        for b in bad:
            print("   ✗ " + b)
        total_bad += bad
    print("\n== 判定：== " + ("所有标识的命名空间都已声明且正确" if not total_bad
                              else f"**{len(total_bad)} 处未声明／未归类／贴错** ⇒ rc=1"))
    print("★ 推定声明：「8 位十六进制且不可解析为提交」一律按**形状**归「记忆」——这是**推定**，不是核对；"
          "若某个这样的值其实不属于记忆命名空间，本检查会**逼人给它贴一个假标签**（后端2 实测：合成负对照值哪一套都不是）。")
    print("★ 盖到哪为止：只证「命名空间已声明且贴对」，**不证**「那个记忆 id 真的存在」（要证得读记忆轨＝外部依赖）。")
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
