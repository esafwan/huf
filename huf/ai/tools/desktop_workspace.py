"""
Desktop workspace tools — 10 handlers for file operations and command execution
on the user's local machine via Huf Desktop.

All paths are workspace-relative POSIX strings. Parameter validation rejects
absolute paths, backslashes, NUL bytes, and paths over 1024 chars. Total params
must not exceed 512 KB. Results for read and exec operations are flagged as
untrusted content.

The handlers verify the pinned executor context (_dx_executor_id, _dx_fingerprint,
_dx_user) matches the current run, then call desktop_executor.dispatch with the
run's pinned ctx {executor_id, fingerprint, user, label}.

See PLAN.md §3.7-3.8 for limits and specifications.
"""

import json
from typing import Any

import frappe
from frappe import _

# Limits from the spec (§3.7)
MAX_PATH_LENGTH = 1024
MAX_PARAMS_BYTES = 512 * 1024  # 512 KB
MAX_WRITE_CONTENT_BYTES = 256 * 1024  # 256 KB
MAX_FS_TIMEOUT_MS = 20000
DEFAULT_EXEC_TIMEOUT_SECONDS = 60
MIN_EXEC_TIMEOUT_SECONDS = 1
MAX_EXEC_TIMEOUT_SECONDS = 120


def _validate_path(path: str) -> str:
	"""Validate a workspace-relative POSIX path.

	Rejects:
	- Absolute paths (starting with /)
	- Paths with backslashes (Windows-style)
	- Paths with NUL bytes
	- Paths longer than 1024 chars
	- Empty paths

	Converts to string to handle LLM stringification of numbers.
	"""
	path = str(path or "").strip()

	if not path:
		frappe.throw(_("Path cannot be empty."))

	if len(path) > MAX_PATH_LENGTH:
		frappe.throw(
			_("Path exceeds maximum length of {0} characters.").format(MAX_PATH_LENGTH)
		)

	if path.startswith("/"):
		frappe.throw(_("Absolute paths are not allowed. Use workspace-relative paths."))

	if "\\" in path:
		frappe.throw(_("Windows-style paths (backslashes) are not allowed. Use forward slashes."))

	if "\0" in path:
		frappe.throw(_("Paths with NUL bytes are not allowed."))

	return path


def _validate_params_size(params: dict) -> None:
	"""Reject if total params exceed 512 KB."""
	try:
		params_json = json.dumps(params)
		if len(params_json.encode("utf-8")) > MAX_PARAMS_BYTES:
			frappe.throw(
				_("Parameters exceed maximum size of {0} KB.").format(
					MAX_PARAMS_BYTES // 1024
				)
			)
	except Exception as e:
		if "exceed" not in str(e).lower():
			frappe.log_error(title="desktop_workspace: param size validation error")
		raise


def _parse_runtime_context(value) -> dict:
	"""Parse ``Agent Run.runtime_context`` (JSON string, dict, or empty) into a dict."""
	if isinstance(value, dict):
		return value
	if not value or not isinstance(value, (str, bytes)):
		return {}
	try:
		parsed = frappe.parse_json(value)
	except Exception:
		return {}
	return parsed if isinstance(parsed, dict) else {}


def _validate_executor_context(
	_dx_executor_id: str,
	_dx_fingerprint: str,
	_dx_user: str,
	agent_run_id: str,
) -> dict:
	"""Verify that the pinned executor context belongs to this run.

	Reads the Agent Run to confirm:
	- runtime_context.desktop.executor_id matches _dx_executor_id
	- The run owner is _dx_user
	- The session user is _dx_user

	Returns the canonical dispatch ctx ``{executor_id, fingerprint, user, label}``
	built from the run's pinned desktop context.
	"""
	if frappe.session.user == "Guest":
		frappe.throw(_("Desktop tools are not available in guest sessions."))

	if frappe.session.user != _dx_user:
		frappe.throw(
			_("Executor belongs to a different user."),
			frappe.PermissionError,
		)

	# Load the run to verify ownership and executor context
	try:
		run = frappe.get_doc("Agent Run", agent_run_id)
	except frappe.DoesNotExistError:
		frappe.throw(_("Agent run not found."), frappe.DoesNotExistError)

	if run.owner != _dx_user:
		frappe.throw(
			_("Agent run belongs to a different user."),
			frappe.PermissionError,
		)

	# runtime_context is a JSON field: usually a string, sometimes already a dict.
	runtime_context = _parse_runtime_context(run.get("runtime_context"))
	if not runtime_context:
		frappe.throw(_("Desktop context not found on this run."))

	desktop_ctx = runtime_context.get("desktop")
	if not desktop_ctx or not isinstance(desktop_ctx, dict):
		frappe.throw(_("Desktop context not found on this run."))

	pinned_executor_id = desktop_ctx.get("executor_id")
	if pinned_executor_id != _dx_executor_id:
		frappe.throw(_("Executor ID mismatch with the pinned context."))

	# Canonical ctx for desktop_executor.dispatch: {executor_id, fingerprint, user, label}.
	# The fingerprint is the one pinned on the run at send time (not the live one).
	return {
		"executor_id": pinned_executor_id,
		"fingerprint": desktop_ctx.get("fingerprint") or _dx_fingerprint or None,
		"user": _dx_user,
		"label": desktop_ctx.get("label"),
	}


def _import_dispatch_lazily():
	"""Import dispatch lazily so tests can mock it even before desktop_executor.py lands."""
	try:
		from huf.ai import desktop_executor
		return desktop_executor.dispatch
	except ImportError:
		# H3 hasn't implemented desktop_executor.py yet; stub for testing
		def _stub_dispatch(op, params, ctx, call_id, conversation_id, agent_run_id, timeout_ms):
			raise frappe.ValidationError(_("Desktop executor not yet implemented."))
		return _stub_dispatch


def handle_workspace_info(
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Return workspace info: label, mode, platform, exec availability, top-level listing.

	No parameters. Returns untrusted_content=False (metadata only).
	"""
	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="ws.info",
		params={},
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	# Unwrap result from dispatch, which returns {ok, data|error, ...}
	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_list_files(
	path: str = ".",
	depth: int = 1,
	include_hidden: bool = False,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""List files in a directory.

	Args:
		path: workspace-relative path (default ".")
		depth: recursion depth, 1-3 (default 1)
		include_hidden: include hidden files (default False)
	"""
	# Validate parameters
	path = _validate_path(path)

	if not isinstance(depth, int):
		try:
			depth = int(depth)
		except (ValueError, TypeError):
			frappe.throw(_("depth must be an integer."))

	if depth < 1 or depth > 3:
		depth = max(1, min(3, depth))  # Clamp to 1-3

	include_hidden = bool(include_hidden)

	params = {"path": path, "depth": depth, "include_hidden": include_hidden}
	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.list",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_read_file(
	path: str,
	offset: int = 0,
	limit: int = 2000,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Read file content.

	Args:
		path: workspace-relative path (required)
		offset: line offset (default 0)
		limit: max lines to return (default 2000)

	Returns untrusted_content=True (file content).
	"""
	# Validate parameters
	path = _validate_path(path)

	if not isinstance(offset, int):
		try:
			offset = int(offset)
		except (ValueError, TypeError):
			frappe.throw(_("offset must be an integer."))

	if not isinstance(limit, int):
		try:
			limit = int(limit)
		except (ValueError, TypeError):
			frappe.throw(_("limit must be an integer."))

	offset = max(0, offset)
	limit = max(1, min(2000, limit))  # Clamp to 1-2000

	params = {"path": path, "offset": offset, "limit": limit}
	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.read",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		error_result = {"error": result.get("error", {}).get("message", "Unknown error")}
		error_result["untrusted_content"] = False
		return error_result

	data = result.get("data", {})
	data["untrusted_content"] = True
	return data


def handle_search_files(
	query: str,
	path: str = ".",
	mode: str = "name",
	glob: str = None,
	case_sensitive: bool = False,
	max_results: int = 100,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Search files by name or content.

	Args:
		query: search term (required)
		path: workspace-relative path to search in (default ".")
		mode: "name" or "content" (default "name")
		glob: glob pattern to filter files
		case_sensitive: case-sensitive search (default False)
		max_results: max results to return (default 100)
	"""
	# Validate parameters
	query = str(query or "").strip()
	if not query:
		frappe.throw(_("search query cannot be empty."))

	path = _validate_path(path)

	if mode not in ("name", "content"):
		mode = "name"  # Default to name search

	if glob:
		glob = str(glob).strip()

	case_sensitive = bool(case_sensitive)

	if not isinstance(max_results, int):
		try:
			max_results = int(max_results)
		except (ValueError, TypeError):
			frappe.throw(_("max_results must be an integer."))

	max_results = max(1, min(100, max_results))  # Clamp to 1-100

	params = {
		"query": query,
		"path": path,
		"mode": mode,
		"case_sensitive": case_sensitive,
		"max_results": max_results,
	}
	if glob:
		params["glob"] = glob

	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.search",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		error_result = {"error": result.get("error", {}).get("message", "Unknown error")}
		error_result["untrusted_content"] = False
		return error_result

	data = result.get("data", {})
	data["untrusted_content"] = True
	return data


def handle_write_file(
	path: str,
	content: str,
	mode: str = "overwrite",
	expected_sha256: str = None,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Write or append to a file.

	Args:
		path: workspace-relative path (required)
		content: file content (required)
		mode: "overwrite" or "create" or "append" (default "overwrite")
		expected_sha256: expected file SHA256 before write (for conflict detection)
	"""
	# Validate parameters
	path = _validate_path(path)

	content = str(content or "")
	if len(content.encode("utf-8")) > MAX_WRITE_CONTENT_BYTES:
		frappe.throw(
			_("Content exceeds maximum size of {0} KB.").format(MAX_WRITE_CONTENT_BYTES // 1024)
		)

	if mode not in ("overwrite", "create", "append"):
		mode = "overwrite"  # Default

	if expected_sha256:
		expected_sha256 = str(expected_sha256).strip()

	params = {"path": path, "content": content, "mode": mode}
	if expected_sha256:
		params["expected_sha256"] = expected_sha256

	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.write",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_edit_file(
	path: str,
	old_text: str,
	new_text: str,
	replace_all: bool = False,
	expected_sha256: str = None,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Edit file content with exact text replacement.

	Args:
		path: workspace-relative path (required)
		old_text: text to find and replace (required)
		new_text: replacement text (required)
		replace_all: replace all occurrences (default False, replace only first)
		expected_sha256: expected file SHA256 before edit (for conflict detection)
	"""
	# Validate parameters
	path = _validate_path(path)

	old_text = str(old_text or "")
	new_text = str(new_text or "")

	if len(old_text.encode("utf-8")) > MAX_WRITE_CONTENT_BYTES:
		frappe.throw(_("old_text exceeds maximum size."))
	if len(new_text.encode("utf-8")) > MAX_WRITE_CONTENT_BYTES:
		frappe.throw(_("new_text exceeds maximum size."))

	replace_all = bool(replace_all)

	if expected_sha256:
		expected_sha256 = str(expected_sha256).strip()

	params = {"path": path, "old_text": old_text, "new_text": new_text, "replace_all": replace_all}
	if expected_sha256:
		params["expected_sha256"] = expected_sha256

	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.edit",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_make_directory(
	path: str,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Create a directory.

	Args:
		path: workspace-relative path (required)
	"""
	# Validate parameters
	path = _validate_path(path)

	params = {"path": path}
	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.mkdir",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_move_path(
	source: str,
	destination: str,
	overwrite: bool = False,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Move or rename a file or directory.

	Args:
		source: workspace-relative source path (required)
		destination: workspace-relative destination path (required)
		overwrite: overwrite destination if it exists (default False)
	"""
	# Validate parameters
	source = _validate_path(source)
	destination = _validate_path(destination)

	overwrite = bool(overwrite)

	params = {"source": source, "destination": destination, "overwrite": overwrite}
	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.move",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_delete_path(
	path: str,
	recursive: bool = False,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Move a file or directory to the OS Trash.

	Args:
		path: workspace-relative path (required)
		recursive: recursively trash directories (default False)
	"""
	# Validate parameters
	path = _validate_path(path)

	recursive = bool(recursive)

	params = {"path": path, "recursive": recursive}
	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	result = dispatch(
		op="fs.trash",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=MAX_FS_TIMEOUT_MS,
	)

	if not result.get("ok"):
		return {"error": result.get("error", {}).get("message", "Unknown error")}

	return result.get("data", {})


def handle_run_command(
	command: str,
	cwd: str = ".",
	timeout_seconds: int = DEFAULT_EXEC_TIMEOUT_SECONDS,
	_dx_executor_id: str = None,
	_dx_fingerprint: str = None,
	_dx_user: str = None,
	agent_run_id: str = None,
	call_id: str = None,
	conversation_id: str = None,
	**kwargs
) -> dict:
	"""Run a shell command in the workspace.

	Args:
		command: shell command to execute (required)
		cwd: workspace-relative working directory (default ".")
		timeout_seconds: execution timeout in seconds, clamped 1-120 (default 60)

	Returns untrusted_content=True (command output).
	"""
	# Validate parameters
	command = str(command or "").strip()
	if not command:
		frappe.throw(_("command cannot be empty."))

	cwd = _validate_path(cwd)

	if not isinstance(timeout_seconds, (int, float)):
		try:
			timeout_seconds = int(timeout_seconds)
		except (ValueError, TypeError):
			frappe.throw(_("timeout_seconds must be an integer."))

	timeout_seconds = max(MIN_EXEC_TIMEOUT_SECONDS, min(MAX_EXEC_TIMEOUT_SECONDS, int(timeout_seconds)))

	params = {"command": command, "cwd": cwd, "timeout_seconds": timeout_seconds}
	_validate_params_size(params)

	# Validate executor context
	dx_ctx = _validate_executor_context(_dx_executor_id, _dx_fingerprint, _dx_user, agent_run_id)

	dispatch = _import_dispatch_lazily()

	# Exec timeout is longer than fs timeout since it waits for command completion
	exec_timeout_ms = timeout_seconds * 1000 + 5000  # Add 5s buffer

	result = dispatch(
		op="exec.run",
		params=params,
		ctx=dx_ctx,
		call_id=call_id,
		conversation_id=conversation_id,
		agent_run_id=agent_run_id,
		timeout_ms=exec_timeout_ms,
	)

	if not result.get("ok"):
		error_result = {"error": result.get("error", {}).get("message", "Unknown error")}
		error_result["untrusted_content"] = False
		return error_result

	data = result.get("data", {})
	data["untrusted_content"] = True
	return data
