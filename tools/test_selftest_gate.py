"""Memory-only tests: no release build, data, network or executable invocation."""
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

try:
    from . import build_release
    from .selftest_gate import PREFIX, validate_selftest
except ImportError:
    import build_release
    from selftest_gate import PREFIX, validate_selftest


MANIFEST = {"schema_version": 1, "profile": "all-required",
            "required_ids": ["prerequisites", "c001"],
            "inventory": [{"id": "c001", "kind": "required_callsite"},
                          {"id": "c002", "kind": "error_observation"}]}


def complete():
    cases = []
    for cid in MANIFEST["required_ids"]:
        cases.append({"id": cid, "name": cid, "status": "pass", "required": True,
                      "reason": "", "exercised": 1, "check_count": 1, "failed_checks": 0,
                      "checks": [{"case_id": cid, "name": cid, "status": "pass",
                                  "reason": "", "exercised": 1, "got": "true"}]})
    return {"schema_version": 1, "profile": "all-required", "completed": True,
            "passed": True, "rc": 0, "manifest": list(MANIFEST["required_ids"]),
            "cases": cases, "summary": {"pass": 2, "fail": 0, "skip": 0, "exercised": 2},
            "errors": []}


def stdout(report):
    return "human diagnostic\n" + PREFIX + json.dumps(report) + "\n"


class GateTests(unittest.TestCase):
    def reject(self, report, reason, rc=0):
        with self.assertRaisesRegex(ValueError, reason):
            validate_selftest(stdout(report), rc, MANIFEST)

    def test_complete(self):
        report = complete()
        self.assertEqual(validate_selftest(stdout(report), 0, MANIFEST), report)

    def test_nonzero_process(self):
        self.reject(complete(), "process returncode", 3)

    def test_top_fields(self):
        for field, value, reason in [("schema_version", 2, "schema_version"),
                                      ("completed", False, "incomplete"),
                                      ("passed", False, "passed"), ("rc", 1, "report rc"),
                                      ("errors", ["failure"], "errors"),
                                      ("profile", "optional", "profile")]:
            with self.subTest(field=field):
                report = complete()
                report[field] = value
                self.reject(report, reason)

    def test_missing_report_fields(self):
        for field in complete():
            with self.subTest(field=field):
                report = complete()
                del report[field]
                self.reject(report, ".+")

    def test_required_skip(self):
        r = complete()
        c = r["cases"][0]
        c.update(status="skip", exercised=0, reason="no data")
        c["checks"][0].update(status="skip", exercised=0, reason="no data")
        self.reject(r, "prerequisites.*skip")

    def test_case_ids(self):
        for mode in ("missing", "duplicate", "unknown"):
            with self.subTest(mode=mode):
                r = complete()
                if mode == "missing":
                    r["cases"].pop()
                elif mode == "duplicate":
                    r["cases"].append(copy.deepcopy(r["cases"][0]))
                else:
                    r["cases"][0]["id"] = "unknown"
                self.reject(r, "report cases")

    def test_manifest_ids(self):
        for ids in (["prerequisites"], ["prerequisites", "prerequisites"], ["prerequisites", "unknown"]):
            r = complete()
            r["manifest"] = ids
            self.reject(r, "report manifest")

    def test_prefix_missing_duplicate_legacy(self):
        for text in ("", "✓" * 200 + "结论：**全绿**", stdout(complete()) * 2,
                     "noise " + PREFIX + json.dumps(complete())):
            with self.subTest(text=text[:30]), self.assertRaisesRegex(ValueError, "prefix"):
                validate_selftest(text, 0, MANIFEST)

    def test_false_summary(self):
        for key in complete()["summary"]:
            r = complete()
            r["summary"][key] += 1
            self.reject(r, "summary " + key)

    def test_zero_exercise(self):
        r = complete()
        r["cases"][0]["exercised"] = 0
        r["cases"][0]["checks"][0]["exercised"] = 0
        self.reject(r, "pass without exercise")

    def test_counters_independently_recomputed(self):
        for key, value in (("check_count", 2), ("failed_checks", 1), ("exercised", 2)):
            r = complete()
            r["cases"][0][key] = value
            self.reject(r, key)

    def test_failed_check_cannot_hide_behind_green_fields(self):
        r = complete()
        r["cases"][0]["checks"][0].update(status="fail", reason="negative")
        self.reject(r, "status differs from checks")
        r["cases"][0].update(status="fail", failed_checks=1)
        self.reject(r, "required fail")

    def test_invalid_check_fields(self):
        for key, value in (("case_id", "other"), ("status", "unknown"),
                           ("expected_false", 1), ("exercised", True), ("got", None)):
            r = complete()
            r["cases"][0]["checks"][0][key] = value
            self.reject(r, "check")

    def test_expected_false_is_pass_not_discounted_failure(self):
        r = complete()
        r["cases"][0]["checks"][0].update(expected_false=True, got="false")
        self.assertEqual(validate_selftest(stdout(r), 0, MANIFEST), r)

    def test_static_minimum_checks(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["minimum_checks"] = {"c001": 2}
        r = complete()
        with self.assertRaisesRegex(ValueError, "c001.*minimum_checks"):
            validate_selftest(stdout(r), 0, manifest)
        c = r["cases"][1]
        c["checks"].append(copy.deepcopy(c["checks"][0]))
        c.update(check_count=2, exercised=2)
        r["summary"]["exercised"] = 3
        self.assertEqual(validate_selftest(stdout(r), 0, manifest), r)
        manifest["minimum_checks"] = {"unknown": 2}
        with self.assertRaisesRegex(ValueError, "minimum_checks"):
            validate_selftest(stdout(r), 0, manifest)

    def test_inventory_not_runtime_total(self):
        manifest = copy.deepcopy(MANIFEST)
        manifest["inventory"][0]["kind"] = "error_observation"
        with self.assertRaisesRegex(ValueError, "inventory"):
            validate_selftest(stdout(complete()), 0, manifest)


class ReleaseTests(unittest.TestCase):
    def smoke_with(self, data, process=None):
        tree = MagicMock(spec=Path)
        with patch.object(build_release, "run_preflight", side_effect=[
                (3, "eng/data/gamedata"), (2, "引擎"), (2, "工程侧")]), \
                patch.object(build_release, "sh", return_value=(1, "首次运行准备 找不到工程侧脚本", "")), \
                patch.object(build_release.subprocess, "run", return_value=process) as run, \
                redirect_stdout(io.StringIO()):
            result = build_release.smoke(tree, data)
        return result, run

    def test_none_explicit_unverified(self):
        result, run = self.smoke_with(None)
        self.assertEqual(result["status"], "unverified")
        self.assertIn("--no-selftest", result["reason"])
        run.assert_not_called()

    def test_missing_data_rejected(self):
        data = MagicMock(spec=Path)
        data.__truediv__.return_value.is_file.return_value = False
        with self.assertRaises(SystemExit) as exc:
            self.smoke_with(data)
        self.assertEqual(exc.exception.code, 1)

    def test_smoke_verified_only_machine_gate_stdout(self):
        data = MagicMock(spec=Path)
        data.__truediv__.return_value.is_file.return_value = True
        root = MagicMock(spec=Path)
        root.__truediv__.return_value.__truediv__.return_value.read_text.return_value = json.dumps(MANIFEST)
        with patch.object(build_release, "ROOT", root):
            result, _ = self.smoke_with(data, SimpleNamespace(returncode=0, stdout=stdout(complete()), stderr="diagnostic"))
            self.assertEqual(result["status"], "verified")
            with self.assertRaises(SystemExit):
                self.smoke_with(data, SimpleNamespace(returncode=0, stdout="✓" * 200, stderr=stdout(complete())))

    def test_mocked_main_no_selftest_status(self):
        output = MagicMock(spec=Path)
        tree = output.__truediv__.return_value
        tree.exists.return_value = False
        tree.rglob.return_value = []
        log = io.StringIO()
        with patch.object(build_release, "Path", return_value=output), \
                patch.object(build_release, "build_exes"), patch.object(build_release, "copy_eng"), \
                patch.object(build_release, "assert_only_runtime_files", return_value=[]), \
                patch.object(build_release, "clean_pycache", return_value=0), \
                patch.object(build_release, "smoke", return_value={"status": "verified"}) as smoke, \
                patch("sys.argv", ["build_release.py", "--version", "unit", "--out", "memory", "--no-selftest"]), \
                redirect_stdout(log):
            self.assertEqual(build_release.main(), 0)
        smoke.assert_called_once_with(tree, None)
        writes = tree.__truediv__.return_value.write_text.call_args_list
        verification = json.loads(writes[0].args[0])
        self.assertEqual(verification["status"], "unverified")
        self.assertIn("--no-selftest", verification["reason"])
        self.assertIn("构建完成与发布验收是不同结论", log.getvalue())
        self.assertIn("发布验收：unverified", log.getvalue())


if __name__ == "__main__":
    unittest.main()
