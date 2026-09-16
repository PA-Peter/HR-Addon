# Copyright (c) 2022, phamos.eu and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from hr_addon.hr_addon.doctype.workday.workday import (
    date_is_in_holiday_list,
    evaluate_minimum_break,
    parse_employee_checkins,
)

IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "Company",
    "Attendance",
    "Employee Checkin",
]

def _make_checkin(
    name,
    log_type,
    timestamp,
    skip_auto_attendance=0,
):
    return frappe._dict(
        {
            "name": name,
            "log_type": log_type,
            "time": timestamp,
            "skip_auto_attendance": skip_auto_attendance,
            "attendance": None,
        }
    )


class TestEmployeeCheckinParser(UnitTestCase):
    def test_valid_multiple_in_out_pairs_use_log_types(self):
        checkins = [
            _make_checkin("CI-3", "IN", "2026-09-10 13:00:00"),
            _make_checkin("CI-4", "OUT", "2026-09-10 17:00:00"),
            _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
            _make_checkin("CI-2", "OUT", "2026-09-10 12:00:00"),
        ]

        result = parse_employee_checkins(checkins)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["raw_work_minutes"], 480)
        self.assertEqual(result["physical_break_minutes"], 60)
        self.assertEqual(len(result["work_intervals"]), 2)

    def test_sequence_starting_with_out_is_invalid(self):
        result = parse_employee_checkins(
            [
                _make_checkin("CI-1", "OUT", "2026-09-10 08:00:00"),
                _make_checkin("CI-2", "IN", "2026-09-10 17:00:00"),
            ]
        )

        self.assertFalse(result["is_valid"])
        self.assertIn("expected IN", result["error"])

    def test_double_in_is_invalid(self):
        result = parse_employee_checkins(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
                _make_checkin("CI-2", "IN", "2026-09-10 12:00:00"),
                _make_checkin("CI-3", "OUT", "2026-09-10 17:00:00"),
            ]
        )

        self.assertFalse(result["is_valid"])
        self.assertIn("expected OUT", result["error"])

    def test_missing_out_is_invalid(self):
        result = parse_employee_checkins(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
            ]
        )

        self.assertFalse(result["is_valid"])
        self.assertEqual(result["error"], "Missing OUT Employee Checkin.")

    def test_skip_auto_attendance_is_ignored_but_kept_for_audit(self):
        checkins = [
            _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
            _make_checkin(
                "CI-X",
                "OUT",
                "2026-09-10 10:00:00",
                skip_auto_attendance=1,
            ),
            _make_checkin("CI-2", "OUT", "2026-09-10 12:00:00"),
        ]

        result = parse_employee_checkins(checkins)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["raw_work_minutes"], 240)
        self.assertEqual(len(result["audit_checkins"]), 3)
        self.assertEqual(len(result["effective_checkins"]), 2)

    def test_only_skipped_checkins_have_no_time_effect(self):
        result = parse_employee_checkins(
            [
                _make_checkin(
                    "CI-1",
                    "IN",
                    "2026-09-10 08:00:00",
                    skip_auto_attendance=1,
                ),
                _make_checkin(
                    "CI-2",
                    "OUT",
                    "2026-09-10 17:00:00",
                    skip_auto_attendance=1,
                ),
            ]
        )

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["raw_work_minutes"], 0)
        self.assertEqual(result["physical_break_minutes"], 0)
        self.assertEqual(len(result["audit_checkins"]), 2)
        self.assertEqual(len(result["effective_checkins"]), 0)

    def test_seconds_are_not_rounded_up(self):
        result = parse_employee_checkins(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:59"),
                _make_checkin("CI-2", "OUT", "2026-09-10 09:00:01"),
            ]
        )

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["raw_work_minutes"], 59)

class TestWorkday(IntegrationTestCase):
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
                "first_name": f"HLA Test {self._testMethodName}",
                "company": self.company,
                "date_of_birth": "1990-01-01",
                "date_of_joining": "2026-01-01",
                "gender": gender,
                "status": "Active",
            }
        ).insert().name

        self.holiday_list = frappe.get_doc(
            {
                "doctype": "Holiday List",
                "holiday_list_name": f"_Test HLA {self._testMethodName}",
                "from_date": "2026-09-01",
                "to_date": "2026-12-31",
                "holidays": [
                    {
                        "holiday_date": "2026-09-04",
                        "description": "Test Holiday",
                    }
                ],
            }
        ).insert().name

        assignment = frappe.get_doc(
            {
                "doctype": "Holiday List Assignment",
                "applicable_for": "Employee",
                "assigned_to": self.employee,
                "holiday_list": self.holiday_list,
                "from_date": "2026-09-04",
            }
        )
        assignment.insert()
        assignment.submit()

    def test_date_before_holiday_list_assignment_is_not_holiday(self):
        self.assertFalse(
            date_is_in_holiday_list(
                self.employee,
                "2026-09-03",
            )
        )

    def test_assigned_holiday_is_detected(self):
        self.assertTrue(
            date_is_in_holiday_list(
                self.employee,
                "2026-09-04",
            )
        )

    def test_assigned_non_holiday_is_not_holiday(self):
        self.assertFalse(
            date_is_in_holiday_list(
                self.employee,
                "2026-09-08",
            )
        )

class TestMinimumBreakEvaluation(UnitTestCase):
    RULES = [
        frappe._dict(
            from_hours=0,
            to_hours=6,
            minimum_break_minutes=0,
        ),
        frappe._dict(
            from_hours=6,
            to_hours=9,
            minimum_break_minutes=30,
        ),
        frappe._dict(
            from_hours=9,
            to_hours=None,
            minimum_break_minutes=45,
        ),
    ]

    def evaluate(self, raw_work_minutes, breaks=None):
        return evaluate_minimum_break(
            raw_work_minutes,
            breaks or [],
            self.RULES,
        )

    def test_6_hours_requires_no_break(self):
        result = self.evaluate(360)

        self.assertEqual(result["required_break_minutes"], 0)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 0
        )
        self.assertEqual(result["accountable_minutes"], 360)

    def test_6_hours_1_minute_requires_30_minutes(self):
        result = self.evaluate(361)

        self.assertEqual(result["required_break_minutes"], 30)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 30
        )
        self.assertEqual(result["accountable_minutes"], 331)

    def test_9_hours_requires_30_minutes(self):
        result = self.evaluate(540)

        self.assertEqual(result["required_break_minutes"], 30)

    def test_9_hours_1_minute_requires_45_minutes(self):
        result = self.evaluate(541)

        self.assertEqual(result["required_break_minutes"], 45)

    def test_20_minute_break_reduces_45_minute_requirement(self):
        result = self.evaluate(
            600,
            [{"minutes": 20}],
        )

        self.assertEqual(result["qualifying_break_minutes"], 20)
        self.assertEqual(result["required_break_minutes"], 45)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 25
        )
        self.assertEqual(result["accountable_minutes"], 575)

    def test_two_15_minute_breaks_both_qualify(self):
        result = self.evaluate(
            600,
            [{"minutes": 15}, {"minutes": 15}],
        )

        self.assertEqual(result["qualifying_break_minutes"], 30)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 15
        )

    def test_14_minute_break_does_not_qualify(self):
        result = self.evaluate(
            600,
            [{"minutes": 14}, {"minutes": 30}],
        )

        self.assertEqual(result["qualifying_break_minutes"], 30)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 15
        )

    def test_longer_real_break_causes_no_extra_deduction(self):
        result = self.evaluate(
            600,
            [{"minutes": 60}],
        )

        self.assertEqual(result["qualifying_break_minutes"], 60)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 0
        )
        self.assertEqual(result["accountable_minutes"], 600)

    def test_short_breaks_are_not_combined_to_qualify(self):
        result = self.evaluate(
            600,
            [{"minutes": 5}, {"minutes": 10}],
        )

        self.assertEqual(result["qualifying_break_minutes"], 0)
        self.assertEqual(
            result["automatic_break_deduction_minutes"], 45
        )
