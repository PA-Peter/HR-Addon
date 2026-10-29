# Copyright (c) 2026, RieckMedia and contributors
# For license information, please see license.txt

"""Planned personnel capacity and approved absence statistics.

Read-only. Uses submitted WWH schedules, approved HRMS leave
applications, and the existing HR-Addon holiday semantics.
"""

import json
from collections import defaultdict
from datetime import timedelta

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from hr_addon.hr_addon.holiday_semantics import (
    get_holiday_fraction,
)


CATEGORIES = ("Krankheit", "Urlaub", "Unbezahlt", "Sonstige")


def _category(leave_type, types):
    if leave_type == "Krankheit":
        return "Krankheit"
    if leave_type == "Urlaub":
        return "Urlaub"
    if cint(types.get(leave_type, {}).get("is_lwp")):
        return "Unbezahlt"
    return "Sonstige"


def _period(day, aggregation):
    if aggregation == "Woche":
        iso = day.isocalendar()
        return f"{iso.year}-KW{iso.week:02d}"
    if aggregation == "Quartal":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    if aggregation == "Jahr":
        return str(day.year)
    return f"{day.year}-{day.month:02d}"


def _empty():
    return {
        "planned": 0,
        "selected": 0,
        "Krankheit": 0,
        "Urlaub": 0,
        "Unbezahlt": 0,
        "Sonstige": 0,
    }


def _add(target, source):
    for key in target:
        target[key] += source[key]


def _result_row(period, employee, name, values):
    planned = values["planned"]
    absent = sum(values[c] for c in CATEGORIES)
    available = max(planned - absent, 0)

    def hours(value):
        return round(value / 60, 2)

    def percentage(value):
        return round(100 * value / planned, 2) if planned else 0

    return {
        "periode": period,
        "employee": employee,
        "mitarbeiter": name,
        "soll_h": hours(planned),
        "verfuegbar_h": hours(available),
        "krank_h": hours(values["Krankheit"]),
        "urlaub_h": hours(values["Urlaub"]),
        "unbezahlt_h": hours(values["Unbezahlt"]),
        "sonstige_h": hours(values["Sonstige"]),
        "auswahl_h": hours(values["selected"]),
        "krank_pct": percentage(values["Krankheit"]),
        "urlaub_pct": percentage(values["Urlaub"]),
        "ausfall_pct": percentage(absent),
        "verfuegbar_pct": percentage(available),
    }



def _normalize_multi_filter(value):
    """Accept MultiSelectList values as list or JSON array."""
    if value is None or value == "" or value == []:
        return []

    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []

        if value.startswith("["):
            try:
                value = json.loads(value)
            except ValueError:
                frappe.throw(_("Invalid selection filter."))
        else:
            value = [value]

    if not isinstance(value, list):
        frappe.throw(_("Invalid selection filter."))

    result = []

    for item in value:
        if isinstance(item, dict):
            item = item.get("value")

        if not isinstance(item, str) or not item.strip():
            frappe.throw(_("Invalid selection filter."))

        item = item.strip()

        if item not in result:
            result.append(item)

    return result


def execute(filters=None):
    if (
        frappe.session.user != "Administrator"
        and not (
            {"HR Manager", "System Manager"}
            & set(frappe.get_roles())
        )
    ):
        frappe.throw(
            _("HR administration permission required."),
            frappe.PermissionError,
        )

    filters = frappe._dict(filters or {})
    today = getdate(frappe.utils.today())
    start = getdate(filters.get("from_date") or today.replace(day=1))
    end = getdate(filters.get("to_date") or today)

    if start > end:
        frappe.throw(_("Start date must not exceed end date."))

    aggregation = filters.get("aggregation") or "Monat"
    if aggregation not in ("Woche", "Monat", "Quartal", "Jahr"):
        frappe.throw(_("Invalid aggregation."))

    employee_filter = _normalize_multi_filter(
        filters.get("employee")
    )
    type_filter = _normalize_multi_filter(
        filters.get("leave_types")
    )

    employees = frappe.get_all(
        "Employee",
        fields=[
            "name",
            "employee_name",
            "date_of_joining",
            "relieving_date",
        ],
        filters=(
            {"name": ["in", employee_filter]}
            if employee_filter else None
        ),
        limit_page_length=0,
    )

    employee_lookup = {e.name: e for e in employees}
    employee_ids = list(employee_lookup)

    columns = [
        {"fieldname": "periode", "label": _("Zeitraum"),
         "fieldtype": "Data", "width": 105},
        {"fieldname": "employee", "label": _("Mitarbeiter-ID"),
         "fieldtype": "Link", "options": "Employee", "width": 145},
        {"fieldname": "mitarbeiter", "label": _("Mitarbeiter"),
         "fieldtype": "Data", "width": 175},
    ]

    for fieldname, label in (
        ("soll_h", "Soll [h]"),
        ("verfuegbar_h", "Verfügbar [h]"),
        ("krank_h", "Krankheit [h]"),
        ("urlaub_h", "Urlaub [h]"),
        ("unbezahlt_h", "Unbezahlt [h]"),
        ("sonstige_h", "Sonstige [h]"),
        ("auswahl_h", "Ausfall [h]"),
        ("krank_pct", "Krankheit [%]"),
        ("urlaub_pct", "Urlaub [%]"),
        ("ausfall_pct", "Ausfall gesamt [%]"),
        ("verfuegbar_pct", "Verfügbar [%]"),
    ):
        columns.append({
            "fieldname": fieldname,
            "label": _(label),
            "fieldtype": "Float",
            "precision": 2,
            "width": max(88, min(148, 30 + 7 * len(label))),
        })

    if not employee_ids:
        return columns, []

    models = frappe.get_all(
        "Weekly Working Hours",
        filters={
            "docstatus": 1,
            "employee": ["in", employee_ids],
            "valid_from": ["<=", end],
        },
        fields=["name", "employee", "valid_from", "valid_to"],
        limit_page_length=0,
    )

    models_by_employee = defaultdict(list)
    for model in models:
        if model.valid_to and getdate(model.valid_to) < start:
            continue
        models_by_employee[model.employee].append(model)

    schedule = defaultdict(dict)
    if models:
        daily = frappe.get_all(
            "Daily Hours Detail",
            filters={
                "parent": ["in", [m.name for m in models]],
                "parenttype": "Weekly Working Hours",
            },
            fields=["parent", "day", "hours"],
            limit_page_length=0,
        )
        for d in daily:
            schedule[d.parent][d.day] = max(
                int(round(flt(d.hours) * 60)), 0
            )

    leave_types = {
        r.name: r
        for r in frappe.get_all(
            "Leave Type",
            fields=["name", "is_lwp", "include_holiday"],
            limit_page_length=0,
        )
    }

    leaves = frappe.get_all(
        "Leave Application",
        filters={
            "docstatus": 1,
            "status": "Approved",
            "employee": ["in", employee_ids],
            "from_date": ["<=", end],
            "to_date": [">=", start],
        },
        fields=[
            "name", "employee", "leave_type",
            "from_date", "to_date",
            "half_day", "half_day_date",
        ],
        limit_page_length=0,
    )

    leaves_by_employee = defaultdict(list)
    for leave in leaves:
        leaves_by_employee[leave.employee].append(leave)

    rows_by_key = defaultdict(_empty)

    for employee, person in employee_lookup.items():
        day = start
        while day <= end:
            if (
                person.date_of_joining
                and day < getdate(person.date_of_joining)
            ) or (
                person.relieving_date
                and day > getdate(person.relieving_date)
            ):
                day += timedelta(days=1)
                continue

            matching = [
                model
                for model in models_by_employee[employee]
                if getdate(model.valid_from) <= day
                and (
                    not model.valid_to
                    or getdate(model.valid_to) >= day
                )
            ]

            if len(matching) > 1:
                frappe.throw(
                    f"Overlapping WWH: {employee}, {day}"
                )

            if not matching:
                day += timedelta(days=1)
                continue

            base = schedule[matching[0].name].get(
                day.strftime("%A"), 0
            )

            if base <= 0:
                day += timedelta(days=1)
                continue

            holiday = get_holiday_fraction(employee, day)
            planned = max(int(round(base * (1 - holiday))), 0)

            if planned <= 0:
                day += timedelta(days=1)
                continue

            values = rows_by_key[
                (_period(day, aggregation), employee)
            ]
            values["planned"] += planned

            remaining = planned

            applicable = [
                leave
                for leave in leaves_by_employee[employee]
                if getdate(leave.from_date) <= day
                <= getdate(leave.to_date)
            ]

            for leave in applicable:
                fraction = 0.5 if (
                    cint(leave.half_day)
                    and (
                        not leave.half_day_date
                        or getdate(leave.half_day_date) == day
                    )
                ) else 1.0

                loss = min(
                    int(round(base * fraction)),
                    remaining,
                )

                category = _category(
                    leave.leave_type, leave_types
                )

                values[category] += loss

                if (
                    not type_filter
                    or leave.leave_type in type_filter
                ):
                    values["selected"] += loss

                remaining -= loss

                if not remaining:
                    break

            day += timedelta(days=1)

    totals = defaultdict(_empty)
    output = []

    for (period, employee), values in sorted(
        rows_by_key.items()
    ):
        output.append(
            _result_row(
                period,
                employee,
                employee_lookup[employee].employee_name,
                values,
            )
        )
        _add(totals[period], values)

    for period, values in sorted(totals.items()):
        output.append(
            _result_row(
                period, None, "GESAMT", values
            )
        )

    output.sort(
        key=lambda row: (
            row["periode"],
            row["employee"] is None,
            row["employee"] or "",
        )
    )

    combined = _empty()
    for values in totals.values():
        _add(combined, values)

    planned = combined["planned"]
    absent = sum(combined[c] for c in CATEGORIES)

    def rate(minutes):
        return round(
            minutes * 100 / planned, 2
        ) if planned else 0

    summary = [
        {
            "label": "Geplante Sollstunden",
            "value": round(planned / 60, 1),
            "datatype": "Float",
        },
        {
            "label": "Verfügbare Kapazität [%]",
            "value": rate(planned - absent),
            "datatype": "Float",
            "indicator": "Green",
        },
        {
            "label": "Urlaubsquote [%]",
            "value": rate(combined["Urlaub"]),
            "datatype": "Float",
            "indicator": "Blue",
        },
        {
            "label": "Krankheitsquote [%]",
            "value": rate(combined["Krankheit"]),
            "datatype": "Float",
            "indicator": "Orange",
        },
    ]

    chart = {
        "data": {
            "labels": sorted(totals),
            "datasets": [
                {
                    "name": label,
                    "values": [
                        (
                            round(totals[p][category] * 100
                                  / totals[p]["planned"], 2)
                            if totals[p]["planned"] else 0
                        )
                        for p in sorted(totals)
                    ],
                }
                for label, category in (
                    ("Krankheit", "Krankheit"),
                    ("Urlaub", "Urlaub"),
                    ("Unbezahlt", "Unbezahlt"),
                    ("Sonstige", "Sonstige"),
                )
            ],
        },
        "type": "bar",
        "colors": ["#E3A047", "#4B87CE", "#9298A6", "#9276B5"],
        "barOptions": {"stacked": 1},
    }

    return columns, output, None, chart, summary
