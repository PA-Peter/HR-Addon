# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe

from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_scheduler import (
    _get_reportable_employees,
    generate_previous_month_reports,
    get_previous_month_period,
    reconcile_previous_month_reports,
)


MODULE = (
    "hr_addon.hr_addon.doctype."
    "monthly_time_report."
    "monthly_time_report_scheduler"
)


class TestMonthlyTimeReportScheduler(
    IntegrationTestCase
):
    def _employee(
        self,
        name,
        **overrides,
    ):
        values = {
            "name": name,
            "employee_name": name,
            "date_of_joining": (
                getdate(
                    "2020-01-01"
                )
            ),
            "relieving_date": None,
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def test_previous_month_period(
        self,
    ):
        (
            year,
            month,
            period_from,
            period_to,
        ) = get_previous_month_period(
            datetime(
                2026,
                11,
                3,
                3,
                0,
                0,
            )
        )

        self.assertEqual(
            year,
            2026,
        )

        self.assertEqual(
            month,
            10,
        )

        self.assertEqual(
            period_from,
            getdate(
                "2026-10-01"
            ),
        )

        self.assertEqual(
            period_to,
            getdate(
                "2026-10-31"
            ),
        )

    def test_reportable_employee_overlap(
        self,
    ):
        rows = [
            self._employee(
                "EMP-A",
            ),
            self._employee(
                "EMP-B",
                date_of_joining=(
                    getdate(
                        "2026-11-01"
                    )
                ),
            ),
            self._employee(
                "EMP-C",
                relieving_date=(
                    getdate(
                        "2026-09-30"
                    )
                ),
            ),
            self._employee(
                "EMP-D",
                relieving_date=(
                    getdate(
                        "2026-10-15"
                    )
                ),
            ),
        ]

        with patch(
            f"{MODULE}.frappe.get_all",
            return_value=rows,
        ):
            result = (
                _get_reportable_employees(
                    getdate(
                        "2026-10-01"
                    ),
                    getdate(
                        "2026-10-31"
                    ),
                )
            )

        self.assertEqual(
            [
                row.name
                for row in result
            ],
            [
                "EMP-A",
                "EMP-D",
            ],
        )

    def test_complete_previous_month_is_created_and_published(
        self,
    ):
        reference = datetime(
            2026,
            9,
            3,
            3,
            0,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        snapshot = {
            "is_complete": 1,
            "blocking_issue_count": 0,
        }

        publication = {
            "report": "MTR-1",
            "employee_document": "EDOC-1",
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=None,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "create_and_publish_monthly_time_report"
                ),
                return_value=publication,
            ) as create,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
        ):
            result = (
                generate_previous_month_reports(
                    reference
                )
            )

        create.assert_called_once_with(
            "EMP-A",
            2026,
            8,
            reference_datetime=(
                reference
            ),
        )

        self.assertEqual(
            len(
                result[
                    "created"
                ]
            ),
            1,
        )

        self.assertFalse(
            result[
                "failed"
            ]
        )

    def test_incomplete_source_is_not_published(
        self,
    ):
        reference = datetime(
            2026,
            9,
            3,
            3,
            0,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        snapshot = {
            "is_complete": 0,
            "blocking_issue_count": 2,
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=None,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "create_and_publish_monthly_time_report"
                )
            ) as create,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
            patch(
                f"{MODULE}.frappe.logger"
            ),
        ):
            result = (
                generate_previous_month_reports(
                    reference
                )
            )

        create.assert_not_called()

        self.assertEqual(
            result[
                "blocked"
            ][0][
                "blocking_issue_count"
            ],
            2,
        )

    def test_already_published_report_is_idempotent(
        self,
    ):
        reference = datetime(
            2026,
            9,
            3,
            3,
            0,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        current = frappe._dict({
            "name": "MTR-1",
            "is_complete": 1,
            "blocking_issue_count": 0,
            "employee_document": "EDOC-1",
            "pdf_file": (
                "/private/files/report.pdf"
            ),
        })

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=current,
            ),
            patch(
                (
                    f"{MODULE}."
                    "create_and_publish_monthly_time_report"
                )
            ) as create,
            patch(
                (
                    f"{MODULE}."
                    "publish_monthly_time_report"
                )
            ) as publish,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
        ):
            result = (
                generate_previous_month_reports(
                    reference
                )
            )

        create.assert_not_called()
        publish.assert_not_called()

        self.assertEqual(
            result[
                "already_published"
            ][0][
                "report"
            ],
            "MTR-1",
        )

    def test_complete_unpublished_report_is_published(
        self,
    ):
        reference = datetime(
            2026,
            9,
            3,
            3,
            0,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        current = frappe._dict({
            "name": "MTR-1",
            "is_complete": 1,
            "blocking_issue_count": 0,
            "employee_document": None,
            "pdf_file": None,
        })

        publication = {
            "report": "MTR-1",
            "employee_document": "EDOC-1",
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=current,
            ),
            patch(
                (
                    f"{MODULE}."
                    "publish_monthly_time_report"
                ),
                return_value=publication,
            ) as publish,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
        ):
            result = (
                generate_previous_month_reports(
                    reference
                )
            )

        publish.assert_called_once_with(
            "MTR-1"
        )

        self.assertEqual(
            result[
                "published_existing"
            ][0][
                "employee_document"
            ],
            "EDOC-1",
        )

    def test_one_employee_failure_does_not_block_next_employee(
        self,
    ):
        reference = datetime(
            2026,
            9,
            3,
            3,
            0,
            0,
        )

        employees = [
            self._employee(
                "EMP-A"
            ),
            self._employee(
                "EMP-B"
            ),
        ]

        snapshot = {
            "is_complete": 1,
            "blocking_issue_count": 0,
        }

        def create(
            employee,
            year,
            month,
            reference_datetime=None,
        ):
            if employee == "EMP-A":
                raise RuntimeError(
                    "Synthetic failure"
                )

            return {
                "report": "MTR-B",
                "employee_document": (
                    "EDOC-B"
                ),
            }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=employees,
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=None,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "create_and_publish_monthly_time_report"
                ),
                side_effect=create,
            ),
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
            patch(
                f"{MODULE}.frappe.db.rollback"
            ) as rollback,
            patch(
                f"{MODULE}.frappe.log_error"
            ),
        ):
            result = (
                generate_previous_month_reports(
                    reference
                )
            )

        self.assertEqual(
            len(
                result[
                    "failed"
                ]
            ),
            1,
        )

        self.assertEqual(
            result[
                "failed"
            ][0][
                "employee"
            ],
            "EMP-A",
        )

        self.assertEqual(
            result[
                "created"
            ][0][
                "employee"
            ],
            "EMP-B",
        )

        rollback.assert_called_once()


    def test_reconcile_before_day_three_is_skipped(
        self,
    ):
        reference = datetime(
            2026,
            10,
            2,
            3,
            15,
            0,
        )

        with patch(
            (
                f"{MODULE}."
                "_get_reportable_employees"
            )
        ) as employees:
            result = (
                reconcile_previous_month_reports(
                    reference
                )
            )

        employees.assert_not_called()

        self.assertTrue(
            result[
                "skipped_before_day_3"
            ]
        )

    def test_reconcile_creates_missing_report_after_day_three(
        self,
    ):
        reference = datetime(
            2026,
            10,
            4,
            3,
            15,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        snapshot = {
            "is_complete": 1,
            "blocking_issue_count": 0,
        }

        publication = {
            "report": "MTR-1",
            "employee_document": "EDOC-1",
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=None,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "create_and_publish_monthly_time_report"
                ),
                return_value=publication,
            ) as create,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
        ):
            result = (
                reconcile_previous_month_reports(
                    reference
                )
            )

        create.assert_called_once_with(
            "EMP-A",
            2026,
            9,
            reference_datetime=(
                reference
            ),
        )

        self.assertEqual(
            result[
                "created"
            ][0][
                "report"
            ],
            "MTR-1",
        )

    def test_reconcile_unchanged_published_report_is_idempotent(
        self,
    ):
        reference = datetime(
            2026,
            10,
            4,
            3,
            15,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        current = frappe._dict(
            {
                "name": "MTR-1",
                "employee_document": "EDOC-1",
                "pdf_file": (
                    "/private/files/r1.pdf"
                ),
            }
        )

        snapshot = {
            "is_complete": 1,
            "blocking_issue_count": 0,
        }

        current_doc = frappe._dict(
            {
                "name": "MTR-1",
            }
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=current,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=current_doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "monthly_time_report_source_fingerprint"
                ),
                side_effect=[
                    "same",
                    "same",
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "regenerate_and_publish_monthly_time_report"
                )
            ) as regenerate,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
        ):
            result = (
                reconcile_previous_month_reports(
                    reference
                )
            )

        regenerate.assert_not_called()

        self.assertEqual(
            result[
                "unchanged"
            ][0][
                "report"
            ],
            "MTR-1",
        )

    def test_reconcile_changed_published_report_creates_revision(
        self,
    ):
        reference = datetime(
            2026,
            10,
            4,
            3,
            15,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        current = frappe._dict(
            {
                "name": "MTR-1",
                "employee_document": "EDOC-1",
                "pdf_file": (
                    "/private/files/r1.pdf"
                ),
            }
        )

        snapshot = {
            "is_complete": 1,
            "blocking_issue_count": 0,
        }

        current_doc = frappe._dict(
            {
                "name": "MTR-1",
            }
        )

        publication = {
            "report": "MTR-2",
            "previous_report": "MTR-1",
            "employee_document": "EDOC-2",
            "revision": 2,
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=current,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=current_doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "monthly_time_report_source_fingerprint"
                ),
                side_effect=[
                    "old",
                    "new",
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "regenerate_and_publish_monthly_time_report"
                ),
                return_value=publication,
            ) as regenerate,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
        ):
            result = (
                reconcile_previous_month_reports(
                    reference
                )
            )

        regenerate.assert_called_once_with(
            "MTR-1",
            reference_datetime=(
                reference
            ),
        )

        self.assertEqual(
            result[
                "revised"
            ][0][
                "report"
            ],
            "MTR-2",
        )

        self.assertEqual(
            result[
                "revised"
            ][0][
                "revision"
            ],
            2,
        )

    def test_reconcile_blocked_source_does_not_replace_report(
        self,
    ):
        reference = datetime(
            2026,
            10,
            4,
            3,
            15,
            0,
        )

        employee = (
            self._employee(
                "EMP-A"
            )
        )

        current = frappe._dict(
            {
                "name": "MTR-1",
                "employee_document": "EDOC-1",
                "pdf_file": (
                    "/private/files/r1.pdf"
                ),
            }
        )

        snapshot = {
            "is_complete": 0,
            "blocking_issue_count": 1,
        }

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_reportable_employees"
                ),
                return_value=[
                    employee
                ],
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_current_report"
                ),
                return_value=current,
            ),
            patch(
                (
                    f"{MODULE}."
                    "build_monthly_time_report_snapshot"
                ),
                return_value=snapshot,
            ),
            patch(
                (
                    f"{MODULE}."
                    "regenerate_and_publish_monthly_time_report"
                )
            ) as regenerate,
            patch(
                f"{MODULE}.frappe.db.savepoint"
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.release_savepoint"
                )
            ),
            patch(
                f"{MODULE}.frappe.logger"
            ),
        ):
            result = (
                reconcile_previous_month_reports(
                    reference
                )
            )

        regenerate.assert_not_called()

        self.assertEqual(
            result[
                "blocked"
            ][0][
                "blocking_issue_count"
            ],
            1,
        )
