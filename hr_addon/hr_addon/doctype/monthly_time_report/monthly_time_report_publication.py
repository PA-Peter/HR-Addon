# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import base64
import mimetypes
import re

import frappe

from frappe import _
from frappe.utils import (
    add_months,
    cint,
    getdate,
    get_datetime,
    now_datetime,
)
from frappe.utils.file_manager import save_file
from frappe.utils.pdf import get_pdf

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report import (
    SERVICE_FLAG,
    STATUS_FINAL,
    STATUS_GENERATED,
    STATUS_SUPERSEDED,
)
from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_service import (
    build_monthly_time_report_snapshot,
    create_monthly_time_report_snapshot,
)


DOCUMENT_TYPE = "Monthly Time Report"
DOCUMENT_SOURCE = "Monthly Time Report"

PDF_TEMPLATE = (
    "hr_addon/templates/"
    "monthly_time_report.html"
)

PDF_OPTIONS = {
    "page-size": "A4",
    "orientation": "Landscape",
    "margin-top": "8mm",
    "margin-right": "8mm",
    "margin-bottom": "8mm",
    "margin-left": "8mm",
}

LEDGER_LABELS = {
    "Opening Balance": "Eröffnungssaldo",
    "Payout": "Auszahlung",
    "Positive Adjustment": "Positive Korrektur",
    "Negative Adjustment": "Negative Korrektur",
    "Reversal": "Storno",
    "Workday": "Tagesdelta",
}

WEEKDAY_LABELS = {
    0: "Mo",
    1: "Di",
    2: "Mi",
    3: "Do",
    4: "Fr",
    5: "Sa",
    6: "So",
}


def format_minutes(
    minutes,
    signed=False,
):
    minutes = cint(
        minutes
    )

    sign = ""

    if signed:
        if minutes > 0:
            sign = "+"
        elif minutes < 0:
            sign = "-"

    hours, remaining_minutes = (
        divmod(
            abs(
                minutes
            ),
            60,
        )
    )

    return (
        f"{sign}"
        f"{hours:02d}:"
        f"{remaining_minutes:02d}"
    )


def _format_report_date(
    value,
):
    if not value:
        return ""

    return getdate(
        value
    ).strftime(
        "%d.%m.%Y"
    )


def _format_generated_at(
    value,
):
    if not value:
        return ""

    return get_datetime(
        value
    ).strftime(
        "%d.%m.%Y %H:%M"
    )


def _format_absence(
    row,
):
    if not row.leave_type:
        return ""

    value = str(
        row.leave_type
    )

    if (
        row.leave_portion
        == "Half Day"
    ):
        value += " (½ Tag)"

    if cint(
        row.absence_credit_minutes
    ):
        value += (
            " · Gutschrift "
            + format_minutes(
                row.absence_credit_minutes
            )
        )

    return value


def _format_break(
    row,
):
    physical = (
        format_minutes(
            row.physical_break_minutes
        )
    )

    automatic = cint(
        row.automatic_break_deduction_minutes
    )

    if not automatic:
        return physical

    return (
        f"{physical} phys. · "
        f"{format_minutes(automatic)} auto"
    )


def _format_day_row(
    row,
):
    report_date = getdate(
        row.report_date
    )

    if (
        row.snapshot_status
        == "Outside Employment"
    ):
        return {
            "date": (
                report_date.strftime(
                    "%d.%m.%Y"
                )
            ),
            "weekday": (
                WEEKDAY_LABELS[
                    report_date.weekday()
                ]
            ),
            "checkins": "—",
            "target": "—",
            "raw_work": "—",
            "breaks": "—",
            "absence": (
                "Außerhalb Beschäftigung"
            ),
            "accountable": "—",
            "delta": "—",
        }

    checkins_text = (
        row.checkins_text
        or "—"
    )

    if (
        row.snapshot_status
        == "Missing Checkin"
    ):
        checkins_text = (
            "FEHLER: unvollständige Buchung"
        )

        if row.checkins_text:
            checkins_text += (
                " · "
                + row.checkins_text
            )

    return {
        "date": (
            report_date.strftime(
                "%d.%m.%Y"
            )
        ),
        "weekday": (
            WEEKDAY_LABELS[
                report_date.weekday()
            ]
        ),
        "checkins": (
            checkins_text
        ),
        "target": (
            format_minutes(
                row.target_minutes
            )
        ),
        "raw_work": (
            format_minutes(
                row.raw_work_minutes
            )
        ),
        "breaks": (
            _format_break(
                row
            )
        ),
        "absence": (
            _format_absence(
                row
            )
            or "—"
        ),
        "accountable": (
            format_minutes(
                row.accountable_minutes
            )
        ),
        "delta": (
            format_minutes(
                row.daily_delta_minutes,
                signed=True,
            )
        ),
    }


def _format_ledger_row(
    row,
):
    return {
        "date": (
            _format_report_date(
                row.effective_date
            )
        ),
        "entry_type": (
            LEDGER_LABELS.get(
                row.entry_type,
                row.entry_type,
            )
        ),
        "delta": (
            format_minutes(
                row.delta_minutes,
                signed=True,
            )
        ),
        "remarks": (
            row.remarks
            or ""
        ),
    }


def _image_file_data_uri(
    file_url,
):
    if not file_url:
        return ""

    file_name = frappe.db.get_value(
        "File",
        {
            "file_url": file_url,
        },
        "name",
    )

    if not file_name:
        return ""

    try:
        file_doc = frappe.get_doc(
            "File",
            file_name,
        )

        content = file_doc.get_content()

    except (
        frappe.DoesNotExistError,
        FileNotFoundError,
        OSError,
    ):
        return ""

    if isinstance(
        content,
        str,
    ):
        content = content.encode(
            "utf-8"
        )

    mime_type = (
        mimetypes.guess_type(
            file_doc.file_name
            or file_url
        )[0]
    )

    if (
        not mime_type
        or not mime_type.startswith(
            "image/"
        )
    ):
        return ""

    encoded = (
        base64.b64encode(
            content
        ).decode(
            "ascii"
        )
    )

    return (
        f"data:{mime_type};base64,"
        f"{encoded}"
    )


def _get_company_branding(
    employee,
):
    company = frappe.db.get_value(
        "Employee",
        employee,
        "company",
    )

    if not company:
        return {
            "company_name": "",
            "company_logo_data_uri": "",
        }

    company_doc = frappe.get_cached_doc(
        "Company",
        company,
    )

    company_name = (
        company_doc.company_name
        or company_doc.name
        or company
    )

    logo_data_uri = ""

    letter_head_name = (
        company_doc.default_letter_head
    )

    if letter_head_name:
        letter_head = frappe.get_cached_doc(
            "Letter Head",
            letter_head_name,
        )

        if (
            not letter_head.disabled
            and letter_head.source == "Image"
            and letter_head.image
        ):
            logo_data_uri = (
                _image_file_data_uri(
                    letter_head.image
                )
            )

    return {
        "company_name": company_name,
        "company_logo_data_uri": (
            logo_data_uri
        ),
    }


def build_pdf_context(
    report,
):
    company_branding = (
        _get_company_branding(
            report.employee
        )
    )
    day_rows = [
        _format_day_row(
            row
        )
        for row in (
            report.days or []
        )
    ]

    non_workday_ledger_rows = [
        _format_ledger_row(
            row
        )
        for row in (
            report.ledger_entries or []
        )
        if (
            row.entry_type
            != "Workday"
        )
    ]

    total_target = sum(
        cint(
            row.target_minutes
        )
        for row in (
            report.days or []
        )
    )

    total_raw_work = sum(
        cint(
            row.raw_work_minutes
        )
        for row in (
            report.days or []
        )
    )

    total_accountable = sum(
        cint(
            row.accountable_minutes
        )
        for row in (
            report.days or []
        )
    )

    total_absence_credit = sum(
        cint(
            row.absence_credit_minutes
        )
        for row in (
            report.days or []
        )
    )

    total_daily_delta = sum(
        cint(
            row.daily_delta_minutes
        )
        for row in (
            report.days or []
        )
    )

    report_year = cint(
        report.report_year
    )

    report_month = cint(
        report.report_month
    )

    return {
        "company_name": (
            company_branding[
                "company_name"
            ]
        ),
        "company_logo_data_uri": (
            company_branding[
                "company_logo_data_uri"
            ]
        ),
        "employee_name": (
            report.employee_name
            or report.employee
        ),
        "period_label": (
            f"{report_month:02d}/"
            f"{report_year:04d}"
        ),
        "revision": (
            cint(
                report.revision
            )
        ),
        "period_from": (
            _format_report_date(
                report.period_from
            )
        ),
        "period_to": (
            _format_report_date(
                report.period_to
            )
        ),
        "generated_at": (
            _format_generated_at(
                report.generated_at
            )
        ),
        "days": (
            day_rows
        ),
        "total_target": (
            format_minutes(
                total_target
            )
        ),
        "total_raw_work": (
            format_minutes(
                total_raw_work
            )
        ),
        "total_accountable": (
            format_minutes(
                total_accountable
            )
        ),
        "total_absence_credit": (
            format_minutes(
                total_absence_credit
            )
        ),
        "total_daily_delta": (
            format_minutes(
                total_daily_delta,
                signed=True,
            )
        ),
        "opening_balance": (
            format_minutes(
                report.opening_balance_minutes,
                signed=True,
            )
        ),
        "ledger_movement": (
            format_minutes(
                report.ledger_movement_minutes,
                signed=True,
            )
        ),
        "closing_balance": (
            format_minutes(
                report.closing_balance_minutes,
                signed=True,
            )
        ),
        "ledger_rows": (
            non_workday_ledger_rows
        ),
    }


def render_monthly_time_report_pdf(
    report,
):
    html = frappe.render_template(
        PDF_TEMPLATE,
        build_pdf_context(
            report
        ),
    )

    return get_pdf(
        html,
        options=PDF_OPTIONS,
    )


def _pdf_filename(
    report,
):
    employee = re.sub(
        r"[^A-Za-z0-9._-]+",
        "_",
        str(
            report.employee
            or "employee"
        ),
    ).strip(
        "_"
    )

    return (
        "Arbeitszeitnachweis_"
        f"{employee}_"
        f"{cint(report.report_year):04d}-"
        f"{cint(report.report_month):02d}_"
        f"R{cint(report.revision):02d}.pdf"
    )


def _assert_publication_state(
    report,
):
    if (
        report.status
        != STATUS_GENERATED
        or not cint(
            report.is_current_revision
        )
    ):
        frappe.throw(
            _(
                "Only the current generated "
                "Monthly Time Report revision "
                "can be published."
            )
        )

    if (
        not cint(
            report.is_complete
        )
        or cint(
            report.blocking_issue_count
        )
    ):
        frappe.throw(
            _(
                "Monthly Time Report {0} is "
                "incomplete and cannot be "
                "published to the employee."
            ).format(
                report.name
            )
        )

    has_employee_document = bool(
        report.employee_document
    )

    has_pdf_file = bool(
        report.pdf_file
    )

    if (
        has_employee_document
        != has_pdf_file
    ):
        frappe.throw(
            _(
                "Monthly Time Report {0} has "
                "an inconsistent publication "
                "state."
            ).format(
                report.name
            )
        )


def _save_private_pdf(
    report,
    pdf_content,
):
    return save_file(
        _pdf_filename(
            report
        ),
        pdf_content,
        "Monthly Time Report",
        report.name,
        is_private=1,
    )


def _employee_document_values(
    report,
    file_url,
    previous_employee_document=None,
):
    return {
        "doctype": (
            "Employee Document"
        ),
        "employee": (
            report.employee
        ),
        "document_title": (
            "Arbeitszeitnachweis "
            f"{cint(report.report_month):02d}/"
            f"{cint(report.report_year):04d}"
        ),
        "document_type": (
            DOCUMENT_TYPE
        ),
        "source": (
            DOCUMENT_SOURCE
        ),
        "document_date": (
            report.period_to
        ),
        "period_from": (
            report.period_from
        ),
        "period_to": (
            report.period_to
        ),
        "document_file": (
            file_url
        ),
        "description": (
            "Arbeitszeitnachweis aus "
            "Monthly Time Report "
            f"{report.name}, Revision "
            f"{cint(report.revision)}."
        ),
        "previous_revision": (
            previous_employee_document
        ),
        "external_reference": (
            report.name
        ),
    }


def _insert_employee_document(
    values,
):
    doc = frappe.get_doc(
        values
    )

    return doc.insert(
        ignore_permissions=True
    )


def _set_report_publication_links(
    report,
    file_url,
    employee_document,
):
    frappe.db.set_value(
        "Monthly Time Report",
        report.name,
        {
            "pdf_file": (
                file_url
            ),
            "employee_document": (
                employee_document
            ),
        },
        update_modified=True,
    )


def publish_monthly_time_report(
    name,
    previous_employee_document=None,
):
    report = frappe.get_doc(
        "Monthly Time Report",
        name,
    )

    _assert_publication_state(
        report
    )

    if (
        report.employee_document
        and report.pdf_file
    ):
        return {
            "report": (
                report.name
            ),
            "pdf_file": (
                report.pdf_file
            ),
            "employee_document": (
                report.employee_document
            ),
            "already_published": True,
        }

    pdf_content = (
        render_monthly_time_report_pdf(
            report
        )
    )

    file_doc = (
        _save_private_pdf(
            report,
            pdf_content,
        )
    )

    employee_document = (
        _insert_employee_document(
            _employee_document_values(
                report,
                file_doc.file_url,
                previous_employee_document=(
                    previous_employee_document
                ),
            )
        )
    )

    _set_report_publication_links(
        report,
        file_doc.file_url,
        employee_document.name,
    )

    return {
        "report": (
            report.name
        ),
        "pdf_file": (
            file_doc.file_url
        ),
        "employee_document": (
            employee_document.name
        ),
        "already_published": False,
    }


def create_and_publish_monthly_time_report(
    employee,
    year,
    month,
    reference_datetime=None,
):
    report = (
        create_monthly_time_report_snapshot(
            employee,
            year,
            month,
            reference_datetime=(
                reference_datetime
            ),
        )
    )

    return publish_monthly_time_report(
        report.name
    )


def _assert_revision_source(
    report,
):
    if (
        report.status
        == STATUS_FINAL
    ):
        frappe.throw(
            _(
                "Final Monthly Time Report "
                "{0} cannot be revised."
            ).format(
                report.name
            )
        )

    _assert_publication_state(
        report
    )

    if (
        not report.employee_document
        or not report.pdf_file
    ):
        frappe.throw(
            _(
                "The current Monthly Time "
                "Report must be published "
                "before a new revision can "
                "be generated."
            )
        )


def _create_revision_snapshot(
    current_report,
    reference_datetime=None,
):
    values = (
        build_monthly_time_report_snapshot(
            current_report.employee,
            current_report.report_year,
            current_report.report_month,
            reference_datetime=(
                reference_datetime
            ),
        )
    )

    values[
        "revision"
    ] = (
        cint(
            current_report.revision
        )
        + 1
    )

    values[
        "previous_revision"
    ] = (
        current_report.name
    )

    values[
        "is_current_revision"
    ] = 1

    values[
        "status"
    ] = (
        STATUS_GENERATED
    )

    doc = frappe.get_doc(
        values
    )

    doc.flags[
        SERVICE_FLAG
    ] = True

    return doc.insert(
        ignore_permissions=True
    )


def finalize_monthly_time_report(
    name,
    reference_datetime=None,
):
    report = frappe.get_doc(
        "Monthly Time Report",
        name,
    )

    if (
        report.status
        == STATUS_FINAL
    ):
        return {
            "report": report.name,
            "status": report.status,
            "finalized_at": (
                report.finalized_at
            ),
            "finalized_by": (
                report.finalized_by
            ),
            "already_finalized": True,
        }

    _assert_publication_state(
        report
    )

    if (
        not report.employee_document
        or not report.pdf_file
    ):
        frappe.throw(
            _(
                "Monthly Time Report {0} "
                "must be published before "
                "it can be finalized."
            ).format(
                report.name
            )
        )

    finalized_at = (
        get_datetime(
            reference_datetime
        )
        if reference_datetime
        else now_datetime()
    )

    due_date = getdate(
        add_months(
            getdate(
                report.period_from
            ),
            2,
        )
    ).replace(
        day=1
    )

    if (
        getdate(
            finalized_at
        )
        < due_date
    ):
        frappe.throw(
            _(
                "Monthly Time Report {0} "
                "cannot be finalized before "
                "{1}."
            ).format(
                report.name,
                frappe.format(
                    due_date,
                    {
                        "fieldtype": (
                            "Date"
                        )
                    },
                ),
            )
        )

    finalized_by = (
        getattr(
            frappe.session,
            "user",
            None,
        )
        or "Administrator"
    )

    if (
        finalized_by
        == "Guest"
    ):
        finalized_by = (
            "Administrator"
        )

    report.status = (
        STATUS_FINAL
    )

    report.finalized_at = (
        finalized_at
    )

    report.finalized_by = (
        finalized_by
    )

    report.flags[
        SERVICE_FLAG
    ] = True

    report.save(
        ignore_permissions=True
    )

    return {
        "report": (
            report.name
        ),
        "status": (
            report.status
        ),
        "finalized_at": (
            report.finalized_at
        ),
        "finalized_by": (
            report.finalized_by
        ),
        "already_finalized": False,
    }

def regenerate_and_publish_monthly_time_report(
    name,
    reference_datetime=None,
):
    current_report = (
        frappe.get_doc(
            "Monthly Time Report",
            name,
        )
    )

    _assert_revision_source(
        current_report
    )

    new_report = (
        _create_revision_snapshot(
            current_report,
            reference_datetime=(
                reference_datetime
            ),
        )
    )

    publication = (
        publish_monthly_time_report(
            new_report.name,
            previous_employee_document=(
                current_report.employee_document
            ),
        )
    )

    frappe.db.set_value(
        "Monthly Time Report",
        current_report.name,
        {
            "status": (
                STATUS_SUPERSEDED
            ),
            "is_current_revision": 0,
        },
        update_modified=True,
    )

    publication[
        "previous_report"
    ] = current_report.name

    publication[
        "revision"
    ] = cint(
        new_report.revision
    )

    return publication
