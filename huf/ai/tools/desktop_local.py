"""
Desktop local-capability tools -- currently the three local-skill tools.

Skills are folders the local user enabled inside Huf Desktop. They are addressed by
id (``local:<dirLabel>/<name>``) and by paths relative to the skill directory; absolute
paths never leave the machine. Every handler uses the same ``_desktop_tool`` machinery as
the workspace tools (:mod:`huf.ai.tools.desktop_workspace`): ``prepare`` validates on the
loop thread and verifies the ``_dx_pin`` token and the run's pinned executor, ``execute``
talks to Redis in a worker thread, and the ``desktop_executor.dispatch`` result is returned
UNCHANGED (``untrusted_content`` / ``trust`` labels and error codes reach the model).

The catalog the run is pinned to (``runtime_context.desktop.catalog_hash``) is read by
``dispatch``: a skill that is not in it is refused with ``tool_unavailable`` before anything
is published.

Server skills win. ``sdk_tools`` passes ``_dx_hidden_skills`` (local skill ids shadowed by an
attached server skill of the same name, pinned like the other ``_dx_*`` values) and the
read/run handlers refuse those ids.
"""

import functools
import json
import re

import frappe
from frappe import _

from huf.ai.tools.desktop_workspace import (
	MAX_EXEC_TIMEOUT_SECONDS,
	MIN_EXEC_TIMEOUT_SECONDS,
	DEFAULT_EXEC_TIMEOUT_SECONDS,
	_as_int,
	_desktop_tool,
	_validate_path,
)

MAX_LIST_LIMIT = 50
DEFAULT_LIST_LIMIT = 20
MAX_READ_LINES = 2000
MAX_SCRIPT_ARGS = 32
MAX_SCRIPT_ARGS_BYTES = 4 * 1024
MAX_QUERY_CHARS = 200
SKILL_ID_RE = re.compile(r"^local:[a-z0-9_-]{1,48}/[a-z0-9_-]{1,48}$")


def _validate_skill_id(skill) -> str:
	skill = str(skill or "").strip()
	if not SKILL_ID_RE.match(skill):
		frappe.throw(_("skill must be a local skill id such as local:<dir>/<name>."))
	return skill


def _skill_tool(op: str):
	"""``_desktop_tool`` plus the server-skill-wins check on the pinned ``skill`` id."""

	def decorator(build):
		inner = _desktop_tool(op)(build)

		def prepare(**kwargs):
			hidden = kwargs.pop("_dx_hidden_skills", None) or ()
			prepared = inner.prepare(**kwargs)
			skill = prepared["params"].get("skill")
			if skill and skill in tuple(hidden):
				frappe.throw(
					_("A server skill with the same name is attached to this agent; use that one instead.")
				)
			return prepared

		@functools.wraps(build)
		def handler(**kwargs):
			return inner.execute(prepare(**kwargs))

		handler.prepare = prepare
		handler.execute = inner.execute
		return handler

	return decorator


@_skill_tool("skill.list")
def handle_skill_list(query: str = "", limit: int = DEFAULT_LIST_LIMIT, **_ignored):
	"""Search enabled local skills (limit clamped to 1-50)."""
	params = {"limit": max(1, min(MAX_LIST_LIMIT, _as_int(limit, "limit")))}
	query = " ".join(str(query or "").split())[:MAX_QUERY_CHARS]
	if query:
		params["query"] = query
	return params


@_skill_tool("skill.read")
def handle_skill_read(
	skill: str, path: str = "SKILL.md", offset: int = 0, limit: int = MAX_READ_LINES, **_ignored
):
	"""Read SKILL.md or a bundled file of an enabled local skill: ``offset`` (>= 0) and ``limit`` (1-2000) count lines."""
	return {
		"skill": _validate_skill_id(skill),
		"path": _validate_path(path or "SKILL.md"),
		"offset": max(0, _as_int(offset, "offset")),
		"limit": max(1, min(MAX_READ_LINES, _as_int(limit, "limit"))),
	}


def _clean_args(args) -> list:
	if args is None or args == "":
		return []
	if isinstance(args, str):
		try:
			args = json.loads(args)
		except (TypeError, ValueError):
			frappe.throw(_("args must be a list of strings."))
	if not isinstance(args, (list, tuple)):
		frappe.throw(_("args must be a list of strings."))
	if len(args) > MAX_SCRIPT_ARGS:
		frappe.throw(_("args may have at most {0} entries.").format(MAX_SCRIPT_ARGS))
	out = []
	for item in args:
		if isinstance(item, (dict, list, tuple)):
			frappe.throw(_("args entries must be strings."))
		text = str(item)
		if "\0" in text:
			frappe.throw(_("args must not contain NUL bytes."))
		out.append(text)
	if sum(len(a.encode("utf-8")) for a in out) > MAX_SCRIPT_ARGS_BYTES:
		frappe.throw(_("args exceed {0} bytes in total.").format(MAX_SCRIPT_ARGS_BYTES))
	return out


@_skill_tool("skill.exec")
def handle_skill_run(
	skill: str,
	script: str,
	args=None,
	timeout_seconds: int = DEFAULT_EXEC_TIMEOUT_SECONDS,
	**_ignored,
):
	"""Run a script bundled in an enabled local skill, without a shell (timeout clamped to 1-120)."""
	timeout_seconds = max(
		MIN_EXEC_TIMEOUT_SECONDS,
		min(MAX_EXEC_TIMEOUT_SECONDS, _as_int(timeout_seconds, "timeout_seconds")),
	)
	params = {
		"skill": _validate_skill_id(skill),
		"script": _validate_path(script),
		"args": _clean_args(args),
		"timeout_seconds": timeout_seconds,
	}
	# The desktop needs the script's own timeout plus a buffer.
	return params, timeout_seconds * 1000 + 5000
