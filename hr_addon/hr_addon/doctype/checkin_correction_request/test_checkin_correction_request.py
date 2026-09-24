# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.checkin_correction_request.checkin_correction_request import (
    CORRECTION_EXTRA_BOOKING,
    CORRECTION_MISSING_BOOKING,
    CORRECTION_WRONG_LOG_TYPE,
    STATUS_APPLIED,
    STATUS_DRAFT,
    STATUS_PENDING,
    STATUS_REJECTED,
    approve_correction_request,
    reject_correction_request,
    submit_correction_request,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "Company",
    "Employee Checkin",
    "Workday",
    "Workday Reprocessing Log",
    "User",
]


class TestCheckinCorrectionRequest(
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
                    "Correction Test "
                    f"{self._testMethodName}"
                ),
                "company": self.company,
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2026-01-01",
                "gender": gender,
                "status": "Active",
            }
        ).insert().name

    def _make_checkin(
        self,
        log_type="IN",
        timestamp="2026-09-23 08:00:00",
        skip_auto_attendance=0,
    ):
        return frappe.get_doc(
            {
                "doctype": "Employee Checkin",
                "employee": self.employee,
                "time": timestamp,
                "log_type": log_type,
                "skip_auto_attendance": (
                    skip_auto_attendance
                ),
            }
        ).insert()

    def _make_workday(
        self,
        log_date="2026-09-23",
    ):
        workday = frappe.get_doc(
            {
                "doctype": "Workday",
                "employee": self.employee,
                "company": self.company,
                "log_date": log_date,
                "daily_delta_minutes": 0,
            }
        )

        workday.name = (
            "WD-CCR-"
            + frappe.generate_hash(
                length=10
            )
        )

        workday.db_insert()

        return workday

    def _make_missing_request(
        self,
    ):
        return frappe.get_doc(
            {
                "doctype": (
                    "Checkin Correction Request"
                ),
                "employee": self.employee,
                "correction_date": (
                    "2026-09-23"
                ),
                "correction_type": (
                    CORRECTION_MISSING_BOOKING
                ),
                "requested_log_type": "OUT",
                "requested_time": (
                    "2026-09-23 17:00:00"
                ),
                "reason": "Forgot to punch out",
            }
        ).insert()

    def _make_existing_request(
        self,
        correction_type,
        checkin,
        requested_log_type=None,
    ):
        return frappe.get_doc(
            {
                "doctype": (
                    "Checkin Correction Request"
                ),
                "employee": self.employee,
                "correction_date": (
                    "2026-09-23"
                ),
                "correction_type": (
                    correction_type
                ),
                "existing_checkin": (
                    checkin.name
                ),
                "requested_log_type": (
                    requested_log_type
                ),
                "reason": "Correction required",
            }
        ).insert()

    def _submit(
        self,
        request,
    ):
        submit_correction_request(
            request.name
        )

        return frappe.get_doc(
            "Checkin Correction Request",
            request.name,
        )

    def _approve_with_mocked_reprocess(
        self,
        request,
    ):
        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "reprocess_workday",
            return_value=frappe._dict(
                {
                    "reprocessing_log": None,
                }
            ),
        ) as mocked:
            result = (
                approve_correction_request(
                    request.name
                )
            )

        return result, mocked

    def test_missing_booking_requires_requested_time(
        self,
    ):
        request = frappe.get_doc(
            {
                "doctype": (
                    "Checkin Correction Request"
                ),
                "employee": self.employee,
                "correction_date": (
                    "2026-09-23"
                ),
                "correction_type": (
                    CORRECTION_MISSING_BOOKING
                ),
                "requested_log_type": "OUT",
                "reason": "Forgotten booking",
            }
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            request.insert()

    def test_existing_request_stores_source_snapshot(
        self,
    ):
        checkin = self._make_checkin(
            log_type="IN",
        )

        request = self._make_existing_request(
            CORRECTION_WRONG_LOG_TYPE,
            checkin,
            requested_log_type="OUT",
        )

        self.assertEqual(
            request.current_log_type,
            "IN",
        )
        self.assertEqual(
            str(request.current_time),
            "2026-09-23 08:00:00",
        )
        self.assertEqual(
            request.current_skip_auto_attendance,
            0,
        )

    def test_direct_status_change_is_rejected(
        self,
    ):
        request = self._make_missing_request()

        request.status = STATUS_APPLIED

        with self.assertRaises(
            frappe.ValidationError
        ):
            request.save()

    def test_submit_moves_request_to_pending(
        self,
    ):
        request = self._make_missing_request()

        result = submit_correction_request(
            request.name
        )

        request.reload()

        self.assertEqual(
            result.status,
            STATUS_PENDING,
        )
        self.assertEqual(
            request.status,
            STATUS_PENDING,
        )

    def test_reject_marks_request_rejected(
        self,
    ):
        request = self._make_missing_request()
        request = self._submit(
            request
        )

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "_require_approver",
            return_value="Administrator",
        ):
            reject_correction_request(
                request.name,
                "Request is not correct",
            )

        request.reload()

        self.assertEqual(
            request.status,
            STATUS_REJECTED,
        )
        self.assertEqual(
            request.rejection_reason,
            "Request is not correct",
        )

    def test_wrong_log_type_changes_only_type(
        self,
    ):
        checkin = self._make_checkin(
            log_type="IN",
        )

        original_time = checkin.time

        request = self._make_existing_request(
            CORRECTION_WRONG_LOG_TYPE,
            checkin,
            requested_log_type="OUT",
        )

        request = self._submit(
            request
        )

        self._make_workday()

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "_require_approver",
            return_value="Administrator",
        ):
            result, mocked = (
                self._approve_with_mocked_reprocess(
                    request
                )
            )

        checkin.reload()

        self.assertEqual(
            checkin.log_type,
            "OUT",
        )
        self.assertEqual(
            checkin.time,
            original_time,
        )
        self.assertEqual(
            result.status,
            STATUS_APPLIED,
        )
        self.assertEqual(
            mocked.call_count,
            1,
        )

    def test_extra_booking_is_skipped_not_deleted(
        self,
    ):
        checkin = self._make_checkin(
            log_type="IN",
        )

        request = self._make_existing_request(
            CORRECTION_EXTRA_BOOKING,
            checkin,
        )

        request = self._submit(
            request
        )

        self._make_workday()

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "_require_approver",
            return_value="Administrator",
        ):
            self._approve_with_mocked_reprocess(
                request
            )

        self.assertTrue(
            frappe.db.exists(
                "Employee Checkin",
                checkin.name,
            )
        )

        checkin.reload()

        self.assertEqual(
            checkin.skip_auto_attendance,
            1,
        )

    def test_missing_booking_creates_checkin(
        self,
    ):
        request = self._make_missing_request()
        request = self._submit(
            request
        )

        self._make_workday()

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "_require_approver",
            return_value="Administrator",
        ):
            result, mocked = (
                self._approve_with_mocked_reprocess(
                    request
                )
            )

        checkin = frappe.get_doc(
            "Employee Checkin",
            result.employee_checkin,
        )

        self.assertEqual(
            checkin.employee,
            self.employee,
        )
        self.assertEqual(
            checkin.log_type,
            "OUT",
        )
        self.assertEqual(
            str(checkin.time),
            "2026-09-23 17:00:00",
        )
        self.assertEqual(
            mocked.call_count,
            1,
        )

    def test_changed_source_is_rejected_fail_closed(
        self,
    ):
        checkin = self._make_checkin(
            log_type="IN",
        )

        request = self._make_existing_request(
            CORRECTION_WRONG_LOG_TYPE,
            checkin,
            requested_log_type="OUT",
        )

        request = self._submit(
            request
        )

        self._make_workday()

        frappe.db.set_value(
            "Employee Checkin",
            checkin.name,
            "log_type",
            "OUT",
        )

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "_require_approver",
            return_value="Administrator",
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                approve_correction_request(
                    request.name
                )

        request.reload()

        self.assertEqual(
            request.status,
            STATUS_PENDING,
        )

    def test_approval_requires_pending_status(
        self,
    ):
        request = self._make_missing_request()

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "_require_approver",
            return_value="Administrator",
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                approve_correction_request(
                    request.name
                )

        request.reload()

        self.assertEqual(
            request.status,
            STATUS_DRAFT,
        )

    def test_approval_passes_request_as_reprocessing_source(
        self,
    ):
        checkin = self._make_checkin(
            log_type="IN",
        )

        request = self._make_existing_request(
            CORRECTION_WRONG_LOG_TYPE,
            checkin,
            requested_log_type="OUT",
        )

        request = self._submit(
            request
        )

        workday = self._make_workday()

        with (
            patch(
                "hr_addon.hr_addon.doctype."
                "checkin_correction_request."
                "checkin_correction_request."
                "_require_approver",
                return_value="Administrator",
            ),
            patch(
                "hr_addon.hr_addon.doctype."
                "checkin_correction_request."
                "checkin_correction_request."
                "reprocess_workday",
                return_value=frappe._dict(
                    {
                        "reprocessing_log": None,
                    }
                ),
            ) as mocked,
        ):
            approve_correction_request(
                request.name
            )

        kwargs = mocked.call_args.kwargs

        self.assertEqual(
            kwargs["workday_name"],
            workday.name,
        )
        self.assertEqual(
            kwargs["trigger"],
            "Checkin Correction",
        )
        self.assertEqual(
            kwargs["source_doctype"],
            "Checkin Correction Request",
        )
        self.assertEqual(
            kwargs["source_name"],
            request.name,
        )

    def test_submit_requires_write_permission(
        self,
    ):
        request = self._make_missing_request()

        with patch(
            "hr_addon.hr_addon.doctype."
            "checkin_correction_request."
            "checkin_correction_request."
            "CheckinCorrectionRequest."
            "check_permission",
            side_effect=frappe.PermissionError,
        ):
            with self.assertRaises(
                frappe.PermissionError
            ):
                submit_correction_request(
                    request.name
                )

        request.reload()

        self.assertEqual(
            request.status,
            STATUS_DRAFT,
        )
