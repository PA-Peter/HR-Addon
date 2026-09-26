# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe

from frappe import _
from frappe.utils import cint, get_datetime, getdate, now_datetime


KIOSK_DEVICE_ID = "RM-KIOSK"
DEBOUNCE_SECONDS = 3

VALID_LOG_TYPES = {
    "IN",
    "OUT",
}

def _clean_attendance_device_id(
    attendance_device_id,
):
    """
    RFID/HID values are identifiers, not numbers.

    In particular, leading zeroes must never be removed by
    numeric conversion.
    """
    if not isinstance(
        attendance_device_id,
        str,
    ):
        frappe.throw(
            _(
                "Attendance Device ID must be "
                "provided as text."
            )
        )

    clean_value = (
        attendance_device_id.strip()
    )

    if not clean_value:
        frappe.throw(
            _("Attendance Device ID is required.")
        )

    return clean_value


def _clean_log_type(log_type):
    clean_log_type = str(
        log_type or ""
    ).strip().upper()

    if clean_log_type not in VALID_LOG_TYPES:
        frappe.throw(
            _(
                "Log Type must be IN or OUT."
            )
        )

    return clean_log_type


def _resolve_and_lock_employee(
    attendance_device_id,
):
    """
    Resolve the RFID/HID value exactly against
    Employee.attendance_device_id.

    The Employee rows are locked for the current transaction so
    concurrent punch requests for the same employee are serialized.
    """
    employees = frappe.db.sql(
        """
        SELECT
            name,
            employee_name,
            status,
            attendance_device_id
        FROM
            `tabEmployee`
        WHERE
            attendance_device_id = %s
        FOR UPDATE
        """,
        (attendance_device_id,),
        as_dict=True,
    )

    if not employees:
        frappe.throw(
            _(
                "No Employee is assigned to "
                "Attendance Device ID {0}."
            ).format(
                attendance_device_id
            )
        )

    if len(employees) > 1:
        frappe.throw(
            _(
                "Attendance Device ID {0} is assigned "
                "to more than one Employee. "
                "Punching was stopped."
            ).format(
                attendance_device_id
            )
        )

    employee = employees[0]

    if employee.status != "Active":
        frappe.throw(
            _(
                "Employee {0} is not active. "
                "Punching was stopped."
            ).format(
                employee.employee_name
                or employee.name
            )
        )

    return employee


def _get_recent_identical_kiosk_punch(
    employee,
    log_type,
    current_time,
):
    """
    Return the last identical kiosk punch inside the debounce
    window.

    IN followed by OUT is intentionally NOT suppressed.
    """
    window_start = (
        current_time
        - timedelta(
            seconds=DEBOUNCE_SECONDS
        )
    )

    rows = frappe.db.sql(
        """
        SELECT
            name,
            time
        FROM
            `tabEmployee Checkin`
        WHERE
            employee = %s
            AND log_type = %s
            AND device_id = %s
            AND time >= %s
            AND time <= %s
        ORDER BY
            time DESC,
            creation DESC
        LIMIT 1
        """,
        (
            employee,
            log_type,
            KIOSK_DEVICE_ID,
            window_start,
            current_time,
        ),
        as_dict=True,
    )

    if not rows:
        return None

    return rows[0]


def _get_balance_before_date(
    employee,
    before_date,
):
    """
    Time-account balance at 00:00 of before_date.

    Therefore the kiosk balance for today uses:
        effective_date < today

    Opening Balance is not special-cased. Once imported later,
    it automatically becomes part of this SUM.
    """
    rows = frappe.db.sql(
        """
        SELECT
            COALESCE(
                SUM(delta_minutes),
                0
            ) AS balance_minutes
        FROM
            `tabTime Account Ledger Entry`
        WHERE
            employee = %s
            AND effective_date < %s
        """,
        (
            employee,
            before_date,
        ),
        as_dict=True,
    )

    if not rows:
        return 0

    return cint(
        rows[0].balance_minutes
    )


def _get_open_checkin_error_count(
    employee,
    before_date,
):
    """
    Only historical Workdays count.

    The current day is deliberately excluded because an IN
    without the later OUT is normal while the employee is still
    working.
    """
    rows = frappe.db.sql(
        """
        SELECT
            COUNT(*) AS error_count
        FROM
            `tabWorkday`
        WHERE
            employee = %s
            AND log_date < %s
            AND status = 'Missing Checkin'
        """,
        (
            employee,
            before_date,
        ),
        as_dict=True,
    )

    if not rows:
        return 0

    return cint(
        rows[0].error_count
    )


def _build_punch_result(
    employee,
    log_type,
    checkin_name,
    checkin_time,
    current_date,
    debounced=False,
):
    balance_minutes = (
        _get_balance_before_date(
            employee.name,
            current_date,
        )
    )

    open_checkin_errors = (
        _get_open_checkin_error_count(
            employee.name,
            current_date,
        )
    )

    balance_as_of = (
        current_date
        - timedelta(days=1)
    )

    return frappe._dict(
        {
            "employee": employee.name,
            "employee_name": (
                employee.employee_name
            ),
            "log_type": log_type,
            "time": checkin_time,
            "employee_checkin": (
                checkin_name
            ),
            "debounced": bool(
                debounced
            ),
            "balance_minutes": (
                balance_minutes
            ),
            "balance_as_of": (
                balance_as_of
            ),
            "open_checkin_errors": (
                open_checkin_errors
            ),
        }
    )


def process_punch(
    attendance_device_id,
    log_type,
    current_time=None,
):
    """
    Core Stage-6.1 punch service.

    current_time exists only as an internal/test seam.
    The public endpoint never accepts a caller supplied timestamp.
    """
    clean_device_id = (
        _clean_attendance_device_id(
            attendance_device_id
        )
    )

    clean_log_type = (
        _clean_log_type(
            log_type
        )
    )

    effective_time = get_datetime(
        current_time
        or now_datetime()
    ).replace(
        microsecond=0
    )

    current_date = getdate(
        effective_time
    )

    employee = (
        _resolve_and_lock_employee(
            clean_device_id
        )
    )

    recent_punch = (
        _get_recent_identical_kiosk_punch(
            employee.name,
            clean_log_type,
            effective_time,
        )
    )

    if recent_punch:
        return _build_punch_result(
            employee=employee,
            log_type=clean_log_type,
            checkin_name=(
                recent_punch.name
            ),
            checkin_time=(
                recent_punch.time
            ),
            current_date=current_date,
            debounced=True,
        )

    checkin = frappe.get_doc(
        {
            "doctype": (
                "Employee Checkin"
            ),
            "employee": (
                employee.name
            ),
            "time": effective_time,
            "log_type": (
                clean_log_type
            ),
            "device_id": (
                KIOSK_DEVICE_ID
            ),
        }
    )

    checkin.insert(
        ignore_permissions=True
    )

    return _build_punch_result(
        employee=employee,
        log_type=clean_log_type,
        checkin_name=checkin.name,
        checkin_time=checkin.time,
        current_date=current_date,
        debounced=False,
    )


@frappe.whitelist(
    allow_guest=True,
    methods=["POST"],
)
def punch(
    attendance_device_id,
    log_type,
):
    """
    Login-free kiosk/terminal punch endpoint.

    The endpoint deliberately exposes only the narrow punch contract:
    Attendance Device ID plus explicit IN or OUT. The timestamp is
    always generated by the server; all actual processing remains in
    process_punch().
    """
    return process_punch(
        attendance_device_id=(
            attendance_device_id
        ),
        log_type=log_type,
    )
