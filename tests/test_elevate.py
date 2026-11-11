"""The optional "Restart with administrator permission" (Windows only): asks first, declining changes nothing."""
import json
import unittest
from unittest import mock

from tests.test_web_security import ServerCase
from core import config, platform_utils


class ElevateTest(ServerCase):
    def call(self, body=None, **kw):
        st, _, raw = self.req("/api/elevate", {} if body is None else body, **kw)
        return st, json.loads(raw or b"{}")

    def test_needs_the_pin(self):
        with mock.patch.object(config, "WIN", True), mock.patch.object(platform_utils, "relaunch_elevated") as rel:
            st, r = self.call(pin=False)
        self.assertEqual((st, r.get("code")), (403, "pin_required"))
        rel.assert_not_called()

    def test_declined_changes_nothing(self):
        with mock.patch.object(config, "WIN", True), mock.patch.object(platform_utils, "is_admin", return_value=False), \
                mock.patch.object(platform_utils, "relaunch_elevated", return_value=False) as rel, \
                mock.patch.object(self.server_mod, "_hand_over") as hand:
            st, r = self.call()
        self.assertEqual((st, r), (200, {"ok": False, "declined": True}))
        rel.assert_called_once()
        hand.assert_not_called()
        args, cwd = rel.call_args[0]
        self.assertIn("--wait-for-lock", args)
        self.assertNotIn("system32", cwd.lower(), "the new copy never starts in System32")

    def test_accepted_hands_over(self):
        with mock.patch.object(config, "WIN", True), mock.patch.object(platform_utils, "is_admin", return_value=False), \
                mock.patch.object(platform_utils, "relaunch_elevated", return_value=True), \
                mock.patch.object(self.server_mod.threading, "Timer") as timer:
            st, r = self.call()
        self.assertEqual((st, r), (200, {"ok": True}))
        timer.assert_called_once()
        self.assertIs(timer.call_args[0][1], self.server_mod._hand_over)

    def test_already_admin_or_not_windows(self):
        with mock.patch.object(config, "WIN", True), mock.patch.object(platform_utils, "is_admin", return_value=True):
            st, r = self.call()
        self.assertEqual((st, r.get("code")), (400, "already_admin"))
        with mock.patch.object(config, "WIN", False):
            st, r = self.call()
        self.assertEqual((st, r.get("code")), (400, "not_supported"))


if __name__ == "__main__":
    unittest.main()
