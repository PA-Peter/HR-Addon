# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe.utils import getdate

from hr_addon.hr_addon.doctype.workday_reprocessing_log.workday_reprocessing_log import (
    TRIGGER_LEAVE_APPLICATION,
    reprocess_workday,
)


SUPPRESS_SIDE_EFFECTS_FLAG = (
    "hr_addon_suppress_leave_side_effects"
)


def _side_effects_suppressed(doc):
    return bool(
        doc.flags.get(
            SUPPRESS_SIDE_EFFECTS_FLAG
        )
    )


def _date_label(value):
    return getdate(value).strftime(
        "%d.%m.%Y"
    )


def _period_label(doc):
    from_date = _date_label(
        doc.from_date
    )

    to_date = _date_label(
        doc.to_date
    )

    if from_date == to_date:
        return from_date

    return (
        f"{from_date} – {to_date}"
    )


def _current_user():
    user = getattr(
        frappe.session,
        "user",
        None,
    )

    if not user or user == "Guest":
        return "Administrator"

    return user


def _employee_user(doc):
    return frappe.db.get_value(
        "Employee",
        doc.employee,
        "user_id",
    )


def _notification_exists(
    for_user,
    document_name,
    title,
):
    return bool(
        frappe.db.exists(
            "Notification Log",
            {
                "for_user": for_user,
                "type": "Alert",
                "document_type": (
                    "Leave Application"
                ),
                "document_name": (
                    document_name
                ),
                "title": title,
            },
        )
    )


def _create_alert(
    *,
    for_user,
    doc,
    title,
    description,
    suppress_self=False,
):
    if not for_user:
        return None

    actor = _current_user()

    if (
        suppress_self
        and for_user == actor
    ):
        return None

    if _notification_exists(
        for_user,
        doc.name,
        title,
    ):
        return None

    notification = frappe.get_doc(
        {
            "doctype": (
                "Notification Log"
            ),
            "type": "Alert",
            "title": title,
            "description": description,
            "document_type": (
                "Leave Application"
            ),
            "document_name": doc.name,
            "for_user": for_user,
            "from_user": actor,
            "read": 0,
        }
    )

    return notification.insert(
        ignore_permissions=True
    )


def notify_leave_approver(doc):
    if doc.status != "Open":
        return None

    approver = doc.leave_approver

    if not approver:
        return None

    title = (
        "Neuer Abwesenheitsantrag: "
        f"{doc.employee_name}"
    )

    description = (
        f"<b>{doc.leave_type}</b><br>"
        f"{_period_label(doc)}"
    )

    return _create_alert(
        for_user=approver,
        doc=doc,
        title=title,
        description=description,
        suppress_self=True,
    )


def notify_employee_status(doc):
    status_titles = {
        "Approved": (
            "Abwesenheitsantrag genehmigt"
        ),
        "Rejected": (
            "Abwesenheitsantrag abgelehnt"
        ),
        "Cancelled": (
            "Abwesenheitsantrag storniert"
        ),
    }

    title = status_titles.get(
        doc.status
    )

    if not title:
        return None

    employee_user = _employee_user(
        doc
    )

    if not employee_user:
        return None

    description = (
        f"<b>{doc.leave_type}</b><br>"
        f"{_period_label(doc)}"
    )

    return _create_alert(
        for_user=employee_user,
        doc=doc,
        title=title,
        description=description,
    )


def reprocess_leave_workdays(
    doc,
    action,
):
    workdays = frappe.get_all(
        "Workday",
        filters={
            "employee": doc.employee,
            "log_date": [
                "between",
                [
                    doc.from_date,
                    doc.to_date,
                ],
            ],
        },
        fields=[
            "name",
            "log_date",
        ],
        order_by="log_date asc",
    )

    results = []

    for workday in workdays:
        result = reprocess_workday(
            workday_name=workday.name,
            trigger=(
                TRIGGER_LEAVE_APPLICATION
            ),
            reason=(
                f"Leave Application "
                f"{doc.name} {action}."
            ),
            source_doctype=(
                "Leave Application"
            ),
            source_name=doc.name,
        )

        results.append(
            result
        )

    return results


def handle_leave_after_insert(
    doc,
    method=None,
):
    if _side_effects_suppressed(
        doc
    ):
        return

    notify_leave_approver(
        doc
    )


def handle_leave_submit(
    doc,
    method=None,
):
    if _side_effects_suppressed(
        doc
    ):
        return

    reprocess_leave_workdays(
        doc,
        action="submitted",
    )

    notify_employee_status(
        doc
    )


def handle_leave_cancel(
    doc,
    method=None,
):
    from hr_addon.hr_addon.doctype.hr_addon_settings.hr_addon_settings import (
        export_calendar,
    )

    if not _side_effects_suppressed(
        doc
    ):
        reprocess_leave_workdays(
            doc,
            action="cancelled",
        )

        notify_employee_status(
            doc
        )

    # Preserve the previous HR-Addon calendar hook.
    export_calendar(
        doc,
        method,
    )
