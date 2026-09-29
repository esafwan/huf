# Copyright (c) 2026, Tridz Technologies Pvt Ltd and contributors
# For license information, please see license.txt

"""Shared real-DB fixtures for the desktop workspace tool tests (not a test module)."""

import contextvars
import threading

import frappe

FP = "0123456789abcdef"


def make_user(prefix="dxtest"):
	"""Insert a real non-admin user with the Huf User role. Returns the email."""
	email = f"{prefix}-{frappe.generate_hash(length=8)}@example.com"
	user = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": prefix,
			"send_welcome_email": 0,
			"enabled": 1,
			"roles": [{"role": "Huf User"}],
		}
	)
	user.flags.ignore_permissions = True
	user.insert()
	frappe.db.commit()
	return email


def delete_docs(pairs):
	frappe.set_user("Administrator")
	for doctype, name in pairs:
		try:
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
		except Exception:
			pass
	frappe.db.commit()


def make_run(user, runtime_context):
	"""Insert a real Agent Run owned by ``user`` whose runtime_context is a JSON STRING
	(as ``run_agent_sync`` stores it). Returns the run name."""
	frappe.set_user(user)
	run = frappe.get_doc(
		{
			"doctype": "Agent Run",
			"status": "Started",
			"prompt": "desktop tool test",
			"runtime_context": frappe.as_json(runtime_context),
		}
	)
	run.insert(ignore_permissions=True)
	frappe.db.commit()
	return run.name


def desktop_pin(executor_id, user, fingerprint=FP, label="my-project"):
	return {"desktop": {"executor_id": executor_id, "fingerprint": fingerprint, "user": user, "label": label}}


def workspace(fingerprint=FP, mode="ask"):
	return {"label": "my-project", "fingerprint": fingerprint, "permission_mode": mode, "exec_confined": True}


def run_in_thread(fn):
	"""Run ``fn`` in a thread that shares frappe.local (same as asyncio.to_thread does).

	Returns ``(thread, errors)``; ``errors`` collects exceptions raised in the thread."""
	errors = []

	def target():
		try:
			fn()
		except BaseException as exc:  # noqa: BLE001 - reported to the test
			errors.append(exc)

	thread = threading.Thread(target=contextvars.copy_context().run, args=(target,), daemon=True)
	thread.start()
	return thread, errors
