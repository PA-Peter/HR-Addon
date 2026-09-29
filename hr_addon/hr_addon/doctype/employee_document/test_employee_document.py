# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

from datetime import datetime
from unittest.mock import patch

import frappe

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.employee_document.employee_document import (
    FOLDER_ARCHIVE,
    FOLDER_INBOX,
    READ_STATUS_NEW,
    READ_STATUS_SEEN,
    _archive_previous_revision,
    _prepare_revision,
    _validate_delete,
    _validate_period,
    _validate_private_file,
    archive_document,
    auto_archive_old_employee_documents,
    mark_seen,
)
from hr_addon.hr_addon.doctype.employee_document.employee_document_permissions import (
    assert_document_action_access,
    get_permission_query_conditions,
    has_permission,
)


IGNORE_TEST_RECORD_DEPENDENCIES = [
    "Employee",
    "File",
    "User",
]


MODULE = (
    "hr_addon.hr_addon.doctype."
    "employee_document.employee_document"
)

PERMISSIONS_MODULE = (
    "hr_addon.hr_addon.doctype."
    "employee_document."
    "employee_document_permissions"
)


class TestEmployeeDocument(
    IntegrationTestCase
):
    def _doc(
        self,
        **overrides,
    ):
        values = {
            "doctype": (
                "Employee Document"
            ),
            "name": "EDOC-TEST",
            "employee": (
                "HR-EMP-SELF"
            ),
            "document_title": (
                "Test Document"
            ),
            "document_type": (
                "Monthly Time Report"
            ),
            "source": (
                "Monthly Time Report"
            ),
            "document_date": (
                "2026-09-30"
            ),
            "period_from": (
                "2026-09-01"
            ),
            "period_to": (
                "2026-09-30"
            ),
            "document_file": (
                "/private/files/test.pdf"
            ),
            "read_status": (
                READ_STATUS_NEW
            ),
            "folder": (
                FOLDER_INBOX
            ),
            "revision": 1,
            "is_current_revision": 1,
            "previous_revision": None,
            "provided_at": datetime(
                2026,
                9,
                29,
                8,
                0,
                0,
            ),
            "seen_at": None,
            "archived_at": None,
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def _previous_revision(
        self,
        **overrides,
    ):
        values = {
            "name": "EDOC-OLD",
            "employee": (
                "HR-EMP-SELF"
            ),
            "document_type": (
                "Monthly Time Report"
            ),
            "source": (
                "Monthly Time Report"
            ),
            "period_from": (
                "2026-09-01"
            ),
            "period_to": (
                "2026-09-30"
            ),
            "revision": 2,
            "is_current_revision": 1,
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def test_manager_query_is_unrestricted(
        self,
    ):
        with patch(
            (
                f"{PERMISSIONS_MODULE}."
                "has_management_access"
            ),
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
                (
                    f"{PERMISSIONS_MODULE}."
                    "has_management_access"
                ),
                return_value=False,
            ),
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "_get_employee_for_user"
                ),
                return_value=(
                    "HR-EMP-SELF"
                ),
            ),
        ):
            condition = (
                get_permission_query_conditions(
                    "employee@example.com"
                )
            )

        self.assertIn(
            (
                "`tabEmployee Document`."
                "`employee`"
            ),
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
                (
                    f"{PERMISSIONS_MODULE}."
                    "has_management_access"
                ),
                return_value=False,
            ),
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "_get_employee_for_user"
                ),
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

    def test_employee_can_read_but_not_write_own_document(
        self,
    ):
        doc = self._doc()

        with (
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "has_management_access"
                ),
                return_value=False,
            ),
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "_get_employee_for_user"
                ),
                return_value=(
                    "HR-EMP-SELF"
                ),
            ),
        ):
            self.assertTrue(
                has_permission(
                    doc,
                    ptype="read",
                    user=(
                        "employee@example.com"
                    ),
                )
            )

            self.assertFalse(
                has_permission(
                    doc,
                    ptype="write",
                    user=(
                        "employee@example.com"
                    ),
                )
            )

    def test_employee_cannot_read_other_document(
        self,
    ):
        doc = self._doc(
            employee="HR-EMP-OTHER"
        )

        with (
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "has_management_access"
                ),
                return_value=False,
            ),
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "_get_employee_for_user"
                ),
                return_value=(
                    "HR-EMP-SELF"
                ),
            ),
        ):
            allowed = (
                has_permission(
                    doc,
                    ptype="read",
                    user=(
                        "employee@example.com"
                    ),
                )
            )

        self.assertFalse(
            allowed
        )

    def test_action_access_rejects_other_employee(
        self,
    ):
        doc = self._doc(
            employee="HR-EMP-OTHER"
        )

        with (
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "has_management_access"
                ),
                return_value=False,
            ),
            patch(
                (
                    f"{PERMISSIONS_MODULE}."
                    "_get_employee_for_user"
                ),
                return_value=(
                    "HR-EMP-SELF"
                ),
            ),
        ):
            with self.assertRaises(
                frappe.PermissionError
            ):
                assert_document_action_access(
                    doc,
                    user=(
                        "employee@example.com"
                    ),
                )

    def test_period_validation(
        self,
    ):
        with self.assertRaises(
            frappe.ValidationError
        ):
            _validate_period(
                self._doc(
                    period_to=None
                )
            )

        with self.assertRaises(
            frappe.ValidationError
        ):
            _validate_period(
                self._doc(
                    period_from=(
                        "2026-10-01"
                    ),
                    period_to=(
                        "2026-09-30"
                    ),
                )
            )

    def test_first_revision_is_revision_one(
        self,
    ):
        doc = self._doc(
            revision=99,
            previous_revision=None,
        )

        _prepare_revision(
            doc
        )

        self.assertEqual(
            doc.revision,
            1,
        )

    def test_next_revision_increments_revision(
        self,
    ):
        doc = self._doc(
            previous_revision=(
                "EDOC-OLD"
            )
        )

        with patch(
            (
                f"{MODULE}."
                "frappe.db.get_value"
            ),
            return_value=(
                self._previous_revision()
            ),
        ):
            _prepare_revision(
                doc
            )

        self.assertEqual(
            doc.revision,
            3,
        )

    def test_new_revision_rejects_non_current_previous_revision(
        self,
    ):
        doc = self._doc(
            previous_revision=(
                "EDOC-OLD"
            )
        )

        with patch(
            (
                f"{MODULE}."
                "frappe.db.get_value"
            ),
            return_value=(
                self._previous_revision(
                    is_current_revision=0
                )
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                _prepare_revision(
                    doc
                )

    def test_new_revision_requires_same_employee(
        self,
    ):
        doc = self._doc(
            previous_revision=(
                "EDOC-OLD"
            )
        )

        with patch(
            (
                f"{MODULE}."
                "frappe.db.get_value"
            ),
            return_value=(
                self._previous_revision(
                    employee=(
                        "HR-EMP-OTHER"
                    )
                )
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                _prepare_revision(
                    doc
                )

    def test_previous_revision_is_archived_after_insert(
        self,
    ):
        doc = self._doc(
            previous_revision=(
                "EDOC-OLD"
            )
        )

        archived_at = datetime(
            2026,
            9,
            29,
            8,
            30,
            0,
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "now_datetime"
                ),
                return_value=(
                    archived_at
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            _archive_previous_revision(
                doc
            )

        set_value.assert_called_once_with(
            "Employee Document",
            "EDOC-OLD",
            {
                "folder": (
                    FOLDER_ARCHIVE
                ),
                "archived_at": (
                    archived_at
                ),
                "is_current_revision": 0,
            },
            update_modified=True,
        )

    def test_only_private_files_are_allowed(
        self,
    ):
        doc = self._doc()

        with patch(
            (
                f"{MODULE}."
                "frappe.db.get_value"
            ),
            return_value=frappe._dict(
                {
                    "name": (
                        "FILE-TEST"
                    ),
                    "is_private": 0,
                }
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                _validate_private_file(
                    doc
                )

        with patch(
            (
                f"{MODULE}."
                "frappe.db.get_value"
            ),
            return_value=frappe._dict(
                {
                    "name": (
                        "FILE-TEST"
                    ),
                    "is_private": 1,
                }
            ),
        ):
            _validate_private_file(
                doc
            )

    def test_employee_open_marks_document_seen(
        self,
    ):
        doc = self._doc()

        seen_at = datetime(
            2026,
            9,
            29,
            9,
            0,
            0,
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_action_document"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "has_management_access"
                ),
                return_value=False,
            ),
            patch(
                (
                    f"{MODULE}."
                    "now_datetime"
                ),
                return_value=seen_at,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            result = mark_seen(
                doc.name
            )

        self.assertTrue(
            result["changed"]
        )

        self.assertEqual(
            result["read_status"],
            READ_STATUS_SEEN,
        )

        set_value.assert_called_once()

    def test_manager_open_does_not_mark_document_seen(
        self,
    ):
        doc = self._doc()

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_action_document"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "has_management_access"
                ),
                return_value=True,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            result = mark_seen(
                doc.name
            )

        self.assertFalse(
            result["changed"]
        )

        set_value.assert_not_called()

    def test_manual_archive_moves_document_to_archive(
        self,
    ):
        doc = self._doc()

        archived_at = datetime(
            2026,
            9,
            29,
            9,
            30,
            0,
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_action_document"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "now_datetime"
                ),
                return_value=archived_at,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            result = (
                archive_document(
                    doc.name
                )
            )

        self.assertTrue(
            result["changed"]
        )

        self.assertEqual(
            result["folder"],
            FOLDER_ARCHIVE,
        )

        set_value.assert_called_once()

    def test_auto_archive_archives_old_inbox_documents(
        self,
    ):
        now = datetime(
            2026,
            9,
            29,
            10,
            0,
            0,
        )

        cutoff = datetime(
            2026,
            6,
            29,
            10,
            0,
            0,
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "now_datetime"
                ),
                return_value=now,
            ),
            patch(
                (
                    f"{MODULE}."
                    "add_months"
                ),
                return_value=cutoff,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_all"
                ),
                return_value=[
                    "EDOC-1",
                    "EDOC-2",
                ],
            ) as get_all,
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            count = (
                auto_archive_old_employee_documents()
            )

        self.assertEqual(
            count,
            2,
        )

        get_all.assert_called_once_with(
            "Employee Document",
            filters={
                "folder": (
                    FOLDER_INBOX
                ),
                "provided_at": (
                    "<",
                    cutoff,
                ),
            },
            pluck="name",
        )

        self.assertEqual(
            set_value.call_count,
            2,
        )

    def test_revision_chain_document_cannot_be_deleted(
        self,
    ):
        doc = self._doc(
            previous_revision=(
                "EDOC-OLD"
            )
        )

        with self.assertRaises(
            frappe.ValidationError
        ):
            _validate_delete(
                doc
            )
