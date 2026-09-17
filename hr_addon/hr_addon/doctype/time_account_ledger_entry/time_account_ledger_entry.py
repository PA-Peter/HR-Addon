# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate


ENTRY_TYPE_WORKDAY = "Workday"
ENTRY_TYPE_REVERSAL = "Reversal"
ENTRY_TYPE_OPENING_BALANCE = "Opening Balance"
ENTRY_TYPE_PAYOUT = "Payout"
ENTRY_TYPE_POSITIVE_ADJUSTMENT = "Positive Adjustment"
ENTRY_TYPE_NEGATIVE_ADJUSTMENT = "Negative Adjustment"


ENTRY_TYPES = (
    ENTRY_TYPE_WORKDAY,
    ENTRY_TYPE_REVERSAL,
    ENTRY_TYPE_OPENING_BALANCE,
    ENTRY_TYPE_PAYOUT,
    ENTRY_TYPE_POSITIVE_ADJUSTMENT,
    ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
)


MANUAL_ENTRY_TYPES = (
    ENTRY_TYPE_OPENING_BALANCE,
    ENTRY_TYPE_PAYOUT,
    ENTRY_TYPE_POSITIVE_ADJUSTMENT,
    ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
)


class TimeAccountLedgerEntry(Document):
    def validate(self):
        self._validate_immutable()
        self._validate_entry_type()

        if self.entry_type == ENTRY_TYPE_REVERSAL:
            self._apply_reversal()
        else:
            self._validate_non_reversal_reference()

        self.delta_minutes = cint(self.delta_minutes)

        self._validate_non_zero_delta()
        self._validate_entry_type_sign()
        self._validate_workday_source()
        self._validate_manual_remarks()

    def _validate_immutable(self):
        if not self.is_new():
            frappe.throw(
                _(
                    "Time Account Ledger Entry {0} is immutable. "
                    "Create a reversal or adjustment instead."
                ).format(self.name)
            )

    def _validate_entry_type(self):
        if self.entry_type not in ENTRY_TYPES:
            frappe.throw(
                _("Invalid Time Account Ledger Entry type: {0}").format(
                    self.entry_type
                )
            )

    def _validate_non_zero_delta(self):
        if self.delta_minutes == 0:
            frappe.throw(
                _(
                    "A Time Account Ledger Entry with Delta Minutes 0 "
                    "is not permitted."
                )
            )

    def _validate_entry_type_sign(self):
        if (
            self.entry_type == ENTRY_TYPE_PAYOUT
            and self.delta_minutes >= 0
        ):
            frappe.throw(
                _("Payout must have a negative Delta Minutes value.")
            )

        if (
            self.entry_type == ENTRY_TYPE_POSITIVE_ADJUSTMENT
            and self.delta_minutes <= 0
        ):
            frappe.throw(
                _(
                    "Positive Adjustment must have a positive "
                    "Delta Minutes value."
                )
            )

        if (
            self.entry_type == ENTRY_TYPE_NEGATIVE_ADJUSTMENT
            and self.delta_minutes >= 0
        ):
            frappe.throw(
                _(
                    "Negative Adjustment must have a negative "
                    "Delta Minutes value."
                )
            )

    def _validate_non_reversal_reference(self):
        if self.reverses_entry:
            frappe.throw(
                _(
                    "Reverses Entry may only be used for "
                    "Entry Type Reversal."
                )
            )

    def _apply_reversal(self):
        if not self.reverses_entry:
            frappe.throw(
                _("Reversal requires Reverses Entry.")
            )

        original = frappe.db.get_value(
            "Time Account Ledger Entry",
            self.reverses_entry,
            [
                "employee",
                "effective_date",
                "effective_time",
                "delta_minutes",
                "entry_type",
                "voucher_type",
                "voucher_no",
            ],
            as_dict=True,
        )

        if not original:
            frappe.throw(
                _(
                    "Ledger entry {0} does not exist."
                ).format(self.reverses_entry)
            )

        if original.entry_type == ENTRY_TYPE_REVERSAL:
            frappe.throw(
                _(
                    "A Reversal entry cannot itself be reversed."
                )
            )

        existing_reversal = frappe.db.get_value(
            "Time Account Ledger Entry",
            {
                "entry_type": ENTRY_TYPE_REVERSAL,
                "reverses_entry": self.reverses_entry,
            },
            "name",
        )

        if existing_reversal and existing_reversal != self.name:
            frappe.throw(
                _(
                    "Ledger entry {0} has already been reversed by {1}."
                ).format(
                    self.reverses_entry,
                    existing_reversal,
                )
            )

        self.employee = original.employee
        self.effective_date = original.effective_date
        self.effective_time = original.effective_time

        self.delta_minutes = -cint(
            original.delta_minutes
        )

        self.voucher_type = original.voucher_type
        self.voucher_no = original.voucher_no

    def _validate_workday_source(self):
        if self.entry_type != ENTRY_TYPE_WORKDAY:
            return

        if self.voucher_type != "Workday":
            frappe.throw(
                _(
                    "Workday ledger entries require "
                    "Voucher Type Workday."
                )
            )

        if not self.voucher_no:
            frappe.throw(
                _(
                    "Workday ledger entries require "
                    "a Workday Voucher No."
                )
            )

        workday = frappe.db.get_value(
            "Workday",
            self.voucher_no,
            [
                "employee",
                "log_date",
                "daily_delta_minutes",
            ],
            as_dict=True,
        )

        if not workday:
            frappe.throw(
                _(
                    "Workday {0} does not exist."
                ).format(self.voucher_no)
            )

        if self.employee != workday.employee:
            frappe.throw(
                _(
                    "Ledger employee does not match "
                    "the Workday employee."
                )
            )

        if (
            getdate(self.effective_date)
            != getdate(workday.log_date)
        ):
            frappe.throw(
                _(
                    "Effective Date must match "
                    "the Workday date."
                )
            )

        if (
            cint(self.delta_minutes)
            != cint(workday.daily_delta_minutes)
        ):
            frappe.throw(
                _(
                    "Delta Minutes must match "
                    "the Workday Daily Delta Minutes."
                )
            )

    def _validate_manual_remarks(self):
        if (
            self.entry_type in MANUAL_ENTRY_TYPES
            and not str(self.remarks or "").strip()
        ):
            frappe.throw(
                _(
                    "Remarks are required for manual "
                    "time-account entries."
                )
            )

    def on_trash(self):
        frappe.throw(
            _(
                "Time Account Ledger Entries cannot be deleted. "
                "Create a reversal instead."
            )
        )


def get_time_account_balance(employee):
    if not employee:
        frappe.throw(_("Employee is required."))

    result = frappe.db.sql(
        """
        SELECT
            COALESCE(SUM(delta_minutes), 0)
        FROM
            `tabTime Account Ledger Entry`
        WHERE
            employee = %s
        """,
        (employee,),
    )

    if not result:
        return 0

    return cint(result[0][0])
