// RieckMedia / HR Addon
//
// HRMS v16 normally limits Leave Type selection to:
//   - Leave Types with an active Leave Allocation
//   - Leave Without Pay types
//
// RieckMedia additionally uses paid non-quota absences:
//   - Krankheit
//   - Sonderurlaub
//
// The HRMS server natively supports these without an allocation
// when allow_negative is enabled.
//
// Important:
// HRMS resets the Leave Type query inside make_dashboard().
// Therefore our extension deliberately registers its own
// make_dashboard handler. Frappe executes the handlers serially;
// the HR Addon handler runs after the native HRMS handler and
// applies the final query deterministically.

const RM_NON_QUOTA_PAID_LEAVE_TYPES = [
    "Krankheit",
    "Sonderurlaub",
];


function rm_update_leave_ui(frm) {
    // Generic wording: this value is not necessarily vacation.
    frm.set_df_property(
        "total_leave_days",
        "label",
        "Abwesenheitstage insgesamt"
    );

    const allocated =
        frm.__rm_allocated_leave_types || [];

    const current_type =
        frm.doc.leave_type || "";

    const has_balance =
        allocated.includes(current_type);

    // Only quota-based leave types have a meaningful balance.
    frm.toggle_display(
        "leave_balance",
        has_balance
    );

    if (has_balance) {
        frm.set_df_property(
            "leave_balance",
            "label",
            "Abwesenheitssaldo vor Antrag"
        );
    }

    // Make the new-document title unambiguous.
    if (frm.is_new()) {
        frm.page.set_title(
            "Neuer Abwesenheitsantrag"
        );
    }
}


function rm_apply_leave_type_query(frm) {
    if (!frm.doc.employee) {
        frm.__rm_allocated_leave_types = [];
        rm_update_leave_ui(frm);
        return;
    }

    const date =
        frm.doc.from_date
        || frm.doc.posting_date
        || frappe.datetime.get_today();

    let details = null;

    frappe.call({
        async: false,
        method:
            "hrms.hr.doctype.leave_application."
            + "leave_application.get_leave_details",
        args: {
            employee: frm.doc.employee,
            date: date,
        },
        callback: function (r) {
            if (!r.exc && r.message) {
                details = r.message;
            }
        },
    });

    if (!details) {
        return;
    }

    const allocated = Object.keys(
        details.leave_allocation || {}
    );

    const lwps =
        details.lwps || [];

    frm.__rm_allocated_leave_types =
        allocated;

    const allowed = [
        ...new Set([
            ...allocated,
            ...lwps,
            ...RM_NON_QUOTA_PAID_LEAVE_TYPES,
        ]),
    ];

    frm.set_query(
        "leave_type",
        function () {
            return {
                filters: [
                    [
                        "leave_type_name",
                        "in",
                        allowed,
                    ],
                ],
            };
        }
    );

    rm_update_leave_ui(frm);
}


frappe.ui.form.on(
    "Leave Application",
    {
        // Native HRMS invokes make_dashboard whenever its
        // allocation-dependent Leave Type filter needs rebuilding.
        // Our handler is appended after the native handler.
        make_dashboard(frm) {
            rm_apply_leave_type_query(frm);
        },

        refresh(frm) {
            rm_update_leave_ui(frm);
        },

        leave_type(frm) {
            rm_update_leave_ui(frm);
        },
    }
);
