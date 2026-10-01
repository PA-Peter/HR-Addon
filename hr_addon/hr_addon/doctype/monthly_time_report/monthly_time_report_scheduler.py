# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe.utils import (
    add_days,
    cint,
    getdate,
    now_datetime,
)

from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report import (
    STATUS_FINAL,
    STATUS_GENERATED,
)
from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_publication import (
    create_and_publish_monthly_time_report,
    finalize_monthly_time_report,
    publish_monthly_time_report,
    regenerate_and_publish_monthly_time_report,
)
from hr_addon.hr_addon.doctype.monthly_time_report.monthly_time_report_service import (
    build_monthly_time_report_snapshot,
    monthly_time_report_source_fingerprint,
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
            "status",
            "revision",
            "finalized_at",
            "finalized_by",
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


def reconcile_previous_month_reports(
    reference_datetime=None,
):
    """
    Reconcile the previous calendar month.

    The normal monthly scheduler creates the first
    revision on day 3.

    This daily reconciliation:
    - does nothing before day 3,
    - catches up reports that were previously blocked,
    - publishes a complete unpublished report,
    - creates a new revision when source data changed,
    - does nothing when the published snapshot is
      still identical.
    """

    reference_datetime = (
        reference_datetime
        or now_datetime()
    )

    (
        year,
        month,
        period_from,
        period_to,
    ) = get_previous_month_period(
        reference_datetime
    )

    result = {
        "year": year,
        "month": month,
        "employees": 0,
        "skipped_before_day_3": False,
        "created": [],
        "published_existing": [],
        "revised": [],
        "unchanged": [],
        "blocked": [],
        "failed": [],
    }

    if (
        getdate(
            reference_datetime
        ).day
        < 3
    ):
        result[
            "skipped_before_day_3"
        ] = True

        return result

    employees = (
        _get_reportable_employees(
            period_from,
            period_to,
        )
    )

    result[
        "employees"
    ] = len(
        employees
    )

    for index, employee in enumerate(
        employees,
        start=1,
    ):
        save_point = (
            f"monthly_reconcile_{index}"
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
                        "report": (
                            current.name
                            if current
                            else None
                        ),
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
                        "reconciliation blocked for "
                        "%s / %02d/%04d because "
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

            if not current:
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

                continue

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

            current_doc = (
                frappe.get_doc(
                    "Monthly Time Report",
                    current.name,
                )
            )

            current_fingerprint = (
                monthly_time_report_source_fingerprint(
                    current_doc
                )
            )

            source_fingerprint = (
                monthly_time_report_source_fingerprint(
                    snapshot
                )
            )

            if (
                current.employee_document
                and current.pdf_file
            ):
                if (
                    current_fingerprint
                    == source_fingerprint
                ):
                    result[
                        "unchanged"
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

                publication = (
                    regenerate_and_publish_monthly_time_report(
                        current.name,
                        reference_datetime=(
                            reference_datetime
                        ),
                    )
                )

                result[
                    "revised"
                ].append(
                    {
                        "employee": (
                            employee.name
                        ),
                        "previous_report": (
                            current.name
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
                        "revision": (
                            publication[
                                "revision"
                            ]
                        ),
                    }
                )

                frappe.db.release_savepoint(
                    save_point
                )

                continue

            #
            # An unpublished current report should
            # normally only exist after an interrupted
            # administrative/manual process.
            #
            # It may safely be published only if its
            # immutable snapshot still exactly matches
            # the current source.
            #
            if (
                current_fingerprint
                != source_fingerprint
            ):
                raise RuntimeError(
                    (
                        "Unpublished Monthly Time "
                        f"Report {current.name} no "
                        "longer matches the source "
                        "snapshot."
                    )
                )

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
                    "Reconciliation"
                ),
                message=(
                    frappe.get_traceback()
                ),
            )

    return result


def get_finalization_period(
    reference_datetime=None,
):
    """
    Return the calendar month that becomes
    final on the first day of the current
    month.

    Example:
    2026-11-01 -> September 2026
    """

    reference_datetime = (
        reference_datetime
        or now_datetime()
    )

    reference_date = getdate(
        reference_datetime
    )

    first_current = (
        reference_date.replace(
            day=1
        )
    )

    previous_month_to = (
        add_days(
            first_current,
            -1,
        )
    )

    previous_month_from = (
        previous_month_to.replace(
            day=1
        )
    )

    period_to = add_days(
        previous_month_from,
        -1,
    )

    period_from = (
        period_to.replace(
            day=1
        )
    )

    return (
        period_to.year,
        period_to.month,
        period_from,
        period_to,
    )


def finalize_due_month_reports(
    reference_datetime=None,
):
    """
    Perform the final source reconciliation
    and finalize the latest report revision
    for the month that has just left the
    normal correction window.

    Source changes made on the final day of
    the correction month are therefore still
    captured before finalization.
    """

    reference_datetime = (
        reference_datetime
        or now_datetime()
    )

    (
        year,
        month,
        period_from,
        period_to,
    ) = get_finalization_period(
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
        "revised": [],
        "unchanged": [],
        "finalized": [],
        "already_final": [],
        "blocked": [],
        "failed": [],
    }

    for index, employee in enumerate(
        employees,
        start=1,
    ):
        save_point = (
            f"monthly_finalize_{index}"
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

            if (
                current
                and current.status
                == STATUS_FINAL
            ):
                if (
                    not _publication_state_is_consistent(
                        current
                    )
                    or not current.employee_document
                    or not current.pdf_file
                ):
                    raise RuntimeError(
                        (
                            "Final Monthly Time Report "
                            f"{current.name} has an "
                            "inconsistent publication "
                            "state."
                        )
                    )

                result[
                    "already_final"
                ].append(
                    {
                        "employee": (
                            employee.name
                        ),
                        "report": (
                            current.name
                        ),
                        "revision": (
                            cint(
                                current.revision
                            )
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
                        "report": (
                            current.name
                            if current
                            else None
                        ),
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
                        "finalization blocked for "
                        "%s / %02d/%04d because "
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

            report_name = None

            if not current:
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

                report_name = (
                    publication[
                        "report"
                    ]
                )

                result[
                    "created"
                ].append(
                    {
                        "employee": (
                            employee.name
                        ),
                        "report": (
                            report_name
                        ),
                        "employee_document": (
                            publication[
                                "employee_document"
                            ]
                        ),
                    }
                )

            else:
                if (
                    current.status
                    != STATUS_GENERATED
                ):
                    raise RuntimeError(
                        (
                            "Current Monthly Time "
                            f"Report {current.name} "
                            f"has invalid status "
                            f"{current.status} for "
                            "finalization."
                        )
                    )

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

                current_doc = (
                    frappe.get_doc(
                        "Monthly Time Report",
                        current.name,
                    )
                )

                current_fingerprint = (
                    monthly_time_report_source_fingerprint(
                        current_doc
                    )
                )

                source_fingerprint = (
                    monthly_time_report_source_fingerprint(
                        snapshot
                    )
                )

                if (
                    current.employee_document
                    and current.pdf_file
                ):
                    if (
                        current_fingerprint
                        != source_fingerprint
                    ):
                        publication = (
                            regenerate_and_publish_monthly_time_report(
                                current.name,
                                reference_datetime=(
                                    reference_datetime
                                ),
                            )
                        )

                        report_name = (
                            publication[
                                "report"
                            ]
                        )

                        result[
                            "revised"
                        ].append(
                            {
                                "employee": (
                                    employee.name
                                ),
                                "previous_report": (
                                    current.name
                                ),
                                "report": (
                                    report_name
                                ),
                                "employee_document": (
                                    publication[
                                        "employee_document"
                                    ]
                                ),
                                "revision": (
                                    publication[
                                        "revision"
                                    ]
                                ),
                            }
                        )

                    else:
                        report_name = (
                            current.name
                        )

                        result[
                            "unchanged"
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

                else:
                    if (
                        current_fingerprint
                        != source_fingerprint
                    ):
                        raise RuntimeError(
                            (
                                "Unpublished Monthly "
                                "Time Report "
                                f"{current.name} no "
                                "longer matches the "
                                "source snapshot."
                            )
                        )

                    publication = (
                        publish_monthly_time_report(
                            current.name
                        )
                    )

                    report_name = (
                        publication[
                            "report"
                        ]
                    )

                    result[
                        "published_existing"
                    ].append(
                        {
                            "employee": (
                                employee.name
                            ),
                            "report": (
                                report_name
                            ),
                            "employee_document": (
                                publication[
                                    "employee_document"
                                ]
                            ),
                        }
                    )

            finalization = (
                finalize_monthly_time_report(
                    report_name,
                    reference_datetime=(
                        reference_datetime
                    ),
                )
            )

            result[
                "finalized"
            ].append(
                {
                    "employee": (
                        employee.name
                    ),
                    "report": (
                        finalization[
                            "report"
                        ]
                    ),
                    "finalized_at": (
                        finalization[
                            "finalized_at"
                        ]
                    ),
                    "finalized_by": (
                        finalization[
                            "finalized_by"
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
                    "Finalization"
                ),
                message=(
                    frappe.get_traceback()
                ),
            )

    return result
