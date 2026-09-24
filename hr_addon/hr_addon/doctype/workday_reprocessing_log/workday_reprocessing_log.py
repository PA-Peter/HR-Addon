# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate


TRIGGER_CHECKIN_CORRECTION = "Checkin Correction"
TRIGGER_WEEKLY_WORKING_HOURS = "Weekly Working Hours"
TRIGGER_LEAVE_APPLICATION = "Leave Application"
TRIGGER_ATTENDANCE_REQUEST = "Attendance Request"
TRIGGER_MANUAL_RECALCULATE = "Manual Recalculate"
TRIGGER_SYSTEM_RECALCULATE = "System Recalculate"
TRIGGER_PERIOD_OVERRIDE = "Period Override"


TRIGGERS = (
    TRIGGER_CHECKIN_CORRECTION,
    TRIGGER_WEEKLY_WORKING_HOURS,
    TRIGGER_LEAVE_APPLICATION,
    TRIGGER_ATTENDANCE_REQUEST,
    TRIGGER_MANUAL_RECALCULATE,
    TRIGGER_SYSTEM_RECALCULATE,
    TRIGGER_PERIOD_OVERRIDE,
)


SERVICE_INSERT_FLAG = "workday_reprocessing_service"


class WorkdayReprocessingLog(Document):
    def validate(self):
        self._validate_immutable()
        self._validate_service_origin()
        self._validate_trigger()
        self._validate_reason()
        self._validate_source_reference()
        self._validate_workday_reference()

        self.old_delta_minutes = cint(
            self.old_delta_minutes
        )
        self.new_delta_minutes = cint(
            self.new_delta_minutes
        )

    def _validate_immutable(self):
        if not self.is_new():
            frappe.throw(
                _(
                    "Workday Reprocessing Log {0} is immutable."
                ).format(self.name)
            )

    def _validate_service_origin(self):
        if not self.flags.get(SERVICE_INSERT_FLAG):
            frappe.throw(
                _(
                    "Workday Reprocessing Logs may only be "
                    "created by the reprocessing service."
                )
            )

    def _validate_trigger(self):
        if self.trigger not in TRIGGERS:
            frappe.throw(
                _(
                    "Invalid Workday Reprocessing trigger: {0}"
                ).format(self.trigger)
            )

    def _validate_reason(self):
        reason = str(self.reason or "").strip()

        if not reason:
            frappe.throw(
                _(
                    "Reason is required for a "
                    "Workday Reprocessing Log."
                )
            )

        self.reason = reason

    def _validate_source_reference(self):
        has_source_doctype = bool(
            self.source_doctype
        )
        has_source_name = bool(
            self.source_name
        )

        if has_source_doctype != has_source_name:
            frappe.throw(
                _(
                    "Source DocType and Source Document "
                    "must either both be set or both be empty."
                )
            )

        if (
            self.source_doctype
            and not frappe.db.exists(
                self.source_doctype,
                self.source_name,
            )
        ):
            frappe.throw(
                _(
                    "Source document {0} {1} does not exist."
                ).format(
                    self.source_doctype,
                    self.source_name,
                )
            )

    def _validate_workday_reference(self):
        workday = frappe.db.get_value(
            "Workday",
            self.workday,
            [
                "employee",
                "log_date",
            ],
            as_dict=True,
        )

        if not workday:
            frappe.throw(
                _(
                    "Workday {0} does not exist."
                ).format(self.workday)
            )

        if self.employee != workday.employee:
            frappe.throw(
                _(
                    "Reprocessing Log employee does not "
                    "match the Workday employee."
                )
            )

        if (
            getdate(self.log_date)
            != getdate(workday.log_date)
        ):
            frappe.throw(
                _(
                    "Reprocessing Log date must match "
                    "the Workday date."
                )
            )

    def on_trash(self):
        frappe.throw(
            _(
                "Workday Reprocessing Logs cannot be deleted."
            )
        )


def create_workday_reprocessing_log(
    workday_name,
    trigger,
    reason,
    old_delta_minutes,
    new_delta_minutes,
    source_doctype=None,
    source_name=None,
    triggered_by=None,
):
    if not workday_name:
        frappe.throw(_("Workday is required."))

    if old_delta_minutes is None:
        frappe.throw(
            _("Old Delta Minutes is required.")
        )

    if new_delta_minutes is None:
        frappe.throw(
            _("New Delta Minutes is required.")
        )

    workday = frappe.db.get_value(
        "Workday",
        workday_name,
        [
            "employee",
            "log_date",
        ],
        as_dict=True,
    )

    if not workday:
        frappe.throw(
            _(
                "Workday {0} does not exist."
            ).format(workday_name)
        )

    user = (
        triggered_by
        or getattr(frappe.session, "user", None)
        or "Administrator"
    )

    if user == "Guest":
        user = "Administrator"

    log = frappe.get_doc(
        {
            "doctype": "Workday Reprocessing Log",
            "employee": workday.employee,
            "workday": workday_name,
            "log_date": workday.log_date,
            "trigger": trigger,
            "old_delta_minutes": cint(
                old_delta_minutes
            ),
            "new_delta_minutes": cint(
                new_delta_minutes
            ),
            "source_doctype": source_doctype,
            "source_name": source_name,
            "reason": reason,
            "triggered_by": user,
        }
    )

    log.flags[SERVICE_INSERT_FLAG] = True

    return log.insert(
        ignore_permissions=True
    )
