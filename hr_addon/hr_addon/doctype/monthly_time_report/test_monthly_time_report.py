# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe

from frappe.tests import IntegrationTestCase
from frappe.utils import getdate

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report import (
    SERVICE_FLAG,
    MonthlyTimeReport,
    _validate_snapshot_consistency,
)
from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_service import (
    SNAPSHOT_STATUS_MISSING_CHECKIN,
    SNAPSHOT_STATUS_MISSING_WORKDAY,
    SNAPSHOT_STATUS_NO_WWH,
    SNAPSHOT_STATUS_OK,
    SNAPSHOT_STATUS_OUTSIDE_EMPLOYMENT,
    _build_day_snapshot,
    _format_checkins,
    _has_valid_wwh,
    build_monthly_time_report_snapshot,
    create_monthly_time_report_snapshot,
    get_report_period,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "User",
    "Employee Document",
    "Workday",
    "Leave Application",
    "Leave Type",
    "Time Account Ledger Entry",
    "DocType",
]


SERVICE_MODULE = (
    "hr_addon.hr_addon.doctype."
    "monthly_time_report."
    "monthly_time_report_service"
)


class TestMonthlyTimeReport(
    IntegrationTestCase
):
    def _employee(
        self,
        **overrides,
    ):
        values = {
            "name": (
                "HR-EMP-00001"
            ),
            "employee_name": (
                "Christian Gold"
            ),
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

    def _workday(
        self,
        **overrides,
    ):
        values = {
            "name": (
                "WD-2026-00001"
            ),
            "log_date": (
                getdate(
                    "2026-08-03"
                )
            ),
            "status": (
                "Present"
            ),
            "target_minutes": 480,
            "raw_work_minutes": 480,
            "physical_break_minutes": 30,
            "qualifying_break_minutes": 30,
            "required_break_minutes": 30,
            "automatic_break_deduction_minutes": 0,
            "absence_credit_minutes": 0,
            "accountable_minutes": 480,
            "daily_delta_minutes": 0,
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def test_report_period_normal_month(
        self,
    ):
        period_from, period_to = (
            get_report_period(
                2026,
                9,
            )
        )

        self.assertEqual(
            period_from,
            getdate(
                "2026-09-01"
            ),
        )

        self.assertEqual(
            period_to,
            getdate(
                "2026-09-30"
            ),
        )

    def test_report_period_leap_year(
        self,
    ):
        _, period_to = (
            get_report_period(
                2028,
                2,
            )
        )

        self.assertEqual(
            period_to,
            getdate(
                "2028-02-29"
            ),
        )

    def test_invalid_month_is_rejected(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            get_report_period(
                2026,
                13,
            )

    def test_checkin_sequence_is_preserved(
        self,
    ):
        checkins = [
            frappe._dict(
                {
                    "log_type": "IN",
                    "log_time": (
                        "2026-08-03 "
                        "08:01:12"
                    ),
                    "skip_auto_attendance": 0,
                }
            ),
            frappe._dict(
                {
                    "log_type": "OUT",
                    "log_time": (
                        "2026-08-03 "
                        "12:03:00"
                    ),
                    "skip_auto_attendance": 0,
                }
            ),
            frappe._dict(
                {
                    "log_type": "IN",
                    "log_time": (
                        "2026-08-03 "
                        "12:32:00"
                    ),
                    "skip_auto_attendance": 1,
                }
            ),
        ]

        self.assertEqual(
            _format_checkins(
                checkins
            ),
            (
                "08:01 IN · "
                "12:03 OUT · "
                "12:32 IN [ignored]"
            ),
        )

    def test_valid_wwh_period_is_detected(
        self,
    ):
        periods = [
            frappe._dict(
                {
                    "name": "WWH-1",
                    "valid_from": (
                        "2026-08-01"
                    ),
                    "valid_to": None,
                }
            )
        ]

        self.assertTrue(
            _has_valid_wwh(
                periods,
                "2026-08-03",
            )
        )

    def test_multiple_wwh_periods_fail_closed(
        self,
    ):
        periods = [
            frappe._dict(
                {
                    "name": "WWH-1",
                    "valid_from": (
                        "2026-08-01"
                    ),
                    "valid_to": None,
                }
            ),
            frappe._dict(
                {
                    "name": "WWH-2",
                    "valid_from": (
                        "2026-08-02"
                    ),
                    "valid_to": None,
                }
            ),
        ]

        with self.assertRaises(
            frappe.ValidationError
        ):
            _has_valid_wwh(
                periods,
                "2026-08-03",
            )

    def test_day_snapshot_copies_authoritative_minutes(
        self,
    ):
        workday = self._workday(
            target_minutes=480,
            raw_work_minutes=505,
            physical_break_minutes=20,
            qualifying_break_minutes=20,
            required_break_minutes=45,
            automatic_break_deduction_minutes=25,
            absence_credit_minutes=0,
            accountable_minutes=480,
            daily_delta_minutes=0,
        )

        row = _build_day_snapshot(
            getdate(
                "2026-08-03"
            ),
            self._employee(),
            workday,
            [],
            None,
            True,
        )

        self.assertEqual(
            row[
                "snapshot_status"
            ],
            SNAPSHOT_STATUS_OK,
        )

        self.assertEqual(
            row[
                "raw_work_minutes"
            ],
            505,
        )

        self.assertEqual(
            row[
                "physical_break_minutes"
            ],
            20,
        )

        self.assertEqual(
            row[
                "automatic_break_deduction_minutes"
            ],
            25,
        )

        self.assertEqual(
            row[
                "accountable_minutes"
            ],
            480,
        )

    def test_missing_workday_is_blocking(
        self,
    ):
        row = _build_day_snapshot(
            getdate(
                "2026-08-03"
            ),
            self._employee(),
            None,
            [],
            None,
            True,
        )

        self.assertEqual(
            row[
                "snapshot_status"
            ],
            SNAPSHOT_STATUS_MISSING_WORKDAY,
        )

    def test_missing_checkin_workday_is_blocking(
        self,
    ):
        row = _build_day_snapshot(
            getdate(
                "2026-08-03"
            ),
            self._employee(),
            self._workday(
                status=(
                    "Missing Checkin"
                )
            ),
            [],
            None,
            True,
        )

        self.assertEqual(
            row[
                "snapshot_status"
            ],
            SNAPSHOT_STATUS_MISSING_CHECKIN,
        )

    def test_missing_wwh_is_blocking(
        self,
    ):
        row = _build_day_snapshot(
            getdate(
                "2026-08-03"
            ),
            self._employee(),
            None,
            [],
            None,
            False,
        )

        self.assertEqual(
            row[
                "snapshot_status"
            ],
            SNAPSHOT_STATUS_NO_WWH,
        )

    def test_outside_employment_is_not_a_workday_issue(
        self,
    ):
        row = _build_day_snapshot(
            getdate(
                "2026-08-03"
            ),
            self._employee(
                date_of_joining=(
                    getdate(
                        "2026-08-10"
                    )
                )
            ),
            None,
            [],
            None,
            False,
        )

        self.assertEqual(
            row[
                "snapshot_status"
            ],
            SNAPSHOT_STATUS_OUTSIDE_EMPLOYMENT,
        )

    def test_build_snapshot_uses_ledger_for_balances(
        self,
    ):
        employee = (
            self._employee()
        )

        workdays = {}

        for day in range(
            1,
            32,
        ):
            report_date = getdate(
                f"2026-08-{day:02d}"
            )

            workdays[
                report_date
            ] = self._workday(
                name=(
                    f"WD-{day:02d}"
                ),
                log_date=(
                    report_date
                ),
                target_minutes=0,
                raw_work_minutes=0,
                physical_break_minutes=0,
                qualifying_break_minutes=0,
                required_break_minutes=0,
                automatic_break_deduction_minutes=0,
                absence_credit_minutes=0,
                accountable_minutes=0,
                daily_delta_minutes=0,
            )

        ledger_entries = [
            frappe._dict(
                {
                    "name": "TAL-1",
                    "effective_date": (
                        "2026-08-03"
                    ),
                    "effective_time": (
                        "00:00:00"
                    ),
                    "entry_type": (
                        "Positive Adjustment"
                    ),
                    "delta_minutes": 60,
                    "voucher_type": None,
                    "voucher_no": None,
                    "reverses_entry": None,
                    "remarks": "Test +60",
                }
            ),
            frappe._dict(
                {
                    "name": "TAL-2",
                    "effective_date": (
                        "2026-08-04"
                    ),
                    "effective_time": (
                        "00:00:00"
                    ),
                    "entry_type": (
                        "Negative Adjustment"
                    ),
                    "delta_minutes": -15,
                    "voucher_type": None,
                    "voucher_no": None,
                    "reverses_entry": None,
                    "remarks": "Test -15",
                }
            ),
        ]

        with (
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_employee_row"
                ),
                return_value=employee,
            ),
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_workdays"
                ),
                return_value=workdays,
            ),
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_checkins_by_workday"
                ),
                return_value={},
            ),
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_leave_by_date"
                ),
                return_value={},
            ),
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_wwh_periods"
                ),
                return_value=[
                    frappe._dict(
                        {
                            "name": "WWH-1",
                            "valid_from": (
                                "2026-01-01"
                            ),
                            "valid_to": None,
                        }
                    )
                ],
            ),
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_opening_balance"
                ),
                return_value=120,
            ),
            patch(
                (
                    f"{SERVICE_MODULE}."
                    "_get_period_ledger_entries"
                ),
                return_value=(
                    ledger_entries
                ),
            ),
        ):
            snapshot = (
                build_monthly_time_report_snapshot(
                    "HR-EMP-00001",
                    2026,
                    8,
                    reference_datetime=(
                        datetime(
                            2026,
                            9,
                            29,
                            10,
                            0,
                            0,
                        )
                    ),
                )
            )

        self.assertEqual(
            snapshot[
                "opening_balance_minutes"
            ],
            120,
        )

        self.assertEqual(
            snapshot[
                "ledger_movement_minutes"
            ],
            45,
        )

        self.assertEqual(
            snapshot[
                "closing_balance_minutes"
            ],
            165,
        )

        self.assertEqual(
            len(
                snapshot[
                    "ledger_entries"
                ]
            ),
            2,
        )

        self.assertEqual(
            len(
                snapshot[
                    "days"
                ]
            ),
            31,
        )

        self.assertEqual(
            snapshot[
                "blocking_issue_count"
            ],
            0,
        )

        self.assertEqual(
            snapshot[
                "is_complete"
            ],
            1,
        )

    def test_current_month_is_rejected(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            build_monthly_time_report_snapshot(
                "HR-EMP-00001",
                2026,
                9,
                reference_datetime=(
                    datetime(
                        2026,
                        9,
                        29,
                        10,
                        0,
                        0,
                    )
                ),
            )

    def test_duplicate_current_report_is_rejected(
        self,
    ):
        with patch(
            (
                f"{SERVICE_MODULE}."
                "frappe.db.get_value"
            ),
            return_value=(
                "MTR-2026-00001"
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                create_monthly_time_report_snapshot(
                    "HR-EMP-00001",
                    2026,
                    8,
                    reference_datetime=(
                        datetime(
                            2026,
                            9,
                            29,
                            10,
                            0,
                            0,
                        )
                    ),
                )

    def test_direct_document_change_is_rejected(
        self,
    ):
        doc = MonthlyTimeReport(
            {
                "doctype": (
                    "Monthly Time Report"
                )
            }
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            doc.validate()

    def test_service_flag_allows_controller_validation_path(
        self,
    ):
        doc = MonthlyTimeReport(
            {
                "doctype": (
                    "Monthly Time Report"
                ),
                "report_year": 2026,
                "report_month": 8,
                "period_from": (
                    "2026-08-01"
                ),
                "period_to": (
                    "2026-08-31"
                ),
                "revision": 1,
                "status": (
                    "Generated"
                ),
                "opening_balance_minutes": 0,
                "ledger_movement_minutes": 0,
                "closing_balance_minutes": 0,
                "blocking_issue_count": 31,
                "is_complete": 0,
            }
        )

        doc.flags[
            SERVICE_FLAG
        ] = True

        for day in range(
            1,
            32,
        ):
            doc.append(
                "days",
                {
                    "report_date": (
                        f"2026-08-{day:02d}"
                    ),
                    "snapshot_status": (
                        "Missing Workday"
                    ),
                },
            )

        doc.validate()

    def test_snapshot_consistency_rejects_wrong_closing_balance(
        self,
    ):
        doc = frappe._dict(
            {
                "report_year": 2026,
                "report_month": 8,
                "period_from": (
                    "2026-08-01"
                ),
                "period_to": (
                    "2026-08-31"
                ),
                "opening_balance_minutes": 100,
                "ledger_movement_minutes": 60,
                "closing_balance_minutes": 999,
                "blocking_issue_count": 31,
                "is_complete": 0,
                "days": [],
                "ledger_entries": [],
            }
        )

        for day in range(
            1,
            32,
        ):
            doc.days.append(
                frappe._dict(
                    {
                        "report_date": (
                            f"2026-08-{day:02d}"
                        ),
                        "snapshot_status": (
                            "Missing Workday"
                        ),
                    }
                )
            )

        doc.ledger_entries.append(
            frappe._dict(
                {
                    "delta_minutes": 60
                }
            )
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            _validate_snapshot_consistency(
                doc
            )

    def test_report_cannot_be_deleted(
        self,
    ):
        doc = MonthlyTimeReport(
            {
                "doctype": (
                    "Monthly Time Report"
                )
            }
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            doc.on_trash()
