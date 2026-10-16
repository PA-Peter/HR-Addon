# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe.utils import (
    add_days,
    cint,
    flt,
    getdate,
)

from hrms.utils.holiday_list import (
    get_holiday_list_for_employee,
)


PATCH_MARKER = (
    "_rieckmedia_half_day_holiday_patch"
)


def _get_holiday_row(
    employee,
    holiday_date,
    holiday_list=None,
):
    holiday_date = getdate(
        holiday_date
    )

    effective_holiday_list = (
        holiday_list
        or get_holiday_list_for_employee(
            employee,
            raise_exception=False,
            as_on=holiday_date,
        )
    )

    if not effective_holiday_list:
        return None

    return frappe.db.get_value(
        "Holiday",
        {
            "parent": effective_holiday_list,
            "holiday_date": holiday_date,
        },
        [
            "holiday_date",
            "weekly_off",
            "is_half_day",
        ],
        as_dict=True,
    )


def get_holiday_fraction(
    employee,
    holiday_date,
    holiday_list=None,
):
    """
    Return the non-working fraction represented by
    the effective Holiday entry:

      0.0 -> normal working day
      0.5 -> half-day holiday
      1.0 -> full holiday / weekly off
    """

    row = _get_holiday_row(
        employee,
        holiday_date,
        holiday_list=holiday_list,
    )

    if not row:
        return 0.0

    if cint(
        row.is_half_day
    ):
        return 0.5

    return 1.0


@frappe.whitelist()
def get_number_of_leave_days(
    employee,
    leave_type,
    from_date,
    to_date,
    half_day=None,
    half_day_date=None,
    holiday_list=None,
):
    """
    HRMS-v16.17 compatibility implementation.

    Native HRMS treats every Holiday row as one
    complete non-working day, although ERPNext's
    Holiday child table supports is_half_day.

    RieckMedia semantics:

      normal working day      -> 1.0 leave day
      explicit half-day leave -> 0.5 leave day
      half-day holiday        -> max 0.5 leave day
      full holiday/weekly off -> 0.0 leave day

    Leave Types with include_holiday=1 preserve
    normal calendar-day semantics.
    """

    import hrms.hr.doctype.leave_application.leave_application as hrms_leave

    from_date = getdate(
        from_date
    )
    to_date = getdate(
        to_date
    )

    if to_date < from_date:
        return 0.0

    include_holiday = cint(
        frappe.db.get_value(
            "Leave Type",
            leave_type,
            "include_holiday",
        )
        or 0
    )

    # Native get_number_of_leave_days() reaches this
    # permission check via get_holidays().
    if not include_holiday:
        hrms_leave.validate_leave_access(
            employee
        )

    explicit_half_day = cint(
        half_day
    )

    explicit_half_day_date = (
        getdate(
            half_day_date
        )
        if half_day_date
        else None
    )

    total = 0.0
    current = from_date

    while current <= to_date:

        requested_fraction = 1.0

        if explicit_half_day:
            if from_date == to_date:
                requested_fraction = 0.5
            elif (
                explicit_half_day_date
                and current
                == explicit_half_day_date
            ):
                requested_fraction = 0.5

        if include_holiday:
            total += requested_fraction

        else:
            holiday_fraction = (
                get_holiday_fraction(
                    employee,
                    current,
                    holiday_list=(
                        holiday_list
                    ),
                )
            )

            working_fraction = max(
                1.0 - holiday_fraction,
                0.0,
            )

            total += min(
                requested_fraction,
                working_fraction,
            )

        current = getdate(
            add_days(
                current,
                1,
            )
        )

    return flt(
        total,
        3,
    )


def install_hrms_half_day_leave_patch():
    """
    Replace exactly one HRMS free function in memory.

    No HRMS source file is modified. All internal
    functions in leave_application.py resolve
    get_number_of_leave_days through that module
    global, so validation, ledger calculations and
    balance calculations share one corrected rule.

    This is deliberately isolated as an HRMS-v16.17
    compatibility shim and can be removed if upstream
    gains equivalent half-day-holiday semantics.
    """

    import hrms.hr.doctype.leave_application.leave_application as hrms_leave

    current = (
        hrms_leave.get_number_of_leave_days
    )

    if getattr(
        current,
        PATCH_MARKER,
        False,
    ):
        return

    if not hasattr(
        hrms_leave,
        "_rieckmedia_original_get_number_of_leave_days",
    ):
        setattr(
            hrms_leave,
            "_rieckmedia_original_get_number_of_leave_days",
            current,
        )

    setattr(
        get_number_of_leave_days,
        PATCH_MARKER,
        True,
    )

    hrms_leave.get_number_of_leave_days = (
        get_number_of_leave_days
    )
