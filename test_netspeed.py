"""Tests against a local HTTP server. Run: python -m unittest -v"""

import contextlib
import io
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import netspeed

BODY = b"x" * 100_000


class Handler(BaseHTTPRequestHandler):
    hits = 0

    def do_GET(self):
        Handler.hits += 1
        if self.path == "/flaky" and Handler.hits % 2 == 0:
            self.send_error(503)
            return
        if self.path == "/dies" and Handler.hits > 2:
            self.send_error(503)
            return
        if self.path == "/broken":  # promises 1000 bytes, sends 10
            self.send_response(200)
            self.send_header("Content-Length", "1000")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(b"x" * 10)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


class NetspeedTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Handler.hits = 0

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = netspeed.main(list(argv))
            except SystemExit as e:  # argparse exits on invalid input
                code = e.code
        return code, out.getvalue(), err.getvalue()

    def test_ten_requests_and_only_speed_on_stdout(self):
        code, out, err = self.run_cli(self.base + "/file")
        self.assertEqual(code, 0)
        self.assertEqual(Handler.hits, 10)
        self.assertRegex(out, r"^\d+\.\d\d Mbit/s\n$")
        self.assertEqual(err, "")

    def test_failed_requests_are_skipped(self):
        code, out, err = self.run_cli(self.base + "/flaky")
        self.assertEqual(code, 0)
        self.assertEqual(Handler.hits, 10)
        self.assertEqual(err.count("failed"), 5)
        self.assertIn("Mbit/s", out)

    def test_truncated_response_is_a_failure(self):
        code, out, err = self.run_cli(self.base + "/broken")
        self.assertEqual(code, 1)
        self.assertIn("bytes missing", err)
        self.assertEqual(out, "")

    def test_dead_address_stops_after_three_failures(self):
        code, out, err = self.run_cli(self.base + "/broken")
        self.assertEqual(code, 1)
        self.assertEqual(Handler.hits, 3)
        self.assertIn("stopped after 3 failures in a row", err)

    def test_address_dying_mid_run_still_reports_completed_requests(self):
        code, out, err = self.run_cli(self.base + "/dies")
        self.assertEqual(code, 0)
        self.assertEqual(Handler.hits, 5)  # 2 ok + 3 failed
        self.assertIn("Mbit/s", out)

    def test_rejects_non_http_input(self):
        for bad in ("example.com", "file:///etc/passwd", "ftp://example.com/x", "http://",
                    "http://example.com:99999/", "http://example.com:abc/",
                    "http://exa mple.com/", "http://example.com/\n", "http://[::1"):
            code, out, err = self.run_cli(bad)
            self.assertEqual(code, 2, bad)
            self.assertIn("not an http(s) address", err)
            self.assertEqual(Handler.hits, 0)

    def test_speed_formula(self):
        # 1 MB in 1 s and 1 MB in 9 s: 2 MB in 10 s = 1.6 Mbit/s,
        # not the mean of per-request speeds (8 and 0.89 -> 4.4).
        self.assertAlmostEqual(netspeed.speed_mbps([(1_000_000, 1.0), (1_000_000, 9.0)]), 1.6)


if __name__ == "__main__":
    unittest.main()
