# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import calendar
import hashlib
import json
from collections import defaultdict
from datetime import timedelta

import frappe

from frappe import _
from frappe.utils import (
    cint,
    get_datetime,
    getdate,
    now_datetime,
)

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report import (
    SERVICE_FLAG,
    STATUS_GENERATED,
)


SNAPSHOT_STATUS_OK = "OK"
SNAPSHOT_STATUS_OUTSIDE_EMPLOYMENT = (
    "Outside Employment"
)
SNAPSHOT_STATUS_NO_WWH = (
    "No Working Hours Model"
)
SNAPSHOT_STATUS_MISSING_WORKDAY = (
    "Missing Workday"
)
SNAPSHOT_STATUS_MISSING_CHECKIN = (
    "Missing Checkin"
)

# A Missing Checkin is intentionally NOT blocking.
# It must be visible in the employee's monthly report
# and its Workday delta remains financially/time-account
# effective until corrected.
#
# Only missing structural calculation sources block
# publication.
BLOCKING_SNAPSHOT_STATUSES = {
    SNAPSHOT_STATUS_NO_WWH,
    SNAPSHOT_STATUS_MISSING_WORKDAY,
}


WORKDAY_FIELDS = [
    "name",
    "log_date",
    "status",
    "target_minutes",
    "raw_work_minutes",
    "physical_break_minutes",
    "qualifying_break_minutes",
    "required_break_minutes",
    "automatic_break_deduction_minutes",
    "absence_credit_minutes",
    "accountable_minutes",
    "daily_delta_minutes",
]


FINGERPRINT_REPORT_FIELDS = (
    "employee",
    "employee_name",
    "report_title",
    "report_year",
    "report_month",
    "period_from",
    "period_to",
    "opening_balance_minutes",
    "ledger_movement_minutes",
    "closing_balance_minutes",
    "is_complete",
    "blocking_issue_count",
)

FINGERPRINT_DAY_FIELDS = (
    "report_date",
    "snapshot_status",
    "workday",
    "workday_status",
    "checkins_text",
    "leave_application",
    "leave_type",
    "leave_portion",
    "target_minutes",
    "raw_work_minutes",
    "physical_break_minutes",
    "qualifying_break_minutes",
    "required_break_minutes",
    "automatic_break_deduction_minutes",
    "absence_credit_minutes",
    "accountable_minutes",
    "daily_delta_minutes",
    "remarks",
)

FINGERPRINT_LEDGER_FIELDS = (
    "ledger_entry",
    "effective_date",
    "effective_time",
    "entry_type",
    "delta_minutes",
    "voucher_type",
    "voucher_no",
    "reverses_entry",
    "remarks",
)


def _source_value(
    source,
    fieldname,
):
    if hasattr(
        source,
        "get",
    ):
        return source.get(
            fieldname
        )

    return getattr(
        source,
        fieldname,
        None,
    )


def _canonical_fingerprint_value(
    value,
):
    if value is None:
        return None

    if isinstance(
        value,
        bool,
    ):
        return int(
            value
        )

    if isinstance(
        value,
        (
            str,
            int,
            float,
        ),
    ):
        return value

    return str(
        value
    )


def _fingerprint_row(
    row,
    fields,
):
    return {
        fieldname: (
            _canonical_fingerprint_value(
                _source_value(
                    row,
                    fieldname,
                )
            )
        )
        for fieldname in fields
    }


def monthly_time_report_source_fingerprint(
    snapshot,
):
    """
    Build a deterministic hash from the immutable
    source snapshot only.

    Generation metadata, revision numbers, PDF/File
    links and Employee Document links are deliberately
    excluded.
    """

    report_values = (
        _fingerprint_row(
            snapshot,
            FINGERPRINT_REPORT_FIELDS,
        )
    )

    days = [
        _fingerprint_row(
            row,
            FINGERPRINT_DAY_FIELDS,
        )
        for row in (
            _source_value(
                snapshot,
                "days",
            )
            or []
        )
    ]

    days.sort(
        key=lambda row: (
            str(
                row.get(
                    "report_date"
                )
                or ""
            ),
            str(
                row.get(
                    "workday"
                )
                or ""
            ),
        )
    )

    ledger_entries = [
        _fingerprint_row(
            row,
            FINGERPRINT_LEDGER_FIELDS,
        )
        for row in (
            _source_value(
                snapshot,
                "ledger_entries",
            )
            or []
        )
    ]

    ledger_entries.sort(
        key=lambda row: (
            str(
                row.get(
                    "effective_date"
                )
                or ""
            ),
            str(
                row.get(
                    "effective_time"
                )
                or ""
            ),
            str(
                row.get(
                    "ledger_entry"
                )
                or ""
            ),
        )
    )

    payload = {
        "report": (
            report_values
        ),
        "days": (
            days
        ),
        "ledger_entries": (
            ledger_entries
        ),
    }

    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
        ensure_ascii=False,
    ).encode(
        "utf-8"
    )

    return hashlib.sha256(
        encoded
    ).hexdigest()

def get_report_period(
    year,
    month,
):
    year = cint(
        year
    )

    month = cint(
        month
    )

    if year < 2000:
        frappe.throw(
            _(
                "Report Year is invalid."
            )
        )

    if (
        month < 1
        or month > 12
    ):
        frappe.throw(
            _(
                "Report Month must be "
                "between 1 and 12."
            )
        )

    period_from = getdate(
        f"{year:04d}-{month:02d}-01"
    )

    period_to = getdate(
        (
            f"{year:04d}-{month:02d}-"
            f"{calendar.monthrange(year, month)[1]:02d}"
        )
    )

    return (
        period_from,
        period_to,
    )


def _validate_completed_period(
    period_to,
    reference_datetime=None,
):
    reference_datetime = (
        reference_datetime
        or now_datetime()
    )

    today = getdate(
        reference_datetime
    )

    if getdate(
        period_to
    ) >= today:
        frappe.throw(
            _(
                "Monthly Time Reports may "
                "only be generated for fully "
                "completed calendar months."
            )
        )


def _get_employee_row(
    employee,
):
    if not employee:
        frappe.throw(
            _(
                "Employee is required."
            )
        )

    row = frappe.db.get_value(
        "Employee",
        employee,
        [
            "name",
            "employee_name",
            "date_of_joining",
            "relieving_date",
        ],
        as_dict=True,
    )

    if not row:
        frappe.throw(
            _(
                "Employee {0} does not exist."
            ).format(
                employee
            )
        )

    return row


def _employee_overlaps_period(
    employee_row,
    period_from,
    period_to,
):
    joining_date = (
        getdate(
            employee_row.date_of_joining
        )
        if employee_row.date_of_joining
        else None
    )

    relieving_date = (
        getdate(
            employee_row.relieving_date
        )
        if employee_row.relieving_date
        else None
    )

    if (
        joining_date
        and joining_date
        > period_to
    ):
        return False

    if (
        relieving_date
        and relieving_date
        < period_from
    ):
        return False

    return True


def _date_is_in_employment(
    employee_row,
    report_date,
):
    report_date = getdate(
        report_date
    )

    if (
        employee_row.date_of_joining
        and report_date
        < getdate(
            employee_row.date_of_joining
        )
    ):
        return False

    if (
        employee_row.relieving_date
        and report_date
        > getdate(
            employee_row.relieving_date
        )
    ):
        return False

    return True


def _get_workdays(
    employee,
    period_from,
    period_to,
):
    rows = frappe.get_all(
        "Workday",
        filters={
            "employee": employee,
            "log_date": [
                "between",
                [
                    period_from,
                    period_to,
                ],
            ],
        },
        fields=WORKDAY_FIELDS,
        order_by="log_date asc",
    )

    result = {}

    for row in rows:
        report_date = getdate(
            row.log_date
        )

        if report_date in result:
            frappe.throw(
                _(
                    "More than one Workday "
                    "exists for employee {0} "
                    "on {1}."
                ).format(
                    employee,
                    report_date,
                )
            )

        result[
            report_date
        ] = row

    return result


def _get_checkins_by_workday(
    workday_names,
):
    if not workday_names:
        return {}

    rows = frappe.get_all(
        "Employee Checkins",
        filters={
            "parent": [
                "in",
                workday_names,
            ],
            "parenttype": (
                "Workday"
            ),
        },
        fields=[
            "parent",
            "log_type",
            "log_time",
            "skip_auto_attendance",
            "idx",
        ],
        order_by=(
            "parent asc, idx asc"
        ),
    )

    result = defaultdict(
        list
    )

    for row in rows:
        result[
            row.parent
        ].append(
            row
        )

    return dict(
        result
    )


def _format_checkins(
    checkins,
):
    parts = []

    for row in (
        checkins or []
    ):
        log_time = get_datetime(
            row.log_time
        )

        log_type = str(
            row.log_type
            or ""
        ).strip().upper()

        part = (
            f"{log_time:%H:%M} "
            f"{log_type}"
        ).strip()

        if cint(
            row.skip_auto_attendance
        ):
            part += " [ignored]"

        parts.append(
            part
        )

    return " · ".join(
        parts
    )


def _get_wwh_periods(
    employee,
    period_to,
):
    rows = frappe.get_all(
        "Weekly Working Hours",
        filters={
            "employee": employee,
            "docstatus": 1,
            "valid_from": [
                "<=",
                period_to,
            ],
        },
        fields=[
            "name",
            "valid_from",
            "valid_to",
        ],
        order_by=(
            "valid_from asc"
        ),
    )

    return rows


def _has_valid_wwh(
    wwh_periods,
    report_date,
):
    report_date = getdate(
        report_date
    )

    matches = []

    for row in (
        wwh_periods or []
    ):
        valid_from = getdate(
            row.valid_from
        )

        valid_to = (
            getdate(
                row.valid_to
            )
            if row.valid_to
            else None
        )

        if report_date < valid_from:
            continue

        if (
            valid_to
            and report_date
            > valid_to
        ):
            continue

        matches.append(
            row.name
        )

    if len(
        matches
    ) > 1:
        frappe.throw(
            _(
                "More than one submitted "
                "Weekly Working Hours model "
                "is valid on {0}."
            ).format(
                report_date
            )
        )

    return bool(
        matches
    )


def _get_leave_by_date(
    employee,
    period_from,
    period_to,
):
    rows = frappe.get_all(
        "Leave Application",
        filters={
            "employee": employee,
            "docstatus": 1,
            "from_date": [
                "<=",
                period_to,
            ],
            "to_date": [
                ">=",
                period_from,
            ],
        },
        fields=[
            "name",
            "leave_type",
            "from_date",
            "to_date",
            "half_day",
            "half_day_date",
        ],
        order_by=(
            "from_date asc, name asc"
        ),
    )

    result = {}

    for row in rows:
        from_date = max(
            getdate(
                row.from_date
            ),
            period_from,
        )

        to_date = min(
            getdate(
                row.to_date
            ),
            period_to,
        )

        report_date = (
            from_date
        )

        while (
            report_date
            <= to_date
        ):
            if (
                report_date
                in result
            ):
                frappe.throw(
                    _(
                        "Multiple submitted "
                        "Leave Applications "
                        "overlap on {0}."
                    ).format(
                        report_date
                    )
                )

            is_half_day = (
                cint(
                    row.half_day
                )
                and (
                    not row.half_day_date
                    or getdate(
                        row.half_day_date
                    )
                    == report_date
                )
            )

            result[
                report_date
            ] = frappe._dict(
                {
                    "name": (
                        row.name
                    ),
                    "leave_type": (
                        row.leave_type
                    ),
                    "leave_portion": (
                        "Half Day"
                        if is_half_day
                        else "Full Day"
                    ),
                }
            )

            report_date += (
                timedelta(
                    days=1
                )
            )

    return result


def _get_opening_balance(
    employee,
    period_from,
):
    result = frappe.db.sql(
        """
        SELECT
            COALESCE(
                SUM(delta_minutes),
                0
            )
        FROM
            `tabTime Account Ledger Entry`
        WHERE
            employee = %s
            AND effective_date < %s
        """,
        (
            employee,
            period_from,
        ),
    )

    if not result:
        return 0

    return cint(
        result[0][0]
    )


def _get_period_ledger_entries(
    employee,
    period_from,
    period_to,
):
    return frappe.get_all(
        "Time Account Ledger Entry",
        filters={
            "employee": employee,
            "effective_date": [
                "between",
                [
                    period_from,
                    period_to,
                ],
            ],
        },
        fields=[
            "name",
            "effective_date",
            "effective_time",
            "entry_type",
            "delta_minutes",
            "voucher_type",
            "voucher_no",
            "reverses_entry",
            "remarks",
        ],
        order_by=(
            "effective_date asc, "
            "effective_time asc, "
            "creation asc, "
            "name asc"
        ),
    )


def _build_ledger_snapshot(
    ledger_entries,
):
    result = []

    for row in (
        ledger_entries or []
    ):
        result.append(
            {
                "ledger_entry": (
                    row.name
                ),
                "effective_date": (
                    row.effective_date
                ),
                "effective_time": (
                    row.effective_time
                ),
                "entry_type": (
                    row.entry_type
                ),
                "delta_minutes": (
                    cint(
                        row.delta_minutes
                    )
                ),
                "voucher_type": (
                    row.voucher_type
                ),
                "voucher_no": (
                    row.voucher_no
                ),
                "reverses_entry": (
                    row.reverses_entry
                ),
                "remarks": (
                    row.remarks
                ),
            }
        )

    return result


def _zero_day_values():
    return {
        "target_minutes": 0,
        "raw_work_minutes": 0,
        "physical_break_minutes": 0,
        "qualifying_break_minutes": 0,
        "required_break_minutes": 0,
        "automatic_break_deduction_minutes": 0,
        "absence_credit_minutes": 0,
        "accountable_minutes": 0,
        "daily_delta_minutes": 0,
    }


def _build_day_snapshot(
    report_date,
    employee_row,
    workday,
    checkins,
    leave,
    has_valid_wwh,
):
    row = {
        "report_date": (
            report_date
        ),
        "snapshot_status": (
            SNAPSHOT_STATUS_OK
        ),
        "workday": None,
        "workday_status": None,
        "checkins_text": "",
        "leave_application": (
            leave.name
            if leave
            else None
        ),
        "leave_type": (
            leave.leave_type
            if leave
            else None
        ),
        "leave_portion": (
            leave.leave_portion
            if leave
            else None
        ),
        "remarks": None,
    }

    row.update(
        _zero_day_values()
    )

    if not _date_is_in_employment(
        employee_row,
        report_date,
    ):
        row[
            "snapshot_status"
        ] = (
            SNAPSHOT_STATUS_OUTSIDE_EMPLOYMENT
        )

        return row

    if not has_valid_wwh:
        row[
            "snapshot_status"
        ] = (
            SNAPSHOT_STATUS_NO_WWH
        )

        row[
            "remarks"
        ] = (
            "No submitted Weekly Working "
            "Hours model is valid for "
            "this date."
        )

        return row

    if not workday:
        row[
            "snapshot_status"
        ] = (
            SNAPSHOT_STATUS_MISSING_WORKDAY
        )

        row[
            "remarks"
        ] = (
            "No Workday exists for "
            "this date."
        )

        return row

    row.update(
        {
            "workday": (
                workday.name
            ),
            "workday_status": (
                workday.status
            ),
            "checkins_text": (
                _format_checkins(
                    checkins
                )
            ),
            "target_minutes": (
                cint(
                    workday.target_minutes
                )
            ),
            "raw_work_minutes": (
                cint(
                    workday.raw_work_minutes
                )
            ),
            "physical_break_minutes": (
                cint(
                    workday.physical_break_minutes
                )
            ),
            "qualifying_break_minutes": (
                cint(
                    workday.qualifying_break_minutes
                )
            ),
            "required_break_minutes": (
                cint(
                    workday.required_break_minutes
                )
            ),
            "automatic_break_deduction_minutes": (
                cint(
                    workday.automatic_break_deduction_minutes
                )
            ),
            "absence_credit_minutes": (
                cint(
                    workday.absence_credit_minutes
                )
            ),
            "accountable_minutes": (
                cint(
                    workday.accountable_minutes
                )
            ),
            "daily_delta_minutes": (
                cint(
                    workday.daily_delta_minutes
                )
            ),
        }
    )

    if (
        workday.status
        == "Missing Checkin"
    ):
        row[
            "snapshot_status"
        ] = (
            SNAPSHOT_STATUS_MISSING_CHECKIN
        )

        row[
            "remarks"
        ] = (
            "Workday contains incomplete "
            "or invalid checkins."
        )

    return row


def build_monthly_time_report_snapshot(
    employee,
    year,
    month,
    reference_datetime=None,
):
    (
        period_from,
        period_to,
    ) = get_report_period(
        year,
        month,
    )

    _validate_completed_period(
        period_to,
        reference_datetime=(
            reference_datetime
        ),
    )

    employee_row = (
        _get_employee_row(
            employee
        )
    )

    if not _employee_overlaps_period(
        employee_row,
        period_from,
        period_to,
    ):
        frappe.throw(
            _(
                "Employee {0} was not "
                "employed during the "
                "selected report period."
            ).format(
                employee
            )
        )

    workdays = _get_workdays(
        employee,
        period_from,
        period_to,
    )

    checkins_by_workday = (
        _get_checkins_by_workday(
            [
                row.name
                for row in (
                    workdays.values()
                )
            ]
        )
    )

    leave_by_date = (
        _get_leave_by_date(
            employee,
            period_from,
            period_to,
        )
    )

    wwh_periods = (
        _get_wwh_periods(
            employee,
            period_to,
        )
    )

    day_rows = []

    blocking_issue_count = 0

    report_date = (
        period_from
    )

    while (
        report_date
        <= period_to
    ):
        workday = (
            workdays.get(
                report_date
            )
        )

        leave = (
            leave_by_date.get(
                report_date
            )
        )

        has_valid_wwh = (
            _has_valid_wwh(
                wwh_periods,
                report_date,
            )
        )

        day_row = (
            _build_day_snapshot(
                report_date,
                employee_row,
                workday,
                (
                    checkins_by_workday.get(
                        workday.name,
                        [],
                    )
                    if workday
                    else []
                ),
                leave,
                has_valid_wwh,
            )
        )

        if (
            day_row[
                "snapshot_status"
            ]
            in BLOCKING_SNAPSHOT_STATUSES
        ):
            blocking_issue_count += 1

        day_rows.append(
            day_row
        )

        report_date += (
            timedelta(
                days=1
            )
        )

    opening_balance_minutes = (
        _get_opening_balance(
            employee,
            period_from,
        )
    )

    period_ledger_entries = (
        _get_period_ledger_entries(
            employee,
            period_from,
            period_to,
        )
    )

    ledger_rows = (
        _build_ledger_snapshot(
            period_ledger_entries
        )
    )

    ledger_movement_minutes = sum(
        cint(
            row[
                "delta_minutes"
            ]
        )
        for row in ledger_rows
    )

    closing_balance_minutes = (
        opening_balance_minutes
        + ledger_movement_minutes
    )

    generated_at = (
        reference_datetime
        or now_datetime()
    )

    generated_by = (
        getattr(
            frappe.session,
            "user",
            None,
        )
        or "Administrator"
    )

    employee_name = (
        employee_row.employee_name
        or employee
    )

    return {
        "doctype": (
            "Monthly Time Report"
        ),
        "employee": (
            employee
        ),
        "employee_name": (
            employee_name
        ),
        "report_title": (
            f"{employee_name} · "
            f"{cint(year):04d}-"
            f"{cint(month):02d}"
        ),
        "report_year": (
            cint(
                year
            )
        ),
        "report_month": (
            cint(
                month
            )
        ),
        "period_from": (
            period_from
        ),
        "period_to": (
            period_to
        ),
        "opening_balance_minutes": (
            opening_balance_minutes
        ),
        "ledger_movement_minutes": (
            ledger_movement_minutes
        ),
        "closing_balance_minutes": (
            closing_balance_minutes
        ),
        "is_complete": (
            1
            if blocking_issue_count == 0
            else 0
        ),
        "blocking_issue_count": (
            blocking_issue_count
        ),
        "revision": 1,
        "previous_revision": None,
        "is_current_revision": 1,
        "status": (
            STATUS_GENERATED
        ),
        "generated_at": (
            generated_at
        ),
        "generated_by": (
            generated_by
        ),
        "days": (
            day_rows
        ),
        "ledger_entries": (
            ledger_rows
        ),
        "employee_document": None,
        "pdf_file": None,
    }


def create_monthly_time_report_snapshot(
    employee,
    year,
    month,
    reference_datetime=None,
):
    (
        period_from,
        period_to,
    ) = get_report_period(
        year,
        month,
    )

    existing = (
        frappe.db.get_value(
            "Monthly Time Report",
            {
                "employee": (
                    employee
                ),
                "period_from": (
                    period_from
                ),
                "period_to": (
                    period_to
                ),
                "is_current_revision": 1,
            },
            "name",
        )
    )

    if existing:
        frappe.throw(
            _(
                "Current Monthly Time Report "
                "{0} already exists for "
                "employee {1} and this period."
            ).format(
                existing,
                employee,
            )
        )

    values = (
        build_monthly_time_report_snapshot(
            employee,
            year,
            month,
            reference_datetime=(
                reference_datetime
            ),
        )
    )

    doc = frappe.get_doc(
        values
    )

    doc.flags[
        SERVICE_FLAG
    ] = True

    return doc.insert(
        ignore_permissions=True
    )
