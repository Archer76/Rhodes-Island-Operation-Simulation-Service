"""Offline O6 positive/negative controls; never build a release or use accounts."""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import build_release as release


class IdentityTests(unittest.TestCase):
    def test_environment_cleans_and_pins_both_components(self):
        with tempfile.TemporaryDirectory() as root:
            tree = pathlib.Path(root)
            poison = {k: "external-poison" for k in ("RIOS_DB", "RIOS_DATA", "RIOS_SIM_BIN", "RIOS_BRIDGE", "RIOS_PYTHON", "PYTHONPATH", "PYTHONHOME")}
            with patch.dict(os.environ, poison):
                env = release.release_env(tree, data_dir=tree / "data")
                self.assertEqual(env["RIOS_SIM_BIN"], str((tree / "rios-sim.exe").resolve()))
                self.assertEqual(env["RIOS_BRIDGE"], str((tree / "eng/tools/rios_bridge.py").resolve()))
                self.assertEqual(env["RIOS_DATA"], str((tree / "data/gamedata").resolve()))
                self.assertNotIn("PYTHONPATH", env)
                self.assertNotIn("PYTHONHOME", env)
                negative = release.release_env(tree, pin=False)
                for key in poison:
                    if key == "RIOS_PYTHON":
                        self.assertEqual(negative[key], sys.executable)
                    else:
                        self.assertNotIn(key, negative)
                self.assertEqual(os.environ["RIOS_BRIDGE"], "external-poison")

    def fixture(self, root):
        tree = pathlib.Path(root)
        (tree / "eng/tools").mkdir(parents=True)
        (tree / "rios-sim.exe").write_bytes(b"engine bytes")
        (tree / "eng/tools/rios_bridge.py").write_bytes(b"bridge bytes")
        return tree

    def replies(self):
        return [SimpleNamespace(returncode=0, stdout=json.dumps({"id":719,"ok":True,"pong":{"version":1,"go":"test"}}), stderr=""),
                SimpleNamespace(returncode=0, stdout=json.dumps({"id":719,"ok":True,"proto":1,"python":"test","uid":"private-account","cred_state":"cred"}), stderr="")]

    def test_identity_exact_paths_fingerprints_and_no_private_fields(self):
        with tempfile.TemporaryDirectory() as root:
            tree = self.fixture(root)
            with patch.object(release.subprocess, "run", side_effect=self.replies()) as run:
                result = release.component_identity(tree)
            self.assertEqual(run.call_args_list[0].args[0], [str((tree / "rios-sim.exe").resolve())])
            self.assertEqual(run.call_args_list[1].args[0], [sys.executable, "-I", str((tree / "eng/tools/rios_bridge.py").resolve())])
            for name, rel in (("engine", "rios-sim.exe"), ("bridge", "eng/tools/rios_bridge.py")):
                item = result["components"][name]
                self.assertEqual(item["sha256"], release.sha256(tree / rel))
                self.assertEqual(item["protocol"], 1)
            self.assertNotIn("private-account", json.dumps(result))
            self.assertNotIn("cred_state", json.dumps(result))

    def test_identity_rejects_bad_protocol_id_and_output(self):
        for change in ("protocol", "id", "extra", "rc"):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as root:
                tree = self.fixture(root)
                replies = self.replies()
                if change == "protocol": replies[1].stdout = '{"id":719,"ok":true,"proto":2}'
                if change == "id": replies[1].stdout = '{"id":718,"ok":true,"proto":1}'
                if change == "extra": replies[1].stdout += '\n{}'
                if change == "rc": replies[1].returncode = 1
                with patch.object(release.subprocess, "run", side_effect=replies):
                    with self.assertRaises(SystemExit): release.component_identity(tree)

    def test_missing_package_bridge_is_not_replaced_by_override(self):
        with tempfile.TemporaryDirectory() as root:
            tree = self.fixture(root)
            (tree / "eng/tools/rios_bridge.py").unlink()
            with patch.dict(os.environ, {"RIOS_BRIDGE": sys.executable}), patch.object(release.subprocess, "run", return_value=self.replies()[0]):
                with self.assertRaises(SystemExit): release.component_identity(tree)

    def test_changed_bytes_during_handshake_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            tree = self.fixture(root)
            def mutate(*args, **kwargs):
                (tree / "rios-sim.exe").write_bytes(b"changed")
                return self.replies()[0]
            with patch.object(release.subprocess, "run", side_effect=mutate):
                with self.assertRaises(SystemExit): release.component_identity(tree)

    def test_failed_bridge_response_does_not_print_private_data(self):
        import io
        from contextlib import redirect_stdout
        with tempfile.TemporaryDirectory() as root:
            tree = self.fixture(root)
            replies = self.replies()
            replies[1].stdout += '\n{}'
            replies[1].stderr = 'private-credential'
            log = io.StringIO()
            with patch.object(release.subprocess, "run", side_effect=replies), redirect_stdout(log):
                with self.assertRaises(SystemExit): release.component_identity(tree)
            self.assertNotIn('private-account', log.getvalue())
            self.assertNotIn('private-credential', log.getvalue())

    def test_preflight_does_not_inherit_overrides(self):
        with tempfile.TemporaryDirectory() as root:
            tree = pathlib.Path(root)
            with patch.dict(os.environ, {"RIOS_SIM_BIN":"poison", "RIOS_BRIDGE":"poison", "RIOS_DATA":"poison"}), patch.object(release, "sh", return_value=(3,"eng/data/gamedata","")) as sh:
                release.run_preflight(tree)
            env = sh.call_args.kwargs["env"]
            for key in ("RIOS_SIM_BIN", "RIOS_BRIDGE", "RIOS_DATA", "RIOS_DB"):
                self.assertNotIn(key, env)


if __name__ == "__main__":
    unittest.main(verbosity=2)
