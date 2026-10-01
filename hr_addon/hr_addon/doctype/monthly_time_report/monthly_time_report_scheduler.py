# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe.utils import (
    add_days,
    cint,
    getdate,
    now_datetime,
)

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_publication import (
    create_and_publish_monthly_time_report,
    publish_monthly_time_report,
)
from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_service import (
    build_monthly_time_report_snapshot,
)


def get_previous_month_period(
    reference_datetime=None,
):
    reference_datetime = (
        reference_datetime
        or now_datetime()
    )

    reference_date = getdate(
        reference_datetime
    )

    first_of_current_month = (
        reference_date.replace(
            day=1
        )
    )

    period_to = add_days(
        first_of_current_month,
        -1,
    )

    period_from = getdate(
        (
            f"{period_to.year:04d}-"
            f"{period_to.month:02d}-01"
        )
    )

    return (
        period_to.year,
        period_to.month,
        period_from,
        period_to,
    )


def _get_reportable_employees(
    period_from,
    period_to,
):
    rows = frappe.get_all(
        "Employee",
        fields=[
            "name",
            "employee_name",
            "date_of_joining",
            "relieving_date",
        ],
        order_by="name",
    )

    result = []

    for row in rows:
        joining_date = (
            getdate(
                row.date_of_joining
            )
            if row.date_of_joining
            else None
        )

        relieving_date = (
            getdate(
                row.relieving_date
            )
            if row.relieving_date
            else None
        )

        if (
            joining_date
            and joining_date > period_to
        ):
            continue

        if (
            relieving_date
            and relieving_date < period_from
        ):
            continue

        result.append(
            row
        )

    return result


def _get_current_report(
    employee,
    year,
    month,
):
    rows = frappe.get_all(
        "Monthly Time Report",
        filters={
            "employee": employee,
            "report_year": year,
            "report_month": month,
            "is_current_revision": 1,
        },
        fields=[
            "name",
            "is_complete",
            "blocking_issue_count",
            "employee_document",
            "pdf_file",
        ],
        limit_page_length=2,
    )

    if len(rows) > 1:
        frappe.throw(
            (
                "More than one current Monthly "
                "Time Report exists for "
                f"{employee} / "
                f"{month:02d}/{year:04d}."
            )
        )

    return (
        rows[0]
        if rows
        else None
    )


def _publication_state_is_consistent(
    report,
):
    return bool(
        report.employee_document
    ) == bool(
        report.pdf_file
    )


def generate_previous_month_reports(
    reference_datetime=None,
):
    (
        year,
        month,
        period_from,
        period_to,
    ) = get_previous_month_period(
        reference_datetime
    )

    employees = (
        _get_reportable_employees(
            period_from,
            period_to,
        )
    )

    result = {
        "year": year,
        "month": month,
        "employees": len(
            employees
        ),
        "created": [],
        "published_existing": [],
        "already_published": [],
        "blocked": [],
        "failed": [],
    }

    for index, employee in enumerate(
        employees,
        start=1,
    ):
        save_point = (
            f"monthly_report_{index}"
        )

        frappe.db.savepoint(
            save_point
        )

        try:
            current = (
                _get_current_report(
                    employee.name,
                    year,
                    month,
                )
            )

            if current:
                if not (
                    _publication_state_is_consistent(
                        current
                    )
                ):
                    raise RuntimeError(
                        (
                            "Monthly Time Report "
                            f"{current.name} has an "
                            "inconsistent publication "
                            "state."
                        )
                    )

                if (
                    current.employee_document
                    and current.pdf_file
                ):
                    result[
                        "already_published"
                    ].append(
                        {
                            "employee": (
                                employee.name
                            ),
                            "report": (
                                current.name
                            ),
                        }
                    )

                    frappe.db.release_savepoint(
                        save_point
                    )

                    continue

                if (
                    not cint(
                        current.is_complete
                    )
                    or cint(
                        current.blocking_issue_count
                    )
                ):
                    result[
                        "blocked"
                    ].append(
                        {
                            "employee": (
                                employee.name
                            ),
                            "report": (
                                current.name
                            ),
                            "blocking_issue_count": (
                                cint(
                                    current.blocking_issue_count
                                )
                            ),
                        }
                    )

                    frappe.db.release_savepoint(
                        save_point
                    )

                    continue

                publication = (
                    publish_monthly_time_report(
                        current.name
                    )
                )

                result[
                    "published_existing"
                ].append(
                    {
                        "employee": (
                            employee.name
                        ),
                        "report": (
                            publication[
                                "report"
                            ]
                        ),
                        "employee_document": (
                            publication[
                                "employee_document"
                            ]
                        ),
                    }
                )

                frappe.db.release_savepoint(
                    save_point
                )

                continue

            snapshot = (
                build_monthly_time_report_snapshot(
                    employee.name,
                    year,
                    month,
                    reference_datetime=(
                        reference_datetime
                    ),
                )
            )

            if (
                not cint(
                    snapshot.get(
                        "is_complete"
                    )
                )
                or cint(
                    snapshot.get(
                        "blocking_issue_count"
                    )
                )
            ):
                result[
                    "blocked"
                ].append(
                    {
                        "employee": (
                            employee.name
                        ),
                        "report": None,
                        "blocking_issue_count": (
                            cint(
                                snapshot.get(
                                    "blocking_issue_count"
                                )
                            )
                        ),
                    }
                )

                frappe.logger(
                    "hr_addon"
                ).warning(
                    (
                        "Monthly Time Report "
                        "not published for %s / "
                        "%02d/%04d because "
                        "source data is incomplete."
                    ),
                    employee.name,
                    month,
                    year,
                )

                frappe.db.release_savepoint(
                    save_point
                )

                continue

            publication = (
                create_and_publish_monthly_time_report(
                    employee.name,
                    year,
                    month,
                    reference_datetime=(
                        reference_datetime
                    ),
                )
            )

            result[
                "created"
            ].append(
                {
                    "employee": (
                        employee.name
                    ),
                    "report": (
                        publication[
                            "report"
                        ]
                    ),
                    "employee_document": (
                        publication[
                            "employee_document"
                        ]
                    ),
                }
            )

            frappe.db.release_savepoint(
                save_point
            )

        except Exception:
            frappe.db.rollback(
                save_point=(
                    save_point
                )
            )

            result[
                "failed"
            ].append(
                {
                    "employee": (
                        employee.name
                    ),
                }
            )

            frappe.log_error(
                title=(
                    "Monthly Time Report "
                    "Scheduler"
                ),
                message=(
                    frappe.get_traceback()
                ),
            )

    return result
