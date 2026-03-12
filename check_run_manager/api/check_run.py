import frappe
from frappe import _
from frappe.utils import now_datetime


def format_check_number(number: int) -> str:
    return str(int(number)).zfill(6)


@frappe.whitelist()
def get_check_run(docname: str):
    doc = frappe.get_doc("Check Run", docname)
    return doc.as_dict()


@frappe.whitelist()
def load_eligible_payments(company: str, bank_account: str):
    linked_payment_entries = frappe.get_all(
        "Check Run Item",
        filters={"docstatus": ["<", 2]},
        pluck="payment_entry"
    )

    filters = {
        "docstatus": 1,
        "company": company,
        "payment_type": "Pay",
        "party_type": "Supplier",
        "paid_from": bank_account,
    }

    if linked_payment_entries:
        filters["name"] = ["not in", linked_payment_entries]

    payments = frappe.get_all(
        "Payment Entry",
        filters=filters,
        fields=[
            "name",
            "party",
            "party_name",
            "posting_date",
            "paid_amount",
            "reference_no",
        ],
        order_by="posting_date asc, name asc",
    )

    return payments


@frappe.whitelist()
def add_payments_to_run(check_run_name: str, payment_entry_names: list[str]):
    doc = frappe.get_doc("Check Run", check_run_name)
    existing = {row.payment_entry for row in (doc.items or [])}

    for pe_name in payment_entry_names:
        if pe_name in existing:
            continue

        pe = frappe.get_doc("Payment Entry", pe_name)

        doc.append("items", {
            "supplier": pe.party,
            "supplier_name": pe.party_name,
            "payment_entry": pe.name,
            "amount": pe.paid_amount,
            "net_amount": pe.paid_amount,
            "invoice_reference": pe.reference_no or "",
            "payee_name": pe.party_name or pe.party,
            "memo": pe.reference_no or pe.name,
            "print_status": "Pending",
        })

    doc.save()
    return doc.as_dict()


@frappe.whitelist()
def assign_check_numbers(check_run_name: str, starting_number: int | None = None):
    doc = frappe.get_doc("Check Run", check_run_name)

    if starting_number is None:
        starting_number = doc.start_check_number or 2

    starting_number = int(starting_number)

    if starting_number < 2:
        frappe.throw(_("Starting Check Number must be 2 or greater."))

    next_number = starting_number
    sequence = 1

    for row in doc.items or []:
        if row.print_status in ("Voided",):
            continue

        row.sequence_no = sequence
        row.check_number = next_number
        sequence += 1
        next_number += 1

    doc.start_check_number = starting_number
    doc.next_check_number = next_number
    doc.calculate_totals()
    doc.status = "Ready to Print"
    doc.save()

    return {
        "ok": True,
        "message": f"Assigned check numbers {format_check_number(starting_number)} to {format_check_number(next_number - 1)}",
        "doc": doc.as_dict(),
    }


@frappe.whitelist()
def mark_printed(check_run_name: str):
    doc = frappe.get_doc("Check Run", check_run_name)

    for row in doc.items or []:
        if row.check_number and row.print_status == "Pending":
            row.print_status = "Printed"
            row.printed_on = now_datetime()
            row.printed_by = frappe.session.user

    doc.status = "Printed"
    doc.printed_on = now_datetime()
    doc.printed_by = frappe.session.user
    doc.save()

    return {
        "ok": True,
        "message": f"Marked Check Run {doc.name} as printed.",
        "doc": doc.as_dict(),
    }


@frappe.whitelist()
def void_check(check_run_name: str, row_name: str, reason: str):
    doc = frappe.get_doc("Check Run", check_run_name)

    target = None
    for row in doc.items or []:
        if row.name == row_name:
            target = row
            break

    if not target:
        frappe.throw(_("Check Run Item not found."))

    target.print_status = "Voided"
    target.void_reason = reason
    doc.status = "Partially Voided"
    doc.save()

    return {
        "ok": True,
        "message": f"Voided check {format_check_number(target.check_number)}",
        "doc": doc.as_dict(),
    }


@frappe.whitelist()
def create_check_run(company: str, bank_account: str, payment_date: str, print_format: str | None = None):
    doc = frappe.get_doc({
        "doctype": "Check Run",
        "company": company,
        "bank_account": bank_account,
        "payment_date": payment_date,
        "status": "Draft",
        "start_check_number": 2,
        "next_check_number": 2,
        "print_format": print_format,
    })

    doc.insert()
    return doc.as_dict()