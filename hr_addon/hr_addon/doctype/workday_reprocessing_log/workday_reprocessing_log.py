# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

from datetime import timedelta

import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, getdate, today


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
PERIOD_OVERRIDE_FLAG = "workday_period_override"


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


def get_reprocessing_unlocked_start(
    reference_date=None,
):
    reference_date = getdate(
        reference_date or today()
    )

    current_month_start = reference_date.replace(
        day=1
    )

    previous_month_last_day = (
        current_month_start
        - timedelta(days=1)
    )

    return previous_month_last_day.replace(
        day=1
    )


def is_workday_period_locked(
    log_date,
    reference_date=None,
):
    if not log_date:
        return False

    return (
        getdate(log_date)
        < get_reprocessing_unlocked_start(
            reference_date
        )
    )


def validate_workday_period_for_save(
    workday,
):
    if not workday.log_date:
        return

    if not is_workday_period_locked(
        workday.log_date
    ):
        return

    if workday.flags.get(
        PERIOD_OVERRIDE_FLAG
    ):
        return

    frappe.throw(
        _(
            "Workday {0} for {1} is in a locked "
            "time-account period. Only the current "
            "month and previous month may be changed "
            "normally. Use the authorized Workday "
            "reprocessing service for an older period."
        ).format(
            workday.name or _("New Workday"),
            frappe.format(
                workday.log_date,
                {"fieldtype": "Date"},
            ),
        )
    )


def _validate_reprocessing_request(
    trigger,
    reason,
    source_doctype=None,
    source_name=None,
):
    if trigger not in TRIGGERS:
        frappe.throw(
            _(
                "Invalid Workday Reprocessing trigger: {0}"
            ).format(trigger)
        )

    if trigger == TRIGGER_PERIOD_OVERRIDE:
        frappe.throw(
            _(
                "Period Override is assigned automatically "
                "by the reprocessing service."
            )
        )

    clean_reason = str(
        reason or ""
    ).strip()

    if not clean_reason:
        frappe.throw(
            _(
                "Reason is required for Workday "
                "reprocessing."
            )
        )

    has_source_doctype = bool(
        source_doctype
    )
    has_source_name = bool(
        source_name
    )

    if has_source_doctype != has_source_name:
        frappe.throw(
            _(
                "Source DocType and Source Document "
                "must either both be set or both be empty."
            )
        )

    if (
        source_doctype
        and not frappe.db.exists(
            source_doctype,
            source_name,
        )
    ):
        frappe.throw(
            _(
                "Source document {0} {1} does not exist."
            ).format(
                source_doctype,
                source_name,
            )
        )

    return clean_reason


def _get_reprocessing_user():
    user = getattr(
        frappe.session,
        "user",
        None,
    )

    if not user or user == "Guest":
        frappe.throw(
            _(
                "An authenticated user is required "
                "for Workday reprocessing."
            )
        )

    return user


def _user_can_override_period(
    user,
):
    if user == "Administrator":
        return True

    return (
        "System Manager"
        in frappe.get_roles(user)
    )


def _get_workday_for_reprocessing(
    workday_name,
):
    if not workday_name:
        frappe.throw(_("Workday is required."))

    rows = frappe.db.sql(
        """
        SELECT
            name,
            employee,
            log_date,
            daily_delta_minutes
        FROM
            `tabWorkday`
        WHERE
            name = %s
        FOR UPDATE
        """,
        (workday_name,),
        as_dict=True,
    )

    if not rows:
        frappe.throw(
            _(
                "Workday {0} does not exist."
            ).format(workday_name)
        )

    return rows[0]


def reprocess_workday(
    workday_name,
    trigger,
    reason,
    source_doctype=None,
    source_name=None,
    allow_period_override=False,
):
    clean_reason = (
        _validate_reprocessing_request(
            trigger=trigger,
            reason=reason,
            source_doctype=source_doctype,
            source_name=source_name,
        )
    )

    user = _get_reprocessing_user()

    workday_before = (
        _get_workday_for_reprocessing(
            workday_name
        )
    )

    period_locked = (
        is_workday_period_locked(
            workday_before.log_date
        )
    )

    period_override_used = False

    if period_locked:
        if not cint(
            allow_period_override
        ):
            frappe.throw(
                _(
                    "Workday {0} for {1} is in a locked "
                    "time-account period. An authorized "
                    "period override with a reason is "
                    "required."
                ).format(
                    workday_before.name,
                    frappe.format(
                        workday_before.log_date,
                        {"fieldtype": "Date"},
                    ),
                )
            )

        if not _user_can_override_period(
            user
        ):
            frappe.throw(
                _(
                    "Only Administrator or a user with "
                    "System Manager role may override "
                    "a locked time-account period."
                )
            )

        period_override_used = True

    old_delta_minutes = cint(
        workday_before.daily_delta_minutes
    )

    workday = frappe.get_doc(
        "Workday",
        workday_name,
    )

    if period_override_used:
        workday.flags[
            PERIOD_OVERRIDE_FLAG
        ] = True

    workday.save(
        ignore_permissions=True
    )

    new_delta_minutes = cint(
        workday.daily_delta_minutes
    )

    audit_trigger = trigger
    audit_reason = clean_reason

    if period_override_used:
        audit_trigger = (
            TRIGGER_PERIOD_OVERRIDE
        )
        audit_reason = (
            f"{clean_reason}\n"
            f"Underlying trigger: {trigger}"
        )

    reprocessing_log = (
        create_workday_reprocessing_log(
            workday_name=workday.name,
            trigger=audit_trigger,
            reason=audit_reason,
            old_delta_minutes=(
                old_delta_minutes
            ),
            new_delta_minutes=(
                new_delta_minutes
            ),
            source_doctype=source_doctype,
            source_name=source_name,
            triggered_by=user,
        )
    )

    return frappe._dict(
        {
            "workday": workday.name,
            "old_delta_minutes": (
                old_delta_minutes
            ),
            "new_delta_minutes": (
                new_delta_minutes
            ),
            "changed": (
                old_delta_minutes
                != new_delta_minutes
            ),
            "period_override": (
                period_override_used
            ),
            "reprocessing_log": (
                reprocessing_log.name
            ),
        }
    )
