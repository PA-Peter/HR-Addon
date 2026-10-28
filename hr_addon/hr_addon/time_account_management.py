# Copyright (c) 2026, RieckMedia
# Stage 7.5 – Time account management.
# Initial implementation: read-only booking preview.

from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils import cint, getdate, now_datetime


MANAGEMENT_ROLES = frozenset({
    "HR Manager",
    "System Manager",
})

ALLOWED_ENTRY_TYPES = frozenset({
    "Payout",
    "Positive Adjustment",
    "Negative Adjustment",
})


def _require_manager():
    user = frappe.session.user

    if not user or user == "Guest":
        frappe.throw(
            _("Manager permission required."),
            frappe.PermissionError,
        )

    if user == "Administrator":
        return

    if not MANAGEMENT_ROLES.intersection(
        frappe.get_roles(user)
    ):
        frappe.throw(
            _("Manager permission required."),
            frappe.PermissionError,
        )


def _parse_date(value):
    try:
        value = str(value)
        result = datetime.strptime(
            value, "%Y-%m-%d"
        ).date()

        if result.isoformat() != value:
            raise ValueError

        return result

    except (ValueError, TypeError):
        frappe.throw(
            _("Invalid booking date. Use YYYY-MM-DD.")
        )


def _validate_period(booking_date):
    today = getdate(now_datetime())
    current_start = today.replace(day=1)

    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)

    if (
        booking_date < previous_start
        or booking_date > today
    ):
        frappe.throw(
            _(
                "Booking date must be within the "
                "current or previous calendar month "
                "and cannot be in the future."
            )
        )

    return today


def _parse_minutes(hours, minutes):
    values = []

    for value in (hours, minutes):
        if (
            isinstance(value, bool)
            or not str(value).isdigit()
        ):
            frappe.throw(
                _("Hours and minutes must be whole numbers.")
            )

        values.append(int(value))

    hh, mm = values

    if hh > 9999 or mm > 59:
        frappe.throw(
            _("Invalid HH:MM value.")
        )

    total = hh * 60 + mm

    if total == 0:
        frappe.throw(
            _("Booking amount must not be zero.")
        )

    return total


def _prepare_request(
    employee,
    effective_date,
    entry_type,
    hours,
    minutes,
):
    _require_manager()

    if not employee or not frappe.db.exists(
        "Employee", employee
    ):
        frappe.throw(
            _("Employee not found.")
        )

    if entry_type not in ALLOWED_ENTRY_TYPES:
        frappe.throw(
            _("This entry type is not allowed.")
        )

    booking_date = _parse_date(effective_date)
    today = _validate_period(booking_date)

    amount = _parse_minutes(hours, minutes)

    delta = (
        amount
        if entry_type == "Positive Adjustment"
        else -amount
    )

    return frappe._dict({
        "employee": employee,
        "effective_date": booking_date,
        "today": today,
        "entry_type": entry_type,
        "delta_minutes": delta,
    })


def _balance_as_of(employee, date):
    rows = frappe.db.sql(
        """
        SELECT COALESCE(SUM(delta_minutes), 0)
        FROM `tabTime Account Ledger Entry`
        WHERE employee = %s
          AND effective_date <= %s
        """,
        (employee, date),
    )

    return cint(rows[0][0])


@frappe.whitelist()
def get_manual_time_account_preview(
    employee,
    effective_date,
    entry_type,
    hours,
    minutes,
):
    """Manager-only preview. Never writes ledger entries."""

    request = _prepare_request(
        employee,
        effective_date,
        entry_type,
        hours,
        minutes,
    )

    _reject_reset_closed_period(
        request.employee,
        request.effective_date,
    )

    balance_at_date = _balance_as_of(
        employee,
        request.effective_date,
    )

    current_balance = _balance_as_of(
        employee,
        request.today,
    )

    delta = request.delta_minutes

    return {
        "employee": employee,
        "employee_name": frappe.db.get_value(
            "Employee", employee, "employee_name"
        ),
        "effective_date": (
            request.effective_date.isoformat()
        ),
        "entry_type": entry_type,
        "delta_minutes": delta,
        "balance_at_date_before": balance_at_date,
        "balance_at_date_after": balance_at_date + delta,
        "current_balance_before": current_balance,
        "current_balance_after": current_balance + delta,
        "preview_only": True,
    }


@frappe.whitelist(methods=["POST"])
def post_manual_time_account_entry(
    employee,
    effective_date,
    entry_type,
    hours,
    minutes,
    remarks,
    expected_balance,
):
    """
    Manager-only manual booking.

    Requires a fresh preview balance.
    Uses the existing append-only ledger service.
    Transaction commit is handled by Frappe's POST lifecycle.
    """

    import re

    from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
        create_manual_time_account_entry,
    )

    request = _prepare_request(
        employee,
        effective_date,
        entry_type,
        hours,
        minutes,
    )

    if not isinstance(remarks, str):
        frappe.throw(_("Remarks are required."))

    remarks = remarks.strip()

    if not remarks or len(remarks) > 500:
        frappe.throw(
            _("Remarks must contain 1 to 500 characters.")
        )

    # The client must supply the balance shown
    # in the immediately preceding preview.
    raw_balance = str(expected_balance)

    if not re.fullmatch(
        r"-?(0|[1-9][0-9]*)",
        raw_balance,
    ):
        frappe.throw(
            _("Invalid expected balance.")
        )

    expected = int(raw_balance)

    if abs(expected) > 100000000:
        frappe.throw(
            _("Expected balance is out of range.")
        )

    # Serialize concurrent manager bookings
    # for the same employee.
    locked_employee = frappe.db.sql(
        """
        SELECT name
        FROM `tabEmployee`
        WHERE name = %s
        FOR UPDATE
        """,
        (request.employee,),
    )

    if len(locked_employee) != 1:
        frappe.throw(_("Employee not found."))

    # Lock ledger rows and use a current read rather
    # than a potentially stale transaction snapshot.
    def locked_balance():
        rows = frappe.db.sql(
            """
            SELECT delta_minutes
            FROM `tabTime Account Ledger Entry`
            WHERE employee = %s
              AND effective_date <= %s
            FOR UPDATE
            """,
            (
                request.employee,
                request.today,
            ),
        )

        return sum(
            cint(row[0])
            for row in rows
        )

    _reject_reset_closed_period(
        request.employee,
        request.effective_date,
    )

    current = locked_balance()

    if current != expected:
        frappe.throw(
            _(
                "Time account balance changed. "
                "Refresh the preview before booking. "
                "Expected {0}, current {1} minutes."
            ).format(expected, current)
        )

    # Identical existing bookings are not repeated.
    duplicate = frappe.db.sql(
        """
        SELECT name
        FROM `tabTime Account Ledger Entry`
        WHERE employee = %s
          AND effective_date = %s
          AND entry_type = %s
          AND delta_minutes = %s
          AND remarks = %s
        LIMIT 1
        """,
        (
            request.employee,
            request.effective_date,
            request.entry_type,
            request.delta_minutes,
            remarks,
        ),
    )

    if duplicate:
        frappe.throw(
            _(
                "An identical booking already exists: {0}"
            ).format(duplicate[0][0])
        )

    entry = create_manual_time_account_entry(
        employee=request.employee,
        effective_date=request.effective_date,
        entry_type=request.entry_type,
        delta_minutes=request.delta_minutes,
        remarks=remarks,
    )

    actual_after = locked_balance()
    expected_after = current + request.delta_minutes

    if actual_after != expected_after:
        frappe.throw(
            _(
                "Post-booking balance validation failed. "
                "The transaction must be rolled back."
            )
        )

    return {
        "ledger_entry": entry.name,
        "employee": request.employee,
        "effective_date": (
            request.effective_date.isoformat()
        ),
        "entry_type": request.entry_type,
        "delta_minutes": request.delta_minutes,
        "balance_before": current,
        "balance_after": actual_after,
        "remarks": remarks,
    }


@frappe.whitelist()
def get_manual_reversal_preview(entry_name):
    """Read-only manager preview for reversing a manual entry."""

    _require_manager()

    if not isinstance(entry_name, str) or not entry_name.strip():
        frappe.throw(_("Ledger entry is required."))

    entry_name = entry_name.strip()

    original = frappe.db.get_value(
        "Time Account Ledger Entry",
        entry_name,
        [
            "name",
            "employee",
            "effective_date",
            "entry_type",
            "delta_minutes",
            "remarks",
            "voucher_type",
            "voucher_no",
        ],
        as_dict=True,
    )

    if not original:
        frappe.throw(_("Ledger entry not found."))

    # Never allow manually reversing automatic Workday entries
    # or opening balances through the manager interface.
    if original.entry_type not in ALLOWED_ENTRY_TYPES:
        frappe.throw(
            _(
                "Only Payout, Positive Adjustment and "
                "Negative Adjustment may be reversed here."
            )
        )


    # System-generated adjustments belong to their
    # source process, not to manual HR reversals.
    if original.voucher_type or original.voucher_no:
        frappe.throw(
            _(
                "Source-linked ledger entries cannot "
                "be reversed through manual management."
            )
        )

    _reject_reset_closed_period(
        original.employee,
        original.effective_date,
    )

    existing = frappe.db.exists(
        "Time Account Ledger Entry",
        {
            "entry_type": "Reversal",
            "reverses_entry": entry_name,
        },
    )

    if existing:
        frappe.throw(
            _("This ledger entry has already been reversed.")
        )

    today = getdate(now_datetime())
    current_start = today.replace(day=1)
    previous_end = current_start - timedelta(days=1)
    previous_start = previous_end.replace(day=1)

    booking_date = getdate(original.effective_date)

    if booking_date > today:
        frappe.throw(
            _("A future-dated entry cannot be reversed here.")
        )

    older_period = booking_date < previous_start

    if older_period:
        frappe.throw(
            _(
                "This accounting period is finalized. "
                "Historical manual reversals are not permitted. "
                "Create an adjustment in the current open period "
                "and document the original transaction date."
            )
        )

    reversal_delta = -cint(original.delta_minutes)

    balance_at_date = _balance_as_of(
        original.employee,
        booking_date,
    )

    current_balance = _balance_as_of(
        original.employee,
        today,
    )

    return {
        "preview_only": True,
        "original_entry": entry_name,
        "employee": original.employee,
        "employee_name": frappe.db.get_value(
            "Employee",
            original.employee,
            "employee_name",
        ),
        "effective_date": booking_date.isoformat(),
        "original_entry_type": original.entry_type,
        "original_delta_minutes": cint(original.delta_minutes),
        "original_remarks": original.remarks or "",
        "reversal_delta_minutes": reversal_delta,
        "balance_at_date_before": balance_at_date,
        "balance_at_date_after": (
            balance_at_date + reversal_delta
        ),
        "current_balance_before": current_balance,
        "current_balance_after": (
            current_balance + reversal_delta
        ),
        "older_period": older_period,
        "requires_admin_override": older_period,
    }


@frappe.whitelist(methods=["POST"])
def post_manual_time_account_reversal(
    entry_name,
    remarks,
    expected_balance,
):
    """Manager-only reversal of an ordinary manual ledger entry."""

    import re

    from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
        reverse_time_account_entry,
    )

    _require_manager()

    if not isinstance(entry_name, str) or not entry_name.strip():
        frappe.throw(_("Ledger entry is required."))

    entry_name = entry_name.strip()

    if not isinstance(remarks, str):
        frappe.throw(_("Reversal reason is required."))

    remarks = remarks.strip()

    if not remarks or len(remarks) > 500:
        frappe.throw(
            _("Reversal reason must contain 1 to 500 characters.")
        )

    raw_balance = str(expected_balance)

    if not re.fullmatch(r"-?(0|[1-9][0-9]*)", raw_balance):
        frappe.throw(_("Invalid expected balance."))

    expected = int(raw_balance)

    if abs(expected) > 100000000:
        frappe.throw(_("Expected balance is out of range."))

    # Initial lookup: obtain employee for lock ordering.
    employee = frappe.db.get_value(
        "Time Account Ledger Entry",
        entry_name,
        "employee",
    )

    if not employee:
        frappe.throw(_("Ledger entry not found."))

    # Use the same employee-first lock order as
    # the existing manager booking API.
    locked_employee = frappe.db.sql(
        """
        SELECT name
        FROM `tabEmployee`
        WHERE name = %s
        FOR UPDATE
        """,
        (employee,),
    )

    if len(locked_employee) != 1:
        frappe.throw(_("Employee not found."))

    originals = frappe.db.sql(
        """
        SELECT
            name,
            employee,
            effective_date,
            entry_type,
            delta_minutes,
            voucher_type,
            voucher_no
        FROM `tabTime Account Ledger Entry`
        WHERE name = %s
        FOR UPDATE
        """,
        (entry_name,),
        as_dict=True,
    )

    if len(originals) != 1:
        frappe.throw(_("Ledger entry not found."))

    original = originals[0]

    if original.employee != employee:
        frappe.throw(_("Employee reference changed."))

    if original.entry_type not in ALLOWED_ENTRY_TYPES:
        frappe.throw(
            _("This ledger entry cannot be manually reversed.")
        )

    if original.voucher_type or original.voucher_no:
        frappe.throw(
            _("Source-linked entries cannot be manually reversed.")
        )

    # Until the administrative override is implemented,
    # this deliberately rejects historical periods.
    today = _validate_period(
        getdate(original.effective_date)
    )

    _reject_reset_closed_period(
        original.employee,
        original.effective_date,
    )

    previous_reversal = frappe.db.sql(
        """
        SELECT name
        FROM `tabTime Account Ledger Entry`
        WHERE entry_type = 'Reversal'
          AND reverses_entry = %s
        LIMIT 1
        FOR UPDATE
        """,
        (entry_name,),
    )

    if previous_reversal:
        frappe.throw(
            _("This ledger entry has already been reversed.")
        )

    def locked_balance():
        rows = frappe.db.sql(
            """
            SELECT delta_minutes
            FROM `tabTime Account Ledger Entry`
            WHERE employee = %s
              AND effective_date <= %s
            FOR UPDATE
            """,
            (employee, today),
        )

        return sum(cint(row[0]) for row in rows)

    current = locked_balance()

    if current != expected:
        frappe.throw(
            _(
                "Time account balance changed. "
                "Refresh the reversal preview. "
                "Expected {0}, current {1} minutes."
            ).format(expected, current)
        )

    reversal_delta = -cint(original.delta_minutes)

    reversal = reverse_time_account_entry(
        entry_name,
        remarks=remarks,
    )

    actual_after = locked_balance()
    expected_after = current + reversal_delta

    if (
        actual_after != expected_after
        or reversal.reverses_entry != entry_name
        or cint(reversal.delta_minutes) != reversal_delta
    ):
        frappe.throw(
            _(
                "Reversal validation failed. "
                "The transaction must be rolled back."
            )
        )

    return {
        "reversal_entry": reversal.name,
        "original_entry": entry_name,
        "employee": employee,
        "effective_date": getdate(
            original.effective_date
        ).isoformat(),
        "delta_minutes": reversal_delta,
        "balance_before": current,
        "balance_after": actual_after,
        "remarks": remarks,
    }


def _reject_reset_closed_period(employee, effective_date):
    """Reject retroactive changes crossing a posted monthly reset."""

    booking_date = getdate(effective_date)

    resets = frappe.db.sql(
        """
        SELECT
            name,
            effective_date,
            voucher_no
        FROM `tabTime Account Ledger Entry`
        WHERE employee = %s
          AND effective_date >= %s
          AND entry_type IN (
              'Positive Adjustment',
              'Negative Adjustment'
          )
          AND voucher_type = 'Weekly Working Hours'
          AND voucher_no IS NOT NULL
          AND voucher_no != ''
        ORDER BY effective_date ASC, name ASC
        LIMIT 1
        """,
        (employee, booking_date),
        as_dict=True,
    )

    if resets:
        reset = resets[0]

        frappe.throw(
            _(
                "The time account period is already closed "
                "by monthly reset {0} dated {1}. "
                "Retroactive manual bookings or reversals "
                "are not permitted. Create an adjustment "
                "in an open period instead."
            ).format(
                reset.name,
                getdate(reset.effective_date).isoformat(),
            )
        )
