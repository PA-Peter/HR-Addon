# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.workday_reprocessing_log.workday_reprocessing_log import (
    SERVICE_INSERT_FLAG,
    TRIGGER_MANUAL_RECALCULATE,
    create_workday_reprocessing_log,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "Workday",
    "DocType",
    "User",
]


class TestWorkdayReprocessingLog(
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
                    "Reprocessing Log Test "
                    f"{self._testMethodName}"
                ),
                "company": self.company,
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2026-01-01",
                "gender": gender,
                "status": "Active",
            }
        ).insert().name

        self.workday = frappe.get_doc(
            {
                "doctype": "Workday",
                "employee": self.employee,
                "log_date": "2026-09-17",
                "company": self.company,
                "daily_delta_minutes": 42,
            }
        )

        self.workday.name = (
            "WD-REPROCESS-"
            + frappe.generate_hash(length=10)
        )

        self.workday.db_insert()

    def make_direct_log(
        self,
        trigger=TRIGGER_MANUAL_RECALCULATE,
        reason="Test reprocessing",
        log_date="2026-09-17",
        internal_service=False,
    ):
        log = frappe.get_doc(
            {
                "doctype": (
                    "Workday Reprocessing Log"
                ),
                "employee": self.employee,
                "workday": self.workday.name,
                "log_date": log_date,
                "trigger": trigger,
                "old_delta_minutes": 42,
                "new_delta_minutes": 17,
                "reason": reason,
                "triggered_by": "Administrator",
            }
        )

        if internal_service:
            log.flags[
                SERVICE_INSERT_FLAG
            ] = True

        return log.insert(
            ignore_permissions=True
        )

    def test_service_creates_reprocessing_log(self):
        log = create_workday_reprocessing_log(
            workday_name=self.workday.name,
            trigger=TRIGGER_MANUAL_RECALCULATE,
            reason="Corrected employee checkins",
            old_delta_minutes=42,
            new_delta_minutes=17,
        )

        self.assertEqual(
            log.employee,
            self.employee,
        )
        self.assertEqual(
            log.workday,
            self.workday.name,
        )
        self.assertEqual(
            str(log.log_date),
            "2026-09-17",
        )
        self.assertEqual(
            log.old_delta_minutes,
            42,
        )
        self.assertEqual(
            log.new_delta_minutes,
            17,
        )
        self.assertTrue(
            log.triggered_by
        )

    def test_log_cannot_be_created_directly(self):
        with self.assertRaises(
            frappe.ValidationError
        ):
            self.make_direct_log()

    def test_log_is_immutable_after_insert(self):
        log = create_workday_reprocessing_log(
            workday_name=self.workday.name,
            trigger=TRIGGER_MANUAL_RECALCULATE,
            reason="Original reason",
            old_delta_minutes=42,
            new_delta_minutes=17,
        )

        log.reason = "Changed reason"

        with self.assertRaises(
            frappe.ValidationError
        ):
            log.save(
                ignore_permissions=True
            )

    def test_log_cannot_be_deleted(self):
        log = create_workday_reprocessing_log(
            workday_name=self.workday.name,
            trigger=TRIGGER_MANUAL_RECALCULATE,
            reason="Must remain auditable",
            old_delta_minutes=42,
            new_delta_minutes=17,
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            frappe.delete_doc(
                "Workday Reprocessing Log",
                log.name,
                force=1,
                ignore_permissions=True,
            )

    def test_reason_is_required(self):
        with self.assertRaises(
            frappe.ValidationError
        ):
            create_workday_reprocessing_log(
                workday_name=self.workday.name,
                trigger=TRIGGER_MANUAL_RECALCULATE,
                reason="   ",
                old_delta_minutes=42,
                new_delta_minutes=17,
            )

    def test_invalid_trigger_is_rejected(self):
        with self.assertRaises(
            frappe.ValidationError
        ):
            self.make_direct_log(
                trigger="Something Unexpected",
                internal_service=True,
            )

    def test_workday_date_mismatch_is_rejected(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            self.make_direct_log(
                log_date="2026-09-18",
                internal_service=True,
            )

    def test_source_reference_requires_both_fields(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            create_workday_reprocessing_log(
                workday_name=self.workday.name,
                trigger=TRIGGER_MANUAL_RECALCULATE,
                reason="Incomplete source reference",
                old_delta_minutes=42,
                new_delta_minutes=17,
                source_doctype="Workday",
            )
