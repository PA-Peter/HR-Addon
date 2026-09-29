# Copyright (c) 2026, RieckMedia and contributors
# See license.txt

import inspect
from datetime import datetime
from unittest.mock import patch

import frappe

from frappe.tests import IntegrationTestCase

from hr_addon.hr_addon.doctype.employee_document.employee_document_mail import (
    _get_document_for_mail,
    _get_personal_email,
    _get_private_attachment,
    send_to_personal_email,
)


MODULE = (
    "hr_addon.hr_addon.doctype."
    "employee_document.employee_document_mail"
)


class FakeEmailQueue:
    def __init__(
        self,
        name="EMAILQ-TEST",
    ):
        self.name = name
        self.send_called = False

    def send(self):
        self.send_called = True


class TestEmployeeDocumentMail(
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
            "name": (
                "EDOC-2026-00001"
            ),
            "employee": (
                "HR-EMP-00001"
            ),
            "employee_name": (
                "Christian Gold"
            ),
            "document_title": (
                "Test Document"
            ),
            "document_file": (
                "/private/files/"
                "test-document.pdf"
            ),
        }

        values.update(
            overrides
        )

        return frappe._dict(
            values
        )

    def test_api_has_no_recipient_parameter(
        self,
    ):
        parameters = (
            inspect.signature(
                send_to_personal_email
            ).parameters
        )

        self.assertEqual(
            list(
                parameters.keys()
            ),
            [
                "name"
            ],
        )

    def test_permission_failure_stops_mail(
        self,
    ):
        doc = self._doc()

        with (
            patch(
                (
                    f"{MODULE}."
                    "frappe.get_doc"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "assert_document_action_access"
                ),
                side_effect=(
                    frappe.PermissionError(
                        "Not permitted"
                    )
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.sendmail"
                ),
            ) as sendmail,
        ):
            with self.assertRaises(
                frappe.PermissionError
            ):
                _get_document_for_mail(
                    doc.name
                )

        sendmail.assert_not_called()

    def test_personal_email_is_taken_from_employee(
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
                    "employee_name": (
                        "Christian Gold"
                    ),
                    "personal_email": (
                        "christian@example.com"
                    ),
                }
            ),
        ):
            recipient = (
                _get_personal_email(
                    doc
                )
            )

        self.assertEqual(
            recipient,
            "christian@example.com",
        )

    def test_missing_personal_email_is_rejected(
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
                    "employee_name": (
                        "Christian Gold"
                    ),
                    "personal_email": None,
                }
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                _get_personal_email(
                    doc
                )

    def test_multiple_personal_emails_are_rejected(
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
                    "employee_name": (
                        "Christian Gold"
                    ),
                    "personal_email": (
                        "one@example.com,"
                        "two@example.com"
                    ),
                }
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                _get_personal_email(
                    doc
                )

    def test_private_attachment_uses_document_file_url(
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
                    "name": "FILE-TEST",
                    "file_name": (
                        "test-document.pdf"
                    ),
                    "is_private": 1,
                }
            ),
        ):
            attachment = (
                _get_private_attachment(
                    doc
                )
            )

        self.assertEqual(
            attachment,
            {
                "file_url": (
                    "/private/files/"
                    "test-document.pdf"
                )
            },
        )

    def test_public_file_is_rejected(
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
                    "name": "FILE-TEST",
                    "file_name": (
                        "test-document.pdf"
                    ),
                    "is_private": 0,
                }
            ),
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                _get_private_attachment(
                    doc
                )

    def test_successful_send_uses_only_personal_email(
        self,
    ):
        doc = self._doc()

        queue = FakeEmailQueue()

        emailed_at = datetime(
            2026,
            9,
            29,
            10,
            30,
            0,
        )

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_document_for_mail"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_personal_email"
                ),
                return_value=(
                    "christian@example.com"
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_private_attachment"
                ),
                return_value={
                    "file_url": (
                        "/private/files/"
                        "test-document.pdf"
                    )
                },
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.sendmail"
                ),
                return_value=queue,
            ) as sendmail,
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.get_value"
                ),
                return_value="Sent",
            ),
            patch(
                (
                    f"{MODULE}."
                    "now_datetime"
                ),
                return_value=(
                    emailed_at
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            result = (
                send_to_personal_email(
                    doc.name
                )
            )

        self.assertTrue(
            queue.send_called
        )

        self.assertTrue(
            result["sent"]
        )

        self.assertEqual(
            result["last_emailed_at"],
            emailed_at,
        )

        sendmail.assert_called_once()

        kwargs = (
            sendmail.call_args.kwargs
        )

        self.assertEqual(
            kwargs["recipients"],
            [
                "christian@example.com"
            ],
        )

        self.assertEqual(
            kwargs["attachments"],
            [
                {
                    "file_url": (
                        "/private/files/"
                        "test-document.pdf"
                    )
                }
            ],
        )

        self.assertEqual(
            kwargs["reference_doctype"],
            "Employee Document",
        )

        self.assertEqual(
            kwargs["reference_name"],
            doc.name,
        )

        self.assertEqual(
            kwargs["add_unsubscribe_link"],
            0,
        )

        self.assertTrue(
            kwargs["delayed"]
        )

        self.assertTrue(
            kwargs[
                "redact_message_after_send"
            ]
        )

        set_value.assert_called_once_with(
            "Employee Document",
            doc.name,
            {
                "last_emailed_at": (
                    emailed_at
                ),
            },
            update_modified=True,
        )

    def test_failed_queue_does_not_update_last_emailed_at(
        self,
    ):
        doc = self._doc()

        queue = FakeEmailQueue()

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_document_for_mail"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_personal_email"
                ),
                return_value=(
                    "christian@example.com"
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_private_attachment"
                ),
                return_value={
                    "file_url": (
                        "/private/files/"
                        "test-document.pdf"
                    )
                },
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.sendmail"
                ),
                return_value=queue,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.get_value"
                ),
                return_value="Error",
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                send_to_personal_email(
                    doc.name
                )

        self.assertTrue(
            queue.send_called
        )

        set_value.assert_not_called()

    def test_missing_email_queue_is_rejected(
        self,
    ):
        doc = self._doc()

        with (
            patch(
                (
                    f"{MODULE}."
                    "_get_document_for_mail"
                ),
                return_value=doc,
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_personal_email"
                ),
                return_value=(
                    "christian@example.com"
                ),
            ),
            patch(
                (
                    f"{MODULE}."
                    "_get_private_attachment"
                ),
                return_value={
                    "file_url": (
                        "/private/files/"
                        "test-document.pdf"
                    )
                },
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.sendmail"
                ),
                return_value=None,
            ),
            patch(
                (
                    f"{MODULE}."
                    "frappe.db.set_value"
                ),
            ) as set_value,
        ):
            with self.assertRaises(
                frappe.ValidationError
            ):
                send_to_personal_email(
                    doc.name
                )

        set_value.assert_not_called()
