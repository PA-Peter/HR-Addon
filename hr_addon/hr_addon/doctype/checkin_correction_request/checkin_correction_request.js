// Copyright (c) 2026, RieckMedia and contributors
// For license information, please see license.txt

const CCR_METHOD =
	"hr_addon.hr_addon.doctype." +
	"checkin_correction_request." +
	"checkin_correction_request.";


function can_manage_correction_requests() {
	return (
		frappe.session.user === "Administrator" ||
		frappe.user.has_role("System Manager") ||
		frappe.user.has_role("HR Manager")
	);
}


function can_approve_correction_requests() {
	return (
		frappe.session.user === "Administrator" ||
		frappe.user.has_role("System Manager")
	);
}


function is_locked_period(date_string) {
	if (!date_string) {
		return false;
	}

	const correction_date =
		frappe.datetime.str_to_obj(
			date_string
		);

	const today =
		frappe.datetime.str_to_obj(
			frappe.datetime.get_today()
		);

	const unlocked_start =
		new Date(
			today.getFullYear(),
			today.getMonth() - 1,
			1
		);

	return correction_date < unlocked_start;
}


async function set_self_service_employee(frm) {
	if (
		can_manage_correction_requests() ||
		!frm.is_new() ||
		frm.doc.employee
	) {
		return;
	}

	const result =
		await frappe.db.get_value(
			"Employee",
			{
				user_id: frappe.session.user,
				status: "Active",
			},
			"name"
		);

	const employee =
		result?.message?.name;

	if (!employee) {
		frappe.msgprint({
			title: __("Employee Missing"),
			indicator: "red",
			message: __(
				"No active Employee record is linked " +
				"to your user account."
			),
		});

		return;
	}

	await frm.set_value(
		"employee",
		employee
	);
}


function set_request_field_state(frm) {
	const locked =
		!frm.is_new() &&
		frm.doc.status !== "Draft";

	const manager =
		can_manage_correction_requests();

	const fields = [
		"employee",
		"correction_date",
		"correction_type",
		"existing_checkin",
		"requested_log_type",
		"requested_time",
		"reason",
	];

	for (const fieldname of fields) {
		let read_only = locked;

		if (
			fieldname === "employee" &&
			!manager
		) {
			read_only = true;
		}

		frm.set_df_property(
			fieldname,
			"read_only",
			read_only
		);
	}
}


function call_request_method(
	frm,
	method,
	args = {}
) {
	return frappe.call({
		method: CCR_METHOD + method,
		args: {
			request_name: frm.doc.name,
			...args,
		},
		freeze: true,
		freeze_message: __("Processing correction request..."),
	}).then(() => {
		return frm.reload_doc();
	});
}


function add_submit_button(frm) {
	if (
		frm.is_new() ||
		frm.doc.status !== "Draft"
	) {
		return;
	}

	frm.add_custom_button(
		__("Submit for Approval"),
		() => {
			call_request_method(
				frm,
				"submit_correction_request"
			);
		}
	);
}


function approve_request(
	frm,
	allow_period_override
) {
	return call_request_method(
		frm,
		"approve_correction_request",
		{
			allow_period_override:
				allow_period_override ? 1 : 0,
		}
	);
}


function add_approval_buttons(frm) {
	if (
		frm.is_new() ||
		frm.doc.status !== "Pending Approval" ||
		!can_approve_correction_requests()
	) {
		return;
	}

	if (
		is_locked_period(
			frm.doc.correction_date
		)
	) {
		frm.add_custom_button(
			__("Approve with Period Override"),
			() => {
				frappe.confirm(
					__(
						"This correction affects a locked " +
						"time-account period. Continue with " +
						"an audited period override?"
					),
					() => {
						approve_request(
							frm,
							true
						);
					}
				);
			},
			__("Actions")
		);
	} else {
		frm.add_custom_button(
			__("Approve"),
			() => {
				approve_request(
					frm,
					false
				);
			},
			__("Actions")
		);
	}

	frm.add_custom_button(
		__("Reject"),
		() => {
			frappe.prompt(
				[
					{
						fieldname:
							"rejection_reason",
						fieldtype:
							"Small Text",
						label:
							__("Rejection Reason"),
						reqd: 1,
					},
				],
				(values) => {
					call_request_method(
						frm,
						"reject_correction_request",
						{
							rejection_reason:
								values.rejection_reason,
						}
					);
				},
				__("Reject Correction Request"),
				__("Reject")
			);
		},
		__("Actions")
	);
}


frappe.ui.form.on(
	"Checkin Correction Request",
	{
		setup(frm) {
			frm.set_query(
				"existing_checkin",
				() => {
					const filters = {};

					if (frm.doc.employee) {
						filters.employee =
							frm.doc.employee;
					}

					if (
						frm.doc.correction_date
					) {
						filters.time = [
							"between",
							[
								frm.doc.correction_date +
									" 00:00:00",
								frm.doc.correction_date +
									" 23:59:59",
							],
						];
					}

					return {
						filters: filters,
					};
				}
			);
		},

		refresh(frm) {
			set_self_service_employee(
				frm
			);

			set_request_field_state(
				frm
			);

			add_submit_button(
				frm
			);

			add_approval_buttons(
				frm
			);
		},

		employee(frm) {
			if (
				frm.doc.existing_checkin
			) {
				frm.set_value(
					"existing_checkin",
					null
				);
			}
		},

		correction_date(frm) {
			if (
				frm.doc.existing_checkin
			) {
				frm.set_value(
					"existing_checkin",
					null
				);
			}
		},

		correction_type(frm) {
			if (
				frm.doc.correction_type ===
				"Missing Booking"
			) {
				frm.set_value(
					"existing_checkin",
					null
				);
			}

			if (
				frm.doc.correction_type ===
				"Accidental Extra Booking"
			) {
				frm.set_value(
					"requested_log_type",
					null
				);

				frm.set_value(
					"requested_time",
					null
				);
			}

			if (
				frm.doc.correction_type ===
				"Wrong IN/OUT Type"
			) {
				frm.set_value(
					"requested_time",
					null
				);
			}
		},
	}
);
