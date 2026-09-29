// Copyright (c) 2026, RieckMedia and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Document", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		const is_management_user = [
			"System Manager",
			"HR Manager",
		].some(
			(role) => frappe.user_roles.includes(role)
		);

		if (
			!is_management_user
			&& frm.doc.read_status === "New"
		) {
			frappe.call({
				method:
					"hr_addon.hr_addon.doctype."
					+ "employee_document.employee_document."
					+ "mark_seen",
				args: {
					name: frm.doc.name,
				},
			}).then((response) => {
				if (
					response.message
					&& response.message.changed
				) {
					frm.doc.read_status =
						response.message.read_status;

					frm.doc.seen_at =
						response.message.seen_at;

					frm.refresh_field(
						"read_status"
					);

					frm.refresh_field(
						"seen_at"
					);
				}
			});
		}

		if (
			frm.doc.folder === "Inbox"
		) {
			frm.add_custom_button(
				__("Archive"),
				() => {
					frappe.confirm(
						__(
							"Move this document "
							+ "to the archive?"
						),
						() => {
							frappe.call({
								method:
									"hr_addon.hr_addon."
									+ "doctype.employee_document."
									+ "employee_document."
									+ "archive_document",
								args: {
									name:
										frm.doc.name,
								},
								freeze: true,
								freeze_message:
									__(
										"Archiving document..."
									),
							}).then(
								(response) => {
									if (
										response.message
										&& response.message.changed
									) {
										frappe.show_alert({
											message:
												__(
													"Document archived."
												),
											indicator:
												"green",
										});
									}

									frm.reload_doc();
								}
							);
						}
					);
				}
			);
		}
	},
});
