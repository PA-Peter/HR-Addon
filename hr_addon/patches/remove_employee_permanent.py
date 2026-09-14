import frappe


def execute():
	frappe.delete_doc(
		"Custom Field",
		"Employee-permanent",
		force=True,
		ignore_missing=True,
	)

	frappe.clear_cache(doctype="Employee")
