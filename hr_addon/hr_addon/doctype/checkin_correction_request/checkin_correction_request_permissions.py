# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe import _


MANAGEMENT_ROLES = frozenset(
    {
        "System Manager",
        "HR Manager",
    }
)


def _get_user(user=None):
    return (
        user
        or getattr(
            frappe.session,
            "user",
            None,
        )
        or "Guest"
    )


def _has_management_access(user):
    if user == "Administrator":
        return True

    roles = set(
        frappe.get_roles(user)
    )

    return bool(
        MANAGEMENT_ROLES.intersection(
            roles
        )
    )


def _get_employee_for_user(user):
    if not user or user == "Guest":
        return None

    return frappe.db.get_value(
        "Employee",
        {
            "user_id": user,
            "status": "Active",
        },
        "name",
    )


def get_permission_query_conditions(
    user=None,
):
    user = _get_user(user)

    if _has_management_access(user):
        return None

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        return "1=0"

    return (
        "`tabCheckin Correction Request`."
        "`employee` = "
        f"{frappe.db.escape(employee)}"
    )


def has_permission(
    doc,
    ptype=None,
    user=None,
    debug=False,
):
    user = _get_user(user)

    if _has_management_access(user):
        return True

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        return False

    if (
        ptype == "create"
        and not doc.get("employee")
    ):
        return True

    return (
        doc.get("employee")
        == employee
    )


def validate_self_service_employee(
    doc,
    method=None,
):
    user = _get_user()

    if _has_management_access(user):
        return

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        frappe.throw(
            _(
                "No active Employee record is linked "
                "to the current user."
            ),
            frappe.PermissionError,
        )

    if doc.employee != employee:
        frappe.throw(
            _(
                "Employees may only create or edit "
                "Checkin Correction Requests for "
                "their own Employee record."
            ),
            frappe.PermissionError,
        )
