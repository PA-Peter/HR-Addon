# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, get_timedelta

from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
    ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
    ENTRY_TYPE_OPENING_BALANCE,
    ENTRY_TYPE_PAYOUT,
    ENTRY_TYPE_POSITIVE_ADJUSTMENT,
    ENTRY_TYPE_REVERSAL,
    ENTRY_TYPE_WORKDAY,
    get_time_account_balance,
    post_workday,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "DocType",
]


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
        voucher_type=None,
        voucher_no=None,
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
                "voucher_type": voucher_type,
                "voucher_no": voucher_no,
            }
        ).insert(ignore_permissions=True)

    def make_workday(
        self,
        delta_minutes,
        log_date="2026-09-17",
    ):
        workday = frappe.get_doc(
            {
                "doctype": "Workday",
                "employee": self.employee,
                "log_date": log_date,
                "company": self.company,
                "daily_delta_minutes": delta_minutes,
            }
        )

        workday.name = (
            "WD-LEDGER-"
            + frappe.generate_hash(length=10)
        )

        workday.db_insert()

        return workday

    def get_workday_ledger_rows(
        self,
        workday_name,
    ):
        return frappe.get_all(
            "Time Account Ledger Entry",
            filters={
                "voucher_type": "Workday",
                "voucher_no": workday_name,
            },
            fields=[
                "name",
                "entry_type",
                "delta_minutes",
                "reverses_entry",
            ],
            order_by="creation asc, name asc",
        )

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

    def test_post_workday_creates_ledger_entry(self):
        workday = self.make_workday(95)

        result = post_workday(workday.name)

        rows = self.get_workday_ledger_rows(
            workday.name
        )

        self.assertTrue(result.changed)
        self.assertIsNone(result.reversal_entry)
        self.assertEqual(len(rows), 1)

        self.assertEqual(
            rows[0].entry_type,
            ENTRY_TYPE_WORKDAY,
        )
        self.assertEqual(
            rows[0].delta_minutes,
            95,
        )
        self.assertEqual(
            result.workday_entry,
            rows[0].name,
        )

    def test_post_workday_is_idempotent(self):
        workday = self.make_workday(95)

        first = post_workday(workday.name)
        second = post_workday(workday.name)

        rows = self.get_workday_ledger_rows(
            workday.name
        )

        self.assertTrue(first.changed)
        self.assertFalse(second.changed)
        self.assertEqual(
            first.workday_entry,
            second.workday_entry,
        )
        self.assertEqual(len(rows), 1)

    def test_zero_workday_delta_creates_no_entry(self):
        workday = self.make_workday(0)

        result = post_workday(workday.name)

        rows = self.get_workday_ledger_rows(
            workday.name
        )

        self.assertFalse(result.changed)
        self.assertIsNone(result.workday_entry)
        self.assertIsNone(result.reversal_entry)
        self.assertEqual(rows, [])

    def test_workday_recalculation_reverses_old_and_posts_new(self):
        workday = self.make_workday(42)

        first = post_workday(workday.name)

        frappe.db.set_value(
            "Workday",
            workday.name,
            "daily_delta_minutes",
            17,
            update_modified=False,
        )

        second = post_workday(workday.name)

        rows = self.get_workday_ledger_rows(
            workday.name
        )

        self.assertTrue(first.changed)
        self.assertTrue(second.changed)
        self.assertEqual(len(rows), 3)

        self.assertEqual(
            rows[0].entry_type,
            ENTRY_TYPE_WORKDAY,
        )
        self.assertEqual(
            rows[0].delta_minutes,
            42,
        )

        self.assertEqual(
            rows[1].entry_type,
            ENTRY_TYPE_REVERSAL,
        )
        self.assertEqual(
            rows[1].delta_minutes,
            -42,
        )
        self.assertEqual(
            rows[1].reverses_entry,
            rows[0].name,
        )

        self.assertEqual(
            rows[2].entry_type,
            ENTRY_TYPE_WORKDAY,
        )
        self.assertEqual(
            rows[2].delta_minutes,
            17,
        )

        self.assertEqual(
            second.reversal_entry,
            rows[1].name,
        )
        self.assertEqual(
            second.workday_entry,
            rows[2].name,
        )

    def test_repeated_recalculation_is_idempotent(self):
        workday = self.make_workday(42)

        post_workday(workday.name)

        frappe.db.set_value(
            "Workday",
            workday.name,
            "daily_delta_minutes",
            17,
            update_modified=False,
        )

        first_recalc = post_workday(
            workday.name
        )

        second_recalc = post_workday(
            workday.name
        )

        rows = self.get_workday_ledger_rows(
            workday.name
        )

        self.assertTrue(first_recalc.changed)
        self.assertFalse(second_recalc.changed)
        self.assertEqual(len(rows), 3)

        self.assertEqual(
            get_time_account_balance(self.employee),
            17,
        )

    def test_workday_recalculation_to_zero_only_reverses_old(self):
        workday = self.make_workday(42)

        first = post_workday(workday.name)

        frappe.db.set_value(
            "Workday",
            workday.name,
            "daily_delta_minutes",
            0,
            update_modified=False,
        )

        second = post_workday(workday.name)

        rows = self.get_workday_ledger_rows(
            workday.name
        )

        self.assertTrue(first.changed)
        self.assertTrue(second.changed)
        self.assertIsNone(
            second.workday_entry
        )
        self.assertIsNotNone(
            second.reversal_entry
        )

        self.assertEqual(len(rows), 2)

        self.assertEqual(
            rows[0].entry_type,
            ENTRY_TYPE_WORKDAY,
        )
        self.assertEqual(
            rows[0].delta_minutes,
            42,
        )

        self.assertEqual(
            rows[1].entry_type,
            ENTRY_TYPE_REVERSAL,
        )
        self.assertEqual(
            rows[1].delta_minutes,
            -42,
        )

        self.assertEqual(
            get_time_account_balance(self.employee),
            0,
        )

    def test_multiple_active_workday_entries_fail_closed(self):
        workday = self.make_workday(42)

        self.make_entry(
            ENTRY_TYPE_WORKDAY,
            42,
            effective_date=workday.log_date,
            effective_time="00:00:00",
            voucher_type="Workday",
            voucher_no=workday.name,
        )

        self.make_entry(
            ENTRY_TYPE_WORKDAY,
            42,
            effective_date=workday.log_date,
            effective_time="00:00:00",
            voucher_type="Workday",
            voucher_no=workday.name,
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            post_workday(workday.name)
