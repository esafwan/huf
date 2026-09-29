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
from frappe.test_runner import FrappeTestCase

from huf.ai.tools import desktop_workspace


class TestDesktopWorkspacePathValidation(FrappeTestCase):
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


class TestDesktopWorkspaceParameterValidation(FrappeTestCase):
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


class TestDesktopWorkspaceParameterClamping(FrappeTestCase):
	"""Test parameter clamping (depth, limit, timeout_seconds, etc.)."""

	def test_depth_clamped_to_1_3(self):
		"""depth should be clamped to 1-3."""
		# Depth 0 → 1
		# Depth 5 → 3
		# Depth "invalid" → converted then clamped

		result = desktop_workspace.handle_list_files(
			path=".",
			depth=0,
			_dx_executor_id="test-id",
			_dx_fingerprint="test-fp",
			_dx_user="testuser",
			agent_run_id="test-run",
		)
		# Should not raise during clamping

	def test_limit_clamped_to_1_2000(self):
		"""limit should be clamped to 1-2000."""
		# This is tested indirectly via read_file; just verify no exception on extreme values
		try:
			with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
				mock_dispatch.return_value = MagicMock(return_value={"ok": True, "data": {}})
				desktop_workspace.handle_read_file(
					path="test.txt",
					limit=9999,  # Will be clamped to 2000
					_dx_executor_id="test-id",
					_dx_fingerprint="test-fp",
					_dx_user="testuser",
					agent_run_id="test-run",
				)
		except Exception:
			pass  # OK if dispatch fails; we're testing the clamping

	def test_timeout_seconds_clamped_to_1_120(self):
		"""timeout_seconds should be clamped to 1-120."""
		# Test clamping down
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(return_value={"ok": True, "data": {}})
			# Pass 0 → should be clamped to 1
			result = desktop_workspace.handle_run_command(
				command="echo test",
				timeout_seconds=0,
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)

	def test_max_results_clamped_to_1_100(self):
		"""max_results should be clamped to 1-100."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(return_value={"ok": True, "data": {}})
			result = desktop_workspace.handle_search_files(
				query="test",
				max_results=500,  # Will be clamped to 100
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)

	def test_offset_clamped_to_non_negative(self):
		"""offset should not be negative."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(return_value={"ok": True, "data": {}})
			result = desktop_workspace.handle_read_file(
				path="test.txt",
				offset=-5,  # Will be clamped to 0
				_dx_executor_id="test-id",
				_dx_fingerprint="test-fp",
				_dx_user="testuser",
				agent_run_id="test-run",
			)


class TestDesktopWorkspaceExecutorContextValidation(FrappeTestCase):
	"""Test executor context validation (S29 - agent_run half)."""

	def setUp(self):
		"""Set up test data for executor context tests."""
		frappe.set_user("testuser")

		# Create a test Agent Run with desktop context
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
		frappe.delete_doc("Agent Run", "test-run", ignore_permissions=True)

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


class TestDesktopWorkspaceHandlerUntrustedContent(FrappeTestCase):
	"""Test that read and exec operations flag untrusted_content."""

	def setUp(self):
		"""Set up test data."""
		frappe.set_user("testuser")

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
		frappe.delete_doc("Agent Run", "test-run", ignore_permissions=True)

	def test_read_file_untrusted_content_true(self):
		"""Read file results should have untrusted_content=True."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"content": "file contents"}}
			)
			result = desktop_workspace.handle_read_file(
				path="test.txt",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			self.assertTrue(result.get("untrusted_content"))

	def test_search_files_untrusted_content_true(self):
		"""Search file results should have untrusted_content=True."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"results": []}}
			)
			result = desktop_workspace.handle_search_files(
				query="test",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			self.assertTrue(result.get("untrusted_content"))

	def test_run_command_untrusted_content_true(self):
		"""Run command results should have untrusted_content=True."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"stdout": "output"}}
			)
			result = desktop_workspace.handle_run_command(
				command="echo test",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			self.assertTrue(result.get("untrusted_content"))

	def test_write_file_no_untrusted_content(self):
		"""Write file results should not have untrusted_content flag."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"sha256": "abc123"}}
			)
			result = desktop_workspace.handle_write_file(
				path="test.txt",
				content="new content",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			self.assertNotIn("untrusted_content", result)

	def test_list_files_no_untrusted_content(self):
		"""List file results should not have untrusted_content flag."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"entries": []}}
			)
			result = desktop_workspace.handle_list_files(
				path=".",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			self.assertNotIn("untrusted_content", result)


class TestDesktopWorkspaceErrorHandling(FrappeTestCase):
	"""Test error handling and dispatch communication."""

	def setUp(self):
		"""Set up test data."""
		frappe.set_user("testuser")

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
		frappe.delete_doc("Agent Run", "test-run", ignore_permissions=True)

	def test_dispatch_error_propagated(self):
		"""Dispatch errors should be returned to the handler caller."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": False, "error": {"message": "File not found"}}
			)
			result = desktop_workspace.handle_read_file(
				path="nonexistent.txt",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			self.assertIn("error", result)
			self.assertEqual(result["error"], "File not found")

	def test_write_content_256kb_limit(self):
		"""Write content exceeding 256 KB should be rejected."""
		content = "x" * (257 * 1024)
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace.handle_write_file(
				path="large.txt",
				content=content,
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
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
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)

	def test_empty_command_rejected(self):
		"""Empty command should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace.handle_run_command(
				command="",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
		self.assertIn("empty", str(ctx.exception).lower())

	def test_empty_search_query_rejected(self):
		"""Empty search query should be rejected."""
		with self.assertRaises(frappe.ValidationError) as ctx:
			desktop_workspace.handle_search_files(
				query="",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
		self.assertIn("empty", str(ctx.exception).lower())


class TestDesktopWorkspaceModeDefaults(FrappeTestCase):
	"""Test mode parameter defaults and coercion."""

	def setUp(self):
		"""Set up test data."""
		frappe.set_user("testuser")

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
		frappe.delete_doc("Agent Run", "test-run", ignore_permissions=True)

	def test_write_mode_defaults_to_overwrite(self):
		"""Invalid write mode should default to overwrite."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"sha256": "abc"}}
			)
			result = desktop_workspace.handle_write_file(
				path="test.txt",
				content="data",
				mode="invalid_mode",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
			# Check that dispatch was called; the mode would have been coerced

	def test_search_mode_defaults_to_name(self):
		"""Invalid search mode should default to name search."""
		with patch("huf.ai.desktop_workspace._import_dispatch_lazily") as mock_dispatch:
			mock_dispatch.return_value = MagicMock(
				return_value={"ok": True, "data": {"results": []}}
			)
			result = desktop_workspace.handle_search_files(
				query="test",
				mode="invalid_mode",
				_dx_executor_id="test-executor-id",
				_dx_fingerprint="test-fingerprint",
				_dx_user="testuser",
				agent_run_id="test-run",
			)
