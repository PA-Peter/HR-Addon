# Copyright (c) 2026, RieckMedia
# For license information, please see license.txt

"""
Stage 7.4a - Personal Annual Calendar.

Read-only data source for the authenticated employee.
No time calculations, source changes or cross-employee access.
"""

from datetime import date, timedelta
from html import unescape

import frappe
from frappe import _
from frappe.utils import cint, getdate, strip_html_tags, today

from hrms.utils.holiday_list import (
    fill_employee_holiday_list_date_gaps_with_company_holiday_list,
    get_assigned_holiday_lists_to_employee_and_company,
)

from hr_addon.hr_addon.permissions.self_service import (
    _get_employee_for_user,
)


def _personal_employee():
    user = getattr(frappe.session, "user", None)

    if not user or user == "Guest":
        frappe.throw(
            _("Authentication required."),
            frappe.PermissionError,
        )

    employee = _get_employee_for_user(user)

    if not employee:
        frappe.throw(
            _("No active Employee is linked to this user."),
            frappe.PermissionError,
        )

    return frappe.db.get_value(
        "Employee",
        employee,
        ["name", "employee_name", "company"],
        as_dict=True,
    )


def _year(value):
    try:
        year = int(value)
    except (TypeError, ValueError):
        frappe.throw(_("Invalid calendar year."))

    if year < 2000 or year > 2100:
        frappe.throw(_("Calendar year out of range."))

    return year


def _holidays(employee, company, start, end):
    """
    Use the effective HRMS Holiday List assignments.

    Distinguish weekly offs, full holidays and half holidays.
    This function only reads existing HRMS data.
    """

    assignments = (
        get_assigned_holiday_lists_to_employee_and_company(
            [employee, company],
            start,
            end,
        )
    )

    ranges = (
        fill_employee_holiday_list_date_gaps_with_company_holiday_list(
            assignments.get(employee, []),
            assignments.get(company, []),
            start,
            end,
        )
    )

    if not ranges:
        return []

    list_names = sorted({
        item["holiday_list"]
        for item in ranges
    })

    rows = frappe.get_all(
        "Holiday",
        filters={
            "parent": ["in", list_names],
            "holiday_date": ["between", [start, end]],
        },
        fields=[
            "parent",
            "holiday_date",
            "description",
            "weekly_off",
            "is_half_day",
        ],
        order_by="holiday_date asc",
    )

    result = {}

    for period in ranges:
        for row in rows:
            day = getdate(row.holiday_date)

            if row.parent != period["holiday_list"]:
                continue

            if not (
                getdate(period["from_date"])
                <= day
                <= getdate(period["to_date"])
            ):
                continue

            result[str(day)] = {
                "date": str(day),
                "description": unescape(strip_html_tags(row.description or "")).strip(),
                "weekly_off": cint(row.weekly_off),
                "is_half_day": cint(row.is_half_day),
            }

    return [
        result[key]
        for key in sorted(result)
    ]



def _ledger_closing_balances(employee, start, end):
    """
    Reconstruct booked time-account balances as of each past day.

    Source: append-only Time Account Ledger Entry.
    No projection for today or future dates.
    Days preceding the first ledger entry have no balance.
    """
    last_closed_day = getdate(today()) - timedelta(days=1)
    cutoff = min(end, last_closed_day)

    if cutoff < start:
        return {}

    rows = frappe.db.sql(
        """
        SELECT
            effective_date,
            SUM(delta_minutes) AS delta_minutes
        FROM `tabTime Account Ledger Entry`
        WHERE employee = %s
          AND effective_date <= %s
        GROUP BY effective_date
        ORDER BY effective_date ASC
        """,
        (employee, cutoff),
        as_dict=True,
    )

    if not rows:
        return {}

    first_entry_date = getdate(rows[0].effective_date)
    balances = {}
    running_balance = 0
    position = 0
    current = start

    while current <= cutoff:
        while (
            position < len(rows)
            and getdate(rows[position].effective_date) <= current
        ):
            running_balance += cint(rows[position].delta_minutes)
            position += 1

        if current >= first_entry_date:
            balances[str(current)] = running_balance

        current += timedelta(days=1)

    return balances



def _company_events(start, end):
    """
    Read published company events overlapping the requested period.

    These events are informational only.
    No Workday, Holiday, Leave or Ledger side effects.
    """

    rows = frappe.get_all(
        "Company Calendar Event",
        filters={
            "is_published": 1,
            "start_date": ["<=", end],
            "end_date": [">=", start],
        },
        fields=[
            "name",
            "title",
            "category",
            "location",
            "start_date",
            "end_date",
            "all_day",
            "start_time",
            "end_time",
        ],
        order_by="start_date asc, start_time asc, name asc",
        limit_page_length=0,
    )

    return [
        {
            "name": row.name,
            "title": row.title,
            "category": row.category,
            "location": row.location or "",
            "start_date": str(row.start_date),
            "end_date": str(row.end_date),
            "all_day": cint(row.all_day),
            "start_time": (
                str(row.start_time)
                if row.start_time is not None
                else None
            ),
            "end_time": (
                str(row.end_time)
                if row.end_time is not None
                else None
            ),
        }
        for row in rows
    ]


@frappe.whitelist()
def get_personal_year(year=None):
    """
    Annual calendar source for the logged-in employee.

    Employee cannot be selected by the HTTP client.
    Only existing source values are returned.
    """

    employee = _personal_employee()

    year = _year(
        year if year is not None else date.today().year
    )

    start = date(year, 1, 1)
    end = date(year, 12, 31)

    employee_id = employee.name

    workdays = frappe.get_all(
        "Workday",
        filters={
            "employee": employee_id,
            "log_date": ["between", [start, end]],
        },
        fields=[
            "name",
            "log_date",
            "status",
            "target_minutes",
            "raw_work_minutes",
            "physical_break_minutes",
            "automatic_break_deduction_minutes",
            "accountable_minutes",
            "absence_credit_minutes",
            "daily_delta_minutes",
        ],
        order_by="log_date asc",
    )

    checkins = frappe.get_all(
        "Employee Checkin",
        filters={
            "employee": employee_id,
            "time": [
                "between",
                [
                    f"{start} 00:00:00",
                    f"{end} 23:59:59",
                ],
            ],
        },
        fields=[
            "name",
            "time",
            "log_type",
            "skip_auto_attendance",
        ],
        order_by="time asc",
    )

    leaves = frappe.get_all(
        "Leave Application",
        filters={
            "employee": employee_id,
            "from_date": ["<=", end],
            "to_date": [">=", start],
            "docstatus": ["in", [0, 1]],
        },
        fields=[
            "name",
            "from_date",
            "to_date",
            "leave_type",
            "status",
            "docstatus",
            "half_day",
            "half_day_date",
        ],
        order_by="from_date asc",
    )

    return {
        "year": year,
        "employee": {
            "name": employee.name,
            "employee_name": employee.employee_name,
        },
        "workdays": [
            {
                "name": row.name,
                "date": str(row.log_date),
                "status": row.status,
                "target_minutes": cint(row.target_minutes),
                "raw_work_minutes": cint(row.raw_work_minutes),
                "physical_break_minutes": cint(
                    row.physical_break_minutes
                ),
                "automatic_break_deduction_minutes": cint(
                    row.automatic_break_deduction_minutes
                ),
                "accountable_minutes": cint(
                    row.accountable_minutes
                ),
                "absence_credit_minutes": cint(
                    row.absence_credit_minutes
                ),
                "daily_delta_minutes": cint(
                    row.daily_delta_minutes
                ),
            }
            for row in workdays
        ],
        "checkins": [
            {
                "name": row.name,
                "time": str(row.time),
                "log_type": row.log_type,
                "excluded": cint(row.skip_auto_attendance),
            }
            for row in checkins
        ],
        "leaves": [
            {
                "name": row.name,
                "from_date": str(row.from_date),
                "to_date": str(row.to_date),
                "leave_type": row.leave_type,
                "status": row.status,
                "docstatus": cint(row.docstatus),
                "half_day": cint(row.half_day),
                "half_day_date": (
                    str(row.half_day_date)
                    if row.half_day_date
                    else None
                ),
            }
            for row in leaves
        ],
        "holidays": _holidays(
            employee_id,
            employee.company,
            start,
            end,
        ),
        "company_events": _company_events(
            start,
            end,
        ),
        "ledger_closing_balances": _ledger_closing_balances(
            employee_id,
            start,
            end,
        ),
    }
