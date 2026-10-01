# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import calendar

import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate


SERVICE_FLAG = "monthly_time_report_service"

STATUS_GENERATED = "Generated"
STATUS_SUPERSEDED = "Superseded"

VALID_STATUSES = {
    STATUS_GENERATED,
    STATUS_SUPERSEDED,
}


class MonthlyTimeReport(Document):
    def validate(self):
        _validate_service_origin(
            self
        )

        _validate_report_identity(
            self
        )

        _validate_snapshot_consistency(
            self
        )

    def on_trash(self):
        frappe.throw(
            _(
                "Monthly Time Reports cannot "
                "be deleted. Generate a new "
                "revision instead."
            )
        )


def _validate_service_origin(doc):
    if doc.flags.get(
        SERVICE_FLAG
    ):
        return

    frappe.throw(
        _(
            "Monthly Time Reports may only "
            "be created or changed by the "
            "Monthly Time Report service."
        )
    )


def _validate_report_identity(doc):
    year = cint(
        doc.report_year
    )

    month = cint(
        doc.report_month
    )

    if year < 2000:
        frappe.throw(
            _(
                "Report Year is invalid."
            )
        )

    if month < 1 or month > 12:
        frappe.throw(
            _(
                "Report Month must be "
                "between 1 and 12."
            )
        )

    expected_from = getdate(
        f"{year:04d}-{month:02d}-01"
    )

    expected_to = getdate(
        (
            f"{year:04d}-{month:02d}-"
            f"{calendar.monthrange(year, month)[1]:02d}"
        )
    )

    if (
        getdate(
            doc.period_from
        )
        != expected_from
        or getdate(
            doc.period_to
        )
        != expected_to
    ):
        frappe.throw(
            _(
                "Period From and Period To "
                "must exactly match the "
                "selected calendar month."
            )
        )

    if cint(
        doc.revision
    ) < 1:
        frappe.throw(
            _(
                "Revision must be at least 1."
            )
        )

    if (
        doc.status
        not in VALID_STATUSES
    ):
        frappe.throw(
            _(
                "Invalid Monthly Time Report "
                "status: {0}"
            ).format(
                doc.status
            )
        )


def _validate_snapshot_consistency(
    doc,
):
    expected_days = (
        calendar.monthrange(
            cint(
                doc.report_year
            ),
            cint(
                doc.report_month
            ),
        )[1]
    )

    if len(
        doc.days or []
    ) != expected_days:
        frappe.throw(
            _(
                "Monthly Time Report must "
                "contain exactly one day row "
                "for every calendar day."
            )
        )

    day_dates = [
        getdate(
            row.report_date
        )
        for row in (
            doc.days or []
        )
    ]

    if len(
        set(
            day_dates
        )
    ) != len(
        day_dates
    ):
        frappe.throw(
            _(
                "Monthly Time Report contains "
                "duplicate day rows."
            )
        )

    if day_dates:
        if (
            min(
                day_dates
            )
            != getdate(
                doc.period_from
            )
            or max(
                day_dates
            )
            != getdate(
                doc.period_to
            )
        ):
            frappe.throw(
                _(
                    "Monthly Time Report day "
                    "rows do not cover the "
                    "complete report period."
                )
            )

    blocking_issue_count = sum(
        1
        for row in (
            doc.days or []
        )
        if row.snapshot_status
        in {
            "No Working Hours Model",
            "Missing Workday",
        }
    )

    if (
        cint(
            doc.blocking_issue_count
        )
        != blocking_issue_count
    ):
        frappe.throw(
            _(
                "Blocking Issue Count does "
                "not match the daily snapshot."
            )
        )

    expected_complete = (
        1
        if blocking_issue_count == 0
        else 0
    )

    if (
        cint(
            doc.is_complete
        )
        != expected_complete
    ):
        frappe.throw(
            _(
                "Complete flag does not match "
                "the daily snapshot."
            )
        )

    ledger_movement_minutes = sum(
        cint(
            row.delta_minutes
        )
        for row in (
            doc.ledger_entries or []
        )
    )

    if (
        cint(
            doc.ledger_movement_minutes
        )
        != ledger_movement_minutes
    ):
        frappe.throw(
            _(
                "Ledger Movement Minutes do "
                "not match the ledger snapshot."
            )
        )

    expected_closing_balance = (
        cint(
            doc.opening_balance_minutes
        )
        + ledger_movement_minutes
    )

    if (
        cint(
            doc.closing_balance_minutes
        )
        != expected_closing_balance
    ):
        frappe.throw(
            _(
                "Closing Balance Minutes do "
                "not match Opening Balance "
                "plus ledger movements."
            )
        )
