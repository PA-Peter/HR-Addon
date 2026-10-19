// RieckMedia HR Addon – Stage 7.4a
// Persönlicher Jahreskalender – ausschließlich lesende Datenanzeige.

frappe.pages["mein-jahreskalender"].on_page_load = function (wrapper) {
    const page = frappe.ui.make_app_page({
        parent: wrapper,
        title: __("Mein Jahreskalender"),
        single_column: true,
    });

    const root = $(page.body);
    const state = {
        year: new Date().getFullYear(),
        data: null,
        request: 0,
    };

    const esc = (value) => String(value ?? "").replace(
        /[&<>"']/g,
        (char) => ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
        })[char]
    );

    const pad = (value) => String(value).padStart(2, "0");

    const iso = (year, month, day) =>
        `${year}-${pad(month)}-${pad(day)}`;

    const parseDay = (value) => {
        const [year, month, day] = value
            .slice(0, 10)
            .split("-")
            .map(Number);

        return new Date(year, month - 1, day);
    };

    const minutes = (value, signed = false) => {
        const n = Number(value || 0);
        const prefix = n < 0 ? "−" : signed && n > 0 ? "+" : "";
        const abs = Math.abs(n);

        return (
            prefix +
            pad(Math.floor(abs / 60)) +
            ":" +
            pad(abs % 60)
        );
    };

    const statusText = (value) => {
        const labels = {
            "Not Workday": "Arbeitsfrei",
            "On Leave": "Abwesend",
            "Present": "Anwesend",
            "Absent": "Abwesend",
            "Half Day": "Halber Arbeitstag",
            "Approved": "Genehmigt",
            "Open": "Offen",
            "Rejected": "Abgelehnt",
            "Cancelled": "Storniert",
            "Canceled": "Storniert",
        };

        return labels[value] || value || "–";
    };

    const fmtDate = (value) =>
        new Intl.DateTimeFormat("de-DE", {
            weekday: "long",
            day: "numeric",
            month: "long",
            year: "numeric",
        }).format(parseDay(value));

    root.html(`
        <style>
            .rmcal {
                padding: 8px 8px 30px 2px;

                /* Eigener Scrollbereich innerhalb von Frappe Desk */
                max-height: calc(100vh - 140px);
                max-height: calc(100dvh - 140px);

                overflow-y: auto;
                overflow-x: hidden;

                overscroll-behavior-y: contain;
                -webkit-overflow-scrolling: touch;
            }

            .rmcal-toolbar {
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
                align-items: center;
                justify-content: space-between;
                margin-bottom: 16px;
            }

            .rmcal-buttons {
                display: flex;
                gap: 8px;
                align-items: center;
            }

            .rmcal-year {
                font-size: 20px;
                font-weight: 600;
                min-width: 60px;
                text-align: center;
            }

            .rmcal-legend {
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
                font-size: 12px;
                color: var(--text-muted, #666);
                margin-bottom: 15px;
            }

            .rmcal-dot {
                display: inline-block;
                width: 9px;
                height: 9px;
                border-radius: 50%;
                margin-right: 4px;
            }

            .rmcal-dot.holiday {
                background: #b78b42;
            }

            .rmcal-dot.leave {
                background: #39866f;
            }

            .rmcal-dot.work {
                background: #6585a8;
            }

            .rmcal-dot.negative {
                background: #c46a6a;
            }

            .rmcal-months {
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 16px;
            }

            .rmcal-month {
                border: 1px solid var(--border-color, #ddd);
                border-radius: 8px;
                padding: 12px;
                min-width: 0;
            }

            .rmcal-month h4 {
                margin: 0 0 10px;
                font-size: 15px;
                font-weight: 600;
            }

            .rmcal-weekdays,
            .rmcal-days {
                display: grid;
                grid-template-columns: repeat(7, minmax(0, 1fr));
                gap: 3px;
            }

            .rmcal-weekdays {
                color: var(--text-muted, #777);
                font-size: 11px;
                text-align: center;
                margin-bottom: 5px;
            }

            .rmcal-day {
                position: relative;
                width: 100%;
                min-height: 55px;
                padding: 4px 2px;
                border: 1px solid transparent;
                border-radius: 5px;
                background: var(--control-bg, #f6f7f9);
                cursor: pointer;
                text-align: center;
                color: var(--text-color, #333);
            }

            .rmcal-day:hover,
            .rmcal-day:focus {
                border-color: var(--primary, #5e83a4);
            }

            .rmcal-day .rmcal-number {
                display: block;
                font-size: 12px;
                font-weight: 600;
            }

            .rmcal-day .rmcal-label {
                display: block;
                font-size: 10px;
                line-height: 1.3;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }

            .rmcal-dot.company,
            .rmcal-event-dot {
                background: #8660ad;
            }

            .rmcal-event-dot {
                position: absolute;
                top: 4px;
                right: 4px;
                width: 8px;
                height: 8px;
                border-radius: 50%;
                pointer-events: none;
            }

            .rmcal-day.weekend {
                opacity: .75;
            }

            .rmcal-day.holiday {
                background: #f8e9cd;
                color: #674b18;
            }

            .rmcal-day.leave {
                background: #d9f1e7;
                color: #225a49;
            }

            .rmcal-day.work {
                box-shadow: inset 0 -3px 0 #6585a8;
            }

            .rmcal-day.negative {
                box-shadow: inset 0 -3px 0 #c46a6a;
            }

            .rmcal-day.today {
                outline: 2px solid #456aab;
                outline-offset: -2px;
            }

            .rmcal-placeholder {
                min-height: 55px;
            }

            .rmcal-status {
                font-size: 12px;
                color: var(--text-muted, #666);
            }

            .rmcal-details {
                line-height: 1.65;
            }

            .rmcal-company-details {
                margin: 12px 0;
                padding: 10px 12px;
                border-left: 3px solid #8660ad;
                background: var(--control-bg, #f6f7f9);
                border-radius: 4px;
            }

            .rmcal-company-entry {
                margin-top: 8px;
            }

            .rmcal-details table {
                width: 100%;
                margin: 10px 0;
            }

            .rmcal-details td {
                padding: 3px 10px 3px 0;
                vertical-align: top;
            }

            .rmcal-balance {
                display: flex;
                justify-content: space-between;
                flex-wrap: wrap;
                gap: 10px;
                margin: 14px 0;
                padding: 12px 0;
                border-top: 1px solid var(--border-color, #ddd);
                border-bottom: 1px solid var(--border-color, #ddd);
            }

            .rmcal-balance strong {
                font-weight: 700;
            }

            .rmcal-detail-actions {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 16px;
            }

            @media (max-width: 1100px) {
                .rmcal-months {
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }
            }

            @media (max-width: 650px) {
                .rmcal-months {
                    grid-template-columns: 1fr;
                }
            }
        </style>

        <div class="rmcal">
            <div class="rmcal-toolbar">
                <div class="rmcal-buttons">
                    <button class="btn btn-default btn-sm"
                            data-rmcal-nav="-1"
                            aria-label="Vorjahr">&#9664;</button>

                    <span class="rmcal-year"></span>

                    <button class="btn btn-default btn-sm"
                            data-rmcal-nav="1"
                            aria-label="Folgejahr">&#9654;</button>

                    <button class="btn btn-default btn-sm"
                            data-rmcal-refresh="1">
                        Aktualisieren
                    </button>
                </div>

                <span class="rmcal-status"
                      aria-live="polite"></span>
            </div>

            <div class="rmcal-legend">
                <span><i class="rmcal-dot holiday"></i>Feiertag</span>
                <span><i class="rmcal-dot leave"></i>Abwesenheit</span>
                <span><i class="rmcal-dot work"></i>Arbeitstag</span>
                <span><i class="rmcal-dot negative"></i>Negativer Tagesdelta</span>
                <span><i class="rmcal-dot company"></i>Firmentermin</span>
            </div>

            <div class="rmcal-months"></div>
        </div>
    `);

    function makeIndexes(data) {
        const days = Object.create(null);

        const ensure = (date) =>
            (days[date] ||= {
                checkins: [],
                leaves: [],
                company_events: [],
            });

        for (const workday of data.workdays || []) {
            ensure(workday.date).workday = workday;
        }

        for (const checkin of data.checkins || []) {
            ensure(checkin.time.slice(0, 10))
                .checkins.push(checkin);
        }

        for (const holiday of data.holidays || []) {
            ensure(holiday.date).holiday = holiday;
        }

        const first = `${data.year}-01-01`;
        const last = `${data.year}-12-31`;

        for (const event of data.company_events || []) {
            if (!event.start_date || !event.end_date) {
                continue;
            }

            const begin =
                event.start_date < first
                    ? first
                    : event.start_date;

            const end =
                event.end_date > last
                    ? last
                    : event.end_date;

            if (begin > end) {
                continue;
            }

            const stop = parseDay(end);

            for (
                const d = parseDay(begin);
                d <= stop;
                d.setDate(d.getDate() + 1)
            ) {
                const key = iso(
                    d.getFullYear(),
                    d.getMonth() + 1,
                    d.getDate()
                );

                ensure(key).company_events.push(event);
            }
        }

        for (const leave of data.leaves || []) {
            if (
                leave.docstatus === 2 ||
                ["Rejected", "Cancelled"].includes(leave.status)
            ) {
                continue;
            }

            const begin =
                leave.from_date < first ? first : leave.from_date;

            const end =
                leave.to_date > last ? last : leave.to_date;

            if (begin > end) {
                continue;
            }

            const stop = parseDay(end);

            for (
                const d = parseDay(begin);
                d <= stop;
                d.setDate(d.getDate() + 1)
            ) {
                ensure(
                    iso(
                        d.getFullYear(),
                        d.getMonth() + 1,
                        d.getDate()
                    )
                ).leaves.push(leave);
            }
        }

        return days;
    }

    function statusFor(day) {
        const approved = day.leaves.find(
            (leave) =>
                leave.docstatus === 1 &&
                leave.status === "Approved"
        );

        const pending = day.leaves.find(
            (leave) => leave !== approved
        );

        if (approved) {
            return {
                label: approved.leave_type || "Abwesend",
                style: "leave",
            };
        }

        if (day.holiday && !day.holiday.weekly_off) {
            return {
                label: day.holiday.is_half_day
                    ? "½ Feiertag"
                    : "Feiertag",
                style: "holiday",
            };
        }

        if (pending) {
            return {
                label: "Antrag offen",
                style: "leave",
            };
        }

        if (day.workday) {
            return {
                label: minutes(
                    day.workday.daily_delta_minutes,
                    true
                ),
                style:
                    Number(day.workday.daily_delta_minutes) < 0
                        ? "negative"
                        : "work",
            };
        }

        if (day.holiday?.weekly_off) {
            return {
                label: "Wochenruhe",
                style: "",
            };
        }

        return {
            label: "",
            style: "",
        };
    }

    function renderYear() {
        const data = state.data;
        const days = makeIndexes(data);

        state.days = days;

        const today = new Date();

        const todayIso = iso(
            today.getFullYear(),
            today.getMonth() + 1,
            today.getDate()
        );

        const months = [];

        for (let month = 1; month <= 12; month++) {
            const title = new Intl.DateTimeFormat(
                "de-DE",
                { month: "long" }
            ).format(new Date(data.year, month - 1, 1));

            const firstWeekday = (
                new Date(data.year, month - 1, 1).getDay() + 6
            ) % 7;

            const count = new Date(
                data.year,
                month,
                0
            ).getDate();

            const cells = Array(firstWeekday).fill(
                '<span class="rmcal-placeholder"></span>'
            );

            for (let dayNo = 1; dayNo <= count; dayNo++) {
                const date = iso(
                    data.year,
                    month,
                    dayNo
                );

                const day = days[date] || {
                    checkins: [],
                    leaves: [],
                };

                const marker = statusFor(day);

                const weekend = [0, 6].includes(
                    new Date(
                        data.year,
                        month - 1,
                        dayNo
                    ).getDay()
                );

                const checks = day.checkins.map(
                    (c) =>
                        `${c.time.slice(11, 16)} ${c.log_type}` +
                        (c.excluded ? " (ausgeschlossen)" : "")
                ).join("; ");

                const companyTitles = (
                    day.company_events || []
                ).map((event) => event.title).join("; ");

                const tooltip = [
                    date,
                    day.holiday?.description,
                    marker.label,
                    companyTitles,
                    checks,
                ].filter(Boolean).join(" | ");

                const classes = [
                    "rmcal-day",
                    marker.style,
                    weekend && "weekend",
                    date === todayIso && "today",
                ].filter(Boolean).join(" ");

                cells.push(`
                    <button
                        class="${classes}"
                        data-rmcal-date="${date}"
                        title="${esc(tooltip)}"
                        aria-label="${esc(fmtDate(date))}">

                        <span class="rmcal-number">
                            ${dayNo}
                        </span>

                        ${
                            day.company_events?.length
                                ? `<span class="rmcal-event-dot"
                                         aria-hidden="true"></span>`
                                : ""
                        }

                        <span class="rmcal-label">
                            ${esc(marker.label)}
                        </span>
                    </button>
                `);
            }

            months.push(`
                <section class="rmcal-month">
                    <h4>${esc(title)}</h4>

                    <div class="rmcal-weekdays">
                        ${[
                            "Mo", "Di", "Mi", "Do",
                            "Fr", "Sa", "So"
                        ].map(
                            (wd) => `<span>${wd}</span>`
                        ).join("")}
                    </div>

                    <div class="rmcal-days">
                        ${cells.join("")}
                    </div>
                </section>
            `);
        }

        root.find(".rmcal-year").text(data.year);
        root.find(".rmcal-months").html(months.join(""));

        root.find(".rmcal-status").text(
            `Kalender für ${data.employee.employee_name}`
        );
    }

    function showDay(date) {
        const day = state.days[date] || {
            checkins: [],
            leaves: [],
        };

        const wd = day.workday;
        const pairs = [];

        if (wd) {
            const fields = [
                ["Soll", "target_minutes", false],
                ["Arbeitszeit (roh)", "raw_work_minutes", false],
                ["Tatsächliche Pause", "physical_break_minutes", false],
                [
                    "Automatischer Pausenabzug",
                    "automatic_break_deduction_minutes",
                    false,
                ],
                [
                    "Abwesenheitsgutschrift",
                    "absence_credit_minutes",
                    false,
                ],
                ["Anrechenbare Zeit", "accountable_minutes", false],
                ["Tagesdelta", "daily_delta_minutes", true],
            ];

            for (const [label, field, signed] of fields) {
                pairs.push(`
                    <tr>
                        <td>${label}</td>
                        <td><b>${minutes(wd[field], signed)}</b></td>
                    </tr>
                `);
            }

            // No invented status when Workday has none.
            if (wd.status) {
                pairs.unshift(`
                    <tr>
                        <td>Status</td>
                        <td>${esc(statusText(wd.status))}</td>
                    </tr>
                `);
            }
        }

        const holidays = day.holiday
            ? day.holiday.weekly_off
                ? `
                    <p>
                        <b>Wochenruhe:</b>
                        ${esc(day.holiday.description || "–")}
                    </p>
                  `
                : `
                    <p>
                        <b>Feiertag:</b>
                        ${esc(day.holiday.description || "–")}
                        ${day.holiday.is_half_day ? "(halber Tag)" : ""}
                    </p>
                  `
            : "";

        const leaves = day.leaves.length
            ? `
                <p>
                    <b>Abwesenheit:</b>
                    ${day.leaves.map(
                        (leave) =>
                            `${esc(leave.leave_type)} ` +
                            `(${esc(statusText(leave.status))})` +
                            (leave.half_day ? " – halber Tag" : "")
                    ).join("; ")}
                </p>
              `
            : "";

        const checkins = day.checkins.length
            ? `
                <p>
                    <b>IN/OUT:</b><br>
                    ${day.checkins.map(
                        (c) =>
                            `${esc(c.time.slice(11, 16))} ` +
                            `${esc(c.log_type)}` +
                            (c.excluded ? " – ausgeschlossen" : "")
                    ).join("<br>")}
                </p>
              `
            : "<p>Keine Checkins an diesem Datum.</p>";

        const companyMarkup = (day.company_events || []).length
            ? `
                <div class="rmcal-company-details">
                    <b>Firmentermine:</b>

                    ${(day.company_events || []).map((event) => {
                        const startTime = String(
                            event.start_time || ""
                        ).slice(0, 5);

                        const endTime = String(
                            event.end_time || ""
                        ).slice(0, 5);

                        let when = "Ganztägig";

                        if (!event.all_day) {
                            when = event.start_date === event.end_date
                                ? `${startTime}–${endTime} Uhr`
                                : `${event.start_date} ${startTime}` +
                                  ` – ${event.end_date} ${endTime}`;
                        }

                        return `
                            <div class="rmcal-company-entry">
                                <strong>${esc(event.title)}</strong>
                                (${esc(event.category)})<br>
                                ${esc(when)}
                                ${
                                    event.location
                                        ? `<br>Ort: ${esc(event.location)}`
                                        : ""
                                }
                            </div>
                        `;
                    }).join("")}
                </div>
              `
            : "";

        const balances =
            state.data.ledger_closing_balances || {};

        const hasBalance =
            Object.prototype.hasOwnProperty.call(
                balances,
                date
            );

        const balanceMarkup = hasBalance
            ? `
                <div class="rmcal-balance">
                    <span>Zeitkontostand am Tagesende</span>
                    <strong>
                        ${minutes(balances[date], true)}
                    </strong>
                </div>
              `
            : "";

        const details = `
            <div class="rmcal-details">
                ${holidays}
                ${leaves}
                ${companyMarkup}

                ${
                    wd
                        ? `<table>${pairs.join("")}</table>`
                        : "<p>Kein Workday für diesen Tag vorhanden.</p>"
                }

                ${balanceMarkup}

                ${checkins}

                <div class="rmcal-detail-actions">
                    <button class="btn btn-default btn-sm"
                            data-rmcal-action="leave">
                        Urlaub / Abwesenheit beantragen
                    </button>

                    <button class="btn btn-default btn-sm"
                            data-rmcal-action="correction">
                        Checkin-Korrektur
                    </button>

                    ${
                        wd
                            ? `<button class="btn btn-default btn-sm"
                                       data-rmcal-action="workday">
                                   Workday öffnen
                               </button>`
                            : ""
                    }
                </div>
            </div>
        `;

        const dialog = new frappe.ui.Dialog({
            title: fmtDate(date),
            fields: [
                {
                    fieldtype: "HTML",
                    fieldname: "details",
                },
            ],
        });

        dialog.show();

        dialog.fields_dict.details.$wrapper.html(details);

        dialog.$wrapper.on(
            "click",
            "[data-rmcal-action]",
            function () {
                const action = this.dataset.rmcalAction;

                dialog.hide();

                if (action === "leave") {
                    frappe.new_doc(
                        "Leave Application",
                        {
                            from_date: date,
                            to_date: date,
                        }
                    );
                } else if (action === "correction") {
                    frappe.new_doc(
                        "Checkin Correction Request",
                        {
                            correction_date: date,
                        }
                    );
                } else if (action === "workday" && wd) {
                    frappe.set_route(
                        "Form",
                        "Workday",
                        wd.name
                    );
                }
            }
        );
    }

    async function loadYear() {
        if (state.year < 2000 || state.year > 2100) {
            return;
        }

        const request = ++state.request;

        root.find(".rmcal-year").text(state.year);
        root.find(".rmcal-status").text("Lade Kalender …");

        try {
            const response = await frappe.call({
                method:
                    "hr_addon.hr_addon.annual_calendar.get_personal_year",
                args: {
                    year: state.year,
                },
            });

            if (request !== state.request) {
                return;
            }

            if (!response.message) {
                throw new Error(
                    "Leere Antwort der Kalender-API"
                );
            }

            state.data = response.message;
            renderYear();

        } catch (error) {
            if (request !== state.request) {
                return;
            }

            root.find(".rmcal-status").text(
                "Kalenderdaten konnten nicht geladen werden."
            );

            root.find(".rmcal-months").empty();

            console.error(
                "RieckMedia Jahreskalender:",
                error
            );
        }
    }

    root.on(
        "click",
        "[data-rmcal-nav]",
        function () {
            const next =
                state.year + Number(this.dataset.rmcalNav);

            if (next >= 2000 && next <= 2100) {
                state.year = next;
                loadYear();
            }
        }
    );

    root.on(
        "click",
        "[data-rmcal-refresh]",
        loadYear
    );

    root.on(
        "click",
        "[data-rmcal-date]",
        function () {
            if (state.data) {
                showDay(this.dataset.rmcalDate);
            }
        }
    );

    loadYear();
};
