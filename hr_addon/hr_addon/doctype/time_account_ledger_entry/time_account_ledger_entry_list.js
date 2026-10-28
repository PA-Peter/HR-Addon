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

    const PREVIEW_METHOD =
        "hr_addon.hr_addon.time_account_management."
        + "get_manual_time_account_preview";

    const POST_METHOD =
        "hr_addon.hr_addon.time_account_management."
        + "post_manual_time_account_entry";

    const BOOKING_TYPES = {
        "Auszahlung": "Payout",
        "Zeitgutschrift": "Positive Adjustment",
        "Zeitabzug": "Negative Adjustment",
    };

    function openBookingDialog(listview) {
        if (!isManager()) {
            frappe.throw("Keine Berechtigung.");
            return;
        }

        let previewState = null;
        let posting = false;

        const dialog = new frappe.ui.Dialog({
            title: "Zeitkonto buchen",
            fields: [
                {
                    fieldtype: "Link",
                    fieldname: "employee",
                    label: "Mitarbeiter",
                    options: "Employee",
                    default: selectedEmployee(listview) || "",
                    reqd: 1,
                },
                {
                    fieldtype: "Date",
                    fieldname: "effective_date",
                    label: "Buchungsdatum",
                    default: frappe.datetime.get_today(),
                    reqd: 1,
                },
                {
                    fieldtype: "Select",
                    fieldname: "booking_type",
                    label: "Buchungsart",
                    options: Object.keys(BOOKING_TYPES).join("\n"),
                    default: "Auszahlung",
                    reqd: 1,
                },
                {
                    fieldtype: "Column Break",
                },
                {
                    fieldtype: "Data",
                    fieldname: "hours",
                    label: "Stunden",
                    default: "00",
                    length: 4,
                    reqd: 1,
                },
                {
                    fieldtype: "Data",
                    fieldname: "minutes",
                    label: "Minuten (0–59)",
                    default: "00",
                    length: 2,
                    reqd: 1,
                },
                {
                    fieldtype: "Section Break",
                    label: "Begründung",
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "remarks",
                    label: "Bemerkung",
                    reqd: 1,
                    description: "Pflichtfeld. Maximal 500 Zeichen.",
                },
                {
                    fieldtype: "Section Break",
                    label: "Buchungsvorschau",
                },
                {
                    fieldtype: "HTML",
                    fieldname: "booking_preview",
                },
            ],
        });

        const $preview =
            dialog.fields_dict.booking_preview.$wrapper;

        $preview.text(
            "Es wurde noch keine Buchung berechnet."
        );

        function normalized(values) {
            return {
                employee: values.employee,
                effective_date: values.effective_date,
                entry_type: BOOKING_TYPES[values.booking_type],
                hours: String(values.hours),
                minutes: String(values.minutes),
                remarks: String(values.remarks || "").trim(),
            };
        }

        function signature(values) {
            return JSON.stringify(normalized(values));
        }

        function showPreview(data, values) {
            const $box = $("<div>").css({
                padding: "12px",
                border: "1px solid var(--border-color)",
                borderRadius: "6px",
            });

            const lines = [
                "Mitarbeiter: " +
                    (data.employee_name || data.employee),
                "Buchungsdatum: " + data.effective_date,
                "Buchungsart: " + values.booking_type,
                "Zeitänderung: " +
                    formatMinutes(data.delta_minutes),
                "Saldo zum Buchungsdatum vorher: " +
                    formatMinutes(data.balance_at_date_before),
                "Saldo zum Buchungsdatum nachher: " +
                    formatMinutes(data.balance_at_date_after),
                "Aktueller Saldo vorher: " +
                    formatMinutes(data.current_balance_before),
                "Aktueller Saldo nachher: " +
                    formatMinutes(data.current_balance_after),
            ];

            lines.forEach(line => {
                $box.append(
                    $("<div>")
                        .css({ marginBottom: "5px" })
                        .text(line)
                );
            });

            $box.append(
                $("<div>")
                    .addClass("text-muted small")
                    .css({ marginTop: "10px" })
                    .text(
                        "Dies ist nur die Vorschau. " +
                        "Noch wurde nichts gebucht."
                    )
            );

            $preview.empty().append($box);
        }

        async function loadPreview(values) {
            previewState = null;

            const input = normalized(values);

            const validHours = /^\d{1,4}$/.test(input.hours);
            const validMinutes = /^\d{1,2}$/.test(input.minutes);

            if (
                !validHours ||
                !validMinutes ||
                Number(input.minutes) > 59 ||
                (
                    Number(input.hours) === 0 &&
                    Number(input.minutes) === 0
                )
            ) {
                frappe.msgprint(
                    "Bitte eine gültige Zeit eingeben " +
                    "(Stunden 0–9999, Minuten 0–59). " +
                    "00:00 ist nicht zulässig."
                );
                return;
            }

            if (!input.entry_type) {
                frappe.msgprint("Ungültige Buchungsart.");
                return;
            }

            if (!input.remarks || input.remarks.length > 500) {
                frappe.msgprint(
                    "Bitte eine Bemerkung mit maximal " +
                    "500 Zeichen eingeben."
                );
                return;
            }

            dialog.disable_primary_action();

            try {
                const response = await frappe.call({
                    method: PREVIEW_METHOD,
                    args: {
                        employee: input.employee,
                        effective_date: input.effective_date,
                        entry_type: input.entry_type,
                        hours: input.hours,
                        minutes: input.minutes,
                    },
                });

                const data = response.message;

                if (
                    !data ||
                    data.preview_only !== true ||
                    data.employee !== input.employee
                ) {
                    throw new Error(
                        "Keine gültige Buchungsvorschau erhalten."
                    );
                }

                previewState = {
                    signature: signature(values),
                    input,
                    data,
                };

                showPreview(data, values);

                dialog.set_primary_action(
                    "Buchung bestätigen",
                    confirmBooking
                );

            } catch (error) {
                $preview.text(
                    "Vorschau fehlgeschlagen. " +
                    "Es wurde nichts gebucht."
                );

                dialog.set_primary_action(
                    "Vorschau berechnen",
                    loadPreview
                );

            } finally {
                dialog.enable_primary_action();
            }
        }

        async function executeBooking(state) {
            if (posting) {
                return;
            }

            posting = true;
            dialog.disable_primary_action();

            try {
                const response = await frappe.call({
                    method: POST_METHOD,
                    type: "POST",
                    args: {
                        ...state.input,
                        expected_balance: String(
                            state.data.current_balance_before
                        ),
                    },
                });

                const result = response.message;

                if (!result || !result.ledger_entry) {
                    throw new Error(
                        "Keine Buchungsbestätigung erhalten."
                    );
                }

                dialog.hide();

                frappe.show_alert({
                    message:
                        "Zeitkonto gebucht: " +
                        result.ledger_entry,
                    indicator: "green",
                });

                listview.refresh();

            } catch (error) {
                frappe.msgprint({
                    title: "Buchung nicht bestätigt",
                    message:
                        "Die Buchung konnte nicht bestätigt " +
                        "werden. Bitte Ledger prüfen und " +
                        "gegebenenfalls eine neue Vorschau " +
                        "abrufen. Nicht blind erneut buchen.",
                    indicator: "orange",
                });

            } finally {
                posting = false;
                dialog.enable_primary_action();
            }
        }

        function confirmBooking(values) {
            if (
                !previewState ||
                signature(values) !== previewState.signature
            ) {
                previewState = null;

                $preview.text(
                    "Eingaben wurden verändert. " +
                    "Bitte eine neue Vorschau berechnen."
                );

                dialog.set_primary_action(
                    "Vorschau berechnen",
                    loadPreview
                );

                return;
            }

            const state = previewState;

            const message =
                "Diese Zeitkontobuchung jetzt " +
                "verbindlich durchführen?" +
                "<p><strong>" +
                formatMinutes(state.data.delta_minutes) +
                "</strong></p>" +
                "<p>Der Ledger-Eintrag ist danach " +
                "nicht mehr editierbar. Korrekturen " +
                "erfordern eine Gegenbuchung.</p>";

            frappe.confirm(
                message,
                () => executeBooking(state),
                null,
                "Verbindlich buchen",
                "Abbrechen"
            );
        }

        dialog.set_primary_action(
            "Vorschau berechnen",
            loadPreview
        );

        dialog.show();

    // Information immediately after selecting an old booking date.
    // Backend period validation remains authoritative.
    const rmBookingToday = frappe.datetime.get_today();
    const rmBookingParts = rmBookingToday.split("-").map(Number);
    const rmMinimumDate = new Date(Date.UTC(
        rmBookingParts[0],
        rmBookingParts[1] - 2,
        1
    )).toISOString().slice(0, 10);

    const rmDateField = dialog.fields_dict.effective_date;

    if (rmDateField && rmDateField.$wrapper) {
        const rmClosedPeriodHint = $(
            '<div class="small mt-2 rm-closed-period-hint"></div>'
        );

        rmDateField.$wrapper.append(rmClosedPeriodHint);

        const rmRefreshDateHint = () => {
            const selectedDate = dialog.get_value("effective_date");

            if (selectedDate && selectedDate < rmMinimumDate) {
                rmClosedPeriodHint
                    .removeClass("text-muted")
                    .addClass("text-danger")
                    .text(
                        "Dieser Abrechnungszeitraum ist abgeschlossen. " +
                        "Bitte die Korrektur im aktuellen Monat buchen " +
                        "und das ursprüngliche Datum in der Begründung " +
                        "dokumentieren."
                    );
            } else {
                rmClosedPeriodHint
                    .removeClass("text-danger")
                    .addClass("text-muted")
                    .text(
                        "Buchungen sind im laufenden und vorherigen " +
                        "Kalendermonat möglich."
                    );
            }
        };

        if (rmDateField.$input) {
            rmDateField.$input.on(
                "change.rmClosedPeriod input.rmClosedPeriod",
                rmRefreshDateHint
            );
        }

        rmRefreshDateHint();
    }

    }

    function addBookingAction(listview) {
        if (
            !isManager() ||
            listview._rmBookingActionAdded
        ) {
            return;
        }

        listview._rmBookingActionAdded = true;

        listview.page.add_inner_button(
            "Zeitkonto buchen",
            () => openBookingDialog(listview)
        );
    }


    const REVERSAL_PREVIEW_METHOD =
        "hr_addon.hr_addon.time_account_management."
        + "get_manual_reversal_preview";

    const REVERSAL_POST_METHOD =
        "hr_addon.hr_addon.time_account_management."
        + "post_manual_time_account_reversal";

    function openReversalDialog(listview) {
        if (!isManager()) {
            frappe.throw("Keine Berechtigung.");
            return;
        }

        let previewState = null;
        let posting = false;

        const dialog = new frappe.ui.Dialog({
            title: "Zeitkonto stornieren",
            fields: [
                {
                    fieldtype: "Link",
                    fieldname: "entry_name",
                    label: "Originalbuchung",
                    options: "Time Account Ledger Entry",
                    reqd: 1,
                    description: "Die Buchung, die rückgängig gemacht werden soll.",
                },
                {
                    fieldtype: "Small Text",
                    fieldname: "remarks",
                    label: "Stornogrund",
                    reqd: 1,
                    description: "Pflichtfeld, maximal 500 Zeichen.",
                },
                {
                    fieldtype: "Section Break",
                    label: "Stornovorschau",
                },
                {
                    fieldtype: "HTML",
                    fieldname: "reversal_preview",
                },
            ],
        });

        const $preview =
            dialog.fields_dict.reversal_preview.$wrapper;

        $preview.text(
            "Bitte Originalbuchung und Stornogrund angeben."
        );

        function normalized(values) {
            return {
                entry_name: String(
                    values.entry_name || ""
                ).trim(),
                remarks: String(
                    values.remarks || ""
                ).trim(),
            };
        }

        function signature(values) {
            return JSON.stringify(normalized(values));
        }

        function detailRow(label, value) {
            const $row = $("<div>").css({
                display: "flex",
                justifyContent: "space-between",
                gap: "12px",
                marginBottom: "7px",
            });

            $row.append(
                $("<span>")
                    .addClass("text-muted")
                    .text(label),
                $("<strong>").text(String(value))
            );

            return $row;
        }

        function showPreview(data) {
            $preview.empty();

            const $box = $("<div>").css({
                border: "1px solid var(--border-color)",
                borderRadius: "8px",
                padding: "14px",
            });

            $box.append(
                detailRow(
                    "Originalbuchung",
                    data.original_entry
                ),
                detailRow(
                    "Mitarbeiter",
                    data.employee_name || data.employee
                ),
                detailRow(
                    "Buchungsdatum",
                    data.effective_date
                ),
                detailRow(
                    "Ursprüngliche Buchung",
                    formatMinutes(data.original_delta_minutes)
                ),
                detailRow(
                    "Gegenbuchung",
                    formatMinutes(data.reversal_delta_minutes)
                ),
                detailRow(
                    "Aktueller Saldo vorher",
                    formatMinutes(data.current_balance_before)
                ),
                detailRow(
                    "Aktueller Saldo nachher",
                    formatMinutes(data.current_balance_after)
                )
            );

            if (data.requires_admin_override) {
                $box.append(
                    $("<p>")
                        .css({
                            marginTop: "12px",
                            marginBottom: "0",
                            fontWeight: "600",
                        })
                        .text(
                            "Dieser Buchungszeitraum ist gesperrt. "
                            + "Die administrative Sonderfreigabe "
                            + "ist noch nicht implementiert."
                        )
                );
            } else {
                $box.append(
                    $("<p>")
                        .addClass("text-muted small")
                        .css({
                            marginTop: "12px",
                            marginBottom: "0",
                        })
                        .text(
                            "Dies ist nur eine Vorschau. "
                            + "Die Originalbuchung bleibt erhalten; "
                            + "bei Bestätigung entsteht eine Gegenbuchung."
                        )
                );
            }

            $preview.append($box);
        }

        async function loadPreview(values) {
            previewState = null;

            if (!values) {
                return;
            }

            const input = normalized(values);

            if (
                !input.entry_name
                || !input.remarks
                || input.remarks.length > 500
            ) {
                frappe.msgprint(
                    "Bitte Originalbuchung und einen Stornogrund "
                    + "mit maximal 500 Zeichen angeben."
                );
                return;
            }

            dialog.disable_primary_action();
            $preview.text("Stornovorschau wird berechnet …");

            try {
                const response = await frappe.call({
                    method: REVERSAL_PREVIEW_METHOD,
                    args: {
                        entry_name: input.entry_name,
                    },
                });

                const data = response.message;

                if (
                    !data
                    || data.preview_only !== true
                    || data.original_entry !== input.entry_name
                ) {
                    throw new Error(
                        "Ungültige Stornovorschau."
                    );
                }

                showPreview(data);

                if (data.requires_admin_override) {
                    dialog.set_primary_action(
                        "Vorschau berechnen",
                        loadPreview
                    );
                    return;
                }

                previewState = {
                    signature: signature(values),
                    input,
                    data,
                };

                dialog.set_primary_action(
                    "Stornierung bestätigen",
                    confirmReversal
                );

            } catch (error) {
                $preview.text(
                    "Stornovorschau fehlgeschlagen. "
                    + "Es wurde nichts storniert."
                );

                dialog.set_primary_action(
                    "Vorschau berechnen",
                    loadPreview
                );

            } finally {
                dialog.enable_primary_action();
            }
        }

        async function executeReversal(state) {
            if (posting) {
                return;
            }

            posting = true;
            dialog.disable_primary_action();

            try {
                const response = await frappe.call({
                    method: REVERSAL_POST_METHOD,
                    type: "POST",
                    args: {
                        entry_name: state.input.entry_name,
                        remarks: state.input.remarks,
                        expected_balance: String(
                            state.data.current_balance_before
                        ),
                    },
                });

                if (!response.message?.reversal_entry) {
                    throw new Error(
                        "Keine Stornobuchung bestätigt."
                    );
                }

                dialog.hide();

                frappe.show_alert({
                    message:
                        "Stornobuchung erstellt: "
                        + response.message.reversal_entry,
                    indicator: "green",
                }, 7);

                listview.refresh();

            } catch (error) {
                previewState = null;

                dialog.set_primary_action(
                    "Vorschau berechnen",
                    loadPreview
                );

                $preview.text(
                    "Die Stornierung konnte nicht sicher "
                    + "bestätigt werden. Bitte zuerst das "
                    + "Ledger kontrollieren und die Vorschau "
                    + "neu laden. Nicht blind erneut buchen."
                );

                frappe.msgprint({
                    title: "Stornierung nicht bestätigt",
                    message:
                        "Bitte prüfen, ob bereits eine "
                        + "Gegenbuchung existiert. "
                        + "Nicht ungeprüft erneut ausführen.",
                    indicator: "orange",
                });

            } finally {
                posting = false;
                dialog.enable_primary_action();
            }
        }

        function confirmReversal(values) {
            if (
                !previewState
                || !values
                || signature(values) !== previewState.signature
            ) {
                previewState = null;

                $preview.text(
                    "Eingaben wurden verändert. "
                    + "Bitte die Stornovorschau neu berechnen."
                );

                dialog.set_primary_action(
                    "Vorschau berechnen",
                    loadPreview
                );

                return;
            }

            const state = previewState;

            frappe.confirm(
                "Soll die angezeigte Zeitkontobuchung "
                + "wirklich verbindlich storniert werden? "
                + "Dabei wird eine neue, unveränderliche "
                + "Gegenbuchung erstellt.",
                () => executeReversal(state),
                null,
                "Verbindlich stornieren",
                "Abbrechen"
            );
        }

        dialog.set_primary_action(
            "Vorschau berechnen",
            loadPreview
        );

        dialog.show();
    }

    function addReversalAction(listview) {
        if (
            !isManager()
            || listview._rmReversalActionAdded
        ) {
            return;
        }

        listview._rmReversalActionAdded = true;

        listview.page.add_inner_button(
            "Zeitkonto stornieren",
            () => openReversalDialog(listview)
        );
    }

    frappe.listview_settings[DOCTYPE] = {
        onload(listview) {
            // Disable Frappe's generic Add action.
            // Manual ledger entries use our manager dialog.
            listview.can_create = false;
            listview.set_primary_action();

            createSummary(listview);
            addBookingAction(listview);
            addReversalAction(listview);
        },

        refresh(listview) {
            refreshSummary(listview);
        },
    };
})();
