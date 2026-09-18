# 命令行速查

> 本文件自 `README.md` 拆出（2026-09-17）：README 只留「是什么 / 怎么用」，实测结论与历史记录按主题收到这里。总览见 [`README.md`](../README.md)。

```bash
cd <仓库目录>

# ── 干员（prts.wiki）
python -m ak_tactic get 能天使                          # 人读格式
python -m ak_tactic get 能天使 --range                  # 连攻击范围网格一起画
python -m ak_tactic get 能天使 --full                   # 展开全部 10 个技能等级
python -m ak_tactic get 能天使 --json                   # 结构化 JSON
python -m ak_tactic list                                 # 名录
python -m ak_tactic list --profession 狙击 --rarity 6
python -m ak_tactic range 3-3 1-1 2-1                    # 单看某个范围代号

# ── 干员属性计算（gamedata excel/ 表，默认走 GitHub 镜像）
python -m ak_tactic stats 阿米娅 --elite 2 --level 80     # 精英2 满级
python -m ak_tactic stats 阿米娅 --elite 2 --level 80 --trust 100 --potential 6
python -m ak_tactic stats 阿米娅 --elite 1 --level 35     # 中间等级也能算
python -m ak_tactic stats 银灰 --modules                  # 看它有哪些模组
python -m ak_tactic stats 银灰 --elite 2 --level 90 \
        --module uniequip_002_svrash --module-level 3     # 带模组
python -m ak_tactic stats --search 银灰                   # 按中文名找干员
python -m ak_tactic stats 阿米娅 --elite 0 --level 3 --rounding round   # 换取整方式

# ── 关卡与敌人（gamedata，默认走 map.ark-nights.com）
python -m ak_tactic stage --search SR-EX                # 按关卡号找（只在本项目的口径内找，见 tui-plan.md）
python -m ak_tactic stage 1-7                           # 关卡号与 levelId 都收
python -m ak_tactic stage SR-EX-8                       # 活动关一样能取
python -m ak_tactic stage SR-EX-8 --map                 # 只看地图，不加载敌人库（快）
python -m ak_tactic stage SR-EX-8 --timeline            # 打印全部出怪时刻
python -m ak_tactic stage SR-EX-8 --json                # 全量 JSON
python -m ak_tactic enemy enemy_1030_wteeth             # 单看一个敌人
python -m ak_tactic enemy --search 源石虫                # 按中文名搜

# ── 本地库：干员与敌人**两个独立文件**
python -m ak_tactic db build                             # 干员库（gamedata，不联网，~3.4s）
python -m ak_tactic db info                              # 版本戳 + 各表行数
python -m ak_tactic db char 望                            # 干员详情（同名时用 id）
python -m ak_tactic db skill 取势 --key sluggish          # 按技能名 + 黑板键搜
python -m ak_tactic db talent 铸子                        # 按天赋名或描述搜
python -m ak_tactic db sql "SELECT name FROM operator WHERE is_operator=1 LIMIT 5"
python -m ak_tactic db tiles                              # 地块字典（95 条：tileKey → 中文名 + 说明）
python -m ak_tactic db tiles 田                            # 按关键词/键名搜地块
python -m ak_tactic db tile-fetch --force                 # 重取地块字典（缓存 7 天）
python -m ak_tactic enemydb build                        # 敌人库（prts.wiki，首次 ~51s）
python -m ak_tactic enemydb find 死志                     # 找敌人
python -m ak_tactic enemydb find --grade 领袖              # 只列领袖
python -m ak_tactic enemydb show 源石虫                   # 图鉴 + 逐档 + 抗性 + 技能
python -m ak_tactic enemydb show 挥铳圣像 --json           # 原样 JSON
python -m ak_tactic enemydb sql "SELECT page,grade FROM enemy WHERE grade='领袖'"

# ── 验证一份打法（阶段 5 的验证器）
python -m ak_tactic verify --plan p.json --box 名册.json   # 关卡号在文件里
python -m ak_tactic verify act54side_06 \
    --team "圣聆初雪:5,4:Right:2:3; 德克萨斯:6,3:Right:1" --box 名册.json
python -m ak_tactic verify main_01-07 --team "阿米娅:5,2:Left:0@1" --json
#   --team 语法：名字:x,y[:朝向[:技能槽[:专精]]]@时刻，干员之间用 `;`
#   不给 @时刻 就是「钱够了就下」（与 MAA 自动作战同规则）
#   退出码：0 = 三星，1 = 通关但不满星或失败，2 = 打法本身有问题

# ── 搜索一套能三星的阵容（阶段 5 的搜索器）
python -m ak_tactic search main_01-07 --box 名册.json --team "能天使;银灰"
python -m ak_tactic search act54side_06 --box 名册.json --top 10 \
        --max-ops 4 --beam 6 --per-op 8 --save-plan out/p.json
#   --beam/--per-op 是预算旋钮；不指定 --team 时阵容由组队建议层给（见「组队建议」）
#   存下来的打法自带练度，之后 verify --plan 不带 --box 也能复跑

# ── 输出：摆位图 / 时间轴 / 完整报告（阶段 6）
python -m ak_tactic verify main_01-07 --team "阿米娅:5,2:Left:0@1" --box 名册.json \
        --diagram --timeline
python -m ak_tactic verify --plan out/p.json --report out/report.md
#   --heat-metric routes 把热度图从「敌人·秒」换成「经过的路线条数」

# ── 自检（十一套；全绿才算没退化）
#    各套项数会随规则增删而变，本文件不写死——每套末行自报当前项数
python tools/check_db.py              # 干员库（含地块字典）
python tools/check_enemy_db.py        # 敌人库
python tools/check_battle.py          # 战斗模型 + 三关基线 + 攻速链路 + 口径断言
python tools/check_p3r.py             # 相性与全场总攻击
python tools/check_formula.py         # 干员正文 → 公式项（含算式解析器）
python tools/check_enemy_formula.py   # 敌人正文 → 公式项（含带变量的算式）
python tools/check_verify.py          # 验证器（含跨局复用可重复性）
python tools/check_eta.py             # 到达时刻（与模拟器逐只对拍）
python tools/check_search.py          # 搜索器 + 组队建议
python tools/check_diagram.py         # 摆位图 / 热度图 / 时间轴 / 报告
python tools/check_parallel.py        # 并行等价性（串并行逐字一致）
python tools/enemy_field_audit.py     #     敌人字段总账（非 0 退出即有字段没入库）

# ── 缓存
python -m ak_tactic cache                                # 看两个缓存目录的占用
python -m ak_tactic cache --clear                        # 清 prts 缓存
python -m ak_tactic cache --clear-gamedata               # 清 gamedata 缓存（约 17 MB）
```
