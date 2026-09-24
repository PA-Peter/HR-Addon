# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, get_datetime, getdate, now_datetime

from hr_addon.hr_addon.doctype.workday_reprocessing_log.workday_reprocessing_log import (
    TRIGGER_CHECKIN_CORRECTION,
    reprocess_workday,
)


CORRECTION_MISSING_BOOKING = "Missing Booking"
CORRECTION_WRONG_LOG_TYPE = "Wrong IN/OUT Type"
CORRECTION_EXTRA_BOOKING = "Accidental Extra Booking"

CORRECTION_TYPES = (
    CORRECTION_MISSING_BOOKING,
    CORRECTION_WRONG_LOG_TYPE,
    CORRECTION_EXTRA_BOOKING,
)

STATUS_DRAFT = "Draft"
STATUS_PENDING = "Pending Approval"
STATUS_APPLIED = "Applied"
STATUS_REJECTED = "Rejected"

STATUSES = (
    STATUS_DRAFT,
    STATUS_PENDING,
    STATUS_APPLIED,
    STATUS_REJECTED,
)

SERVICE_TRANSITION_FLAG = "checkin_correction_service"


class CheckinCorrectionRequest(Document):
    def validate(self):
        if not self.status:
            self.status = STATUS_DRAFT

        self._validate_status()
        self._validate_service_transition()
        self._validate_locked_request()
        self._validate_reason()
        self._validate_correction()

    def _validate_status(self):
        if self.status not in STATUSES:
            frappe.throw(
                _("Invalid correction request status: {0}").format(
                    self.status
                )
            )

    def _validate_service_transition(self):
        if self.is_new():
            if (
                self.status != STATUS_DRAFT
                and not self.flags.get(
                    SERVICE_TRANSITION_FLAG
                )
            ):
                frappe.throw(
                    _(
                        "New Checkin Correction Requests "
                        "must start in Draft status."
                    )
                )

            return

        previous = self.get_doc_before_save()

        if not previous:
            return

        if (
            self.status != previous.status
            and not self.flags.get(
                SERVICE_TRANSITION_FLAG
            )
        ):
            frappe.throw(
                _(
                    "Checkin Correction Request status "
                    "may only be changed by the "
                    "correction service."
                )
            )

    def _validate_locked_request(self):
        if self.is_new():
            return

        previous = self.get_doc_before_save()

        if not previous:
            return

        if (
            previous.status != STATUS_DRAFT
            and not self.flags.get(
                SERVICE_TRANSITION_FLAG
            )
        ):
            frappe.throw(
                _(
                    "Checkin Correction Request {0} "
                    "is locked after submission."
                ).format(self.name)
            )

    def _validate_reason(self):
        reason = str(
            self.reason or ""
        ).strip()

        if not reason:
            frappe.throw(
                _(
                    "Reason is required for a "
                    "Checkin Correction Request."
                )
            )

        self.reason = reason

    def _validate_correction(self):
        if self.correction_type not in CORRECTION_TYPES:
            frappe.throw(
                _("Invalid correction type: {0}").format(
                    self.correction_type
                )
            )

        if self.correction_type == CORRECTION_MISSING_BOOKING:
            self._validate_missing_booking()
            return

        self._validate_existing_checkin_request()

    def _validate_missing_booking(self):
        if self.existing_checkin:
            frappe.throw(
                _(
                    "Missing Booking must not reference "
                    "an existing Employee Checkin."
                )
            )

        if not self.requested_time:
            frappe.throw(
                _(
                    "Requested Time is required for "
                    "a missing booking."
                )
            )

        if self.requested_log_type not in ("IN", "OUT"):
            frappe.throw(
                _(
                    "Requested Log Type must be "
                    "IN or OUT."
                )
            )

        if (
            getdate(self.requested_time)
            != getdate(self.correction_date)
        ):
            frappe.throw(
                _(
                    "Requested Time must be on the "
                    "Correction Date."
                )
            )

        self.current_log_type = None
        self.current_time = None
        self.current_skip_auto_attendance = 0

    def _get_existing_checkin(self):
        if not self.existing_checkin:
            frappe.throw(
                _(
                    "Existing Employee Checkin is "
                    "required for this correction type."
                )
            )

        values = frappe.db.get_value(
            "Employee Checkin",
            self.existing_checkin,
            [
                "employee",
                "time",
                "log_type",
                "skip_auto_attendance",
            ],
            as_dict=True,
        )

        if not values:
            frappe.throw(
                _(
                    "Employee Checkin {0} does not exist."
                ).format(self.existing_checkin)
            )

        return values

    def _validate_existing_checkin_request(self):
        checkin = self._get_existing_checkin()

        if checkin.employee != self.employee:
            frappe.throw(
                _(
                    "Employee Checkin does not belong "
                    "to the selected Employee."
                )
            )

        if (
            getdate(checkin.time)
            != getdate(self.correction_date)
        ):
            frappe.throw(
                _(
                    "Employee Checkin must be on the "
                    "Correction Date."
                )
            )

        if self.status == STATUS_DRAFT:
            self.current_log_type = (
                checkin.log_type or ""
            )
            self.current_time = checkin.time
            self.current_skip_auto_attendance = cint(
                checkin.skip_auto_attendance
            )

        if (
            self.correction_type
            == CORRECTION_WRONG_LOG_TYPE
        ):
            if self.requested_log_type not in (
                "IN",
                "OUT",
            ):
                frappe.throw(
                    _(
                        "Requested Log Type must be "
                        "IN or OUT."
                    )
                )

            if (
                self.requested_log_type
                == self.current_log_type
            ):
                frappe.throw(
                    _(
                        "Requested Log Type must differ "
                        "from the existing Log Type."
                    )
                )

            self.requested_time = None

        elif (
            self.correction_type
            == CORRECTION_EXTRA_BOOKING
        ):
            if cint(
                self.current_skip_auto_attendance
            ):
                frappe.throw(
                    _(
                        "Employee Checkin is already "
                        "excluded from time evaluation."
                    )
                )

            self.requested_log_type = None
            self.requested_time = None

    def on_trash(self):
        if self.status != STATUS_DRAFT:
            frappe.throw(
                _(
                    "Submitted Checkin Correction "
                    "Requests cannot be deleted."
                )
            )


def _get_current_user():
    user = getattr(
        frappe.session,
        "user",
        None,
    )

    if not user or user == "Guest":
        frappe.throw(
            _(
                "An authenticated user is required."
            )
        )

    return user


def _user_is_approver(user):
    if user == "Administrator":
        return True

    return (
        "System Manager"
        in frappe.get_roles(user)
    )


def _require_approver():
    user = _get_current_user()

    if not _user_is_approver(user):
        frappe.throw(
            _(
                "Only Administrator or a user with "
                "System Manager role may approve or "
                "reject Checkin Correction Requests."
            )
        )

    return user


def _lock_request(request_name):
    if not request_name:
        frappe.throw(
            _("Checkin Correction Request is required.")
        )

    rows = frappe.db.sql(
        """
        SELECT
            name,
            status
        FROM
            `tabCheckin Correction Request`
        WHERE
            name = %s
        FOR UPDATE
        """,
        (request_name,),
        as_dict=True,
    )

    if not rows:
        frappe.throw(
            _(
                "Checkin Correction Request {0} "
                "does not exist."
            ).format(request_name)
        )

    return rows[0]


def _get_request(request_name):
    return frappe.get_doc(
        "Checkin Correction Request",
        request_name,
    )


def _save_service_transition(request):
    request.flags[
        SERVICE_TRANSITION_FLAG
    ] = True

    return request.save(
        ignore_permissions=True
    )


def _validate_source_unchanged(request):
    if (
        request.correction_type
        == CORRECTION_MISSING_BOOKING
    ):
        return

    checkin = frappe.db.get_value(
        "Employee Checkin",
        request.existing_checkin,
        [
            "employee",
            "time",
            "log_type",
            "skip_auto_attendance",
        ],
        as_dict=True,
    )

    if not checkin:
        frappe.throw(
            _(
                "Employee Checkin {0} no longer exists."
            ).format(request.existing_checkin)
        )

    unchanged = (
        checkin.employee == request.employee
        and get_datetime(checkin.time)
        == get_datetime(request.current_time)
        and (checkin.log_type or "")
        == (request.current_log_type or "")
        and cint(checkin.skip_auto_attendance)
        == cint(
            request.current_skip_auto_attendance
        )
    )

    if not unchanged:
        frappe.throw(
            _(
                "Employee Checkin {0} changed after "
                "the correction request was submitted. "
                "The request must be reviewed again."
            ).format(request.existing_checkin)
        )


def _get_affected_workday(request):
    workday_name = frappe.db.exists(
        "Workday",
        {
            "employee": request.employee,
            "log_date": request.correction_date,
        },
    )

    if not workday_name:
        frappe.throw(
            _(
                "No Workday exists for Employee {0} "
                "on {1}. Create/evaluate the Workday "
                "before applying this correction."
            ).format(
                request.employee,
                frappe.format(
                    request.correction_date,
                    {"fieldtype": "Date"},
                ),
            )
        )

    return workday_name


def _apply_source_correction(request):
    if (
        request.correction_type
        == CORRECTION_MISSING_BOOKING
    ):
        checkin = frappe.get_doc(
            {
                "doctype": "Employee Checkin",
                "employee": request.employee,
                "time": request.requested_time,
                "log_type": request.requested_log_type,
                "device_id": "Correction Request",
            }
        )

        checkin.insert(
            ignore_permissions=True
        )

        return checkin

    checkin = frappe.get_doc(
        "Employee Checkin",
        request.existing_checkin,
    )

    if (
        request.correction_type
        == CORRECTION_WRONG_LOG_TYPE
    ):
        checkin.log_type = (
            request.requested_log_type
        )

    elif (
        request.correction_type
        == CORRECTION_EXTRA_BOOKING
    ):
        checkin.skip_auto_attendance = 1

    checkin.save(
        ignore_permissions=True
    )

    return checkin


@frappe.whitelist()
def submit_correction_request(
    request_name,
):
    _lock_request(request_name)

    request = _get_request(
        request_name
    )

    if request.status != STATUS_DRAFT:
        frappe.throw(
            _(
                "Only Draft Checkin Correction "
                "Requests can be submitted."
            )
        )

    request.status = STATUS_PENDING

    _save_service_transition(
        request
    )

    return frappe._dict(
        {
            "request": request.name,
            "status": request.status,
        }
    )


@frappe.whitelist()
def reject_correction_request(
    request_name,
    rejection_reason,
):
    user = _require_approver()

    locked = _lock_request(
        request_name
    )

    if locked.status != STATUS_PENDING:
        frappe.throw(
            _(
                "Only Pending Approval requests "
                "can be rejected."
            )
        )

    clean_reason = str(
        rejection_reason or ""
    ).strip()

    if not clean_reason:
        frappe.throw(
            _("Rejection Reason is required.")
        )

    request = _get_request(
        request_name
    )

    request.status = STATUS_REJECTED
    request.rejection_reason = clean_reason
    request.decided_by = user
    request.decided_at = now_datetime()

    _save_service_transition(
        request
    )

    return frappe._dict(
        {
            "request": request.name,
            "status": request.status,
        }
    )


@frappe.whitelist()
def approve_correction_request(
    request_name,
    allow_period_override=False,
):
    user = _require_approver()

    locked = _lock_request(
        request_name
    )

    if locked.status != STATUS_PENDING:
        frappe.throw(
            _(
                "Only Pending Approval requests "
                "can be approved."
            )
        )

    request = _get_request(
        request_name
    )

    _validate_source_unchanged(
        request
    )

    workday_name = (
        _get_affected_workday(
            request
        )
    )

    checkin = _apply_source_correction(
        request
    )

    reprocessing_result = (
        reprocess_workday(
            workday_name=workday_name,
            trigger=TRIGGER_CHECKIN_CORRECTION,
            reason=(
                f"{request.correction_type}: "
                f"{request.reason}"
            ),
            source_doctype=(
                "Checkin Correction Request"
            ),
            source_name=request.name,
            allow_period_override=(
                allow_period_override
            ),
        )
    )

    request.status = STATUS_APPLIED
    request.applied_checkin = checkin.name
    request.affected_workday = (
        workday_name
    )
    request.reprocessing_log = (
        reprocessing_result.get(
            "reprocessing_log"
        )
    )
    request.decided_by = user
    request.decided_at = now_datetime()
    request.rejection_reason = None

    _save_service_transition(
        request
    )

    return frappe._dict(
        {
            "request": request.name,
            "status": request.status,
            "employee_checkin": (
                checkin.name
            ),
            "workday": workday_name,
            "reprocessing_log": (
                request.reprocessing_log
            ),
        }
    )
