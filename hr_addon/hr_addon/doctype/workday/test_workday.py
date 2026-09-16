# Copyright (c) 2022, phamos.eu and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from hr_addon.hr_addon.doctype.workday.workday import (
    date_is_in_holiday_list,
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
