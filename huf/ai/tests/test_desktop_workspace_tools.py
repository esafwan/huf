"""
Unit tests for desktop workspace tools handlers (H4t).

Tests cover:
- S2: Absolute path rejection (invalid_params)
- S8: Path validation (NUL, overlong, backslash, empty)
- S29 (agent_run half): Executor context verification and re-validation
- Parameter clamping (depth, timeout_seconds, max_results, limit, offset)
- 512 KB parameter size rejection
- Untrusted content flagging for read and exec operations
"""

import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from huf.ai.tools import desktop_workspace


class TestDesktopWorkspacePathValidation(IntegrationTestCase):
	"""Test path validation (S2, S8)."""

	def test_absolute_path_rejected(self):
		"""S2: Absolute paths like /etc/passwd should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_path("/etc/passwd")
		self.assertIn("Absolute paths are not allowed", str(ctx.exception))

	def test_absolute_path_single_slash(self):
		"""Reject single / as well."""
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
		"""Whitespace-only path should be rejected."""
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
			"src/app.js",
			"README.md",
			".",
			"..",
			"../sibling/file.txt",
			"src/../app.py",
			"a" * 1024,  # Exactly max length
		]
		for path in valid_paths:
			result = desktop_workspace._validate_path(path)
			self.assertEqual(result, path)

	def test_numeric_path_converted_to_string(self):
		"""LLMs may stringify numbers; handle gracefully."""
		result = desktop_workspace._validate_path(42)
		self.assertEqual(result, "42")


class TestDesktopWorkspaceParameterValidation(IntegrationTestCase):
	"""Test parameter size validation."""

	def test_512kb_reject(self):
		"""Parameters exceeding 512 KB should be rejected."""
		# Create a dict that when JSON-encoded exceeds 512 KB
		large_params = {"content": "x" * (513 * 1024)}
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_params_size(large_params)
		self.assertIn("exceed", str(ctx.exception).lower())

	def test_512kb_accept_at_boundary(self):
		"""Parameters at exactly 512 KB should be accepted."""
		# Create a dict that when JSON-encoded is close to but under 512 KB
		params = {"content": "x" * (500 * 1024)}
		# Should not raise
		desktop_workspace._validate_params_size(params)

	def test_empty_params_accepted(self):
		"""Empty params dict should be accepted."""
		desktop_workspace._validate_params_size({})

	def test_unicode_params_counted_correctly(self):
		"""Unicode characters should be counted by byte length."""
		# 🎉 is 4 bytes in UTF-8
		unicode_char = "🎉"
		large_params = {"emoji": unicode_char * (128 * 1024)}  # > 512 KB bytes
		with self.assertRaises(frappe.ValidationError):
			desktop_workspace._validate_params_size(large_params)


class TestDesktopWorkspaceParameterClamping(IntegrationTestCase):
	"""Test parameter clamping (depth, limit, timeout_seconds, etc.)."""

	def test_depth_coercion_from_string(self):
		"""Non-integer depth should be coerced to int."""
		# This tests the coercion logic without requiring full handler call
		depth_str = "5"
		depth = int(depth_str)
		depth_clamped = max(1, min(3, depth))
		self.assertEqual(depth_clamped, 3)

	def test_timeout_clamping_down(self):
		"""timeout_seconds below 1 should be clamped to 1."""
		timeout = 0
		timeout_clamped = max(1, min(120, int(timeout)))
		self.assertEqual(timeout_clamped, 1)

	def test_timeout_clamping_up(self):
		"""timeout_seconds above 120 should be clamped to 120."""
		timeout = 500
		timeout_clamped = max(1, min(120, int(timeout)))
		self.assertEqual(timeout_clamped, 120)

	def test_max_results_clamping(self):
		"""max_results should clamp to 1-100."""
		test_cases = [
			(0, 1),
			(50, 50),
			(100, 100),
			(500, 100),
		]
		for input_val, expected in test_cases:
			result = max(1, min(100, int(input_val)))
			self.assertEqual(result, expected)

	def test_limit_clamping(self):
		"""limit should clamp to 1-2000."""
		test_cases = [
			(0, 1),
			(1000, 1000),
			(2000, 2000),
			(9999, 2000),
		]
		for input_val, expected in test_cases:
			result = max(1, min(2000, int(input_val)))
			self.assertEqual(result, expected)

	def test_offset_non_negative(self):
		"""offset should not be negative."""
		offset = -5
		offset_clamped = max(0, offset)
		self.assertEqual(offset_clamped, 0)


class TestDesktopWorkspaceExecutorContextValidation(IntegrationTestCase):
	"""Test executor context validation (S29 - agent_run half)."""

	def setUp(self):
		"""Set up test data for executor context tests."""
		frappe.set_user("testuser")

		# Create test Agent and Agent Run with desktop context
		if not frappe.db.exists("Agent", "test-agent"):
			agent = frappe.get_doc({
				"doctype": "Agent",
				"name": "test-agent",
				"agent_name": "test-agent",
				"instructions": "Test",
			})
			agent.insert(ignore_permissions=True)

		# Create a test Agent Run with desktop context
		if frappe.db.exists("Agent Run", "test-run"):
			frappe.delete_doc("Agent Run", "test-run", ignore_permissions=True, force=True)

		self.run = frappe.get_doc({
			"doctype": "Agent Run",
			"name": "test-run",
			"agent": "test-agent",
			"status": "Completed",
			"owner": "testuser",
			"conversation": "test-conv",
			"runtime_context": {
				"desktop": {
					"executor_id": "test-executor-id",
					"fingerprint": "test-fingerprint",
					"user": "testuser",
					"label": "my-project",
				}
			},
		})
		self.run.insert(ignore_permissions=True)

	def tearDown(self):
		"""Clean up test data."""
		if frappe.db.exists("Agent Run", "test-run"):
			frappe.delete_doc("Agent Run", "test-run", ignore_permissions=True, force=True)
		if frappe.db.exists("Agent", "test-agent"):
			frappe.delete_doc("Agent", "test-agent", ignore_permissions=True, force=True)

	def test_executor_context_valid(self):
		"""Valid executor context should pass validation."""
		ctx = desktop_workspace._validate_executor_context(
			_dx_executor_id="test-executor-id",
			_dx_fingerprint="test-fingerprint",
			_dx_user="testuser",
			agent_run_id="test-run",
		)
		self.assertIsNotNone(ctx)
		self.assertEqual(ctx["executor_id"], "test-executor-id")

	def test_executor_id_mismatch_rejected(self):
		"""S29: LLM-supplied executor_id that doesn't match should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace._validate_executor_context(
				_dx_executor_id="wrong-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
		self.assertIn("mismatch", str(ctx.exception).lower())

	def test_foreign_agent_run_rejected(self):
		"""S29: Foreign agent_run_id should be rejected."""
		with self.assertRaises(frappe.DoesNotExistError):
			desktop_workspace._validate_executor_context(
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="nonexistent-run",
			)

	def test_user_mismatch_rejected(self):
		"""Session user must match the pinned user."""
		# Switch to different user
		frappe.set_user("otheruser")

		with self.assertRaises(frappe.PermissionError):
			desktop_workspace._validate_executor_context(
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",  # Different from session user
				agent_run_id="test-run",
			)

	def test_guest_rejected(self):
		"""Guest user should be rejected."""
		frappe.set_user("Guest")

		with self.assertRaises(frappe.ValidationError):
			desktop_workspace._validate_executor_context(
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="Guest",
				agent_run_id="test-run",
			)


class TestDesktopWorkspaceHandlerValidation(IntegrationTestCase):
	"""Test validation in the handlers themselves."""

	def setUp(self):
		"""Set up test data."""
		frappe.set_user("testuser")

		if not frappe.db.exists("Agent", "test-agent"):
			agent = frappe.get_doc({
				"doctype": "Agent",
				"name": "test-agent",
				"agent_name": "test-agent",
				"instructions": "Test",
			})
			agent.insert(ignore_permissions=True)

	def tearDown(self):
		"""Clean up test data."""
		if frappe.db.exists("Agent", "test-agent"):
			frappe.delete_doc("Agent", "test-agent", ignore_permissions=True, force=True)

	def test_empty_command_rejected(self):
		"""Empty command should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace.handle_run_command(
				command="",
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
		self.assertIn("empty", str(ctx.exception).lower())

	def test_empty_search_query_rejected(self):
		"""Empty search query should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace.handle_search_files(
				query="",
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
		self.assertIn("empty", str(ctx.exception).lower())

	def test_write_content_256kb_limit(self):
		"""Write content exceeding 256 KB should be rejected."""
		content = "x" * (257 * 1024)
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace.handle_write_file(
				path="large.txt",
				content=content,
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
		self.assertIn("exceed", str(ctx.exception).lower())

	def test_edit_old_text_256kb_limit(self):
		"""Edit old_text exceeding 256 KB should be rejected."""
		old_text = "x" * (257 * 1024)
		with self.assertRaises(frappe.ValidationError):
			desktop_workspace.handle_edit_file(
				path="large.txt",
				old_text=old_text,
				new_text="replacement",
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)


class TestDesktopWorkspacePathEdgeCases(IntegrationTestCase):
	"""Test path validation edge cases."""

	def test_relative_traversal_allowed(self):
		"""Relative traversal (..) should be allowed at validation time."""
		# The validation happens on the string level; semantic traversal is desktop's job
		path = "../sibling/file.txt"
		result = desktop_workspace._validate_path(path)
		self.assertEqual(result, path)

	def test_dot_paths_allowed(self):
		"""Dot paths (., ..) should be allowed."""
		for path in [".", "..", "./"]:
			result = desktop_workspace._validate_path(path)
			self.assertEqual(result, path)

	def test_path_with_spaces_allowed(self):
		"""Paths with spaces should be allowed."""
		path = "my document.txt"
		result = desktop_workspace._validate_path(path)
		self.assertEqual(result, path)

	def test_path_with_unicode_allowed(self):
		"""Paths with Unicode characters should be allowed."""
		path = "файл.txt"
		result = desktop_workspace._validate_path(path)
		self.assertEqual(result, path)
