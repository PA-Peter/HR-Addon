# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import add_months, cint, getdate, now_datetime

from hr_addon.hr_addon.doctype.employee_document.employee_document_permissions import (
    assert_document_action_access,
    has_management_access,
)


FOLDER_INBOX = "Inbox"
FOLDER_ARCHIVE = "Archive"

READ_STATUS_NEW = "New"
READ_STATUS_SEEN = "Seen"


class EmployeeDocument(Document):
    def validate(self):
        if self.is_new():
            _set_new_document_defaults(self)
            _prepare_revision(self)
        else:
            _validate_revision_control_fields(self)

        _validate_period(self)
        _validate_private_file(self)

    def after_insert(self):
        _archive_previous_revision(self)

    def on_trash(self):
        _validate_delete(self)


def _set_new_document_defaults(doc):
    doc.read_status = READ_STATUS_NEW
    doc.folder = FOLDER_INBOX
    doc.provided_at = now_datetime()
    doc.seen_at = None
    doc.archived_at = None
    doc.is_current_revision = 1

    if not doc.previous_revision:
        doc.revision = 1


def _prepare_revision(doc):
    if not doc.previous_revision:
        doc.revision = 1
        return

    previous = frappe.db.get_value(
        "Employee Document",
        doc.previous_revision,
        [
            "name",
            "employee",
            "document_type",
            "source",
            "period_from",
            "period_to",
            "revision",
            "is_current_revision",
        ],
        as_dict=True,
    )

    if not previous:
        frappe.throw(
            _(
                "Previous Employee Document {0} does not exist."
            ).format(
                doc.previous_revision
            )
        )

    if not cint(
        previous.is_current_revision
    ):
        frappe.throw(
            _(
                "A new revision may only reference "
                "the current revision of an "
                "Employee Document."
            )
        )

    family_fields = (
        (
            "employee",
            _("Employee"),
        ),
        (
            "document_type",
            _("Document Type"),
        ),
        (
            "source",
            _("Source"),
        ),
    )

    for fieldname, label in family_fields:
        if (
            doc.get(fieldname)
            != previous.get(fieldname)
        ):
            frappe.throw(
                _(
                    "{0} must match the "
                    "previous revision."
                ).format(
                    label
                )
            )

    previous_period_from = (
        getdate(
            previous.period_from
        )
        if previous.period_from
        else None
    )

    previous_period_to = (
        getdate(
            previous.period_to
        )
        if previous.period_to
        else None
    )

    current_period_from = (
        getdate(
            doc.period_from
        )
        if doc.period_from
        else None
    )

    current_period_to = (
        getdate(
            doc.period_to
        )
        if doc.period_to
        else None
    )

    if (
        current_period_from
        != previous_period_from
        or current_period_to
        != previous_period_to
    ):
        frappe.throw(
            _(
                "Period From and Period To "
                "must match the previous revision."
            )
        )

    doc.revision = (
        max(
            cint(
                previous.revision
            ),
            1,
        )
        + 1
    )


def _validate_revision_control_fields(
    doc,
):
    previous = (
        doc.get_doc_before_save()
    )

    if not previous:
        return

    protected_fields = (
        "previous_revision",
        "revision",
        "is_current_revision",
        "provided_at",
    )

    for fieldname in protected_fields:
        if (
            doc.get(fieldname)
            != previous.get(fieldname)
        ):
            frappe.throw(
                _(
                    "Field {0} is maintained by "
                    "the Employee Document service "
                    "and cannot be changed directly."
                ).format(
                    fieldname
                )
            )


def _validate_period(doc):
    has_from = bool(
        doc.period_from
    )

    has_to = bool(
        doc.period_to
    )

    if has_from != has_to:
        frappe.throw(
            _(
                "Period From and Period To must "
                "either both be set or both be empty."
            )
        )

    if (
        has_from
        and getdate(
            doc.period_from
        )
        > getdate(
            doc.period_to
        )
    ):
        frappe.throw(
            _(
                "Period From cannot be "
                "after Period To."
            )
        )


def _validate_private_file(doc):
    if not doc.document_file:
        return

    file_row = frappe.db.get_value(
        "File",
        {
            "file_url": (
                doc.document_file
            ),
        },
        [
            "name",
            "is_private",
        ],
        as_dict=True,
    )

    if not file_row:
        frappe.throw(
            _(
                "Document File must reference "
                "a file stored in Frappe."
            )
        )

    if not cint(
        file_row.is_private
    ):
        frappe.throw(
            _(
                "Employee Documents may only "
                "use private files."
            )
        )


def _archive_previous_revision(doc):
    if not doc.previous_revision:
        return

    archived_at = (
        now_datetime()
    )

    frappe.db.set_value(
        "Employee Document",
        doc.previous_revision,
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


def _validate_delete(doc):
    next_revision = (
        frappe.db.get_value(
            "Employee Document",
            {
                "previous_revision": (
                    doc.name
                ),
            },
            "name",
        )
    )

    if (
        doc.previous_revision
        or next_revision
    ):
        frappe.throw(
            _(
                "Employee Documents that are "
                "part of a revision chain cannot "
                "be deleted. Archive them instead."
            )
        )


def _get_action_document(name):
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


@frappe.whitelist()
def mark_seen(name):
    doc = _get_action_document(
        name
    )

    if has_management_access():
        return {
            "changed": False,
            "read_status": (
                doc.read_status
            ),
            "seen_at": (
                doc.seen_at
            ),
        }

    if (
        doc.read_status
        == READ_STATUS_SEEN
    ):
        return {
            "changed": False,
            "read_status": (
                doc.read_status
            ),
            "seen_at": (
                doc.seen_at
            ),
        }

    seen_at = (
        now_datetime()
    )

    frappe.db.set_value(
        "Employee Document",
        doc.name,
        {
            "read_status": (
                READ_STATUS_SEEN
            ),
            "seen_at": (
                seen_at
            ),
        },
        update_modified=True,
    )

    return {
        "changed": True,
        "read_status": (
            READ_STATUS_SEEN
        ),
        "seen_at": (
            seen_at
        ),
    }


@frappe.whitelist()
def archive_document(name):
    doc = _get_action_document(
        name
    )

    if (
        doc.folder
        == FOLDER_ARCHIVE
    ):
        return {
            "changed": False,
            "folder": (
                doc.folder
            ),
            "archived_at": (
                doc.archived_at
            ),
        }

    archived_at = (
        now_datetime()
    )

    frappe.db.set_value(
        "Employee Document",
        doc.name,
        {
            "folder": (
                FOLDER_ARCHIVE
            ),
            "archived_at": (
                archived_at
            ),
        },
        update_modified=True,
    )

    return {
        "changed": True,
        "folder": (
            FOLDER_ARCHIVE
        ),
        "archived_at": (
            archived_at
        ),
    }


def auto_archive_old_employee_documents():
    cutoff = add_months(
        now_datetime(),
        -3,
    )

    archived_at = (
        now_datetime()
    )

    document_names = (
        frappe.get_all(
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
    )

    for name in document_names:
        frappe.db.set_value(
            "Employee Document",
            name,
            {
                "folder": (
                    FOLDER_ARCHIVE
                ),
                "archived_at": (
                    archived_at
                ),
            },
            update_modified=True,
        )

    return len(
        document_names
    )
