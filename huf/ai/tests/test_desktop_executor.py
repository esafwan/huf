# Copyright (c) 2026, Tridz Technologies Pvt Ltd and contributors
# For license information, please see license.txt

"""Tests for huf.ai.desktop_executor (lease API, event submit, blocking dispatch).

Covers PLAN.md security cases S22-S26 (deadline extension, offline fast-fail,
ack timeout, wrong user, wrong executor / expired / duplicate) plus lease
register / heartbeat / expiry / re-register. ``frappe.cache`` is replaced by an
in-memory fake whose ``blpop`` never blocks, and realtime publishes are
captured, so no Redis or socket server is needed.

Run with:
	bench --site <site> run-tests --app huf --module huf.ai.tests.test_desktop_executor
"""

import json
import unittest
from unittest import mock

import frappe

from huf.ai import desktop_executor as dx

EXEC_ID = "exec-0001-aaaa"
FP = "0123456789abcdef"
USER = "alice@example.com"
OTHER = "mallory@example.com"


class FakeCache:
	"""Just enough of frappe's RedisWrapper for desktop_executor.

	``blpop`` pops immediately (or returns None when empty) and records the timeout
	it was asked for. ``on_blpop`` lets a test act as the desktop between polls.
	"""

	def __init__(self):
		self.values = {}
		self.raw = {}
		self.zsets = {}
		self.sets = {}
		self.expiries = {}
		self.blpop_timeouts = []
		self.on_blpop = None
		self.deleted_raw = []

	# structured values
	def set_value(self, key, val, expires_in_sec=None, **_):
		self.values[key] = val
		if expires_in_sec:
			self.expiries[key] = expires_in_sec

	def get_value(self, key, **_):
		return self.values.get(key)

	def delete_value(self, key, **_):
		self.values.pop(key, None)

	def expire_lease(self, executor_id):
		self.values.pop(dx._lease_key(executor_id), None)

	# raw redis
	def rpush(self, key, val):
		self.raw.setdefault(key, []).append(val)

	def expire(self, key, ttl):
		self.expiries[key] = ttl

	def delete(self, key):
		self.deleted_raw.append(key)
		self.raw.pop(key, None)

	def blpop(self, key, timeout=0):
		self.blpop_timeouts.append(timeout)
		if self.on_blpop:
			cb, self.on_blpop = self.on_blpop, None
			cb()
		lst = self.raw.get(key) or []
		if not lst:
			return None
		return (key, lst.pop(0))

	def zadd(self, key, mapping):
		self.zsets.setdefault(key, {}).update(mapping)

	def zrem(self, key, member):
		self.zsets.get(key, {}).pop(member, None)

	def zremrangebyscore(self, key, lo, hi):
		z = self.zsets.get(key, {})
		for m in [m for m, s in z.items() if s <= hi]:
			del z[m]

	def zrangebyscore(self, key, lo, hi):
		return [m for m, s in self.zsets.get(key, {}).items() if s >= lo]

	def sadd(self, key, member):
		self.sets.setdefault(key, set()).add(member)

	def srem(self, key, member):
		self.sets.get(key, set()).discard(member)


def _ws(fp=FP, mode="ask"):
	return {"label": "my-project", "fingerprint": fp, "permission_mode": mode, "exec_confined": True}


class DesktopExecutorTestCase(unittest.TestCase):
	def setUp(self):
		self.cache = FakeCache()
		self.session = mock.MagicMock()
		self.session.user = USER
		patches = [
			mock.patch.object(dx.frappe, "cache", return_value=self.cache),
			mock.patch.object(dx.frappe, "session", self.session),
			mock.patch.object(dx.frappe, "log_error"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		pub = mock.patch.object(dx.frappe, "publish_realtime")
		self.publish = pub.start()
		self.addCleanup(pub.stop)

	# helpers
	def register(self, user=USER, executor_id=EXEC_ID, caps=None, ws=None):
		self.session.user = user
		return dx.register_desktop_executor(
			executor_id=executor_id,
			protocol_version=1,
			app_version="0.1",
			platform="darwin",
			workspace=ws or _ws(),
			capabilities=caps or ["fs.read", "fs.write", "fs.trash", "exec"],
		)

	def ctx(self, user=USER):
		return {"executor_id": EXEC_ID, "fingerprint": FP, "user": user, "label": "my-project"}

	def desktop_submit(self, call_id, kind, payload=None, user=USER, executor_id=EXEC_ID):
		self.session.user = user
		return dx.submit_desktop_tool_event(
			call_id=call_id, executor_id=executor_id, kind=kind, payload=payload or {}
		)

	def sent_calls(self):
		return [
			c.kwargs
			for c in self.publish.call_args_list
			if c.kwargs.get("event") == dx.TOOL_CALL_EVENT
		]

	def cancels(self):
		return [
			c.kwargs
			for c in self.publish.call_args_list
			if c.kwargs.get("event") == dx.TOOL_CANCEL_EVENT
		]


class TestLease(DesktopExecutorTestCase):
	def test_register_returns_wire_shape_and_stores_lease_with_ttl(self):
		res = self.register()
		self.assertEqual(
			res, {"ok": True, "lease_ttl_s": 60, "heartbeat_s": 20, "protocol_version": 1}
		)
		lease = self.cache.values[dx._lease_key(EXEC_ID)]
		self.assertEqual(lease["user"], USER)
		self.assertEqual(lease["workspace"]["fingerprint"], FP)
		self.assertEqual(self.cache.expiries[dx._lease_key(EXEC_ID)], 60)
		self.assertIn(EXEC_ID, self.cache.sets[dx._user_key(USER)])

	def test_register_rejects_guest_and_bad_protocol(self):
		self.session.user = "Guest"
		with self.assertRaises(frappe.PermissionError):
			dx.register_desktop_executor(
				executor_id=EXEC_ID, protocol_version=1, workspace=_ws(), capabilities=[]
			)
		self.session.user = USER
		with self.assertRaises(frappe.ValidationError):
			dx.register_desktop_executor(
				executor_id=EXEC_ID, protocol_version=2, workspace=_ws(), capabilities=[]
			)

	def test_register_same_id_other_user_rejected(self):
		self.register()
		with self.assertRaises(frappe.PermissionError):
			self.register(user=OTHER)
		self.assertEqual(self.cache.values[dx._lease_key(EXEC_ID)]["user"], USER)

	def test_reregister_same_user_keeps_registered_at(self):
		self.register()
		first = self.cache.values[dx._lease_key(EXEC_ID)]["registered_at"]
		self.register()
		self.assertEqual(self.cache.values[dx._lease_key(EXEC_ID)]["registered_at"], first)

	def test_workspace_accepts_json_string(self):
		self.session.user = USER
		res = dx.register_desktop_executor(
			executor_id=EXEC_ID,
			protocol_version="1",
			workspace=json.dumps(_ws()),
			capabilities=json.dumps(["fs.read"]),
		)
		self.assertTrue(res["ok"])
		self.assertEqual(self.cache.values[dx._lease_key(EXEC_ID)]["capabilities"], ["fs.read"])

	def test_heartbeat_refreshes_ttl_and_socket_flag(self):
		self.register()
		self.cache.expiries[dx._lease_key(EXEC_ID)] = 3
		res = dx.heartbeat_desktop_executor(
			executor_id=EXEC_ID, workspace=_ws(mode="auto"), socket_connected=False
		)
		self.assertEqual(res, {"ok": True, "pending_call_ids": []})
		lease = self.cache.values[dx._lease_key(EXEC_ID)]
		self.assertFalse(lease["socket_connected"])
		self.assertEqual(lease["workspace"]["permission_mode"], "auto")
		self.assertEqual(self.cache.expiries[dx._lease_key(EXEC_ID)], 60)

	def test_heartbeat_after_expiry_asks_reregister_then_register_works(self):
		self.register()
		self.cache.expire_lease(EXEC_ID)
		res = dx.heartbeat_desktop_executor(executor_id=EXEC_ID, workspace=_ws(), socket_connected=True)
		self.assertEqual(res, {"ok": False, "reregister": True})
		self.assertTrue(self.register()["ok"])
		self.assertTrue(
			dx.heartbeat_desktop_executor(executor_id=EXEC_ID, workspace=_ws(), socket_connected=True)["ok"]
		)

	def test_heartbeat_other_user_rejected(self):
		self.register()
		self.session.user = OTHER
		with self.assertRaises(frappe.PermissionError):
			dx.heartbeat_desktop_executor(executor_id=EXEC_ID, workspace=_ws(), socket_connected=True)

	def test_unregister_removes_lease_only_for_owner(self):
		self.register()
		self.session.user = OTHER
		with self.assertRaises(frappe.PermissionError):
			dx.unregister_desktop_executor(executor_id=EXEC_ID)
		self.session.user = USER
		self.assertEqual(dx.unregister_desktop_executor(executor_id=EXEC_ID), {"ok": True})
		self.assertIsNone(self.cache.values.get(dx._lease_key(EXEC_ID)))
		# idempotent
		self.assertEqual(dx.unregister_desktop_executor(executor_id=EXEC_ID), {"ok": True})

	def test_resolve_desktop_ctx(self):
		self.register()
		self.assertEqual(
			dx.resolve_desktop_ctx(EXEC_ID, USER),
			{"executor_id": EXEC_ID, "fingerprint": FP, "user": USER, "label": "my-project"},
		)
		self.assertIsNone(dx.resolve_desktop_ctx(EXEC_ID, OTHER))
		self.assertIsNone(dx.resolve_desktop_ctx("nope", USER))
		self.cache.expire_lease(EXEC_ID)
		self.assertIsNone(dx.resolve_desktop_ctx(EXEC_ID, USER))


class TestDispatch(DesktopExecutorTestCase):
	def setUp(self):
		super().setUp()
		self.register()

	def test_s23_offline_fails_fast_without_publish_or_wait(self):
		self.cache.expire_lease(EXEC_ID)
		res = dx.dispatch("fs.read", {"path": "a.txt"}, self.ctx(), call_id="c-off")
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"]["code"], "desktop_offline")
		self.publish.assert_not_called()
		self.assertEqual(self.cache.blpop_timeouts, [])

	def test_offline_when_lease_belongs_to_other_user(self):
		res = dx.dispatch("fs.read", {"path": "a"}, self.ctx(user=OTHER), call_id="c-other")
		self.assertEqual(res["error"]["code"], "desktop_offline")
		self.publish.assert_not_called()

	def test_s24_ack_timeout_returns_unreachable_and_publishes_cancel(self):
		res = dx.dispatch("fs.read", {"path": "a.txt"}, self.ctx(), call_id="c-noack")
		self.assertEqual(res["error"]["code"], "desktop_unreachable")
		self.assertEqual(len(self.sent_calls()), 1)
		self.assertLessEqual(self.cache.blpop_timeouts[0], 10)
		cancels = self.cancels()
		self.assertEqual(len(cancels), 1)
		self.assertEqual(cancels[0]["user"], USER)
		self.assertEqual(cancels[0]["message"]["call_id"], "c-noack")
		self.assertEqual(cancels[0]["message"]["executor_id"], EXEC_ID)

	def test_publish_payload_scoped_to_lease_user_with_protocol_fields(self):
		dx.dispatch(
			"fs.write",
			{"path": "a.txt", "content": "x"},
			self.ctx(),
			call_id="c-pub",
			conversation_id="conv-1",
			agent_run_id="run-1",
			timeout_ms=30000,
			tool_name="desktop_write_file",
			agent_name="Bot",
		)
		kw = self.sent_calls()[0]
		self.assertEqual(kw["user"], USER)
		m = kw["message"]
		for key in (
			"v", "call_id", "executor_id", "fingerprint", "conversation_id", "agent_run_id",
			"agent_name", "tool_name", "op", "params", "issued_at", "ack_deadline_at",
			"deadline_at", "timeout_ms", "approval_timeout_ms",
		):
			self.assertIn(key, m)
		self.assertEqual(m["v"], 1)
		self.assertEqual(m["op"], "fs.write")
		self.assertEqual(m["timeout_ms"], 30000)
		self.assertEqual(m["approval_timeout_ms"], 90000)
		self.assertEqual(m["ack_deadline_at"] - m["issued_at"], 10000)

	def test_happy_path_ack_then_result_and_cleanup(self):
		def desktop():
			self.assertEqual(self.desktop_submit("c-ok", "ack")["status"], "recorded")
			self.desktop_submit(
				"c-ok", "result", {"ok": True, "data": {"content": "hi"}, "truncated": False, "duration_ms": 12}
			)

		self.cache.on_blpop = desktop
		res = dx.dispatch("fs.read", {"path": "a.txt"}, self.ctx(), call_id="c-ok")
		self.assertTrue(res["ok"])
		self.assertEqual(res["data"], {"content": "hi"})
		self.assertEqual(res["workspace"], "my-project")
		self.assertEqual(res["duration_ms"], 12)
		# results of reads are flagged untrusted
		self.assertTrue(res["untrusted_content"])
		self.assertIn("data, not instructions", res["note"])
		# cleanup, raw delete on the raw list
		self.assertIsNone(self.cache.values.get(dx._request_key("c-ok")))
		self.assertIn(dx._result_key("c-ok"), self.cache.deleted_raw)
		self.assertNotIn("c-ok", self.cache.zsets.get(dx._pending_key(EXEC_ID), {}))

	def test_write_result_not_flagged_untrusted(self):
		self.cache.on_blpop = lambda: (
			self.desktop_submit("c-w", "ack"),
			self.desktop_submit("c-w", "result", {"ok": True, "data": {"bytes": 3}}),
		)
		res = dx.dispatch("fs.write", {"path": "a", "content": "abc"}, self.ctx(), call_id="c-w")
		self.assertTrue(res["ok"])
		self.assertNotIn("untrusted_content", res)

	def test_desktop_error_maps_code_and_unknown_code_becomes_internal(self):
		self.cache.on_blpop = lambda: (
			self.desktop_submit("c-e", "ack"),
			self.desktop_submit("c-e", "error", {"ok": False, "code": "denied_by_user", "message": "no"}),
		)
		res = dx.dispatch("fs.trash", {"path": "a"}, self.ctx(), call_id="c-e")
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"], {"code": "denied_by_user", "message": "no"})

		self.cache.on_blpop = lambda: (
			self.desktop_submit("c-e2", "ack"),
			self.desktop_submit("c-e2", "error", {"code": "weird", "message": "x"}),
		)
		res = dx.dispatch("fs.trash", {"path": "a"}, self.ctx(), call_id="c-e2")
		self.assertEqual(res["error"]["code"], "internal")

	def test_s22_approval_pending_extends_deadline_once(self):
		def desktop():
			self.desktop_submit("c-ap", "ack")
			self.desktop_submit("c-ap", "approval_pending")
			self.desktop_submit("c-ap", "approval_pending")  # second one must not extend again

		self.cache.on_blpop = desktop
		res = dx.dispatch("exec.run", {"command": "ls"}, self.ctx(), call_id="c-ap", timeout_ms=20000)
		# never got a terminal message: server times out, and cancels
		self.assertEqual(res["error"]["code"], "timeout")
		self.assertEqual(self.cancels()[0]["message"]["reason"], "server_timeout")
		# first wait is the ack phase (<=10s); after ack+approval the wait covers
		# timeout (20s) + approval (90s) + grace (10s) = up to 120s, capped by 240s.
		waits = self.cache.blpop_timeouts
		self.assertLessEqual(waits[0], 10)  # ack phase
		self.assertLessEqual(waits[1], 20)  # run phase before approval_pending
		self.assertGreater(waits[2], 100)  # after the one extension
		self.assertLessEqual(waits[2], 120)
		self.assertLessEqual(waits[3], 120)  # a second approval_pending does not extend again

	def test_s22_approval_timeout_from_desktop_is_passed_through(self):
		self.cache.on_blpop = lambda: (
			self.desktop_submit("c-at", "ack"),
			self.desktop_submit("c-at", "approval_pending"),
			self.desktop_submit(
				"c-at", "error", {"ok": False, "code": "approval_timeout", "message": "no answer"}
			),
		)
		res = dx.dispatch("exec.run", {"command": "ls"}, self.ctx(), call_id="c-at")
		self.assertEqual(res["error"]["code"], "approval_timeout")
		self.assertEqual(self.cancels(), [])

	def test_run_phase_timeout_after_ack(self):
		self.cache.on_blpop = lambda: self.desktop_submit("c-to", "ack")
		res = dx.dispatch("fs.list", {"path": "."}, self.ctx(), call_id="c-to", timeout_ms=5000)
		self.assertEqual(res["error"]["code"], "timeout")
		self.assertLessEqual(self.cache.blpop_timeouts[1], 5)

	def test_timeout_ms_is_clamped_to_hard_cap(self):
		dx.dispatch("fs.read", {"path": "a"}, self.ctx(), call_id="c-cap", timeout_ms=10**9)
		self.assertEqual(self.sent_calls()[0]["message"]["timeout_ms"], 240000)
		dx.dispatch("fs.read", {"path": "a"}, self.ctx(), call_id="c-cap2", timeout_ms=1)
		self.assertEqual(self.sent_calls()[1]["message"]["timeout_ms"], 1000)

	def test_params_over_512kb_rejected_before_publish(self):
		res = dx.dispatch(
			"fs.search", {"query": "x" * (513 * 1024)}, self.ctx(), call_id="c-big"
		)
		self.assertEqual(res["error"]["code"], "too_large")
		self.publish.assert_not_called()

	def test_write_content_over_256kb_rejected_before_publish(self):
		res = dx.dispatch(
			"fs.write", {"path": "a", "content": "x" * (257 * 1024)}, self.ctx(), call_id="c-big2"
		)
		self.assertEqual(res["error"]["code"], "too_large")
		self.publish.assert_not_called()

	def test_oversized_result_is_dropped_as_too_large(self):
		big = {"ok": True, "data": {"content": "x" * (97 * 1024)}}
		self.cache.on_blpop = lambda: (
			self.desktop_submit("c-rb", "ack"),
			self.desktop_submit("c-rb", "result", big),
		)
		res = dx.dispatch("fs.read", {"path": "a"}, self.ctx(), call_id="c-rb")
		self.assertFalse(res["ok"])
		self.assertEqual(res["error"]["code"], "too_large")

	def test_workspace_changed_and_capability_fail_fast(self):
		bad = dict(self.ctx(), fingerprint="ffffffffffffffff")
		res = dx.dispatch("fs.read", {"path": "a"}, bad, call_id="c-ws")
		self.assertEqual(res["error"]["code"], "workspace_changed")
		self.publish.assert_not_called()

		self.register(caps=["fs.read"])
		res = dx.dispatch("exec.run", {"command": "ls"}, self.ctx(), call_id="c-cap3")
		self.assertEqual(res["error"]["code"], "capability_unavailable")
		self.publish.assert_not_called()

	def test_unknown_op_and_bad_params(self):
		self.assertEqual(
			dx.dispatch("fs.nuke", {}, self.ctx(), call_id="c1")["error"]["code"], "invalid_params"
		)
		self.assertEqual(
			dx.dispatch("fs.read", "nope", self.ctx(), call_id="c2")["error"]["code"], "invalid_params"
		)

	def test_finished_call_id_is_idempotent(self):
		self.cache.on_blpop = lambda: (
			self.desktop_submit("c-id", "ack"),
			self.desktop_submit("c-id", "result", {"ok": True, "data": {"n": 1}}),
		)
		first = dx.dispatch("fs.mkdir", {"path": "d"}, self.ctx(), call_id="c-id")
		self.assertTrue(first["ok"])
		self.assertEqual(len(self.sent_calls()), 1)
		second = dx.dispatch("fs.mkdir", {"path": "d"}, self.ctx(), call_id="c-id")
		self.assertEqual(second, first)
		self.assertEqual(len(self.sent_calls()), 1)  # not re-sent

	def test_in_flight_call_id_is_rejected(self):
		self.cache.set_value(dx._request_key("c-dup"), {"user": USER, "executor_id": EXEC_ID})
		res = dx.dispatch("fs.read", {"path": "a"}, self.ctx(), call_id="c-dup")
		self.assertEqual(res["error"]["code"], "duplicate_in_flight")
		self.publish.assert_not_called()


class TestSubmit(DesktopExecutorTestCase):
	def setUp(self):
		super().setUp()
		self.register()
		# a call awaiting results: stash in place, nothing consumed yet
		self.cache.set_value(
			dx._request_key("call-1"),
			{"user": USER, "executor_id": EXEC_ID, "request": {"call_id": "call-1"}},
		)
		self.cache.zadd(dx._pending_key(EXEC_ID), {"call-1": dx._now_ms() + 60000})

	def test_s25_other_user_gets_permission_error_and_nothing_is_pushed(self):
		with self.assertRaises(frappe.PermissionError):
			self.desktop_submit("call-1", "result", {"ok": True}, user=OTHER)
		self.assertEqual(self.cache.raw.get(dx._result_key("call-1")), None)

	def test_guest_rejected(self):
		with self.assertRaises(frappe.PermissionError):
			self.desktop_submit("call-1", "result", {"ok": True}, user="Guest")

	def test_s26_wrong_executor_id_rejected(self):
		with self.assertRaises(frappe.PermissionError):
			self.desktop_submit("call-1", "result", {"ok": True}, executor_id="exec-other-bbbb")
		self.assertEqual(self.cache.raw.get(dx._result_key("call-1")), None)

	def test_s26_unknown_or_expired_call(self):
		res = self.desktop_submit("never-issued", "result", {"ok": True})
		self.assertEqual(res["status"], "expired")
		self.cache.values.pop(dx._request_key("call-1"))
		self.assertEqual(self.desktop_submit("call-1", "result", {"ok": True})["status"], "expired")

	def test_s26_second_terminal_is_already_recorded_and_not_pushed(self):
		first = self.desktop_submit("call-1", "result", {"ok": True, "data": 1})
		self.assertEqual(first["status"], "recorded")
		second = self.desktop_submit("call-1", "result", {"ok": True, "data": 2})
		self.assertEqual(second, {"status": "already_recorded"})
		third = self.desktop_submit("call-1", "error", {"code": "internal", "message": "x"})
		self.assertEqual(third["status"], "already_recorded")
		lst = self.cache.raw[dx._result_key("call-1")]
		self.assertEqual(len(lst), 1)
		self.assertEqual(json.loads(lst[0])["payload"]["data"], 1)

	def test_raw_expire_is_set_on_the_result_list_and_pending_cleared_on_terminal(self):
		self.desktop_submit("call-1", "ack")
		self.assertIn(dx._pending_key(EXEC_ID), self.cache.zsets)
		self.assertIn("call-1", self.cache.zsets[dx._pending_key(EXEC_ID)])
		self.desktop_submit("call-1", "result", {"ok": True})
		self.assertEqual(self.cache.expiries[dx._result_key("call-1")], 270)
		self.assertNotIn("call-1", self.cache.zsets[dx._pending_key(EXEC_ID)])

	def test_invalid_kind_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.desktop_submit("call-1", "boom")

	def test_duplicate_acks_are_harmless(self):
		self.assertEqual(self.desktop_submit("call-1", "ack")["status"], "recorded")
		self.assertEqual(self.desktop_submit("call-1", "ack")["status"], "recorded")

	def test_list_pending_and_heartbeat_report_unexpired_calls(self):
		res = dx.list_pending_desktop_tool_calls(executor_id=EXEC_ID)
		self.assertEqual([r["call_id"] for r in res], ["call-1"])
		hb = dx.heartbeat_desktop_executor(executor_id=EXEC_ID, workspace=_ws(), socket_connected=True)
		self.assertEqual(hb["pending_call_ids"], ["call-1"])

		# past deadline: pruned
		self.cache.zsets[dx._pending_key(EXEC_ID)]["call-1"] = dx._now_ms() - 5
		self.assertEqual(dx.list_pending_desktop_tool_calls(executor_id=EXEC_ID), [])

	def test_list_pending_other_user_rejected_and_no_lease_is_empty(self):
		self.session.user = OTHER
		with self.assertRaises(frappe.PermissionError):
			dx.list_pending_desktop_tool_calls(executor_id=EXEC_ID)
		self.session.user = USER
		self.cache.expire_lease(EXEC_ID)
		self.assertEqual(dx.list_pending_desktop_tool_calls(executor_id=EXEC_ID), [])
