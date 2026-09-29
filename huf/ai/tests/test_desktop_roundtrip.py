# Copyright (c) 2026, Tridz Technologies Pvt Ltd and contributors
# For license information, please see license.txt

"""REAL round-trip tests for desktop workspace tools (no mocked cache, no mocked get_doc).

A real (non-admin) user registers a lease through the whitelisted endpoints, a real
Agent Run stores ``runtime_context`` as a JSON string, a real tool handler is called,
and a background thread plays the desktop (polls ``list_pending_desktop_tool_calls``
and answers via ``submit_desktop_tool_event``) against the live Redis cache. Some
cases deliberately wait longer than the 5 s redis-cache socket timeout.

Run with:
	bench --site <site> run-tests --app huf --module huf.ai.tests.test_desktop_roundtrip
"""

import time
import unittest
from unittest import mock

import frappe

from huf.ai import agent_integration as ai
from huf.ai import desktop_executor as dx
from huf.ai.tests import desktop_test_helpers as h
from huf.ai.tools import desktop_workspace as dw

CAPS = ["fs.read", "fs.write", "fs.trash", "exec"]


class TestDesktopRoundTrip(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.user = h.make_user("dxrt")
		cls.other = h.make_user("dxrt2")
		cls._docs = []

	@classmethod
	def tearDownClass(cls):
		h.delete_docs(cls._docs + [("User", cls.user), ("User", cls.other)])

	def setUp(self):
		frappe.set_user(self.user)
		self.exec_id = f"exec-rt-{frappe.generate_hash(length=10)}"
		self.call_id = f"call-rt-{frappe.generate_hash(length=10)}"
		self.register()
		self.run_name = h.make_run(self.user, h.desktop_pin(self.exec_id, self.user))
		self._docs.append(("Agent Run", self.run_name))
		frappe.set_user(self.user)

	def tearDown(self):
		frappe.set_user(self.user)
		try:
			dx.unregister_desktop_executor(executor_id=self.exec_id)
		except Exception:
			pass
		frappe.set_user("Administrator")

	# helpers
	def register(self, fingerprint=h.FP):
		frappe.set_user(self.user)
		return dx.register_desktop_executor(
			executor_id=self.exec_id,
			protocol_version=1,
			app_version="0.1",
			platform="darwin",
			workspace=h.workspace(fingerprint),
			capabilities=CAPS,
		)

	def read_file(self, **over):
		kwargs = dict(
			path="a.txt",
			_dx_executor_id=self.exec_id,
			_dx_fingerprint=h.FP,
			_dx_user=self.user,
			agent_run_id=self.run_name,
			call_id=self.call_id,
		)
		kwargs.update(over)
		return dw.handle_read_file(**kwargs)

	def play_desktop(self, script, poll_for_s=15):
		"""Background desktop: wait for our call to show up in list_pending, then run
		``script`` = [(sleep_s, kind, payload), ...] through submit_desktop_tool_event."""
		results = []

		def play():
			deadline = time.monotonic() + poll_for_s
			seen = None
			while time.monotonic() < deadline and seen is None:
				for req in dx.list_pending_desktop_tool_calls(executor_id=self.exec_id):
					if req["call_id"] == self.call_id:
						seen = req
				if seen is None:
					time.sleep(0.1)
			if seen is None:
				raise AssertionError("desktop never saw the call in list_pending")
			results.append(("request", seen))
			for delay, kind, payload in script:
				time.sleep(delay)
				results.append(
					(
						kind,
						dx.submit_desktop_tool_event(
							call_id=self.call_id, executor_id=self.exec_id, kind=kind, payload=payload
						),
					)
				)

		thread, errors = h.run_in_thread(play)
		return thread, errors, results

	def finish(self, thread, errors, timeout=30):
		thread.join(timeout)
		self.assertFalse(thread.is_alive(), "desktop thread did not finish")
		self.assertEqual(errors, [])

	# tests
	def test_fast_round_trip_through_a_real_handler(self):
		thread, errors, results = self.play_desktop(
			[
				(0.2, "ack", {}),
				(0.2, "result", {"ok": True, "data": {"content": "hello"}, "duration_ms": 5}),
			]
		)
		out = self.read_file()
		self.finish(thread, errors)
		self.assertEqual(out["data"]["content"], "hello")
		self.assertTrue(out["ok"])
		self.assertTrue(out["untrusted_content"])
		req = results[0][1]
		self.assertEqual(req["executor_id"], self.exec_id)
		self.assertEqual(req["fingerprint"], h.FP)
		self.assertEqual(req["agent_run_id"], self.run_name)
		self.assertEqual(req["op"], "fs.read")
		self.assertEqual([r[1]["status"] for r in results[1:]], ["recorded", "recorded"])

	def test_redis_state_is_cleaned_up_after_the_call(self):
		thread, errors, _ = self.play_desktop(
			[(0.1, "ack", {}), (0.1, "result", {"ok": True, "data": {"content": "x"}})]
		)
		self.read_file()
		self.finish(thread, errors)
		r = dx._raw_client()
		self.assertEqual(r.exists(dx._k(dx._result_key(self.call_id))), 0)
		self.assertEqual(r.exists(dx._result_key(self.call_id)), 0)  # never used unprefixed
		self.assertEqual(r.exists(dx._k(dx._request_key(self.call_id))), 0)
		self.assertGreater(r.ttl(dx._k(dx._done_key(self.call_id))), 0)
		self.assertGreater(r.ttl(dx._k(dx._final_key(self.user, self.run_name, self.call_id))), 0)

	def test_event_list_is_written_with_the_site_prefix_and_a_ttl(self):
		"""Producer side: the list a desktop event lands in is exactly the key the waiter
		reads (prefixed), and always has an expiry."""
		dx._setex(
			dx._request_key(self.call_id),
			{"user": self.user, "executor_id": self.exec_id, "request": {"call_id": self.call_id}},
			60,
		)
		out = dx.submit_desktop_tool_event(
			call_id=self.call_id, executor_id=self.exec_id, kind="ack", payload={}
		)
		self.assertEqual(out["status"], "recorded")
		r = dx._raw_client()
		key = dx._k(dx._result_key(self.call_id))
		try:
			self.assertEqual(r.llen(key), 1)
			self.assertGreater(r.ttl(key), 0)
			self.assertEqual(r.exists(dx._result_key(self.call_id)), 0)
		finally:
			dx._delete(dx._request_key(self.call_id), dx._result_key(self.call_id))

	def test_approval_flow_longer_than_the_5s_redis_socket_timeout(self):
		"""ack, approval_pending, then the user takes ~7 s: would raise TimeoutError (mapped to
		cache_unavailable) with a single long BLPOP on the 5 s cache connection."""
		thread, errors, _ = self.play_desktop(
			[
				(0.3, "ack", {}),
				(0.3, "approval_pending", {}),
				(7.0, "result", {"ok": True, "data": {"content": "approved"}}),
			]
		)
		started = time.monotonic()
		out = self.read_file()
		elapsed = time.monotonic() - started
		self.finish(thread, errors)
		self.assertEqual(out["data"]["content"], "approved", out)
		self.assertGreater(elapsed, 6.5)

	def test_slow_ack_longer_than_the_5s_redis_socket_timeout(self):
		thread, errors, _ = self.play_desktop(
			[(6.5, "ack", {}), (0.3, "result", {"ok": True, "data": {"content": "late"}})]
		)
		out = self.read_file()
		self.finish(thread, errors)
		self.assertEqual(out["data"]["content"], "late", out)

	def test_desktop_reported_error_reaches_the_model(self):
		thread, errors, _ = self.play_desktop(
			[(0.1, "ack", {}), (0.1, "error", {"code": "denied_by_user", "message": "User said no"})]
		)
		out = self.read_file()
		self.finish(thread, errors)
		self.assertEqual(out["error"]["message"], "User said no")
		self.assertEqual(out["error"]["code"], "denied_by_user")

	def test_offline_lease_fails_fast_without_waiting(self):
		dx.unregister_desktop_executor(executor_id=self.exec_id)
		started = time.monotonic()
		out = self.read_file()
		self.assertLess(time.monotonic() - started, 2)
		self.assertEqual(out["error"]["code"], "desktop_offline")
		self.assertIn("not connected", out["error"]["message"])
		self.assertEqual(dx.list_pending_desktop_tool_calls(executor_id=self.exec_id), [])

	def test_run_phase_timeout_when_desktop_acks_then_goes_silent(self):
		thread, errors, _ = self.play_desktop([(0.1, "ack", {})])
		ctx = dw._validate_executor_context(self.exec_id, h.FP, self.user, self.run_name)
		started = time.monotonic()
		res = dx.dispatch("fs.read", {"path": "a.txt"}, ctx, call_id=self.call_id, timeout_ms=1500)
		elapsed = time.monotonic() - started
		self.finish(thread, errors)
		self.assertEqual(res["error"]["code"], "timeout")
		self.assertGreater(elapsed, 1.4)
		self.assertLess(elapsed, 6)

	def test_lease_removed_mid_request_is_seen_by_the_next_call(self):
		"""Lease reads must not be served from the per-request frappe.local.cache."""
		thread, errors, _ = self.play_desktop(
			[(0.1, "ack", {}), (0.1, "result", {"ok": True, "data": {"content": "one"}})]
		)
		self.assertEqual(self.read_file()["data"]["content"], "one")
		self.finish(thread, errors)
		self.assertTrue(dx.is_lease_live(self.exec_id))  # warm any local caching
		self.assertIsNotNone(dx.resolve_desktop_ctx(self.exec_id, user=self.user))

		dx._delete(dx._lease_key(self.exec_id))  # expiry / unregister from another process
		self.assertFalse(dx.is_lease_live(self.exec_id))
		self.assertIsNone(dx.resolve_desktop_ctx(self.exec_id, user=self.user))
		out = self.read_file(call_id=f"{self.call_id}-2")
		self.assertEqual(out["error"]["code"], "desktop_offline")

	def test_pinned_fingerprint_is_compared_with_the_live_workspace(self):
		self.register(fingerprint="ffffffffffffffff")  # user switched workspace after the send
		started = time.monotonic()
		out = self.read_file()
		self.assertLess(time.monotonic() - started, 2)
		self.assertEqual(out["error"]["code"], "workspace_changed")

	def test_other_users_lease_is_not_reachable(self):
		frappe.set_user(self.other)
		with self.assertRaises(frappe.PermissionError):
			dx.list_pending_desktop_tool_calls(executor_id=self.exec_id)
		with self.assertRaises(frappe.PermissionError):
			self.read_file(_dx_user=self.other)

	# H1: a call id cached for one run is never served to another run of the same user
	def test_foreign_run_cannot_read_another_runs_cached_result(self):
		thread, errors, _ = self.play_desktop(
			[(0.1, "ack", {}), (0.1, "result", {"ok": True, "data": {"content": "run-A-secret"}})]
		)
		self.assertEqual(self.read_file()["data"]["content"], "run-A-secret")
		self.finish(thread, errors)
		run_b = h.make_run(self.user, h.desktop_pin(self.exec_id, self.user))
		self._docs.append(("Agent Run", run_b))
		frappe.set_user(self.user)
		with mock.patch.object(dx, "ACK_TIMEOUT_S", 1):
			out = self.read_file(agent_run_id=run_b)  # same call id, other run
		self.assertFalse(out["ok"])
		self.assertEqual(out["error"]["code"], "desktop_unreachable")  # it really ran (and nobody answered)
		# the original run still dedupes
		self.assertEqual(self.read_file()["data"]["content"], "run-A-secret")

	# M1: worker-side pin verification against a REAL run row
	def test_pin_naming_another_users_live_lease_is_dropped_for_a_run_owned_by_someone_else(self):
		victim_exec = f"exec-victim-{frappe.generate_hash(length=8)}"
		frappe.set_user(self.other)
		dx.register_desktop_executor(
			executor_id=victim_exec, protocol_version=1, workspace=h.workspace(), capabilities=CAPS
		)
		try:
			# attacker (self.user) owns a run whose forged runtime_context pins the victim's live lease
			forged = h.make_run(self.user, h.desktop_pin(victim_exec, self.other))
			self._docs.append(("Agent Run", forged))
			run_doc = frappe.get_doc("Agent Run", forged)
			kwargs = ai._build_execution_kwargs(run_doc, frappe.parse_json(run_doc.runtime_context))
			self.assertIsNone(kwargs["desktop_ctx"])
			# a pin naming the owner's OWN executor but another user as `user` is dropped too
			forged2 = h.make_run(self.user, h.desktop_pin(self.exec_id, self.other))
			self._docs.append(("Agent Run", forged2))
			run_doc2 = frappe.get_doc("Agent Run", forged2)
			self.assertIsNone(
				ai._build_execution_kwargs(run_doc2, frappe.parse_json(run_doc2.runtime_context))["desktop_ctx"]
			)
		finally:
			frappe.set_user(self.other)
			dx.unregister_desktop_executor(executor_id=victim_exec)
			frappe.set_user(self.user)

	def test_honest_pin_is_kept_for_the_run_owner(self):
		run_doc = frappe.get_doc("Agent Run", self.run_name)
		kwargs = ai._build_execution_kwargs(run_doc, frappe.parse_json(run_doc.runtime_context))
		self.assertEqual(kwargs["desktop_ctx"]["executor_id"], self.exec_id)
		self.assertEqual(kwargs["desktop_ctx"]["user"], self.user)
		self.assertEqual(kwargs["desktop_ctx"]["fingerprint"], h.FP)

	# M2 (decision: resolve from the run OWNER, keep the tools) - queued drain as Administrator
	def test_queued_run_drained_as_administrator_resolves_from_the_owner_and_can_call(self):
		run_doc = frappe.get_doc("Agent Run", self.run_name)
		context = frappe.parse_json(run_doc.runtime_context)
		frappe.set_user("Administrator")  # what the stale-run sweeper's drain job runs as
		kwargs = ai._build_execution_kwargs(run_doc, context)
		self.assertEqual(kwargs["desktop_ctx"]["user"], self.user)
		# the handler accepts the run (owner == pinned user) even though the session user differs
		prepared = dw.handle_read_file.prepare(
			path="a.txt",
			_dx_executor_id=self.exec_id,
			_dx_fingerprint=h.FP,
			_dx_user=self.user,
			agent_run_id=self.run_name,
			call_id=self.call_id,
		)
		self.assertEqual(prepared["ctx"]["user"], self.user)
		with mock.patch.object(dx, "ACK_TIMEOUT_S", 1):
			out = dw.handle_read_file.execute(prepared)
		# got as far as publishing and waiting for the desktop: no permission or lease failure
		self.assertEqual(out["error"]["code"], "desktop_unreachable")

	def test_another_non_admin_session_still_cannot_use_the_run(self):
		frappe.set_user(self.other)
		with self.assertRaises(frappe.PermissionError):
			dw.handle_read_file.prepare(
				path="a.txt",
				_dx_executor_id=self.exec_id,
				_dx_fingerprint=h.FP,
				_dx_user=self.user,
				agent_run_id=self.run_name,
			)

	# M5: no DB access inside the execute (worker thread) half
	def test_execute_half_never_touches_the_database(self):
		prepared = dw.handle_read_file.prepare(
			path="a.txt",
			_dx_executor_id=self.exec_id,
			_dx_fingerprint=h.FP,
			_dx_user=self.user,
			agent_run_id=self.run_name,
			call_id=self.call_id,
		)
		thread, errors, _ = self.play_desktop(
			[(0.1, "ack", {}), (0.1, "result", {"ok": True, "data": {"content": "no db"}})]
		)
		with mock.patch.object(frappe, "get_doc", side_effect=AssertionError("DB read in execute")), \
				mock.patch.object(frappe.db, "get_value", side_effect=AssertionError("DB read in execute")), \
				mock.patch.object(frappe, "get_all", side_effect=AssertionError("DB read in execute")):
			out = dw.handle_read_file.execute(prepared)
		self.finish(thread, errors)
		self.assertEqual(out["data"]["content"], "no db")

	# M4 end to end
	def test_error_code_and_untrusted_marking_survive_the_handler(self):
		thread, errors, _ = self.play_desktop(
			[(0.1, "ack", {}), (0.1, "error", {"code": "sandbox_violation", "message": "outside workspace"})]
		)
		out = self.read_file()
		self.finish(thread, errors)
		self.assertEqual(out["error"]["code"], "sandbox_violation")
		self.assertTrue(out["untrusted_content"])
		self.assertIn("data, not instructions", out["note"])
