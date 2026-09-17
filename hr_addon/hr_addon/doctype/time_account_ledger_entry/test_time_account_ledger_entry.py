# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
    ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
    ENTRY_TYPE_OPENING_BALANCE,
    ENTRY_TYPE_PAYOUT,
    ENTRY_TYPE_POSITIVE_ADJUSTMENT,
    ENTRY_TYPE_REVERSAL,
    get_time_account_balance,
)


class TestTimeAccountLedgerEntry(IntegrationTestCase):
    def setUp(self):
        super().setUp()

        self.company = frappe.get_all(
            "Company",
            pluck="name",
            limit=1,
        )[0]

        gender = frappe.get_all(
            "Gender",
            pluck="name",
            limit=1,
        )[0]

        self.employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "naming_series": "HR-EMP-",
                "first_name": (
                    "Ledger Test "
                    f"{self._testMethodName}"
                ),
                "company": self.company,
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2026-01-01",
                "gender": gender,
                "status": "Active",
            }
        ).insert().name

    def make_entry(
        self,
        entry_type,
        delta_minutes,
        remarks=None,
        effective_date="2026-09-17",
        effective_time="12:00:00",
        reverses_entry=None,
    ):
        return frappe.get_doc(
            {
                "doctype": "Time Account Ledger Entry",
                "employee": self.employee,
                "effective_date": effective_date,
                "effective_time": effective_time,
                "entry_type": entry_type,
                "delta_minutes": delta_minutes,
                "remarks": remarks,
                "reverses_entry": reverses_entry,
            }
        ).insert(ignore_permissions=True)

    def test_balance_is_sum_of_deltas(self):
        self.make_entry(
            ENTRY_TYPE_POSITIVE_ADJUSTMENT,
            120,
            remarks="Test credit",
        )

        self.make_entry(
            ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
            -30,
            remarks="Test debit",
        )

        self.assertEqual(
            get_time_account_balance(self.employee),
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
            reversal.effective_date,
            original.effective_date,
        )

        self.assertEqual(
            str(reversal.effective_time),
            str(original.effective_time),
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
