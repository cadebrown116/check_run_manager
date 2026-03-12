import frappe
from frappe import _
from frappe.utils import nowdate, now_datetime
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry


def format_check_number(number: int) -> str:
    return str(int(number)).zfill(6)


@frappe.whitelist()
def create_check_run(company: str, payment_date: str, paid_from_account: str | None = None):
    doc = frappe.get_doc({
        "doctype": "Check Run",
        "company": company,
        "payment_date": payment_date or nowdate(),
        "status": "Draft",
        "start_check_number": 2,
        "next_check_number": 2,
        "bank_account": paid_from_account or ""
    })
    doc.insert()
    return doc.as_dict()


@frappe.whitelist()
def load_eligible_invoices(company: str, supplier: str | None = None):
    filters = {
        "docstatus": 1,
        "company": company,
        "outstanding_amount": [">", 0]
    }

    if supplier:
        filters["supplier"] = supplier

    invoices = frappe.get_all(
        "Purchase Invoice",
        filters=filters,
        fields=[
            "name",
            "supplier",
            "supplier_name",
            "posting_date",
            "due_date",
            "grand_total",
            "outstanding_amount",
            "currency"
        ],
        order_by="due_date asc, posting_date asc"
    )

    return invoices


@frappe.whitelist()
def add_invoices_to_run(check_run_name: str, invoice_names: list[str]):
    doc = frappe.get_doc("Check Run", check_run_name)
    existing = {row.invoice_reference for row in (doc.items or [])}

    for inv_name in invoice_names:
        if inv_name in existing:
            continue

        inv = frappe.get_doc("Purchase Invoice", inv_name)

        doc.append("items", {
            "supplier": inv.supplier,
            "supplier_name": inv.supplier_name,
            "invoice_reference": inv.name,
            "payee_name": inv.supplier_name or inv.supplier,
            "amount": inv.outstanding_amount,
            "net_amount": inv.outstanding_amount,
            "memo": inv.name,
            "print_status": "Pending"
        })

    doc.save()
    return doc.as_dict()


@frappe.whitelist()
def assign_check_numbers_and_create_payments(
    check_run_name: str,
    starting_number: int | None = None,
    paid_from_account: str | None = None
):
    doc = frappe.get_doc("Check Run", check_run_name)

    if starting_number is None:
        starting_number = doc.start_check_number or 2

    starting_number = int(starting_number)

    if starting_number < 2:
        frappe.throw(_("Starting Check Number must be 2 or greater."))

    if not paid_from_account and not doc.bank_account:
        frappe.throw(_("Paid From Account is required to create Payment Entries."))

    paid_from_account = paid_from_account or doc.bank_account
    next_number = starting_number
    sequence = 1

    for row in doc.items or []:
        if row.print_status == "Voided":
            continue

        if not row.payment_entry:
            pe = _make_payment_entry_from_invoice(
                invoice_name=row.invoice_reference,
                payment_date=doc.payment_date,
                paid_from_account=paid_from_account,
                check_number=next_number
            )
            row.payment_entry = pe.name

        row.sequence_no = sequence
        row.check_number = next_number
        row.print_status = "Pending"

        sequence += 1
        next_number += 1

    doc.start_check_number = starting_number
    doc.next_check_number = next_number
    doc.status = "Ready to Print"
    doc.calculate_totals()
    doc.save()

    return {
        "ok": True,
        "message": f"Assigned check numbers {format_check_number(starting_number)} to {format_check_number(next_number - 1)}",
        "doc": doc.as_dict(),
    }


def _make_payment_entry_from_invoice(invoice_name: str, payment_date: str, paid_from_account: str, check_number: int):
    pe = get_payment_entry("Purchase Invoice", invoice_name)

    pe.paid_from = paid_from_account
    pe.posting_date = payment_date
    pe.reference_no = format_check_number(check_number)

    if hasattr(pe, "reference_date"):
        pe.reference_date = payment_date

    pe.insert()
    pe.submit()
    return pe


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
