# Copyright (c) 2026, RieckMedia
# For license information, please see license.txt

import frappe
from frappe import _


MANAGEMENT_ROLES = frozenset({
    "System Manager",
    "HR Manager",
})

CHECKIN_PRIVILEGED_ROLES = frozenset({
    "System Manager",
    "HR Manager",
    "HR User",
})


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


def _roles(user):
    if user == "Administrator":
        return {"System Manager"}

    return set(
        frappe.get_roles(user)
    )


def _has_any_role(user, roles):
    if user == "Administrator":
        return True

    return bool(
        _roles(user).intersection(
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


def _employee_condition(
    doctype,
    user,
    privileged_roles,
):
    user = _get_user(user)

    if _has_any_role(
        user,
        privileged_roles,
    ):
        return None

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        return "1=0"

    return (
        f"`tab{doctype}`.`employee` = "
        f"{frappe.db.escape(employee)}"
    )


def _own_document_permission(
    doc,
    ptype,
    user,
    privileged_roles,
    allowed_employee_ptypes,
):
    user = _get_user(user)

    if _has_any_role(
        user,
        privileged_roles,
    ):
        return True

    employee = _get_employee_for_user(
        user
    )

    if not employee:
        return False

    if ptype not in allowed_employee_ptypes:
        return False

    return (
        doc.get("employee")
        == employee
    )


# -------------------------------------------------
# Workday
# Employee: own records, read-only
# -------------------------------------------------

def workday_get_permission_query_conditions(
    user=None,
):
    return _employee_condition(
        "Workday",
        user,
        MANAGEMENT_ROLES,
    )


def workday_has_permission(
    doc,
    ptype=None,
    user=None,
    debug=False,
):
    return _own_document_permission(
        doc,
        ptype,
        user,
        MANAGEMENT_ROLES,
        {
            None,
            "read",
        },
    )


# -------------------------------------------------
# Time Account Ledger Entry
# Employee: own records, read-only
# -------------------------------------------------

def ledger_get_permission_query_conditions(
    user=None,
):
    return _employee_condition(
        "Time Account Ledger Entry",
        user,
        MANAGEMENT_ROLES,
    )


def ledger_has_permission(
    doc,
    ptype=None,
    user=None,
    debug=False,
):
    return _own_document_permission(
        doc,
        ptype,
        user,
        MANAGEMENT_ROLES,
        {
            None,
            "read",
        },
    )


# -------------------------------------------------
# Employee Checkin
#
# HR/System roles retain normal HRMS behaviour.
# Normal Employee users may READ their own raw
# records but may not change/delete them.
#
# Corrections belong to Checkin Correction Request.
# -------------------------------------------------

def checkin_get_permission_query_conditions(
    user=None,
):
    return _employee_condition(
        "Employee Checkin",
        user,
        CHECKIN_PRIVILEGED_ROLES,
    )


def checkin_has_permission(
    doc,
    ptype=None,
    user=None,
    debug=False,
):
    return _own_document_permission(
        doc,
        ptype,
        user,
        CHECKIN_PRIVILEGED_ROLES,
        {
            None,
            "read",
        },
    )


def block_employee_direct_checkin_creation(
    doc,
    method=None,
):
    """
    Prevent a normal authenticated Employee from
    inserting raw Employee Checkin documents.

    This deliberately does NOT affect the internal
    kiosk Guest punch service: Guest does not carry
    the Employee role.

    A future authenticated Homeoffice punch service
    must use a dedicated controlled service path,
    not raw DocType CRUD.
    """

    user = _get_user()

    if _has_any_role(
        user,
        CHECKIN_PRIVILEGED_ROLES,
    ):
        return

    roles = _roles(user)

    if "Employee" not in roles:
        return

    frappe.throw(
        _(
            "Employee Checkins cannot be created "
            "directly. Please use the designated "
            "punch function."
        ),
        frappe.PermissionError,
    )
