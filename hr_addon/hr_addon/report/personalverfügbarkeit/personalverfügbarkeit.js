frappe.query_reports["Personalverfügbarkeit"] = {
    restore_hr_sidebar: function () {
        const route = frappe.get_route();
        const sidebar = frappe.app && frappe.app.sidebar;

        if (
            sidebar &&
            !sidebar.sidebar_title &&
            route[0] === "query-report" &&
            route[1] === "Personalverfügbarkeit"
        ) {
            sidebar.setup("HR Addon");
        }
    },

    onload: function () {
        this.restore_hr_sidebar();
    },

    after_refresh: function () {
        this.restore_hr_sidebar();
    },

    filters: [
        {
            fieldname: "from_date",
            label: __("Von"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.month_start(),
        },
        {
            fieldname: "to_date",
            label: __("Bis"),
            fieldtype: "Date",
            reqd: 1,
            default: frappe.datetime.get_today(),
        },
        {
            fieldname: "aggregation",
            label: __("Zeitliche Gruppierung"),
            fieldtype: "Select",
            options: ["Woche", "Monat", "Quartal", "Jahr"],
            default: "Monat",
        },
        {
            fieldname: "employee",
            label: __("Mitarbeiter"),
            fieldtype: "MultiSelectList",
            get_data: function (txt) {
                return frappe.db.get_link_options(
                    "Employee", txt
                );
            },
        },
        {
            fieldname: "leave_types",
            label: __("Abwesenheitsarten"),
            fieldtype: "MultiSelectList",
            get_data: function (txt) {
                return frappe.db.get_link_options(
                    "Leave Type", txt
                );
            },
        },
    ],

    formatter: function (
        value, row, column, data, default_formatter
    ) {
        let result = default_formatter(
            value, row, column, data
        );

        if (data && data.mitarbeiter === "GESAMT") {
            result = "<strong>" + result + "</strong>";
        }

        return result;
    },
};
