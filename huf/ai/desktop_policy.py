# Copyright (c) 2026, Tridz Technologies Pvt Ltd and contributors
# For license information, please see license.txt

"""Agent-level desktop access policy (Desktop Remote Sessions R1/R2 server half).

An Agent carries a *ceiling* for what a run pinned to a desktop may do on the user's machine:
``cli``, ``files``, ``skills``, ``local_mcp``, ``browser``, ``installs`` and ``processes``, each
``off | ask | allowed``, plus ``allow_remote_desktop`` (may a run started from a web or mobile
client drive the desktop at all). The desktop policy provider intersects this ceiling with the
user's own per-workspace policy; deny wins at every step.

This module is pure (no database access except the optional agent-doc read helpers) so it is safe
to call from a worker thread with a plain dict.

* :func:`policy_from_agent` builds the effective policy of an Agent document. The Agent fields
  default to ``allowed`` so an agent that never configured anything behaves exactly as before: the
  attach model (grant tools on the agent) is still what exposes a tool.
* :func:`tool_capability` / :func:`op_capability` map a tool or a wire op to the policy capability
  it needs; a capability that is ``off`` removes the tool from the model's tool list
  (``sdk_tools``) and is refused again at dispatch.
* :func:`policy_hash` is a short digest recorded next to the pin.
"""

import hashlib
import json

CAPABILITIES = ("cli", "files", "skills", "local_mcp", "browser", "installs", "processes")
LEVELS = ("off", "ask", "allowed")
DEFAULT_LEVEL = "allowed"
FIELD_PREFIX = "desktop_access_"
REMOTE_FIELD = "allow_remote_desktop"

_TOOL_CAPABILITY = {
	"desktop_workspace_info": "files",
	"desktop_list_files": "files",
	"desktop_read_file": "files",
	"desktop_search_files": "files",
	"desktop_write_file": "files",
	"desktop_edit_file": "files",
	"desktop_make_directory": "files",
	"desktop_move_path": "files",
	"desktop_delete_path": "files",
	"desktop_run_command": "cli",
	"desktop_skill_list": "skills",
	"desktop_skill_read": "skills",
	"desktop_skill_run": "skills",
	"desktop_process_start": "processes",
	"desktop_process_list": "processes",
	"desktop_process_logs": "processes",
	"desktop_process_stop": "processes",
	"desktop_local_mcp": "local_mcp",
	"desktop_mcp_find": "local_mcp",
	"desktop_mcp_call": "local_mcp",
	"desktop_browser": "browser",
}
_DYNAMIC_PREFIX_CAPABILITY = (("lmcp__", "local_mcp"), ("lbrowser__", "browser"))

_OP_CAPABILITY = {
	"ws.info": "files",
	"fs.list": "files",
	"fs.read": "files",
	"fs.search": "files",
	"fs.write": "files",
	"fs.edit": "files",
	"fs.mkdir": "files",
	"fs.move": "files",
	"fs.trash": "files",
	"exec.run": "cli",
	"skill.list": "skills",
	"skill.read": "skills",
	"skill.exec": "skills",
	"proc.start": "processes",
	"proc.stop": "processes",
	"proc.list": "processes",
	"proc.logs": "processes",
	"mcp.call": "local_mcp",
}
BROWSER_SERVER = "browser"


def clean_level(value):
	value = str(value or "").strip().lower()
	return value if value in LEVELS else DEFAULT_LEVEL


def default_policy():
	policy = {cap: DEFAULT_LEVEL for cap in CAPABILITIES}
	policy[REMOTE_FIELD] = False
	return policy


def sanitize_policy(value):
	"""A clean policy dict from anything (missing keys default to ``allowed``; remote defaults to
	false). Returns None when ``value`` is not a dict."""
	if not isinstance(value, dict):
		return None
	policy = {cap: clean_level(value.get(cap)) for cap in CAPABILITIES}
	policy[REMOTE_FIELD] = bool(value.get(REMOTE_FIELD))
	return policy


def policy_from_agent(agent):
	"""Effective policy of an Agent document (or any object/dict with the ``desktop_access_*``
	fields). Unset fields read as ``allowed`` and ``allow_remote_desktop`` as false."""
	if agent is None:
		return default_policy()
	get = agent.get if hasattr(agent, "get") else (lambda key, default=None: getattr(agent, key, default))
	policy = {}
	for cap in CAPABILITIES:
		policy[cap] = clean_level(get(FIELD_PREFIX + cap, None) or DEFAULT_LEVEL)
	policy[REMOTE_FIELD] = bool(int(get(REMOTE_FIELD, 0) or 0))
	return policy


def policy_hash(policy):
	blob = json.dumps(sanitize_policy(policy) or {}, sort_keys=True, separators=(",", ":"))
	return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def tool_capability(tool_name):
	"""Policy capability a desktop tool needs, or None for a tool this module does not know."""
	name = tool_name or ""
	if name in _TOOL_CAPABILITY:
		return _TOOL_CAPABILITY[name]
	for prefix, cap in _DYNAMIC_PREFIX_CAPABILITY:
		if name.startswith(prefix):
			return cap
	return None


def op_capability(op, params=None):
	"""Policy capability a wire op needs. ``mcp.call`` to the managed browser server is ``browser``,
	every other local MCP server is ``local_mcp``."""
	if op == "mcp.call" and str((params or {}).get("server") or "") == BROWSER_SERVER:
		return "browser"
	return _OP_CAPABILITY.get(op)


def level_of(policy, capability):
	"""The level of a capability in ``policy``. An absent policy or capability reads as
	``allowed`` (the attach model still applies)."""
	if not isinstance(policy, dict) or not capability:
		return DEFAULT_LEVEL
	return clean_level(policy.get(capability))


def tool_allowed(policy, tool_name):
	"""False when the policy switches the tool's capability ``off``."""
	cap = tool_capability(tool_name)
	return cap is None or level_of(policy, cap) != "off"
