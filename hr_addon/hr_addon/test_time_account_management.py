# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

"""Integration tests for the manual time-account management API.

Run on an isolated Frappe test site only.
Do not execute the integration test suite on the production site.
"""

from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import getdate, now_datetime

from hr_addon.hr_addon import time_account_management as api
from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
    create_manual_time_account_entry,
    get_time_account_balance,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "DocType",
]


class TestTimeAccountManagement(IntegrationTestCase):
    def setUp(self):
        super().setUp()

        self.previous_user = frappe.session.user
        frappe.set_user("Administrator")

        company = frappe.get_all(
            "Company",
            pluck="name",
            limit=1,
        )[0]

        gender = frappe.get_all(
            "Gender",
            pluck="name",
            limit=1,
        )[0]

        self.employee = frappe.get_doc({
            "doctype": "Employee",
            "naming_series": "HR-EMP-",
            "first_name": (
                "Management Test "
                + self._testMethodName
            ),
            "company": company,
            "date_of_birth": "1990-01-01",
            "date_of_joining": "2026-01-01",
            "gender": gender,
            "status": "Active",
        }).insert().name

        self.today = getdate(now_datetime())

        current_start = self.today.replace(day=1)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)

        self.old_date = previous_start - timedelta(days=1)

    def tearDown(self):
        try:
            frappe.set_user(self.previous_user)
        finally:
            super().tearDown()

    def preview(self, effective_date=None):
        return api.get_manual_time_account_preview(
            employee=self.employee,
            effective_date=(
                effective_date or self.today
            ).isoformat(),
            entry_type="Positive Adjustment",
            hours="00",
            minutes="15",
        )

    def book(
        self,
        remarks="Automated management test",
        expected_balance="0",
        effective_date=None,
    ):
        return api.post_manual_time_account_entry(
            employee=self.employee,
            effective_date=(
                effective_date or self.today
            ).isoformat(),
            entry_type="Positive Adjustment",
            hours="00",
            minutes="15",
            remarks=remarks,
            expected_balance=expected_balance,
        )

    def make_original(self, effective_date=None):
        return create_manual_time_account_entry(
            employee=self.employee,
            effective_date=(
                effective_date or self.today
            ),
            entry_type="Positive Adjustment",
            delta_minutes=15,
            remarks="Original for reversal test",
        )

    def test_preview_does_not_write_ledger(self):
        before = frappe.db.count(
            "Time Account Ledger Entry",
            {"employee": self.employee},
        )

        preview = self.preview()

        self.assertTrue(preview["preview_only"])
        self.assertEqual(
            preview["delta_minutes"],
            15,
        )
        self.assertEqual(
            preview["current_balance_before"],
            0,
        )
        self.assertEqual(
            preview["current_balance_after"],
            15,
        )
        self.assertEqual(
            frappe.db.count(
                "Time Account Ledger Entry",
                {"employee": self.employee},
            ),
            before,
        )

    def test_manual_booking_changes_balance(self):
        self.book()

        self.assertEqual(
            get_time_account_balance(self.employee),
            15,
        )

        rows = frappe.get_all(
            "Time Account Ledger Entry",
            filters={"employee": self.employee},
            fields=[
                "entry_type",
                "delta_minutes",
                "remarks",
            ],
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0].entry_type,
            "Positive Adjustment",
        )
        self.assertEqual(
            rows[0].delta_minutes,
            15,
        )
        self.assertEqual(
            rows[0].remarks,
            "Automated management test",
        )

    def test_stale_balance_is_rejected(self):
        self.book()

        with self.assertRaises(frappe.ValidationError):
            self.book(
                remarks="Different reason",
                expected_balance="0",
            )

        self.assertEqual(
            get_time_account_balance(self.employee),
            15,
        )

    def test_identical_booking_is_rejected(self):
        self.book()

        with self.assertRaises(frappe.ValidationError):
            self.book(
                expected_balance="15",
            )

        self.assertEqual(
            frappe.db.count(
                "Time Account Ledger Entry",
                {"employee": self.employee},
            ),
            1,
        )

    def test_reversal_is_audited_and_unique(self):
        original = self.make_original()

        preview = api.get_manual_reversal_preview(
            original.name
        )

        self.assertTrue(preview["preview_only"])
        self.assertEqual(
            preview["reversal_delta_minutes"],
            -15,
        )

        result = api.post_manual_time_account_reversal(
            entry_name=original.name,
            remarks="Correction of test booking",
            expected_balance="15",
        )

        reversal = frappe.get_doc(
            "Time Account Ledger Entry",
            result["reversal_entry"],
        )

        self.assertEqual(
            reversal.entry_type,
            "Reversal",
        )
        self.assertEqual(
            reversal.delta_minutes,
            -15,
        )
        self.assertEqual(
            reversal.reverses_entry,
            original.name,
        )
        self.assertEqual(
            reversal.remarks,
            "Correction of test booking",
        )
        self.assertEqual(
            get_time_account_balance(self.employee),
            0,
        )

        with self.assertRaises(frappe.ValidationError):
            api.get_manual_reversal_preview(
                original.name
            )

        with self.assertRaises(frappe.ValidationError):
            api.post_manual_time_account_reversal(
                entry_name=original.name,
                remarks="Second reversal forbidden",
                expected_balance="0",
            )

    def test_old_and_future_booking_dates_are_rejected(self):
        future = self.today + timedelta(days=1)

        for invalid_date in (self.old_date, future):
            with self.subTest(date=invalid_date):
                with self.assertRaises(
                    frappe.ValidationError
                ):
                    self.preview(invalid_date)

                with self.assertRaises(
                    frappe.ValidationError
                ):
                    self.book(
                        effective_date=invalid_date,
                    )

        self.assertEqual(
            get_time_account_balance(self.employee),
            0,
        )

    def test_old_reversal_is_rejected(self):
        original = self.make_original(
            self.old_date
        )

        with self.assertRaises(frappe.ValidationError):
            api.get_manual_reversal_preview(
                original.name
            )

        with self.assertRaises(frappe.ValidationError):
            api.post_manual_time_account_reversal(
                entry_name=original.name,
                remarks="Historical reversal forbidden",
                expected_balance="15",
            )

        self.assertFalse(
            frappe.db.exists(
                "Time Account Ledger Entry",
                {
                    "entry_type": "Reversal",
                    "reverses_entry": original.name,
                },
            )
        )

    def test_guest_cannot_use_manager_preview(self):
        frappe.set_user("Guest")

        try:
            with self.assertRaises(frappe.PermissionError):
                self.preview()
        finally:
            frappe.set_user("Administrator")

    def test_posted_monthly_reset_guard(self):
        reset = frappe._dict({
            "name": "TAL-CLOSED-TEST",
            "effective_date": self.today,
            "voucher_no": "WWH-TEST",
        })

        with patch.object(
            frappe.db,
            "sql",
            return_value=[reset],
        ):
            with self.assertRaisesRegex(
                frappe.ValidationError,
                "TAL-CLOSED-TEST",
            ):
                api._reject_reset_closed_period(
                    self.employee,
                    self.today,
                )

        with patch.object(
            frappe.db,
            "sql",
            return_value=[],
        ):
            api._reject_reset_closed_period(
                self.employee,
                self.today,
            )
