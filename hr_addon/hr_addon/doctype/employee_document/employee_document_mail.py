# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe import _
from frappe.utils import (
    cint,
    now_datetime,
    split_emails,
    validate_email_address,
)

from hr_addon.hr_addon.doctype.employee_document.employee_document_permissions import (
    assert_document_action_access,
)


def _get_document_for_mail(name):
    if not name:
        frappe.throw(
            _(
                "Employee Document is required."
            )
        )

    doc = frappe.get_doc(
        "Employee Document",
        name,
    )

    assert_document_action_access(
        doc
    )

    return doc


def _get_personal_email(doc):
    employee = frappe.db.get_value(
        "Employee",
        doc.employee,
        [
            "employee_name",
            "personal_email",
        ],
        as_dict=True,
    )

    if not employee:
        frappe.throw(
            _(
                "Employee {0} does not exist."
            ).format(
                doc.employee
            )
        )

    personal_email = (
        employee.personal_email
        or ""
    ).strip()

    if not personal_email:
        frappe.throw(
            _(
                "No personal email address is "
                "stored for employee {0}."
            ).format(
                employee.employee_name
                or doc.employee
            )
        )

    validated_email = (
        validate_email_address(
            personal_email,
            throw=True,
        )
    )

    recipients = split_emails(
        validated_email
    )

    if len(recipients) != 1:
        frappe.throw(
            _(
                "Exactly one personal email "
                "address must be stored for "
                "the employee."
            )
        )

    return recipients[0]


def _get_private_attachment(doc):
    if not doc.document_file:
        frappe.throw(
            _(
                "The Employee Document has "
                "no file attached."
            )
        )

    file_row = frappe.db.get_value(
        "File",
        {
            "file_url": (
                doc.document_file
            ),
        },
        [
            "name",
            "file_name",
            "is_private",
        ],
        as_dict=True,
    )

    if not file_row:
        frappe.throw(
            _(
                "The attached file could "
                "not be found."
            )
        )

    if not cint(
        file_row.is_private
    ):
        frappe.throw(
            _(
                "Employee Documents may only "
                "be sent from private files."
            )
        )

    return {
        "file_url": (
            doc.document_file
        ),
    }


def _get_email_subject():
    return _(
        "Your personal document"
    )


def _get_email_message():
    return _(
        "Attached is the personal document "
        "you requested from the employee "
        "self-service. This email was sent "
        "exclusively to the personal email "
        "address stored in your employee record."
    )


@frappe.whitelist()
def send_to_personal_email(name):
    """
    Send one Employee Document to the personal email address
    stored in the Employee record.

    The caller can never supply a recipient address.
    Access to the Employee Document is checked server-side.
    """

    doc = _get_document_for_mail(
        name
    )

    recipient = _get_personal_email(
        doc
    )

    attachment = (
        _get_private_attachment(
            doc
        )
    )

    email_queue = frappe.sendmail(
        recipients=[
            recipient
        ],
        subject=(
            _get_email_subject()
        ),
        message=(
            _get_email_message()
        ),
        attachments=[
            attachment
        ],
        reference_doctype=(
            "Employee Document"
        ),
        reference_name=doc.name,
        add_unsubscribe_link=0,
        delayed=True,
        redact_message_after_send=True,
    )

    if (
        not email_queue
        or not getattr(
            email_queue,
            "name",
            None,
        )
    ):
        frappe.throw(
            _(
                "The email could not be "
                "prepared for sending."
            )
        )

    # Deliberately send synchronously.
    #
    # last_emailed_at must only be updated after
    # Frappe reports the Email Queue as Sent.
    email_queue.send()

    queue_status = (
        frappe.db.get_value(
            "Email Queue",
            email_queue.name,
            "status",
        )
    )

    if queue_status != "Sent":
        frappe.throw(
            _(
                "The email could not be sent. "
                "Email Queue status: {0}"
            ).format(
                queue_status
                or _("Unknown")
            )
        )

    emailed_at = (
        now_datetime()
    )

    frappe.db.set_value(
        "Employee Document",
        doc.name,
        {
            "last_emailed_at": (
                emailed_at
            ),
        },
        update_modified=True,
    )

    return {
        "sent": True,
        "last_emailed_at": (
            emailed_at
        ),
    }
