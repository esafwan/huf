# Copyright (c) 2026, Tridz Technologies Pvt Ltd and contributors
# For license information, please see license.txt

"""Tests for Desktop Workspace tool exposure in huf.ai.sdk_tools.create_agent_tools().

Gate: tool attached to the agent (ordinary Agent Tool row) AND a live
desktop_ctx. Covers S27 (no ctx), S28 (ctx but not attached), S29 (_dx_*
overwrite), S30 (lease expired).

Run with:
	bench --site <site> run-tests --app huf --module huf.ai.tests.test_desktop_tool_exposure
"""

import asyncio
import json
import unittest
from unittest import mock

import frappe

from huf.ai.sdk_tools import create_agent_tools
from huf.ai.tools._registry import DESKTOP_WORKSPACE_TOOL_NAMES, DESKTOP_WORKSPACE_TOOLS

EXECUTOR_ID = "exec-test-0001"
CTX = {"executor_id": EXECUTOR_ID, "fingerprint": "ctxfingerprint", "user": "Administrator"}
LIVE = {"executor_id": EXECUTOR_ID, "fingerprint": "abcdef0123456789", "user": "Administrator", "label": "ws"}

_PATCH_LIVE = (
	mock.patch("huf.ai.desktop_executor.is_lease_live", return_value=True),
	mock.patch("huf.ai.desktop_executor.resolve_desktop_ctx", return_value=LIVE),
)


class TestDesktopToolExposure(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.provider = cls._ensure_provider()
		cls.model = cls._ensure_model(cls.provider)
		cls.tool_docs = cls._ensure_desktop_tool_rows()

	def setUp(self):
		frappe.set_user("Administrator")
		self._agents = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self._agents:
			try:
				frappe.delete_doc("Agent", name, ignore_permissions=True, force=True)
			except Exception:
				pass
		frappe.db.commit()

	@staticmethod
	def _ensure_provider():
		existing = frappe.db.get_value("AI Provider", {}, "name")
		if existing:
			return existing
		doc = frappe.get_doc(
			{
				"doctype": "AI Provider",
				"provider_name": f"Desktop Exposure Test Provider {frappe.generate_hash(length=6)}",
				"api_key": "test-key-not-used",
				"provider_brand": "openai",
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	@staticmethod
	def _ensure_model(provider):
		existing = frappe.db.get_value("AI Model", {"provider": provider}, "name")
		if existing:
			return existing
		doc = frappe.get_doc(
			{
				"doctype": "AI Model",
				"model_name": f"desktop-exposure-test-model-{frappe.generate_hash(length=6)}",
				"provider": provider,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	@staticmethod
	def _ensure_desktop_tool_rows():
		"""Registry-synced Agent Tool Function rows; created here if the sync has not run."""
		if not frappe.db.exists("Agent Tool Type", "Desktop Workspace"):
			frappe.get_doc({"doctype": "Agent Tool Type", "name1": "Desktop Workspace"}).insert(
				ignore_permissions=True
			)
		docs = []
		for spec in DESKTOP_WORKSPACE_TOOLS:
			name = frappe.db.get_value("Agent Tool Function", {"tool_name": spec["tool_name"]}, "name")
			if not name:
				props = {
					p["fieldname"]: {"type": p["type"], "description": p.get("description", "")}
					for p in spec["parameters"]
				}
				doc = frappe.get_doc(
					{
						"doctype": "Agent Tool Function",
						"tool_name": spec["tool_name"],
						"description": spec["description"],
						"tool_type": "Desktop Workspace",
						"types": "App Provided",
						"function_path": spec["function_path"],
						"params": json.dumps({"type": "object", "properties": props}),
					}
				)
				doc.insert(ignore_permissions=True)
				name = doc.name
			docs.append(name)
		frappe.db.commit()
		return docs

	def _make_agent(self, tool_names):
		agent = frappe.get_doc(
			{
				"doctype": "Agent",
				"agent_name": f"desktop-exposure-agent-{frappe.generate_hash(length=8)}",
				"instructions": "Test desktop exposure agent instructions",
				"provider": self.provider,
				"model": self.model,
				"agent_tool": [{"tool": n} for n in tool_names],
			}
		)
		agent.insert(ignore_permissions=True)
		self._agents.append(agent.name)
		return agent

	@staticmethod
	def _desktop_tools(tools):
		return [t for t in tools if getattr(t, "name", "") in DESKTOP_WORKSPACE_TOOL_NAMES]

	def test_registry_has_ten_tools(self):
		self.assertEqual(len(DESKTOP_WORKSPACE_TOOL_NAMES), 10)

	# S27
	def test_s27_no_ctx_tools_absent(self):
		agent = self._make_agent(self.tool_docs)
		self.assertEqual(self._desktop_tools(create_agent_tools(agent)), [])
		self.assertEqual(self._desktop_tools(create_agent_tools(agent, desktop_ctx=None)), [])
		self.assertEqual(self._desktop_tools(create_agent_tools(agent, desktop_ctx={})), [])

	# S28
	def test_s28_ctx_but_not_attached_absent(self):
		agent = self._make_agent([])
		with _PATCH_LIVE[0], _PATCH_LIVE[1]:
			tools = create_agent_tools(agent, desktop_ctx=dict(CTX))
		self.assertEqual(self._desktop_tools(tools), [])

	# S30
	def test_s30_lease_expired_absent(self):
		agent = self._make_agent(self.tool_docs)
		with mock.patch("huf.ai.desktop_executor.is_lease_live", return_value=False), mock.patch(
			"huf.ai.desktop_executor.resolve_desktop_ctx", return_value=None
		):
			tools = create_agent_tools(agent, desktop_ctx=dict(CTX))
		self.assertEqual(self._desktop_tools(tools), [])

	def test_ctx_owned_by_other_user_absent(self):
		agent = self._make_agent(self.tool_docs)
		with mock.patch("huf.ai.desktop_executor.is_lease_live", return_value=True), mock.patch(
			"huf.ai.desktop_executor.resolve_desktop_ctx", return_value=None
		):
			tools = create_agent_tools(agent, desktop_ctx=dict(CTX, user="someone@example.com"))
		self.assertEqual(self._desktop_tools(tools), [])

	def test_attached_and_live_exposes_ten_with_pinned_extra_args(self):
		agent = self._make_agent(self.tool_docs)
		with _PATCH_LIVE[0], _PATCH_LIVE[1]:
			tools = create_agent_tools(agent, desktop_ctx=dict(CTX))
		desktop = self._desktop_tools(tools)
		self.assertEqual({t.name for t in desktop}, set(DESKTOP_WORKSPACE_TOOL_NAMES))
		self.assertEqual(len(desktop), 10)

	def test_partial_attachment_exposes_only_attached(self):
		agent = self._make_agent(self.tool_docs[:2])
		with _PATCH_LIVE[0], _PATCH_LIVE[1]:
			tools = create_agent_tools(agent, desktop_ctx=dict(CTX))
		self.assertEqual(len(self._desktop_tools(tools)), 2)

	# S29
	def test_s29_dx_args_overwrite_llm_values_and_run_blocking(self):
		captured = {}

		def fake_handler(**kwargs):
			captured.update(kwargs)
			return {"ok": True}

		agent = self._make_agent(self.tool_docs)
		with _PATCH_LIVE[0], _PATCH_LIVE[1], mock.patch(
			"huf.ai.tools.desktop_workspace.handle_list_files", fake_handler
		), mock.patch("huf.ai.sdk_tools.asyncio.to_thread", wraps=asyncio.to_thread) as to_thread:
			tools = create_agent_tools(agent, desktop_ctx=dict(CTX))
			tool = next(t for t in tools if t.name == "desktop_list_files")
			evil = {
				"path": ".",
				"_dx_executor_id": "attacker-exec",
				"_dx_fingerprint": "deadbeef",
				"_dx_user": "victim@example.com",
			}
			out = asyncio.run(tool.on_invoke_tool(None, json.dumps(evil)))

		self.assertEqual(json.loads(out), {"ok": True})
		self.assertEqual(captured["_dx_executor_id"], LIVE["executor_id"])
		self.assertEqual(captured["_dx_fingerprint"], LIVE["fingerprint"])
		self.assertEqual(captured["_dx_user"], LIVE["user"])
		self.assertTrue(to_thread.called)
