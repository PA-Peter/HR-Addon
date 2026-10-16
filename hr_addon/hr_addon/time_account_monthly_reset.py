# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

import frappe

from frappe.utils import (
    add_days,
    cint,
    getdate,
    now_datetime,
)

from hr_addon.hr_addon.doctype.time_account_ledger_entry.time_account_ledger_entry import (
    ENTRY_TYPE_NEGATIVE_ADJUSTMENT,
    ENTRY_TYPE_POSITIVE_ADJUSTMENT,
    create_manual_time_account_entry,
)


GERMAN_MONTH_NAMES = (
    "",
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
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

    period_from = period_to.replace(
        day=1
    )

    return (
        period_from,
        period_to,
    )


def _get_reset_models(
    period_to,
):
    return frappe.db.sql(
        """
        SELECT
            name,
            employee
        FROM
            `tabWeekly Working Hours`
        WHERE
            docstatus = 1
            AND reset_time_account_monthly = 1
            AND valid_from <= %s
            AND (
                valid_to IS NULL
                OR valid_to = ''
                OR valid_to >= %s
            )
        ORDER BY
            employee,
            name
        """,
        (
            period_to,
            period_to,
        ),
        as_dict=True,
    )


def get_time_account_balance_as_of(
    employee,
    effective_date,
):
    result = frappe.db.sql(
        """
        SELECT
            COALESCE(
                SUM(delta_minutes),
                0
            )
        FROM
            `tabTime Account Ledger Entry`
        WHERE
            employee = %s
            AND effective_date <= %s
        """,
        (
            employee,
            effective_date,
        ),
    )

    if not result:
        return 0

    return cint(
        result[0][0]
    )


def _get_reset_remarks(
    period_to,
):
    return (
        "Automatischer Monatsreset "
        f"{GERMAN_MONTH_NAMES[period_to.month]} "
        f"{period_to.year}"
    )


def reconcile_previous_month_time_account_resets(
    reference_datetime=None,
):
    (
        period_from,
        period_to,
    ) = get_previous_month_period(
        reference_datetime
    )

    models = _get_reset_models(
        period_to
    )

    result = {
        "period_from": period_from,
        "period_to": period_to,
        "models": len(models),
        "posted": [],
        "already_zero": [],
        "failed": [],
    }

    employees_seen = set()

    for index, model in enumerate(
        models,
        start=1,
    ):
        if model.employee in employees_seen:
            frappe.throw(
                (
                    "More than one submitted Weekly "
                    "Working Hours model with monthly "
                    "reset is valid for employee "
                    f"{model.employee} on {period_to}."
                )
            )

        employees_seen.add(
            model.employee
        )

        savepoint = (
            f"time_account_monthly_reset_{index}"
        )

        frappe.db.savepoint(
            savepoint
        )

        try:
            # Serialize competing reset attempts for
            # the same WWH model.
            frappe.db.sql(
                """
                SELECT name
                FROM `tabWeekly Working Hours`
                WHERE name = %s
                FOR UPDATE
                """,
                (model.name,),
            )

            balance = (
                get_time_account_balance_as_of(
                    model.employee,
                    period_to,
                )
            )

            if balance == 0:
                result[
                    "already_zero"
                ].append(
                    {
                        "employee": (
                            model.employee
                        ),
                        "weekly_working_hours": (
                            model.name
                        ),
                    }
                )

                frappe.db.release_savepoint(
                    savepoint
                )

                continue

            delta_minutes = -balance

            entry_type = (
                ENTRY_TYPE_NEGATIVE_ADJUSTMENT
                if delta_minutes < 0
                else ENTRY_TYPE_POSITIVE_ADJUSTMENT
            )

            entry = (
                create_manual_time_account_entry(
                    employee=model.employee,
                    effective_date=period_to,
                    entry_type=entry_type,
                    delta_minutes=delta_minutes,
                    remarks=_get_reset_remarks(
                        period_to
                    ),
                )
            )

            balance_after = (
                get_time_account_balance_as_of(
                    model.employee,
                    period_to,
                )
            )

            if balance_after != 0:
                raise RuntimeError(
                    (
                        "Monthly time-account reset "
                        f"for {model.employee} did "
                        f"not result in zero. "
                        f"Remaining balance: "
                        f"{balance_after} minutes."
                    )
                )

            result[
                "posted"
            ].append(
                {
                    "employee": (
                        model.employee
                    ),
                    "weekly_working_hours": (
                        model.name
                    ),
                    "ledger_entry": (
                        entry.name
                    ),
                    "entry_type": (
                        entry.entry_type
                    ),
                    "delta_minutes": (
                        cint(
                            entry.delta_minutes
                        )
                    ),
                    "effective_date": (
                        entry.effective_date
                    ),
                    "effective_time": (
                        entry.effective_time
                    ),
                    "remarks": (
                        entry.remarks
                    ),
                }
            )

            frappe.db.release_savepoint(
                savepoint
            )

        except Exception:
            frappe.db.rollback(
                save_point=(
                    savepoint
                )
            )

            result[
                "failed"
            ].append(
                {
                    "employee": (
                        model.employee
                    ),
                    "weekly_working_hours": (
                        model.name
                    ),
                }
            )

            frappe.log_error(
                title=(
                    "Monthly Time Account Reset"
                ),
                message=(
                    frappe.get_traceback()
                ),
            )

    return result
