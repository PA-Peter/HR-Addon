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


def _get_workday_for_update(workday_name):
    if not workday_name:
        frappe.throw(_("Workday is required."))

    rows = frappe.db.sql(
        """
        SELECT
            name,
            employee,
            log_date,
            daily_delta_minutes
        FROM
            `tabWorkday`
        WHERE
            name = %s
        FOR UPDATE
        """,
        (workday_name,),
        as_dict=True,
    )

    if not rows:
        frappe.throw(
            _("Workday {0} does not exist.").format(
                workday_name
            )
        )

    return rows[0]


def _get_active_workday_ledger_entries(workday_name):
    return frappe.db.sql(
        """
        SELECT
            workday_entry.name,
            workday_entry.employee,
            workday_entry.delta_minutes
        FROM
            `tabTime Account Ledger Entry` AS workday_entry
        LEFT JOIN
            `tabTime Account Ledger Entry` AS reversal
            ON reversal.reverses_entry = workday_entry.name
            AND reversal.entry_type = %s
        WHERE
            workday_entry.entry_type = %s
            AND workday_entry.voucher_type = 'Workday'
            AND workday_entry.voucher_no = %s
            AND reversal.name IS NULL
        ORDER BY
            workday_entry.creation ASC,
            workday_entry.name ASC
        """,
        (
            ENTRY_TYPE_REVERSAL,
            ENTRY_TYPE_WORKDAY,
            workday_name,
        ),
        as_dict=True,
    )


def reverse_time_account_entry(entry_name):
    original = frappe.db.get_value(
        "Time Account Ledger Entry",
        entry_name,
        [
            "employee",
            "effective_date",
            "effective_time",
            "delta_minutes",
        ],
        as_dict=True,
    )

    if not original:
        frappe.throw(
            _("Ledger entry {0} does not exist.").format(
                entry_name
            )
        )

    return frappe.get_doc(
        {
            "doctype": "Time Account Ledger Entry",
            "employee": original.employee,
            "effective_date": original.effective_date,
            "effective_time": original.effective_time,
            "entry_type": ENTRY_TYPE_REVERSAL,
            "delta_minutes": -cint(
                original.delta_minutes
            ),
            "reverses_entry": entry_name,
        }
    ).insert(ignore_permissions=True)


def _create_workday_ledger_entry(workday):
    return frappe.get_doc(
        {
            "doctype": "Time Account Ledger Entry",
            "employee": workday.employee,
            "effective_date": workday.log_date,
            "effective_time": "00:00:00",
            "entry_type": ENTRY_TYPE_WORKDAY,
            "delta_minutes": cint(
                workday.daily_delta_minutes
            ),
            "voucher_type": "Workday",
            "voucher_no": workday.name,
        }
    ).insert(ignore_permissions=True)


def post_workday(workday_name):
    workday = _get_workday_for_update(workday_name)

    desired_delta = cint(
        workday.daily_delta_minutes
    )

    active_entries = _get_active_workday_ledger_entries(
        workday.name
    )

    if len(active_entries) > 1:
        frappe.throw(
            _(
                "Workday {0} has multiple active "
                "Time Account Ledger Entries. "
                "Automatic posting was stopped."
            ).format(workday.name)
        )

    current_entry = (
        active_entries[0]
        if active_entries
        else None
    )

    if (
        current_entry
        and current_entry.employee != workday.employee
    ):
        frappe.throw(
            _(
                "Active ledger entry employee does not match "
                "Workday {0}."
            ).format(workday.name)
        )

    if (
        current_entry
        and cint(current_entry.delta_minutes)
        == desired_delta
    ):
        return frappe._dict(
            {
                "changed": False,
                "workday_entry": current_entry.name,
                "reversal_entry": None,
            }
        )

    reversal_entry = None

    if current_entry:
        reversal_entry = reverse_time_account_entry(
            current_entry.name
        )

    if desired_delta == 0:
        return frappe._dict(
            {
                "changed": bool(reversal_entry),
                "workday_entry": None,
                "reversal_entry": (
                    reversal_entry.name
                    if reversal_entry
                    else None
                ),
            }
        )

    new_entry = _create_workday_ledger_entry(
        workday
    )

    return frappe._dict(
        {
            "changed": True,
            "workday_entry": new_entry.name,
            "reversal_entry": (
                reversal_entry.name
                if reversal_entry
                else None
            ),
        }
    )            get_time_account_balance(self.employee),
            90,
        )

    def test_zero_delta_is_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            self.make_entry(
                ENTRY_TYPE_OPENING_BALANCE,
                0,
                remarks="Zero opening balance",
            )

    def test_positive_adjustment_requires_positive_delta(self):
        with self.assertRaises(frappe.ValidationError):
            self.make_entry(
                ENTRY_TYPE_POSITIVE_ADJUSTMENT,
                -15,
                remarks="Invalid positive adjustment",
            )

    def test_negative_adjustment_requires_negative_delta(self):
        with self.assertRaises(frappe.ValidationError):
            self.make_entry(
                ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
                15,
                remarks="Invalid negative adjustment",
            )

    def test_payout_requires_negative_delta(self):
        with self.assertRaises(frappe.ValidationError):
            self.make_entry(
                ENTRY_TYPE_PAYOUT,
                60,
                remarks="Invalid payout",
            )

    def test_payout_may_make_balance_negative(self):
        self.make_entry(
            ENTRY_TYPE_POSITIVE_ADJUSTMENT,
            120,
            remarks="Initial credit",
        )

        self.make_entry(
            ENTRY_TYPE_PAYOUT,
            -600,
            remarks="Advance payout",
        )

        self.assertEqual(
            get_time_account_balance(self.employee),
            -480,
        )

    def test_manual_entry_requires_remarks(self):
        with self.assertRaises(frappe.ValidationError):
            self.make_entry(
                ENTRY_TYPE_POSITIVE_ADJUSTMENT,
                15,
                remarks="",
            )

    def test_entry_is_immutable_after_insert(self):
        entry = self.make_entry(
            ENTRY_TYPE_POSITIVE_ADJUSTMENT,
            15,
            remarks="Original value",
        )

        entry.remarks = "Changed value"

        with self.assertRaises(frappe.ValidationError):
            entry.save(ignore_permissions=True)

    def test_entry_cannot_be_deleted(self):
        entry = self.make_entry(
            ENTRY_TYPE_POSITIVE_ADJUSTMENT,
            15,
            remarks="Must remain",
        )

        with self.assertRaises(frappe.ValidationError):
            frappe.delete_doc(
                "Time Account Ledger Entry",
                entry.name,
                force=1,
                ignore_permissions=True,
            )

    def test_reversal_negates_original_entry(self):
        original = self.make_entry(
            ENTRY_TYPE_POSITIVE_ADJUSTMENT,
            42,
            remarks="Original adjustment",
            effective_date="2026-09-10",
            effective_time="09:30:00",
        )

        reversal = self.make_entry(
            ENTRY_TYPE_REVERSAL,
            999,
            reverses_entry=original.name,
            effective_date="2026-09-17",
            effective_time="15:00:00",
        )

        self.assertEqual(
            reversal.employee,
            original.employee,
        )

        self.assertEqual(
            getdate(reversal.effective_date),
            getdate(original.effective_date),
        )

        self.assertEqual(
            get_timedelta(reversal.effective_time),
            get_timedelta(original.effective_time),
        )

        self.assertEqual(
            reversal.delta_minutes,
            -42,
        )

        self.assertEqual(
            reversal.reverses_entry,
            original.name,
        )

        self.assertEqual(
            get_time_account_balance(self.employee),
            0,
        )

    def test_entry_can_only_be_reversed_once(self):
        original = self.make_entry(
            ENTRY_TYPE_POSITIVE_ADJUSTMENT,
            42,
            remarks="Original adjustment",
        )

        self.make_entry(
            ENTRY_TYPE_REVERSAL,
            -42,
            reverses_entry=original.name,
        )

        with self.assertRaises(frappe.ValidationError):
            self.make_entry(
                ENTRY_TYPE_REVERSAL,
                -42,
                reverses_entry=original.name,
            )
