"""
Unit tests for desktop workspace tools handlers (H4t).

Tests cover:
- S2: Absolute path rejection (invalid_params)
- S8: Path validation (NUL, overlong, backslash, empty)
- S29 (agent_run half): Executor context verification and re-validation
- Parameter clamping (depth, timeout_seconds, max_results, limit, offset)
- 512 KB parameter size rejection
- Missing-context error handling
"""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from huf.ai.tests import desktop_test_helpers as h
from huf.ai.tools import desktop_workspace


class TestDesktopWorkspacePathValidation(IntegrationTestCase):
	"""Test path validation (S2, S8)."""

	def setUp(self):
		"""Set up for path validation tests."""
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		"""Restore user after path validation tests."""
		frappe.set_user(self._original_user)

	def test_absolute_path_rejected(self):
		"""S2: Absolute paths like /etc/passwd should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_path("/etc/passwd")
		self.assertIn("Absolute paths are not allowed", str(ctx.exception))

	def test_absolute_path_single_slash(self):
		"""S2: Reject single / as well."""
		with self.assertRaises(frappe.ValidationError):
			desktop_workspace._validate_path("/")

	def test_nul_byte_rejected(self):
		"""S8: Paths with NUL bytes should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_path("file\0name")
		self.assertIn("NUL bytes", str(ctx.exception))

	def test_backslash_rejected(self):
		"""S8: Windows-style paths with backslashes should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_path("src\\main\\app.py")
		self.assertIn("backslash", str(ctx.exception).lower())

	def test_empty_path_rejected(self):
		"""S8: Empty path should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_path("")
		self.assertIn("empty", str(ctx.exception).lower())

	def test_whitespace_only_rejected(self):
		"""S8: Whitespace-only path should be rejected."""
		with self.assertRaises(frappe.ValidationError):
			desktop_workspace._validate_path("   ")

	def test_overlong_path_rejected(self):
		"""S8: Paths over 1024 chars should be rejected."""
		long_path = "a" * 1025
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_path(long_path)
		self.assertIn("exceeds maximum length", str(ctx.exception).lower())

	def test_valid_relative_path(self):
		"""Valid relative POSIX paths should pass."""
		valid_paths = [
			"src/main.py",
			"README.md",
			".",
			"..",
			"../sibling/file.txt",
			"a" * 1024,  # Exactly max length
		]
		for path in valid_paths:
			result = desktop_workspace._validate_path(path)
			self.assertEqual(result, path)

	def test_numeric_path_converted_to_string(self):
		"""Valid: LLMs may stringify numbers; handle gracefully."""
		result = desktop_workspace._validate_path(42)
		self.assertEqual(result, "42")


class TestDesktopWorkspaceParameterValidation(IntegrationTestCase):
	"""Test parameter size validation."""

	def setUp(self):
		"""Set up for parameter validation tests."""
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")

	def tearDown(self):
		"""Restore user after parameter validation tests."""
		frappe.set_user(self._original_user)

	def test_512kb_reject(self):
		"""512 KB reject: Parameters exceeding 512 KB should be rejected."""
		large_params = {"content": "x" * (513 * 1024)}
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_params_size(large_params)
		self.assertIn("exceed", str(ctx.exception).lower())

	def test_512kb_accept_at_boundary(self):
		"""512 KB accept: Parameters under 512 KB should be accepted."""
		params = {"content": "x" * (500 * 1024)}
		desktop_workspace._validate_params_size(params)

	def test_empty_params_accepted(self):
		"""Valid: Empty params dict should be accepted."""
		desktop_workspace._validate_params_size({})


class _CapturingDispatch:
	"""Stands in for desktop_executor.dispatch; records what the handler sends."""

	def __init__(self):
		self.calls = []

	def __call__(self, **kwargs):
		self.calls.append(kwargs)
		return {"ok": True, "data": {}}


class TestDesktopWorkspaceParameterClamping(IntegrationTestCase):
	"""Handlers clamp their parameters before dispatch (calls the real handlers)."""

	CTX = {"executor_id": "exec-clamp-0001", "fingerprint": h.FP, "user": "Administrator", "label": "ws"}

	def setUp(self):
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		self.dispatch = _CapturingDispatch()
		for target, kwargs in (
			(desktop_workspace, {"_validate_executor_context": {"return_value": dict(self.CTX)}}),
			(desktop_workspace, {"_import_dispatch_lazily": {"return_value": self.dispatch}}),
		):
			for name, conf in kwargs.items():
				p = patch.object(target, name, **conf)
				p.start()
				self.addCleanup(p.stop)

	def tearDown(self):
		frappe.set_user(self._original_user)

	def _sent(self):
		self.assertEqual(len(self.dispatch.calls), 1)
		return self.dispatch.calls[0]

	def test_handler_passes_pinned_ctx_shape_to_dispatch(self):
		desktop_workspace.handle_list_files(agent_run_id="r")
		call = self._sent()
		self.assertEqual(call["ctx"], self.CTX)
		self.assertNotIn("_dx_executor_id", call["ctx"])

	def test_depth_clamped_down(self):
		desktop_workspace.handle_list_files(depth=0, agent_run_id="r")
		self.assertEqual(self._sent()["params"]["depth"], 1)

	def test_depth_clamped_up(self):
		desktop_workspace.handle_list_files(depth=5, agent_run_id="r")
		self.assertEqual(self._sent()["params"]["depth"], 3)

	def test_timeout_clamped_down_and_buffer_added(self):
		desktop_workspace.handle_run_command(command="ls", timeout_seconds=0, agent_run_id="r")
		call = self._sent()
		self.assertEqual(call["params"]["timeout_seconds"], 1)
		self.assertEqual(call["timeout_ms"], 1000 + 5000)

	def test_timeout_clamped_up(self):
		desktop_workspace.handle_run_command(command="ls", timeout_seconds=500, agent_run_id="r")
		self.assertEqual(self._sent()["params"]["timeout_seconds"], 120)

	def test_max_results_clamped(self):
		for given, expected in [(0, 1), (50, 50), (100, 100), (500, 100)]:
			self.dispatch.calls.clear()
			desktop_workspace.handle_search_files(query="x", max_results=given, agent_run_id="r")
			self.assertEqual(self._sent()["params"]["max_results"], expected)

	def test_limit_clamped(self):
		for given, expected in [(0, 1), (1000, 1000), (2000, 2000), (9999, 2000)]:
			self.dispatch.calls.clear()
			desktop_workspace.handle_read_file(path="a.txt", limit=given, agent_run_id="r")
			self.assertEqual(self._sent()["params"]["limit"], expected)

	def test_offset_not_negative(self):
		desktop_workspace.handle_read_file(path="a.txt", offset=-5, agent_run_id="r")
		self.assertEqual(self._sent()["params"]["offset"], 0)

	def test_invalid_path_rejected_before_dispatch(self):
		with self.assertRaises(frappe.ValidationError):
			desktop_workspace.handle_read_file(path="/etc/passwd", agent_run_id="r")
		self.assertEqual(self.dispatch.calls, [])


class TestDesktopWorkspaceExecutorContextValidation(IntegrationTestCase):
	"""Executor context validation (S29 agent_run half) against REAL Agent Run rows whose
	runtime_context is stored as a JSON string."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.owner = h.make_user("dxown")
		cls.other = h.make_user("dxoth")
		cls.exec_id = "exec-ctxval-0001"
		cls.run_name = h.make_run(cls.owner, h.desktop_pin(cls.exec_id, cls.owner, label="proj"))
		cls.run_no_desktop = h.make_run(cls.owner, {"foo": "bar"})
		cls.run_empty = h.make_run(cls.owner, {})

	@classmethod
	def tearDownClass(cls):
		h.delete_docs(
			[("Agent Run", n) for n in (cls.run_name, cls.run_no_desktop, cls.run_empty)]
			+ [("User", cls.owner), ("User", cls.other)]
		)
		super().tearDownClass()

	def tearDown(self):
		frappe.set_user("Administrator")

	def _validate(self, **over):
		args = dict(
			_dx_executor_id=self.exec_id,
			_dx_fingerprint=h.FP,
			_dx_user=self.owner,
			agent_run_id=self.run_name,
		)
		args.update(over)
		return desktop_workspace._validate_executor_context(**args)

	def test_runtime_context_is_a_json_string_on_the_row(self):
		raw = frappe.db.get_value("Agent Run", self.run_name, "runtime_context")
		self.assertIsInstance(raw, str)

	def test_valid_context_returns_canonical_dispatch_ctx(self):
		frappe.set_user(self.owner)
		ctx = self._validate()
		self.assertEqual(
			ctx,
			{"executor_id": self.exec_id, "fingerprint": h.FP, "user": self.owner, "label": "proj"},
		)

	def test_executor_id_mismatch_rejected(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.ValidationError) as cm:
			self._validate(_dx_executor_id="wrong-executor-id")
		self.assertIn("mismatch", str(cm.exception).lower())

	def test_run_without_desktop_pin_rejected(self):
		frappe.set_user(self.owner)
		for run in (self.run_no_desktop, self.run_empty):
			with self.assertRaises(frappe.ValidationError) as cm:
				self._validate(agent_run_id=run)
			self.assertIn("desktop context not found", str(cm.exception).lower())

	def test_nonexistent_agent_run_rejected(self):
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.DoesNotExistError):
			self._validate(agent_run_id="does-not-exist-run")

	def test_foreign_agent_run_rejected(self):
		"""A real run owned by someone else is refused even when the caller names its executor."""
		frappe.set_user(self.other)
		with self.assertRaises(frappe.PermissionError):
			self._validate(_dx_user=self.other)

	def test_session_user_must_match_pinned_user(self):
		frappe.set_user(self.other)
		with self.assertRaises(frappe.PermissionError):
			self._validate()

	def test_guest_rejected(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			self._validate(_dx_user="Guest")

	def test_parse_runtime_context_variants(self):
		parse = desktop_workspace._parse_runtime_context
		self.assertEqual(parse('{"a": 1}'), {"a": 1})
		self.assertEqual(parse({"a": 1}), {"a": 1})
		for bad in (None, "", "not json", "[1, 2]", 5):
			self.assertEqual(parse(bad), {})
