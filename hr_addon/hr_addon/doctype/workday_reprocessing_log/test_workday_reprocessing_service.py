# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
    ENTRY_TYPE_REVERSAL,
    ENTRY_TYPE_WORKDAY,
    post_workday,
)
from hr_addon.hr_addon.doctype.workday.workday import (
    Workday,
)
from hr_addon.hr_addon.doctype.workday_reprocessing_log.workday_reprocessing_log import (
    TRIGGER_MANUAL_RECALCULATE,
    TRIGGER_PERIOD_OVERRIDE,
    is_workday_period_locked,
    reprocess_workday,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "Workday",
    "DocType",
    "User",
]


class TestWorkdayReprocessingService(
    IntegrationTestCase
):
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
                    "Reprocessing Service Test "
                    f"{self._testMethodName}"
                ),
                "company": self.company,
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2026-01-01",
                "gender": gender,
                "status": "Active",
            }
        ).insert().name

    def _make_workday(
        self,
        delta_minutes=42,
        log_date="2026-09-17",
        post_ledger=True,
    ):
        workday = frappe.get_doc(
            {
                "doctype": "Workday",
                "employee": self.employee,
                "log_date": log_date,
                "company": self.company,
                "daily_delta_minutes": (
                    delta_minutes
                ),
            }
        )

        workday.name = (
            "WD-REPROCESS-SVC-"
            + frappe.generate_hash(
                length=10
            )
        )

        workday.db_insert()

        if (
            post_ledger
            and delta_minutes != 0
        ):
            post_workday(
                workday.name
            )

        return workday

    def _ledger_rows(
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
            order_by=(
                "creation asc, name asc"
            ),
        )

    def _reprocessing_rows(
        self,
        workday_name,
    ):
        return frappe.get_all(
            "Workday Reprocessing Log",
            filters={
                "workday": workday_name,
            },
            fields=[
                "name",
                "trigger",
                "old_delta_minutes",
                "new_delta_minutes",
                "reason",
                "triggered_by",
            ],
            order_by=(
                "creation asc, name asc"
            ),
        )

    def _reprocess_with_forced_delta(
        self,
        workday_name,
        new_delta_minutes,
        reason="Test correction",
        allow_period_override=False,
        user="Administrator",
    ):
        def set_actual_employee_log(
            workday,
        ):
            workday.status = ""
            workday.first_checkin = (
                "TEST-IN"
            )
            workday.last_checkout = (
                "TEST-OUT"
            )

            workday.target_hours = 0
            workday.raw_work_minutes = 0
            workday.physical_break_minutes = 0
            workday.qualifying_break_minutes = 0
            workday.required_break_minutes = 0
            workday.automatic_break_deduction_minutes = 0
            workday.accountable_minutes = 0
            workday.employee_checkins = []

        def set_status_for_leave_application(
            workday,
        ):
            return 0

        def finalize_minute_evaluation(
            workday,
            absence_credit_cap_minutes=0,
            delta_is_valid=True,
        ):
            workday.target_minutes = 0
            workday.absence_credit_minutes = 0
            workday.daily_delta_minutes = (
                new_delta_minutes
            )

        with (
            patch.object(
                Workday,
                "set_actual_employee_log",
                set_actual_employee_log,
            ),
            patch.object(
                Workday,
                "set_status_for_leave_application",
                set_status_for_leave_application,
            ),
            patch.object(
                Workday,
                "finalize_minute_evaluation",
                finalize_minute_evaluation,
            ),
            patch(
                "hr_addon.hr_addon.doctype."
                "workday_reprocessing_log."
                "workday_reprocessing_log.today",
                return_value="2026-09-24",
            ),
            patch(
                "hr_addon.hr_addon.doctype."
                "workday_reprocessing_log."
                "workday_reprocessing_log."
                "_get_reprocessing_user",
                return_value=user,
            ),
        ):
            return reprocess_workday(
                workday_name=workday_name,
                trigger=(
                    TRIGGER_MANUAL_RECALCULATE
                ),
                reason=reason,
                allow_period_override=(
                    allow_period_override
                ),
            )

    def test_current_month_is_unlocked(self):
        self.assertFalse(
            is_workday_period_locked(
                "2026-09-01",
                reference_date=(
                    "2026-09-24"
                ),
            )
        )

    def test_previous_month_is_unlocked(self):
        self.assertFalse(
            is_workday_period_locked(
                "2026-08-01",
                reference_date=(
                    "2026-09-24"
                ),
            )
        )

    def test_older_month_is_locked(self):
        self.assertTrue(
            is_workday_period_locked(
                "2026-07-31",
                reference_date=(
                    "2026-09-24"
                ),
            )
        )

    def test_reprocess_corrects_ledger_and_creates_log(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=42,
        )

        result = (
            self._reprocess_with_forced_delta(
                workday.name,
                new_delta_minutes=17,
                reason=(
                    "Corrected employee checkins"
                ),
            )
        )

        ledger_rows = self._ledger_rows(
            workday.name
        )

        self.assertEqual(
            len(ledger_rows),
            3,
        )

        self.assertEqual(
            ledger_rows[0].entry_type,
            ENTRY_TYPE_WORKDAY,
        )
        self.assertEqual(
            ledger_rows[0].delta_minutes,
            42,
        )

        self.assertEqual(
            ledger_rows[1].entry_type,
            ENTRY_TYPE_REVERSAL,
        )
        self.assertEqual(
            ledger_rows[1].delta_minutes,
            -42,
        )
        self.assertEqual(
            ledger_rows[1].reverses_entry,
            ledger_rows[0].name,
        )

        self.assertEqual(
            ledger_rows[2].entry_type,
            ENTRY_TYPE_WORKDAY,
        )
        self.assertEqual(
            ledger_rows[2].delta_minutes,
            17,
        )

        logs = self._reprocessing_rows(
            workday.name
        )

        self.assertEqual(
            len(logs),
            1,
        )
        self.assertEqual(
            logs[0].trigger,
            TRIGGER_MANUAL_RECALCULATE,
        )
        self.assertEqual(
            logs[0].old_delta_minutes,
            42,
        )
        self.assertEqual(
            logs[0].new_delta_minutes,
            17,
        )

        self.assertEqual(
            result.old_delta_minutes,
            42,
        )
        self.assertEqual(
            result.new_delta_minutes,
            17,
        )
        self.assertTrue(
            result.changed
        )
        self.assertFalse(
            result.period_override
        )

    def test_unchanged_reprocess_still_creates_log(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=42,
        )

        result = (
            self._reprocess_with_forced_delta(
                workday.name,
                new_delta_minutes=42,
                reason="Rechecked source data",
            )
        )

        ledger_rows = self._ledger_rows(
            workday.name
        )

        self.assertEqual(
            len(ledger_rows),
            1,
        )
        self.assertEqual(
            ledger_rows[0].delta_minutes,
            42,
        )

        logs = self._reprocessing_rows(
            workday.name
        )

        self.assertEqual(
            len(logs),
            1,
        )
        self.assertEqual(
            logs[0].old_delta_minutes,
            42,
        )
        self.assertEqual(
            logs[0].new_delta_minutes,
            42,
        )

        self.assertFalse(
            result.changed
        )

    def test_locked_period_is_rejected_without_override(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=42,
            log_date="2026-07-15",
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            self._reprocess_with_forced_delta(
                workday.name,
                new_delta_minutes=17,
            )

        ledger_rows = self._ledger_rows(
            workday.name
        )

        self.assertEqual(
            len(ledger_rows),
            1,
        )
        self.assertEqual(
            ledger_rows[0].delta_minutes,
            42,
        )

        self.assertEqual(
            self._reprocessing_rows(
                workday.name
            ),
            [],
        )

    def test_locked_period_admin_override_succeeds(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=42,
            log_date="2026-07-15",
        )

        result = (
            self._reprocess_with_forced_delta(
                workday.name,
                new_delta_minutes=17,
                reason=(
                    "Approved historic correction"
                ),
                allow_period_override=True,
                user="Administrator",
            )
        )

        ledger_rows = self._ledger_rows(
            workday.name
        )

        self.assertEqual(
            len(ledger_rows),
            3,
        )

        logs = self._reprocessing_rows(
            workday.name
        )

        self.assertEqual(
            len(logs),
            1,
        )
        self.assertEqual(
            logs[0].trigger,
            TRIGGER_PERIOD_OVERRIDE,
        )
        self.assertEqual(
            logs[0].old_delta_minutes,
            42,
        )
        self.assertEqual(
            logs[0].new_delta_minutes,
            17,
        )
        self.assertIn(
            "Underlying trigger: "
            "Manual Recalculate",
            logs[0].reason,
        )

        self.assertTrue(
            result.period_override
        )

    def test_locked_period_override_requires_admin(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=42,
            log_date="2026-07-15",
        )

        with patch(
            "hr_addon.hr_addon.doctype."
            "workday_reprocessing_log."
            "workday_reprocessing_log."
            "_user_can_override_period",
            return_value=False,
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                self._reprocess_with_forced_delta(
                    workday.name,
                    new_delta_minutes=17,
                    allow_period_override=True,
                    user=(
                        "normal@example.com"
                    ),
                )

        self.assertEqual(
            len(
                self._ledger_rows(
                    workday.name
                )
            ),
            1,
        )

        self.assertEqual(
            self._reprocessing_rows(
                workday.name
            ),
            [],
        )

    def test_direct_save_of_locked_workday_is_rejected(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=0,
            log_date="2026-07-15",
            post_ledger=False,
        )

        workday = frappe.get_doc(
            "Workday",
            workday.name,
        )

        with patch(
            "hr_addon.hr_addon.doctype."
            "workday_reprocessing_log."
            "workday_reprocessing_log.today",
            return_value="2026-09-24",
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                workday.save(
                    ignore_permissions=True
                )

    def test_reason_is_required_before_reprocessing(
        self,
    ):
        workday = self._make_workday(
            delta_minutes=42,
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            self._reprocess_with_forced_delta(
                workday.name,
                new_delta_minutes=17,
                reason="   ",
            )

        self.assertEqual(
            len(
                self._ledger_rows(
                    workday.name
                )
            ),
            1,
        )

        self.assertEqual(
            self._reprocessing_rows(
                workday.name
            ),
            [],
        )
