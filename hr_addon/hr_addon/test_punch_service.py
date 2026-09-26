# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from frappe.tests import IntegrationTestCase
from frappe.utils import get_datetime, getdate

from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
    ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
    ENTRY_TYPE_POSITIVE_ADJUSTMENT,
)
from hr_addon.hr_addon.punch_service import (
    KIOSK_DEVICE_ID,
    process_punch,
    punch,
)


class TestPunchService(IntegrationTestCase):
    def setUp(self):
        super().setUp()

        previous_user = getattr(
            frappe.session,
            "user",
            "Administrator",
        )

        self.addCleanup(
            frappe.set_user,
            previous_user,
        )

        frappe.set_user(
            "Administrator"
        )

        frappe.db.set_single_value(
            "HR Settings",
            "allow_geolocation_tracking",
            0,
        )

        self.company = frappe.get_all(
            "Company",
            pluck="name",
            limit=1,
        )[0]

        self.gender = frappe.get_all(
            "Gender",
            pluck="name",
            limit=1,
        )[0]

        self.device_id = (
            "00" + frappe.generate_hash(length=10)
        )

        self.employee = self.make_employee(
            attendance_device_id=self.device_id
        )

    def make_employee(
        self,
        attendance_device_id,
        status="Active",
    ):
        token = frappe.generate_hash(
            length=8
        )

        employee = frappe.get_doc(
            {
                "doctype": "Employee",
                "naming_series": (
                    "HR-EMP-"
                ),
                "first_name": (
                    f"Punch {token}"
                ),
                "last_name": "Test",
                "company": self.company,
                "date_of_birth": (
                    "1990-01-01"
                ),
                "date_of_joining": (
                    "2026-01-01"
                ),
                "gender": self.gender,
                "status": status,
                "attendance_device_id": (
                    attendance_device_id
                ),
            }
        )

        return employee.insert(
            ignore_permissions=True
        )

    def make_ledger_entry(
        self,
        employee,
        delta_minutes,
        effective_date,
    ):
        if delta_minutes > 0:
            entry_type = (
                ENTRY_TYPE_POSITIVE_ADJUSTMENT
            )
        else:
            entry_type = (
                ENTRY_TYPE_NEGATIVE_ADJUSTMENT
            )

        return frappe.get_doc(
            {
                "doctype": (
                    "Time Account Ledger Entry"
                ),
                "employee": employee,
                "effective_date": (
                    effective_date
                ),
                "effective_time": (
                    "00:00:00"
                ),
                "entry_type": entry_type,
                "delta_minutes": (
                    delta_minutes
                ),
                "remarks": (
                    "Punch service test"
                ),
            }
        ).insert(
            ignore_permissions=True
        )

    def make_workday(
        self,
        employee,
        log_date,
        status,
    ):
        workday = frappe.new_doc(
            "Workday"
        )

        workday.name = (
            "WD-PUNCH-"
            + frappe.generate_hash(
                length=10
            )
        )

        workday.employee = employee
        workday.log_date = log_date
        workday.company = self.company
        workday.status = status

        workday.db_insert()

        return workday

    def get_kiosk_checkins(
        self,
        employee=None,
    ):
        filters = {
            "device_id": (
                KIOSK_DEVICE_ID
            )
        }

        if employee:
            filters["employee"] = (
                employee
            )

        return frappe.get_all(
            "Employee Checkin",
            filters=filters,
            fields=[
                "name",
                "employee",
                "time",
                "log_type",
                "device_id",
            ],
            order_by="time asc, name asc",
        )

    def test_punch_creates_employee_checkin(
        self,
    ):
        result = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:03:15"
            ),
        )

        checkin = frappe.get_doc(
            "Employee Checkin",
            result.employee_checkin,
        )

        self.assertEqual(
            result.employee,
            self.employee.name,
        )

        self.assertEqual(
            result.employee_name,
            self.employee.employee_name,
        )

        self.assertEqual(
            result.log_type,
            "IN",
        )

        self.assertFalse(
            result.debounced
        )

        self.assertEqual(
            checkin.employee,
            self.employee.name,
        )

        self.assertEqual(
            checkin.log_type,
            "IN",
        )

        self.assertEqual(
            checkin.device_id,
            KIOSK_DEVICE_ID,
        )

        self.assertEqual(
            get_datetime(
                checkin.time
            ),
            get_datetime(
                "2026-09-26 08:03:15"
            ),
        )

    def test_device_id_is_preserved_as_text(
        self,
    ):
        result = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:00:00"
            ),
        )

        self.assertEqual(
            result.employee,
            self.employee.name,
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            process_punch(
                attendance_device_id=(
                    12345678
                ),
                log_type="IN",
                current_time=(
                    "2026-09-26 08:01:00"
                ),
            )

    def test_unknown_device_id_is_rejected(
        self,
    ):
        before_count = len(
            self.get_kiosk_checkins()
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            process_punch(
                attendance_device_id=(
                    "9999999999"
                ),
                log_type="IN",
                current_time=(
                    "2026-09-26 08:00:00"
                ),
            )

        after_count = len(
            self.get_kiosk_checkins()
        )

        self.assertEqual(
            after_count,
            before_count,
        )
    def test_inactive_employee_is_rejected(
        self,
    ):
        frappe.db.set_value(
            "Employee",
            self.employee.name,
            "status",
            "Inactive",
            update_modified=False,
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            process_punch(
                attendance_device_id=(
                    self.device_id
                ),
                log_type="IN",
                current_time=(
                    "2026-09-26 08:00:00"
                ),
            )

        self.assertEqual(
            self.get_kiosk_checkins(
                self.employee.name
            ),
            [],
        )

    def test_invalid_log_type_is_rejected(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            process_punch(
                attendance_device_id=(
                    self.device_id
                ),
                log_type="BREAK",
                current_time=(
                    "2026-09-26 08:00:00"
                ),
            )

    def test_identical_punch_is_debounced(
        self,
    ):
        first = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:00:00"
            ),
        )

        second = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:00:02"
            ),
        )

        rows = self.get_kiosk_checkins(
            self.employee.name
        )

        self.assertEqual(
            len(rows),
            1,
        )

        self.assertFalse(
            first.debounced
        )

        self.assertTrue(
            second.debounced
        )

        self.assertEqual(
            first.employee_checkin,
            second.employee_checkin,
        )

    def test_opposite_log_type_is_not_debounced(
        self,
    ):
        first = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:00:00"
            ),
        )

        second = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="OUT",
            current_time=(
                "2026-09-26 08:00:02"
            ),
        )

        rows = self.get_kiosk_checkins(
            self.employee.name
        )

        self.assertEqual(
            len(rows),
            2,
        )

        self.assertFalse(
            first.debounced
        )

        self.assertFalse(
            second.debounced
        )

        self.assertEqual(
            rows[0].log_type,
            "IN",
        )

        self.assertEqual(
            rows[1].log_type,
            "OUT",
        )

    def test_balance_excludes_current_day(
        self,
    ):
        self.make_ledger_entry(
            employee=self.employee.name,
            delta_minutes=120,
            effective_date=(
                "2026-09-24"
            ),
        )

        self.make_ledger_entry(
            employee=self.employee.name,
            delta_minutes=-30,
            effective_date=(
                "2026-09-25"
            ),
        )

        self.make_ledger_entry(
            employee=self.employee.name,
            delta_minutes=999,
            effective_date=(
                "2026-09-26"
            ),
        )

        result = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:00:00"
            ),
        )

        self.assertEqual(
            result.balance_minutes,
            90,
        )

        self.assertEqual(
            getdate(
                result.balance_as_of
            ),
            getdate(
                "2026-09-25"
            ),
        )

    def test_historical_missing_checkins_are_reported(
        self,
    ):
        self.make_workday(
            employee=self.employee.name,
            log_date="2026-09-20",
            status="Missing Checkin",
        )

        self.make_workday(
            employee=self.employee.name,
            log_date="2026-09-24",
            status="Missing Checkin",
        )

        self.make_workday(
            employee=self.employee.name,
            log_date="2026-09-25",
            status="OK",
        )

        # Current day deliberately does not count.
        self.make_workday(
            employee=self.employee.name,
            log_date="2026-09-26",
            status="Missing Checkin",
        )

        result = process_punch(
            attendance_device_id=(
                self.device_id
            ),
            log_type="IN",
            current_time=(
                "2026-09-26 08:00:00"
            ),
        )

        self.assertEqual(
            result.open_checkin_errors,
            2,
        )

    def test_public_endpoint_is_guest_whitelisted_and_post_only(
        self,
    ):
        self.assertIn(
            punch,
            frappe.guest_methods,
        )

        self.assertEqual(
            frappe.allowed_http_methods_for_whitelisted_func[
                punch
            ],
            ["POST"],
        )

    def test_public_endpoint_allows_guest_punch(
        self,
    ):
        frappe.set_user(
            "Guest"
        )

        try:
            result = punch(
                attendance_device_id=(
                    self.device_id
                ),
                log_type="IN",
            )

            checkin = frappe.get_doc(
                "Employee Checkin",
                result.employee_checkin,
            )

            self.assertEqual(
                result.employee,
                self.employee.name,
            )

            self.assertEqual(
                result.log_type,
                "IN",
            )

            self.assertEqual(
                checkin.employee,
                self.employee.name,
            )

            self.assertEqual(
                checkin.log_type,
                "IN",
            )

            self.assertEqual(
                checkin.device_id,
                KIOSK_DEVICE_ID,
            )
        finally:
            frappe.set_user(
                "Administrator"
            )
