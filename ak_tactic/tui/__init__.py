"""终端界面（TUI）。

包本身**不导入 textual**——第三方依赖只在 `ak_tactic.cli` 的 `tui` 子命令里
惰性导入，这样 `import ak_tactic`、跑 `db` / `formula` / `verify` 都不需要装 textual。

    python -m ak_tactic tui

分层：`app.py` 只放屏幕与编排，`data.py` 放数据访问，`theme.py` 放样式。
"""
