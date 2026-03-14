import json
import frappe
from frappe import _
from frappe.utils import nowdate, now_datetime
from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry


def format_check_number(number: int) -> str:
    return str(int(number)).zfill(6)


def check_number_exists(check_number: int) -> bool:
    return bool(
        frappe.db.exists(
            "Check Run Item",
            {
                "check_number": check_number,
                "docstatus": ["<", 2],
                "print_status": ["!=", "Voided"],
            },
        )
    )


def get_next_check_number() -> int:
    max_no = frappe.db.sql("""
        select max(check_number)
        from `tabCheck Run Item`
        where ifnull(check_number, 0) > 0
    """)[0][0]

    next_no = int(max_no) + 1 if max_no else 2

    while check_number_exists(next_no):
        next_no += 1

    return next_no


@frappe.whitelist()
def create_check_run(company: str, payment_date: str, paid_from_account: str | None = None):
    next_no = get_next_check_number()

    doc = frappe.get_doc({
        "doctype": "Check Run",
        "company": company,
        "payment_date": payment_date or nowdate(),
        "status": "Draft",
        "start_check_number": next_no,
        "next_check_number": next_no,
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
        order_by="supplier asc, due_date asc, posting_date asc"
    )

    return invoices


@frappe.whitelist()
def add_invoices_to_run(check_run_name: str, invoice_names):
    if isinstance(invoice_names, str):
        invoice_names = json.loads(invoice_names)

    if not isinstance(invoice_names, list):
        frappe.throw("invoice_names must be a list.")

    doc = frappe.get_doc("Check Run", check_run_name)
    existing = {row.invoice_reference for row in (doc.items or [])}

    for inv_name in invoice_names:
        if inv_name in existing:
            continue

        # Block duplicate invoice use across runs
        duplicate_item = frappe.db.exists(
            "Check Run Item",
            {
                "invoice_reference": inv_name,
                "docstatus": ["<", 2],
                "print_status": ["!=", "Voided"]
            }
        )
        if duplicate_item:
            frappe.throw(
                _("Invoice {0} already exists in another Check Run Item.").format(inv_name)
            )

        # Block invoices that already have a submitted payment entry
        existing_pe_ref = frappe.db.exists(
            "Payment Entry Reference",
            {
                "reference_doctype": "Purchase Invoice",
                "reference_name": inv_name,
                "docstatus": 1
            }
        )
        if existing_pe_ref:
            frappe.throw(
                _("Invoice {0} already has a submitted Payment Entry.").format(inv_name)
            )

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


def _append_reference(pe, inv):
    pe.append("references", {
        "reference_doctype": "Purchase Invoice",
        "reference_name": inv.name,
        "bill_no": getattr(inv, "bill_no", None),
        "due_date": inv.due_date,
        "total_amount": inv.grand_total,
        "outstanding_amount": inv.outstanding_amount,
        "allocated_amount": inv.outstanding_amount,
    })


def _create_grouped_payment_entry(invoice_names: list[str], paid_from_account: str, payment_date: str, check_number: int):
    if not invoice_names:
        frappe.throw(_("No invoices provided for Payment Entry creation."))

    first_invoice = invoice_names[0]
    pe = get_payment_entry("Purchase Invoice", first_invoice)

    pe.posting_date = payment_date
    pe.paid_from = paid_from_account
    pe.reference_no = format_check_number(check_number)
    pe.reference_date = payment_date
    pe.mode_of_payment = "Check"

    # Replace references with all selected invoices for the supplier
    pe.references = []

    total_allocated = 0
    for inv_name in invoice_names:
        inv = frappe.get_doc("Purchase Invoice", inv_name)
        _append_reference(pe, inv)
        total_allocated += float(inv.outstanding_amount or 0)

    pe.paid_amount = total_allocated
    pe.received_amount = total_allocated

    pe.insert()
    pe.submit()
    return pe


@frappe.whitelist()
def assign_check_numbers(check_run_name: str):
    try:
        doc = frappe.get_doc("Check Run", check_run_name)

        if not doc.bank_account:
            frappe.throw(_("Paid From Account is required."))

        # Rows not yet assigned
        pending_rows = [
            row for row in (doc.items or [])
            if row.print_status != "Voided" and not row.check_number and not row.payment_entry
        ]

        if not pending_rows:
            return {
                "ok": True,
                "message": "No new invoices to assign.",
                "doc": doc.as_dict(),
            }

        # Group rows by supplier
        grouped = {}
        for row in pending_rows:
            grouped.setdefault(row.supplier, []).append(row)

        next_number = get_next_check_number()

        for supplier, rows in grouped.items():
            # Make sure proposed check number is unique
            while check_number_exists(next_number):
                next_number += 1

            invoice_names = [row.invoice_reference for row in rows]

            # Extra safety: do not create duplicate submitted payment entries
            for inv_name in invoice_names:
                existing_pe_ref = frappe.db.exists(
                    "Payment Entry Reference",
                    {
                        "reference_doctype": "Purchase Invoice",
                        "reference_name": inv_name,
                        "docstatus": 1
                    }
                )
                if existing_pe_ref:
                    frappe.throw(
                        _("Invoice {0} already has a submitted Payment Entry.").format(inv_name)
                    )

            pe = _create_grouped_payment_entry(
                invoice_names=invoice_names,
                paid_from_account=doc.bank_account,
                payment_date=doc.payment_date,
                check_number=next_number,
            )

            for idx, row in enumerate(rows, start=1):
                row.sequence_no = idx
                row.check_number = next_number
                row.payment_entry = pe.name
                row.print_status = "Pending"

            next_number += 1

        assigned_numbers = [int(row.check_number) for row in (doc.items or []) if row.check_number]
        doc.start_check_number = min(assigned_numbers) if assigned_numbers else 2
        doc.end_check_number = max(assigned_numbers) if assigned_numbers else 0
        doc.next_check_number = next_number
        doc.status = "Ready to Print"
        doc.save()

        return {
            "ok": True,
            "message": f"Assigned grouped checks through {format_check_number(doc.end_check_number)}",
            "doc": doc.as_dict(),
        }
    except Exception:
        frappe.log_error(
            title="Assign Check Numbers Failed",
            message=frappe.get_traceback()
        )
        raise


@frappe.whitelist()
def mark_printed(check_run_name: str):
    try:
        doc = frappe.get_doc("Check Run", check_run_name)
        changed = False

        for row in doc.items or []:
            if row.check_number and row.print_status == "Pending":
                row.print_status = "Printed"
                row.printed_on = now_datetime()
                row.printed_by = frappe.session.user
                changed = True

        if changed:
            doc.status = "Printed"
            doc.printed_on = now_datetime()
            doc.printed_by = frappe.session.user
            doc.save()

        return {
            "ok": True,
            "message": f"Marked Check Run {doc.name} as printed.",
            "doc": doc.as_dict(),
        }
    except Exception:
        frappe.log_error(
            title="Mark Printed Failed",
            message=frappe.get_traceback()
        )
        raise