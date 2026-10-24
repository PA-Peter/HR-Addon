/*
 * RieckMedia – Stage 7.5
 * Time Account Ledger Entry – ListView Summary
 *
 * Read-only presentation.
 * All balances come from the server-side Ledger API.
 */

(() => {
    "use strict";

    const DOCTYPE = "Time Account Ledger Entry";

    const METHOD =
        "hr_addon.hr_addon.time_account_summary."
        + "get_time_account_summary";

    const MANAGEMENT_ROLES = [
        "HR Manager",
        "System Manager",
    ];

    function isManager() {
        const roles = frappe.user_roles || [];

        return (
            frappe.session.user === "Administrator"
            || MANAGEMENT_ROLES.some(
                role => roles.includes(role)
            )
        );
    }

    function formatMinutes(minutes) {
        const value = Number(minutes);

        if (!Number.isFinite(value)) {
            return "—";
        }

        const total = Math.trunc(value);
        const sign = total < 0 ? "−" : "+";
        const absolute = Math.abs(total);

        const hours = String(
            Math.floor(absolute / 60)
        ).padStart(2, "0");

        const mins = String(
            absolute % 60
        ).padStart(2, "0");

        return `${sign}${hours}:${mins}`;
    }

    function selectedEmployee(listview) {
        if (!listview.filter_area) {
            return null;
        }

        const filters = listview.filter_area.get();

        const employeeFilters = filters.filter(
            filter =>
                filter[0] === DOCTYPE
                && filter[1] === "employee"
        );

        if (
            employeeFilters.length !== 1
            || employeeFilters[0][2] !== "="
        ) {
            return null;
        }

        return employeeFilters[0][3] || null;
    }

    function createSummary(listview) {
        if (listview._rmTimeSummary) {
            return;
        }

        const $container = $("<div>")
            .addClass("rm-time-account-summary")
            .css({
                margin: "12px 0 16px",
                padding: "14px",
                border: "1px solid var(--border-color)",
                borderRadius: "8px",
            });

        const $heading = $("<div>")
            .css({
                fontWeight: "600",
                marginBottom: "10px",
            })
            .text("Zeitkonto – Übersicht");

        const $cards = $("<div>").css({
            display: "flex",
            flexWrap: "wrap",
            gap: "12px",
        });

        const values = {};

        const definitions = [
            ["previous_month_delta_minutes", "Delta Vormonat"],
            ["month_opening_balance_minutes", "Stand Monatsanfang"],
            ["balance_at_today_start_minutes", "Stand heute 0:00"],
        ];

        definitions.forEach(([key, label]) => {
            const $card = $("<div>").css({
                flex: "1 1 170px",
                padding: "10px 12px",
                borderRadius: "6px",
                background: "var(--control-bg)",
            });

            const $label = $("<div>")
                .addClass("text-muted small")
                .text(label);

            const $value = $("<div>")
                .css({
                    fontSize: "22px",
                    fontWeight: "600",
                    fontVariantNumeric: "tabular-nums",
                    marginTop: "4px",
                })
                .text("—");

            values[key] = $value;

            $card.append($label, $value);
            $cards.append($card);
        });

        const $note = $("<div>")
            .addClass("text-muted small")
            .css({ marginTop: "10px" });

        $container.append(
            $heading,
            $cards,
            $note
        );

        listview.$frappe_list.before($container);

        listview._rmTimeSummary = {
            values,
            note: $note,
            sequence: 0,
        };
    }

    function setValues(summary, data) {
        Object.keys(summary.values).forEach(key => {
            summary.values[key].text(
                data ? formatMinutes(data[key]) : "—"
            );
        });
    }

    function refreshSummary(listview) {
        createSummary(listview);

        const summary = listview._rmTimeSummary;
        const sequence = ++summary.sequence;

        const manager = isManager();
        const employee = selectedEmployee(listview);

        if (manager && !employee) {
            setValues(summary, null);

            summary.note.text(
                "Bitte genau einen Mitarbeiter mit "
                + "dem Filter Employee = ... auswählen."
            );

            return;
        }

        setValues(summary, null);
        summary.note.text("Zeitkontostand wird geladen …");

        const args = {};

        if (manager && employee) {
            args.employee = employee;
        }

        frappe.call({
            method: METHOD,
            args,
            freeze: false,
        }).then(response => {
            if (sequence !== summary.sequence) {
                return;
            }

            const data = response.message;

            if (
                !data
                || (
                    manager
                    && data.employee !== employee
                )
            ) {
                setValues(summary, null);
                summary.note.text(
                    "Keine gültigen Zeitkontodaten erhalten."
                );
                return;
            }

            setValues(summary, data);

            summary.note.text(
                "Buchungsstand zu Beginn des "
                + data.as_of_date
                + ". Heutige Stempelungen und "
                + "Buchungen sind nicht enthalten. "
                + "Die Summen sind unabhängig "
                + "von weiteren Listenfiltern."
            );

        }).catch(() => {
            if (sequence !== summary.sequence) {
                return;
            }

            setValues(summary, null);

            summary.note.text(
                "Zeitkontostand konnte nicht "
                + "abgerufen werden."
            );
        });
    }

    frappe.listview_settings[DOCTYPE] = {
        onload(listview) {
            createSummary(listview);
        },

        refresh(listview) {
            refreshSummary(listview);
        },
    };
})();
