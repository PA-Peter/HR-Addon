# Copyright (c) 2026, RieckMedia
# Time account summary for Frappe ListView.
# Read-only; no ledger mutations.

from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime


MANAGEMENT_ROLES = frozenset({
    "HR Manager",
    "System Manager",
})


def _resolve_employee(requested_employee):
    user = frappe.session.user

    if not user or user == "Guest":
        frappe.throw(
            _("Login required."),
            frappe.PermissionError,
        )

    if not frappe.has_permission(
        "Time Account Ledger Entry",
        ptype="read",
        user=user,
    ):
        frappe.throw(
            _("No permission to read time accounts."),
            frappe.PermissionError,
        )

    is_manager = (
        user == "Administrator"
        or bool(
            MANAGEMENT_ROLES.intersection(
                frappe.get_roles(user)
            )
        )
    )

    if is_manager:
        if not requested_employee:
            frappe.throw(
                _("Please select an employee.")
            )

        employee = requested_employee

    else:
        employees = frappe.get_all(
            "Employee",
            filters={
                "user_id": user,
                "status": "Active",
            },
            pluck="name",
            limit_page_length=2,
        )

        if len(employees) != 1:
            frappe.throw(
                _("No unique active employee assignment."),
                frappe.PermissionError,
            )

        employee = employees[0]

        if (
            requested_employee
            and requested_employee != employee
        ):
            frappe.throw(
                _("Access to another employee is denied."),
                frappe.PermissionError,
            )

    if not frappe.db.exists("Employee", employee):
        frappe.throw(
            _("Employee not found."),
            frappe.DoesNotExistError,
        )

    return employee


@frappe.whitelist()
def get_time_account_summary(employee=None):
    """Return ledger totals at the beginning of today."""

    employee = _resolve_employee(employee)

    today = getdate(now_datetime())
    month_start = today.replace(day=1)

    previous_month_end = (
        month_start - timedelta(days=1)
    )
    previous_month_start = (
        previous_month_end.replace(day=1)
    )

    rows = frappe.db.sql(
        """
        SELECT
            COALESCE(SUM(
                CASE
                    WHEN effective_date >= %s
                     AND effective_date < %s
                     AND entry_type != 'Opening Balance'
                    THEN delta_minutes
                    ELSE 0
                END
            ), 0) AS previous_month_delta,

            COALESCE(SUM(
                CASE
                    WHEN effective_date < %s
                    THEN delta_minutes
                    ELSE 0
                END
            ), 0) AS month_opening_balance,

            COALESCE(
                SUM(delta_minutes), 0
            ) AS balance_at_today_start

        FROM `tabTime Account Ledger Entry`
        WHERE employee = %s
          AND effective_date < %s
        """,
        (
            previous_month_start,
            month_start,
            month_start,
            employee,
            today,
        ),
        as_dict=True,
    )

    values = rows[0]

    return {
        "employee": employee,
        "as_of_date": today.isoformat(),
        "previous_month": (
            previous_month_start.strftime("%Y-%m")
        ),
        "previous_month_delta_minutes": cint(
            values.previous_month_delta
        ),
        "month_opening_balance_minutes": cint(
            values.month_opening_balance
        ),
        "balance_at_today_start_minutes": cint(
            values.balance_at_today_start
        ),
    }
