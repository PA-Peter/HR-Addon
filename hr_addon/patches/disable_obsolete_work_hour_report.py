import frappe


def execute():
    report = "Work Hour Report"

    if not frappe.db.exists(
        "Report",
        report,
    ):
        return

    frappe.db.set_value(
        "Report",
        report,
        "disabled",
        1,
        update_modified=False,
    )

    frappe.clear_cache()
