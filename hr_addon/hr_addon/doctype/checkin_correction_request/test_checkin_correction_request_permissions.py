# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import frappe

from unittest.mock import patch

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.checkin_correction_request.checkin_correction_request_permissions import (
    get_permission_query_conditions,
    has_permission,
    validate_self_service_employee,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "Company",
    "Employee Checkin",
    "Workday",
    "Workday Reprocessing Log",
    "User",
]


MODULE = (
    "hr_addon.hr_addon.doctype."
    "checkin_correction_request."
    "checkin_correction_request_permissions"
)


class TestCheckinCorrectionRequestPermissions(
    IntegrationTestCase
):
    def _doc(
        self,
        employee=None,
    ):
        return frappe._dict(
            {
                "doctype": (
                    "Checkin Correction Request"
                ),
                "employee": employee,
            }
        )

    def test_manager_query_is_unrestricted(
        self,
    ):
        with patch(
            f"{MODULE}._has_management_access",
            return_value=True,
        ):
            condition = (
                get_permission_query_conditions(
                    "manager@example.com"
                )
            )

        self.assertIsNone(
            condition
        )

    def test_employee_query_is_restricted_to_own_employee(
        self,
    ):
        with (
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            condition = (
                get_permission_query_conditions(
                    "employee@example.com"
                )
            )

        self.assertIn(
            "`employee`",
            condition,
        )

        self.assertIn(
            "HR-EMP-SELF",
            condition,
        )

    def test_user_without_employee_sees_nothing(
        self,
    ):
        with (
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value=None,
            ),
        ):
            condition = (
                get_permission_query_conditions(
                    "unknown@example.com"
                )
            )

        self.assertEqual(
            condition,
            "1=0",
        )

    def test_manager_has_document_permission(
        self,
    ):
        doc = self._doc(
            "HR-EMP-OTHER"
        )

        with patch(
            f"{MODULE}._has_management_access",
            return_value=True,
        ):
            allowed = has_permission(
                doc,
                ptype="write",
                user="manager@example.com",
            )

        self.assertTrue(
            allowed
        )

    def test_employee_can_access_own_request(
        self,
    ):
        doc = self._doc(
            "HR-EMP-SELF"
        )

        with (
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            allowed = has_permission(
                doc,
                ptype="read",
                user="employee@example.com",
            )

        self.assertTrue(
            allowed
        )

    def test_employee_cannot_access_other_request(
        self,
    ):
        doc = self._doc(
            "HR-EMP-OTHER"
        )

        with (
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            allowed = has_permission(
                doc,
                ptype="read",
                user="employee@example.com",
            )

        self.assertFalse(
            allowed
        )

    def test_employee_can_open_new_request_form(
        self,
    ):
        doc = self._doc()

        with (
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            allowed = has_permission(
                doc,
                ptype="create",
                user="employee@example.com",
            )

        self.assertTrue(
            allowed
        )

    def test_self_service_validation_accepts_own_employee(
        self,
    ):
        doc = self._doc(
            "HR-EMP-SELF"
        )

        with (
            patch(
                f"{MODULE}._get_user",
                return_value="employee@example.com",
            ),
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            validate_self_service_employee(
                doc
            )

    def test_self_service_validation_rejects_other_employee(
        self,
    ):
        doc = self._doc(
            "HR-EMP-OTHER"
        )

        with (
            patch(
                f"{MODULE}._get_user",
                return_value="employee@example.com",
            ),
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            with self.assertRaises(
                frappe.PermissionError
            ):
                validate_self_service_employee(
                    doc
                )

    def test_manager_validation_allows_other_employee(
        self,
    ):
        doc = self._doc(
            "HR-EMP-OTHER"
        )

        with (
            patch(
                f"{MODULE}._get_user",
                return_value="manager@example.com",
            ),
            patch(
                f"{MODULE}._has_management_access",
                return_value=True,
            ),
        ):
            validate_self_service_employee(
                doc
            )

    def test_self_service_cannot_set_audit_fields(
        self,
    ):
        doc = self._doc(
            "HR-EMP-SELF"
        )

        doc.reprocessing_log = (
            "WRL-FAKE"
        )

        with (
            patch(
                f"{MODULE}._get_user",
                return_value="employee@example.com",
            ),
            patch(
                f"{MODULE}._has_management_access",
                return_value=False,
            ),
            patch(
                f"{MODULE}._get_employee_for_user",
                return_value="HR-EMP-SELF",
            ),
        ):
            with self.assertRaises(
                frappe.PermissionError
            ):
                validate_self_service_employee(
                    doc
                )
