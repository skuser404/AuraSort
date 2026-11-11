"""Phase C: the PIN lock, enforced by the server (not only the UI)."""
import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from tests.test_web_security import TEST_PIN, ServerCase
from core import config, history, index_db, pin, web

ROOT = Path(__file__).resolve().parent.parent


class PinCase(ServerCase):
    set_pin = False      # these tests start like a brand-new install: no PIN yet

    def setUp(self):
        super().setUp()
        web._RATE.clear()

    def call(self, path, body=None, **kw):
        st, _, raw = self.req(path, body, **kw)
        return st, json.loads(raw or b"{}")

    def setup_pin(self, value=TEST_PIN):
        st, r = self.call("/api/pin/set", {"pin": value})
        self.assertEqual(st, 200, r)
        return r


class GateTest(PinCase):
    def test_nothing_works_before_a_pin_exists(self):
        st, r = self.call("/api/summary")
        self.assertEqual((st, r["code"]), (423, "pin_not_set"))
        st, info = self.call("/api/info")
        self.assertEqual(st, 200)
        self.assertTrue(info["locked"])
        for private in ("home", "quick", "dest"):
            self.assertNotIn(private, info, "no paths before the PIN is set")
        self.assertIn("device", info)
        self.assertIn("os_user", info)

    def test_unlock_screen_gate(self):
        self.setup_pin()
        self.assertEqual(self.call("/api/summary")[0], 200)
        self.assertEqual(self.call("/api/pin/lock", {})[0], 200)
        st, r = self.call("/api/summary")
        self.assertEqual((st, r["code"]), (423, "locked"))
        self.assertEqual(self.call("/api/thumb?id=1&exp=1&sig=x")[0], 423, "signed preview links are locked too")
        st, r = self.call("/api/pin/unlock", {"pin": "0000"})
        self.assertEqual((st, r["code"]), (403, "wrong_pin"))
        self.assertEqual(r["attempts_left"], 4)
        self.assertEqual(self.call("/api/pin/unlock", {"pin": TEST_PIN})[0], 200)
        self.assertEqual(self.call("/api/summary")[0], 200)

    def test_pin_format_and_change(self):
        for bad in ("123", "12345", "1234567", "12a4", 1234, None):
            st, r = self.call("/api/pin/set", {"pin": bad})
            self.assertEqual(st, 400, bad)
        self.setup_pin()
        st, r = self.call("/api/pin/set", {"pin": "135792"})
        self.assertEqual((st, r["code"]), (409, "pin_exists"), "changing needs the current PIN")
        st, r = self.call("/api/pin/set", {"pin": "135792", "current": "9999"})
        self.assertEqual(st, 403)
        st, r = self.call("/api/pin/set", {"pin": "135792", "current": TEST_PIN})
        self.assertEqual(st, 200)
        self.call("/api/pin/lock", {})
        self.assertEqual(self.call("/api/pin/unlock", {"pin": "135792"})[0], 200)

    def test_idle_auto_lock(self):
        self.setup_pin()
        with mock.patch.object(pin, "idle_s", return_value=0.2):
            self.assertEqual(self.call("/api/summary")[0], 200)
            time.sleep(0.35)
            st, r = self.call("/api/summary")
        self.assertEqual((st, r["code"]), (423, "locked"))

    def test_polling_does_not_keep_it_unlocked(self):
        self.setup_pin()
        with mock.patch.object(pin, "idle_s", return_value=0.3):
            for _ in range(4):
                self.call("/api/scan/status")     # a progress screen polling on its own
                time.sleep(0.1)
            self.assertEqual(self.call("/api/summary")[0], 423)


class LockoutTest(PinCase):
    def test_five_wrong_then_growing_delays_kept_across_restarts(self):
        self.setup_pin()
        self.call("/api/pin/lock", {})
        for i in range(4):
            st, r = self.call("/api/pin/unlock", {"pin": "1111"})
            self.assertEqual(r["code"], "wrong_pin")
            web._RATE.clear()
        st, r = self.call("/api/pin/unlock", {"pin": "1111"})
        self.assertEqual((st, r["code"]), (429, "locked_out"))
        self.assertAlmostEqual(r["retry_after"], 30, delta=2)
        st, r = self.call("/api/pin/unlock", {"pin": TEST_PIN})
        self.assertEqual(r["code"], "locked_out", "even the right PIN waits")
        pin._state.update(unlocked=False)                       # "restart": memory is gone, the file is not
        rec = json.loads((config.DATA_DIR / config.PIN_FILE_NAME).read_text(encoding="utf-8"))
        self.assertGreater(rec["locked_until"], time.time())
        waits = []
        for _ in range(4):
            rec = json.loads((config.DATA_DIR / config.PIN_FILE_NAME).read_text(encoding="utf-8"))
            rec["locked_until"] = 0
            (config.DATA_DIR / config.PIN_FILE_NAME).write_text(json.dumps(rec), encoding="utf-8")
            web._RATE.clear()
            st, r = self.call("/api/pin/unlock", {"pin": "1111"})
            waits.append(r.get("retry_after"))
        self.assertEqual([round(w / 10) * 10 if w < 100 else round(w / 100) * 100 for w in waits], [60, 300, 900, 900])
        rec = json.loads((config.DATA_DIR / config.PIN_FILE_NAME).read_text(encoding="utf-8"))
        rec["locked_until"] = 0
        (config.DATA_DIR / config.PIN_FILE_NAME).write_text(json.dumps(rec), encoding="utf-8")
        self.assertEqual(self.call("/api/pin/unlock", {"pin": TEST_PIN})[0], 200)
        rec = json.loads((config.DATA_DIR / config.PIN_FILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(rec["fails"], 0, "a right PIN resets the counter")


class ActionTokenTest(PinCase):
    def setUp(self):
        super().setUp()
        self.setup_pin()
        self.f = self.make("Docs/a.txt", b"hello")
        from core import scanner
        job = scanner.start("deep", [str(self.home / "Docs")], [])
        while job.state in ("running", "paused"):
            time.sleep(0.02)
        self.fid = next(r["id"] for r in index_db.files_page({"scope": "all"})["rows"] if r["name"] == "a.txt")

    def token(self, action, body):
        st, r = self.call("/api/pin/verify", {"pin": TEST_PIN, "action": action, "request": body})
        self.assertEqual(st, 200, r)
        return r["action_token"]

    def test_every_guarded_route_refuses_a_direct_call(self):
        bodies = {"execute": {"ids": [self.fid], "dest": str(self.home / "Sorted")}, "trash": {"ids": [self.fid]}, "undo": {"id": "x"},
                  "quarantine": {"ids": [self.fid]}, "data/delete": {"confirm": "DELETE"}, "interrupted/resume": {"id": "x"},
                  "interrupted/clean": {"id": "x"}, "ai/key": {"key": "sk-test"}, "ai/reset": {}, "apptrash/restore": {"id": "x"},
                  "pin/settings": {"pin_remember_min": 15}}
        self.assertEqual(set(bodies), set(config.PIN_GUARDED), "every guarded route is covered")
        for route, body in bodies.items():
            st, r = self.call(f"/api/{route}", body, pin=False)
            self.assertEqual((st, r.get("code")), (403, "pin_required"), route)
        self.assertTrue(os.path.exists(self.f), "nothing happened to the file")
        self.assertTrue(config.INDEX_DB.exists())

    def test_token_is_single_use_bound_to_the_request_and_expires(self):
        body = {"ids": [self.fid]}
        tok = self.token("trash", body)
        st, r = self.call("/api/trash", dict(body, ids=[self.fid, 999], action_token=tok), pin=False)
        self.assertEqual((st, r["code"]), (403, "pin_mismatch"), "a token for one request does not fit another")
        tok = self.token("transfer", body)
        st, r = self.call("/api/trash", dict(body, action_token=tok), pin=False)
        self.assertEqual(r["code"], "pin_mismatch", "a 'move' token cannot delete")
        tok = self.token("trash", body)
        with mock.patch.object(config, "PIN_ACTION_TOKEN_S", -1):
            tok_old = self.token("trash", body)
        st, r = self.call("/api/trash", dict(body, action_token=tok_old), pin=False)
        self.assertEqual(r["code"], "pin_expired")
        st, r = self.call("/api/trash", dict(body, action_token=tok), pin=False)
        self.assertEqual(st, 200, r)
        web._RATE.clear()
        st, r = self.call("/api/trash", dict(body, action_token=tok), pin=False)
        self.assertEqual((st, r["code"]), (403, "pin_required"), "used once, then gone")

    def test_wrong_pin_gives_no_token_and_counts(self):
        st, r = self.call("/api/pin/verify", {"pin": "9999", "action": "trash", "request": {"ids": [self.fid]}})
        self.assertEqual((st, r["code"]), (403, "wrong_pin"))
        st, r = self.call("/api/pin/verify", {"action": "trash", "request": {}})
        self.assertEqual((st, r["code"]), (403, "pin_required"), "no PIN, no token (remember is off by default)")

    def test_remember_for_n_minutes_is_opt_in(self):
        st, r = self.call("/api/pin/settings", {"pin_remember_min": 5})
        self.assertEqual(st, 200, r)
        self.token("trash", {"ids": [self.fid]})                    # one PIN entry starts the window
        st, r = self.call("/api/pin/verify", {"action": "trash", "request": {"ids": [self.fid]}})
        self.assertEqual(st, 200, "inside the window no PIN is asked")
        self.call("/api/pin/lock", {})
        self.call("/api/pin/unlock", {"pin": TEST_PIN})
        st, r = self.call("/api/pin/verify", {"action": "trash", "request": {}})
        self.assertEqual(r["code"], "pin_required", "locking ends the window")

    def test_security_settings_need_the_pin(self):
        from core import settings
        st, r = self.call("/api/settings", {"pin_remember_min": 15, "apptrash_purge_days": 30})
        self.assertEqual(st, 200)
        self.assertEqual((settings.load()["pin_remember_min"], settings.load()["apptrash_purge_days"]), (0, 0), "ignored without the PIN")
        with mock.patch.dict(os.environ, {config.SCHEMA_STRICT_ENV: "1"}):
            st, r = self.call("/api/settings", {"pin_remember_min": 15})
        self.assertEqual((st, r["code"]), (400, "unknown_field"), "strict mode refuses them outright")


class StorageTest(PinCase):
    def test_pin_is_never_stored_or_logged_in_plaintext(self):
        config.PIN_SCRYPT_N = self._pin_n            # the real cost, as on a user's PC
        self.setup_pin("739215")
        self.call("/api/pin/lock", {})
        self.call("/api/pin/unlock", {"pin": "000111"})
        self.call("/api/pin/unlock", {"pin": "739215"})
        rec = json.loads((config.DATA_DIR / config.PIN_FILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(rec["algo"], "scrypt")
        self.assertEqual(rec["n"], 2 ** 15)
        self.assertEqual(len(bytes.fromhex(rec["salt"])), 16)
        for f in config.DATA_DIR.rglob("*"):
            if f.is_file() and f.suffix not in (".sqlite3",):
                data = f.read_bytes()
                self.assertNotIn(b"739215", data, f.name)
                self.assertNotIn(b"000111", data, f.name)

    def test_pbkdf2_fallback_without_scrypt(self):
        with mock.patch.object(pin.hashlib, "scrypt", side_effect=ValueError("no scrypt")):
            rec = pin._new_record("482613")
        self.assertEqual(rec["algo"], "pbkdf2")
        self.assertGreaterEqual(rec["iterations"], 600_000)

    def test_weak_pins(self):
        for w in ("1234", "0000", "1111", "4321", "2580", "123456", "121212", "6789"):
            self.assertTrue(pin.is_weak(w), w)
        for s in ("4826", "739215", "1397"):
            self.assertFalse(pin.is_weak(s), s)


class ResetTest(PinCase):
    def test_forgot_pin_wipes_aurasort_data_never_files(self):
        self.setup_pin()
        f = self.make("Pics/keep.jpg", b"jpg")
        self.scan_fixture()
        history.save(dict(id="h1", kind="move", time=1, dest="", ops=[]))
        self.call("/api/pin/lock", {})
        self.assertEqual(self.call("/api/pin/reset", {"confirm": "yes"})[0], 400, "RESET must be typed")
        st, r = self.call("/api/pin/reset", {"confirm": "RESET"})
        self.assertEqual(st, 200, r)
        self.assertTrue(os.path.exists(f), "your files are never touched")
        self.assertFalse((config.DATA_DIR / config.PIN_FILE_NAME).exists())
        self.assertEqual(history.entries(10), [])
        st, r = self.call("/api/summary")
        self.assertEqual(r["code"], "pin_not_set", "setup starts again")


class FrontEndRulesTest(unittest.TestCase):
    """The PIN only ever travels in a POST body: never a URL, never localStorage."""

    def test_no_pin_in_urls_or_storage(self):
        src = (ROOT / "docs" / "js" / "pin.js").read_text(encoding="utf-8")
        self.assertNotIn("localStorage", src)
        self.assertNotIn("sessionStorage", src)
        api = (ROOT / "docs" / "js" / "api.js").read_text(encoding="utf-8")
        for name in ("pinSet", "pinUnlock", "pinVerify"):
            line = next(ln for ln in api.splitlines() if name + ":" in ln)
            frag = line[line.index(name + ":"):].split("),")[0]
            self.assertNotIn("?", frag, f"{name} must not put anything in the URL")
        for f in ("execute", "trash", "undo", "quarantine", "deleteData", "aiKey"):
            self.assertRegex(api, rf"{f}: [^\n]*guarded\(", f)

    def test_inputs_are_numeric_and_not_autofilled(self):
        src = (ROOT / "docs" / "js" / "pin.js").read_text(encoding="utf-8")
        self.assertIn('inputmode="numeric"', src)
        self.assertIn('autocomplete="off"', src)
        self.assertIn('type="password"', src)


if __name__ == "__main__":
    unittest.main()
