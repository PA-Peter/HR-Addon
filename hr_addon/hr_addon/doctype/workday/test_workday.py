# Copyright (c) 2022, phamos.eu and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from unittest.mock import patch

from hr_addon.hr_addon.doctype.workday.workday import (
    MECHANISM_MINIMUM_BREAK_RULE,
    Workday,
    date_is_in_holiday_list,
    evaluate_daily_minutes,
    evaluate_minimum_break,
    get_workday,
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

class TestWorkdayFailClosedDelta(UnitTestCase):
    def _validate_from_parsed_checkins(
        self,
        parsed_checkins,
        absence_credit_cap_minutes=0,
        status_override=None,
    ):
        workday = Workday(
            {
                "doctype": "Workday",
            }
        )

        def set_actual_employee_log():
            workday.status = (
                status_override
                if status_override is not None
                else (
                    "Missing Checkin"
                    if not parsed_checkins["is_valid"]
                    else ""
                )
            )

            workday.first_checkin = parsed_checkins[
                "first_checkin"
            ]
            workday.last_checkout = parsed_checkins[
                "last_checkout"
            ]

            workday.target_hours = 8
            workday.raw_work_minutes = 0
            workday.physical_break_minutes = 0
            workday.qualifying_break_minutes = 0
            workday.required_break_minutes = 0
            workday.automatic_break_deduction_minutes = 0
            workday.accountable_minutes = 0

            workday.employee_checkins = []

            for checkin in parsed_checkins[
                "audit_checkins"
            ]:
                workday.append(
                    "employee_checkins",
                    {
                        "employee_checkin": checkin.get(
                            "name"
                        ),
                        "log_type": checkin.get(
                            "log_type"
                        ),
                        "log_time": checkin.get(
                            "time"
                        ),
                        "skip_auto_attendance": checkin.get(
                            "skip_auto_attendance"
                        ),
                    },
                )

        settings = frappe._dict(
            workday_break_calculation_mechanism=(
                MECHANISM_MINIMUM_BREAK_RULE
            )
        )

        with (
            patch.object(
                workday,
                "set_actual_employee_log",
                side_effect=set_actual_employee_log,
            ),
            patch.object(
                workday,
                "validate_duplicate_workday",
            ),
            patch.object(
                workday,
                "set_status_for_leave_application",
                return_value=absence_credit_cap_minutes,
            ),
            patch(
                "hr_addon.hr_addon.doctype.workday.workday."
                "frappe.get_cached_doc",
                return_value=settings,
            ),
        ):
            workday.validate()

        return workday

    def test_no_checkins_create_negative_target_delta(self):
        parsed = parse_employee_checkins([])

        self.assertTrue(parsed["is_valid"])
        self.assertEqual(
            parsed["effective_checkins"],
            [],
        )
        self.assertEqual(
            parsed["audit_checkins"],
            [],
        )

        workday = self._validate_from_parsed_checkins(
            parsed
        )

        self.assertEqual(
            workday.target_minutes,
            480,
        )
        self.assertEqual(
            workday.accountable_minutes,
            0,
        )
        self.assertEqual(
            workday.absence_credit_minutes,
            0,
        )
        self.assertEqual(
            workday.daily_delta_minutes,
            -480,
        )

    def test_only_skipped_checkins_do_not_create_negative_delta(
        self,
    ):
        parsed = parse_employee_checkins(
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

        self.assertTrue(parsed["is_valid"])
        self.assertEqual(
            parsed["effective_checkins"],
            [],
        )
        self.assertEqual(
            len(parsed["audit_checkins"]),
            2,
        )

        workday = self._validate_from_parsed_checkins(
            parsed
        )

        self.assertEqual(
            workday.target_minutes,
            480,
        )
        self.assertEqual(
            workday.accountable_minutes,
            0,
        )
        self.assertEqual(
            workday.daily_delta_minutes,
            0,
        )

    def test_full_day_leave_without_checkins_is_neutral(
        self,
    ):
        parsed = parse_employee_checkins([])

        workday = self._validate_from_parsed_checkins(
            parsed,
            absence_credit_cap_minutes=480,
        )

        self.assertEqual(
            workday.target_minutes,
            480,
        )
        self.assertEqual(
            workday.accountable_minutes,
            0,
        )
        self.assertEqual(
            workday.absence_credit_minutes,
            480,
        )
        self.assertEqual(
            workday.daily_delta_minutes,
            0,
        )

    def test_not_workday_without_checkins_is_neutral(
        self,
    ):
        parsed = parse_employee_checkins([])

        workday = self._validate_from_parsed_checkins(
            parsed,
            status_override="Not Workday",
        )

        self.assertEqual(
            workday.target_minutes,
            480,
        )
        self.assertEqual(
            workday.accountable_minutes,
            0,
        )
        self.assertEqual(
            workday.daily_delta_minutes,
            0,
        )

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
class TestWorkdayMinimumBreakRouting(UnitTestCase):
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

    def _settings(self, qualifying_break_minutes=15):
        return frappe._dict(
            workday_break_calculation_mechanism=MECHANISM_MINIMUM_BREAK_RULE,
            swap_hours_worked_and_actual_working_hours=0,
            minimum_qualifying_break_minutes=qualifying_break_minutes,
            minimum_break_rule=self.RULES,
        )

    def _work_hours(self):
        return frappe._dict(
            hours=8,
            break_minutes=30,
        )

    def _get_workday(
        self,
        checkins,
        qualifying_break_minutes=15,
            disable_minimum_break_rule=False,
    ):
        with patch(
            "hr_addon.hr_addon.doctype.workday.workday."
            "frappe.get_cached_doc",
            return_value=self._settings(qualifying_break_minutes),
        ):
            return get_workday(
                checkins,
                self._work_hours(),
                disable_minimum_break_rule,
            )

    def test_minimum_break_route_does_not_double_deduct_physical_break(self):
        result = self._get_workday(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
                _make_checkin("CI-2", "OUT", "2026-09-10 12:00:00"),
                _make_checkin("CI-3", "IN", "2026-09-10 12:20:00"),
                _make_checkin("CI-4", "OUT", "2026-09-10 18:20:00"),
            ]
        )

        self.assertEqual(result["raw_work_minutes"], 600)
        self.assertEqual(result["physical_break_minutes"], 20)
        self.assertEqual(result["qualifying_break_minutes"], 20)
        self.assertEqual(result["required_break_minutes"], 45)
        self.assertEqual(
            result["automatic_break_deduction_minutes"],
            25,
        )
        self.assertEqual(result["accountable_minutes"], 575)

        self.assertAlmostEqual(
            result["actual_working_hours"],
            575 / 60,
        )
        self.assertAlmostEqual(result["break_hours"], 45 / 60)
        self.assertAlmostEqual(
            result["expected_break_hours"],
            45 / 60,
        )

    def test_long_physical_break_has_no_automatic_deduction(self):
        result = self._get_workday(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
                _make_checkin("CI-2", "OUT", "2026-09-10 12:00:00"),
                _make_checkin("CI-3", "IN", "2026-09-10 13:00:00"),
                _make_checkin("CI-4", "OUT", "2026-09-10 19:00:00"),
            ]
        )

        self.assertEqual(result["raw_work_minutes"], 600)
        self.assertEqual(result["physical_break_minutes"], 60)
        self.assertEqual(result["qualifying_break_minutes"], 60)
        self.assertEqual(result["required_break_minutes"], 45)
        self.assertEqual(
            result["automatic_break_deduction_minutes"],
            0,
        )
        self.assertEqual(result["accountable_minutes"], 600)

        self.assertAlmostEqual(result["actual_working_hours"], 10)
        self.assertAlmostEqual(result["break_hours"], 1)

    def test_qualification_threshold_comes_from_settings(self):
        result = self._get_workday(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
                _make_checkin("CI-2", "OUT", "2026-09-10 12:00:00"),
                _make_checkin("CI-3", "IN", "2026-09-10 12:15:00"),
                _make_checkin("CI-4", "OUT", "2026-09-10 18:15:00"),
            ],
            qualifying_break_minutes=20,
        )

        self.assertEqual(result["physical_break_minutes"], 15)
        self.assertEqual(result["qualifying_break_minutes"], 0)
        self.assertEqual(result["required_break_minutes"], 45)
        self.assertEqual(
            result["automatic_break_deduction_minutes"],
            45,
        )
        self.assertEqual(result["accountable_minutes"], 555)

    def test_disabled_minimum_break_rule_has_no_auto_deduction(self):
        result = self._get_workday(
            [
                _make_checkin(
                    "CI-1",
                    "IN",
                    "2026-09-10 08:00:00",
                ),
                _make_checkin(
                    "CI-2",
                    "OUT",
                    "2026-09-10 14:01:00",
                ),
            ],
            disable_minimum_break_rule=True,
        )

        self.assertEqual(result["raw_work_minutes"], 361)
        self.assertEqual(result["required_break_minutes"], 0)
        self.assertEqual(
            result["automatic_break_deduction_minutes"],
            0,
        )
        self.assertEqual(result["accountable_minutes"], 361)
    def test_zero_qualification_setting_falls_back_to_15_minutes(self):
        result = self._get_workday(
            [
                _make_checkin("CI-1", "IN", "2026-09-10 08:00:00"),
                _make_checkin("CI-2", "OUT", "2026-09-10 12:00:00"),
                _make_checkin("CI-3", "IN", "2026-09-10 12:10:00"),
                _make_checkin("CI-4", "OUT", "2026-09-10 18:10:00"),
            ],
            qualifying_break_minutes=0,
        )

        self.assertEqual(result["physical_break_minutes"], 10)
        self.assertEqual(result["qualifying_break_minutes"], 0)
        self.assertEqual(
            result["automatic_break_deduction_minutes"],
            45,
        )

class TestDailyMinuteEvaluation(UnitTestCase):
    def test_full_absence_credits_full_target(self):
        result = evaluate_daily_minutes(
            target_minutes=480,
            accountable_minutes=0,
            absence_credit_cap_minutes=480,
        )

        self.assertEqual(result["target_minutes"], 480)
        self.assertEqual(result["absence_credit_minutes"], 480)
        self.assertEqual(result["daily_delta_minutes"], 0)

    def test_partial_absence_credits_only_missing_target(self):
        result = evaluate_daily_minutes(
            target_minutes=480,
            accountable_minutes=240,
            absence_credit_cap_minutes=240,
        )

        self.assertEqual(result["absence_credit_minutes"], 240)
        self.assertEqual(result["daily_delta_minutes"], 0)

    def test_absence_does_not_create_extra_credit(self):
        result = evaluate_daily_minutes(
            target_minutes=480,
            accountable_minutes=495,
            absence_credit_cap_minutes=480,
        )

        self.assertEqual(result["absence_credit_minutes"], 0)
        self.assertEqual(result["daily_delta_minutes"], 15)

    def test_zero_target_day_with_work_is_positive(self):
        result = evaluate_daily_minutes(
            target_minutes=0,
            accountable_minutes=180,
        )

        self.assertEqual(result["absence_credit_minutes"], 0)
        self.assertEqual(result["daily_delta_minutes"], 180)
    
    def test_invalid_day_has_no_delta(self):
        result = evaluate_daily_minutes(
            target_minutes=480,
            accountable_minutes=0,
            absence_credit_cap_minutes=480,
            delta_is_valid=False,
        )

        self.assertEqual(result["daily_delta_minutes"], 0)
