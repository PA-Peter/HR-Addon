# Copyright (c) 2022, phamos.eu and Contributors
# See license.txt

import frappe
from erpnext.setup.doctype.employee.test_employee import make_employee
from frappe.tests import IntegrationTestCase
from hr_addon.hr_addon.doctype.workday.workday import (
	get_employee_default_work_hour,
	has_valid_weekly_working_hours,
)


class TestWeeklyWorkingHours(IntegrationTestCase):
	def setUp(self):
		super().setUp()

		self.company = frappe.get_all(
			"Company",
			pluck="name",
			limit=1,
		)[0]

		test_email = f"wwh-{self._testMethodName}@example.com"

		self.employee = make_employee(
			test_email,
			company=self.company,
		)

	def make_wwh(self, valid_from, valid_to=None, submit=False):
		doc = frappe.get_doc(
			{
				"doctype": "Weekly Working Hours",
				"employee": self.employee,
				"company": self.company,
				"valid_from": valid_from,
				"valid_to": valid_to,
				"hours": [
					{
						"day": "Monday",
						"hours": 8,
					}
				],
			}
		)

		doc.insert()

		if submit:
			doc.submit()

		return doc

	def test_open_ended_period_is_allowed(self):
		doc = self.make_wwh(
			"2027-01-01",
			valid_to=None,
			submit=True,
		)

		self.assertEqual(doc.docstatus, 1)
		self.assertFalse(doc.valid_to)

	def test_valid_from_after_valid_to_is_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.make_wwh(
				"2027-12-31",
				"2027-01-01",
			)

	def test_identical_period_is_rejected(self):
		self.make_wwh(
			"2027-01-01",
			"2027-12-31",
			submit=True,
		)

		with self.assertRaises(frappe.ValidationError):
			self.make_wwh(
				"2027-01-01",
				"2027-12-31",
			)

	def test_new_period_starting_inside_existing_period_is_rejected(self):
		self.make_wwh(
			"2027-01-01",
			"2027-06-30",
			submit=True,
		)

		with self.assertRaises(frappe.ValidationError):
			self.make_wwh(
				"2027-05-01",
				"2027-12-31",
			)

	def test_new_period_ending_inside_existing_period_is_rejected(self):
		self.make_wwh(
			"2027-05-01",
			"2027-12-31",
			submit=True,
		)

		with self.assertRaises(frappe.ValidationError):
			self.make_wwh(
				"2027-01-01",
				"2027-06-30",
			)

	def test_adjacent_periods_are_allowed(self):
		self.make_wwh(
			"2027-01-01",
			"2027-06-30",
			submit=True,
		)

		doc = self.make_wwh(
			"2027-07-01",
			valid_to=None,
			submit=True,
		)

		self.assertEqual(doc.docstatus, 1)
		self.assertFalse(doc.valid_to)

	def test_second_open_ended_period_is_rejected(self):
		self.make_wwh(
			"2027-01-01",
			valid_to=None,
			submit=True,
		)

		with self.assertRaises(frappe.ValidationError):
			self.make_wwh(
				"2027-07-01",
				valid_to=None,
			)

	def test_closed_period_before_future_open_period_is_allowed(self):
		self.make_wwh(
			"2027-07-01",
			valid_to=None,
			submit=True,
		)

		doc = self.make_wwh(
			"2027-01-01",
			"2027-06-30",
			submit=True,
		)

		self.assertEqual(doc.docstatus, 1)

	def test_closed_period_overlapping_open_period_is_rejected(self):
		self.make_wwh(
			"2027-01-01",
			valid_to=None,
			submit=True,
		)

		with self.assertRaises(frappe.ValidationError):
			self.make_wwh(
				"2027-07-01",
				"2027-12-31",
			)
		def test_open_ended_period_is_valid_for_workday_lookup(self):
		self.make_wwh(
			"2027-01-01",
			valid_to=None,
			submit=True,
		)

		self.assertTrue(
			has_valid_weekly_working_hours(
				self.employee,
				"2027-01-04",
			)
		)

	def test_open_ended_period_supplies_target_hours(self):
		self.make_wwh(
			"2027-01-01",
			valid_to=None,
			submit=True,
		)

		work_hours = get_employee_default_work_hour(
			self.employee,
			"2027-01-04",
			skip_workday_if_no_weekly_hours=True,
		)

		self.assertIsNotNone(work_hours)
		self.assertEqual(work_hours.hours, 8)
