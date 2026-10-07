# -*- coding: utf-8 -*-
"""离线回归：凭据过期时**自动补一次 cred**（截图那个"名册取不到"的根因）。

2026-10-07 实测的现场：`~/.skland/cred_<uid>.json` 是 9 月 29 日换的（cred 寿命约两天），
`binding_list` 回 `code 10000 请求异常`（与签名写错同码）⇒ `fetch_all()` 整个失败，
界面只显示"名册取不到"，看不出该做什么。而缓存的 hgToken 还能静默换到新 cred。

这里用假 HTTP 层（monkeypatch `binding_list` / `finish_login` / `player_info`）离线钉住四条：
1. `fetch_all` 遇到 10000 → 补一次 cred → 用**新凭据**成功取全量（旧实现直接失败）；
2. 补完仍失败 → 抛的是**原来那个**错（不拿"补登录失败"顶掉真正原因）；
3. hgToken 也没了（补 cred 抛错）→ 同样是原来那个错；
4. 凭据健康时**一次都不补**（别无谓重铸）；
5. 非当前账号（`resolve_game_uid_for`）**不许**补 —— 拿当前账号的 hgToken 去救别的号会换错号；
6. 桥那条失败提示遇到 `10000` 要说人话（否则玩家只看到"名册取不到"）。
"""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

from ak_tactic import skland

ROOT = Path(__file__).resolve().parent.parent

STALE = ("取绑定列表失败（sign 若错也会报同码）："
         "{'code': 10000, 'message': '请求异常'}")

BINDING_OK = [{"uid": "10404662", "nickName": "Archer#6725", "channelName": "官服",
               "isDefault": True}]


def load_bridge():
    """按路径加载桥模块（不改 sys.path，也不跑它的 main()）。"""
    spec = importlib.util.spec_from_file_location(
        "rios_bridge_uut", ROOT / "tools" / "rios_bridge.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class CredRefreshTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.out = self.home / "out"
        skland.save_cred({"hgToken": "hg-old", "cred": "cred-OLD", "token": "tok-OLD",
                          "userId": "1352155938927", "stage": "ready"}, self.home)
        self._orig = (skland.binding_list, skland.finish_login, skland.player_info,
                      skland.fetch_all, skland.DEFAULT_HOME)
        self.addCleanup(self._restore)

    def _restore(self):
        (skland.binding_list, skland.finish_login, skland.player_info,
         skland.fetch_all, skland.DEFAULT_HOME) = self._orig

    def _patch(self, binding, refresh=None, info=None):
        skland.binding_list = binding
        skland.finish_login = refresh or (lambda home=None: {
            "cred": "cred-NEW", "token": "tok-NEW", "userId": "1352155938927"})
        skland.player_info = info or (lambda cred, token, uid: {
            "chars": [], "charInfoMap": {}})

    # ---------------------------------------------------------------- 1
    def test_fetch_all_refreshes_expired_cred_and_uses_new_one(self):
        seen = []

        def binding(cred, token):
            seen.append(cred)
            if cred == "cred-OLD":
                raise skland.SklandError(STALE)
            return BINDING_OK

        infos = []

        def info(cred, token, uid):
            infos.append((cred, token, uid))
            return {"chars": [], "charInfoMap": {}}

        self._patch(binding, info=info)
        res = skland.fetch_all(home=self.home, out_dir=self.out)

        self.assertEqual(seen, ["cred-OLD", "cred-NEW"])          # 只补一次
        self.assertEqual(res["uid"], "10404662")
        self.assertEqual(infos, [("cred-NEW", "tok-NEW", "10404662")],
                         "取全量必须用补过的新 cred，否则等于白补")
        self.assertTrue((self.out / "opers_10404662.json").exists(),
                        "补完 cred 之后全量数据要真的落盘（供 skland_roster 翻名册）")

    # ---------------------------------------------------------------- 2
    def test_still_failing_raises_the_original_error(self):
        calls = []

        def binding(cred, token):
            calls.append(cred)
            raise skland.SklandError(STALE)

        self._patch(binding)
        with self.assertRaises(skland.SklandError) as ctx:
            skland.fetch_all(home=self.home, out_dir=self.out)
        self.assertEqual(str(ctx.exception), STALE)
        self.assertEqual(calls, ["cred-OLD", "cred-NEW"], "补完仍失败只补一次，不反复刷")

    # ---------------------------------------------------------------- 3
    def test_refresh_failure_does_not_mask_the_real_error(self):
        def binding(cred, token):
            raise skland.SklandError(STALE)

        def dead_refresh(home=None):
            raise skland.SklandError("hgToken 也过期了")

        self._patch(binding, refresh=dead_refresh)
        with self.assertRaises(skland.SklandError) as ctx:
            skland.fetch_all(home=self.home, out_dir=self.out)
        self.assertEqual(str(ctx.exception), STALE,
                         "报的必须是真正的失败原因，不是补登录的失败")

    # ---------------------------------------------------------------- 4
    def test_healthy_cred_never_triggers_refresh(self):
        seen = []
        refreshed = []

        def binding(cred, token):
            seen.append(cred)
            return BINDING_OK

        def refresh(home=None):
            refreshed.append(home)
            return {"cred": "cred-NEW", "token": "tok-NEW",
                    "userId": "1352155938927"}

        self._patch(binding, refresh=refresh)
        res = skland.fetch_all(home=self.home, out_dir=self.out)
        self.assertEqual(res["uid"], "10404662")
        self.assertEqual(seen, ["cred-OLD"], "没坏就别补 cred（避免无谓地重铸凭据）")
        self.assertEqual(refreshed, [], "健康凭据下 finish_login 不该被调用")

    # ---------------------------------------------------------------- 5
    def test_non_current_account_never_refreshes(self):
        skland.save_cred({"hgToken": "hg-other", "cred": "cred-OTHER",
                          "token": "tok-OTHER", "userId": "8888888888",
                          "stage": "ready"}, self.home)
        skland.set_current_uid("1352155938927", self.home)
        refreshed = []

        def binding(cred, token):
            raise skland.SklandError(STALE)

        def refresh(home=None):
            refreshed.append(home)
            return {"cred": "cred-NEW", "token": "tok-NEW",
                    "userId": "1352155938927"}

        self._patch(binding, refresh=refresh)
        with self.assertRaises(skland.SklandError) as ctx:
            skland.resolve_game_uid_for("8888888888", home=self.home)
        self.assertEqual(str(ctx.exception), STALE)
        self.assertEqual(refreshed, [], "非当前账号不许补 cred（会静默换错号）")

    # ---------------------------------------------------------------- 6
    def test_bridge_roster_note_explains_code_10000(self):
        bridge = load_bridge()
        skland.DEFAULT_HOME = self.home          # 桥不带 home 参数，只能改模块属性
        self._patch(lambda c, t: (_ for _ in ()).throw(skland.SklandError(STALE)))

        def dead_fetch(**kw):
            raise skland.SklandError(STALE)

        skland.fetch_all = dead_fetch
        got, note = bridge._try_fetch_roster_from_skland()

        self.assertIsNone(got)
        self.assertIn("10000", note)
        self.assertIn("登录", note, "要给下一步（重新扫码/补 cred），不能只报技术错")
        self.assertNotIn("Traceback", note)


if __name__ == "__main__":
    unittest.main()
