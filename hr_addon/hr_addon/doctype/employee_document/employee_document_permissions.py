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

EMPLOYEE_ALLOWED_PTYPES = frozenset(
    {
        None,
        "read",
        "print",
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


def has_management_access(user=None):
    user = _get_user(user)

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

    if has_management_access(user):
        return None

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        return "1=0"

    return (
        "`tabEmployee Document`.`employee` = "
        f"{frappe.db.escape(employee)}"
    )


def has_permission(
    doc,
    ptype=None,
    user=None,
    debug=False,
):
    user = _get_user(user)

    if has_management_access(user):
        return True

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        return False

    if ptype not in EMPLOYEE_ALLOWED_PTYPES:
        return False

    return (
        doc.get("employee")
        == employee
    )


def assert_document_action_access(
    doc,
    user=None,
):
    user = _get_user(user)

    if has_management_access(user):
        return

    employee = _get_employee_for_user(
        user
    )

    if (
        employee
        and doc.get("employee") == employee
    ):
        return

    frappe.throw(
        _(
            "Employees may only access actions for "
            "their own Employee Documents."
        ),
        frappe.PermissionError,
    )
