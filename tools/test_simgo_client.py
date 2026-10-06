"""Offline O2 checks using real, controlled child processes (no engine fallback)."""
import json
import pathlib
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from ak_tactic.simgo.client import Simgo

REAL_POPEN = subprocess.Popen


class SimgoClientTests(unittest.TestCase):
    def engine(self, source, timeout=0.3):
        def launch(*args, **kwargs):
            return REAL_POPEN([sys.executable, "-u", "-c", source], **kwargs)
        with patch("ak_tactic.simgo.client.subprocess.Popen", side_effect=launch):
            client = Simgo(sys.executable, timeout=timeout)
        self.addCleanup(client.close)
        return client

    def assert_reaped(self, client):
        self.assertIsNotNone(client._proc.poll())
        for stream in (client._proc.stdin, client._proc.stdout, client._proc.stderr):
            self.assertTrue(stream.closed)
        self.assertFalse(client._stderr_thread.is_alive())
        if client._io_thread is not None:
            self.assertFalse(client._io_thread.is_alive())

    def timeout_case(self, source, spec=None):
        client = self.engine(source)
        started = time.monotonic()
        with self.assertRaises(TimeoutError) as caught:
            client._call("sim", spec)
        elapsed = time.monotonic() - started
        self.assertIn("sim", str(caught.exception))
        self.assertGreaterEqual(elapsed, 0.25)
        self.assertLess(elapsed, 2.0)
        self.assert_reaped(client)
        with self.assertRaises(RuntimeError):
            client.ping()
        client.close()

    def test_silent_child_timeout(self):
        self.timeout_case("import sys,time; sys.stdin.readline(); time.sleep(60)")

    def test_partial_line_timeout(self):
        self.timeout_case('import sys,time; sys.stdin.readline(); sys.stdout.write("{\\\"ok\\\":true"); sys.stdout.flush(); time.sleep(60)')

    def test_blocked_request_write_timeout(self):
        self.timeout_case("import time; time.sleep(60)", {"large": "x" * 2_000_000})

    def test_eof_while_child_alive(self):
        client = self.engine("import os,sys,time; sys.stdin.readline(); sys.stderr.write('known error'); sys.stderr.flush(); os.close(1); time.sleep(60)")
        started = time.monotonic()
        with self.assertRaises(RuntimeError):
            client.ping()
        self.assertLess(time.monotonic() - started, 2)
        self.assert_reaped(client)

    def test_invalid_json_closes_connection(self):
        client = self.engine("import sys,time; sys.stdin.readline(); print('not json',flush=True); time.sleep(60)")
        with self.assertRaises(RuntimeError):
            client.ping()
        self.assert_reaped(client)

    def test_non_object_closes_connection(self):
        client = self.engine("import sys,time; sys.stdin.readline(); print('[]',flush=True); time.sleep(60)")
        with self.assertRaises(RuntimeError):
            client.ping()
        self.assert_reaped(client)

    def test_stderr_flood_and_sequential_responses(self):
        client = self.engine('import sys,json\nfor line in sys.stdin:\n req=json.loads(line)\n sys.stderr.write("log"*100000); sys.stderr.flush()\n print(json.dumps({"id":req["id"],"ok":True,"verdict":{"won":True}}),flush=True)', timeout=2)
        self.assertEqual(client.sim_many([{}, {}]), [{"won": True}, {"won": True}])
        client.close()
        self.assert_reaped(client)

    def test_engine_error_keeps_valid_connection(self):
        client = self.engine('import sys,json\nfor line in sys.stdin:\n req=json.loads(line)\n print(json.dumps({"id":req["id"],"ok":False,"error":"explicit rejection"}),flush=True)')
        with self.assertRaisesRegex(RuntimeError, "explicit rejection"):
            client.sim({})
        self.assertIsNone(client._proc.poll())
        self.assertEqual(client._call("sim")["error"], "explicit rejection")

    def test_ping_and_context_close(self):
        client = self.engine('import sys,json\nfor line in sys.stdin:\n req=json.loads(line)\n print(json.dumps({"id":req["id"],"ok":True,"pong":{"version":1}}),flush=True)')
        with client:
            self.assertEqual(client.ping(), {"version": 1})
            self.assertEqual(client.ping(), {"version": 1})
        self.assert_reaped(client)

    def test_broken_stdin_cleanup(self):
        client = self.engine("import os,time; os.close(0); time.sleep(60)")
        with self.assertRaises(RuntimeError):
            client._call("sim", {"large": "x" * 2_000_000})
        self.assert_reaped(client)

    def test_invalid_utf8_stderr_is_drained(self):
        client = self.engine('import os,sys,json\nfor line in sys.stdin:\n req=json.loads(line)\n os.write(2,b"\\xff"*300000)\n print(json.dumps({"ok":True,"pong":{"version":1}}),flush=True)', timeout=2)
        self.assertEqual(client.ping(), {"version": 1})
        client.close()
        self.assert_reaped(client)

    def test_interrupted_wait_aborts_blocked_write(self):
        client = self.engine("import time; time.sleep(60)")
        with patch("ak_tactic.simgo.client.queue.Queue.get", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                client._call("sim", {"large": "x" * 2_000_000})
        self.assert_reaped(client)

    def test_invalid_timeout_before_spawn(self):
        for timeout in (0, -1, float("inf"), float("nan")):
            with self.subTest(timeout=timeout), patch("ak_tactic.simgo.client.subprocess.Popen") as spawn:
                with self.assertRaises(ValueError):
                    Simgo(sys.executable, timeout=timeout)
                spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
