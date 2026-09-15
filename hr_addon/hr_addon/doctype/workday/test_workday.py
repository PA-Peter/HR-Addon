# Copyright (c) 2022, phamos.eu and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.workday.workday import date_is_in_holiday_list


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "Company",
    "Attendance",
    "Employee Checkin",
]


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
