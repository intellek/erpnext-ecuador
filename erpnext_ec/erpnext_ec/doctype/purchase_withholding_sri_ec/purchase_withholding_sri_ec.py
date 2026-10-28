# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from __future__ import unicode_literals

import datetime

import frappe
from frappe.model.document import Document
from erpnext.accounts.doctype.journal_entry.journal_entry import get_payment_entry
from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry

class PurchaseWithholdingSriEc(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	pass
	
	def set_status(self, update=False, status=None, update_modified=True):
		#if self.is_new():
		#	if self.get("amended_from"):
		#		self.status = "Draft"
		#	return

		self.status = "Submitted"

		if update:
			self.db_set("status", self.status, update_modified=update_modified)

	def on_submit(self):
		print('submit!!')
		print('Proceso de asientos contables')
		self.create_journal_entry()
	
	def set_purchase_withholding_supplier(self):
		print('set_purchase_withholding_supplier')
		pass

	def validate(self):
		print('validate_link')
		self.set_status()
		
		pass
	
	def get_posting_date(self):
		value = self.fechaEmision
		if isinstance(value, str) and "/" in value:
			return datetime.datetime.strptime(value.strip()[:10], "%d/%m/%Y").date()
		return frappe.utils.getdate(value)

	def is_sales_withholding(self):
		# The withheld subject is our own Company: the customer withheld us on a sale.
		tax_id = frappe.get_cached_value("Company", self.company, "tax_id")
		return bool(tax_id) and (self.identificacionSujetoRetenido or "").strip() == tax_id.strip()

	def find_sales_invoice(self, num_doc):
		digits = "".join(ch for ch in (num_doc or "") if ch.isdigit())
		if len(digits) != 15:
			frappe.throw(frappe._("Invalid numDocSustento {0}").format(num_doc))
		dashed = f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
		base = {"docstatus": 1, "company": self.company}
		for filters in (
			{"docidsri": ["in", [digits, dashed]]},
			{"estab": digits[:3], "ptoemi": digits[3:6], "secuencial": int(digits[6:])},
			{"remarks": ["like", f"%SRI {dashed}%"]},
		):
			found = frappe.get_all("Sales Invoice", filters={**base, **filters}, fields=["name", "customer", "debit_to"], limit=2)
			if len(found) == 1:
				return found[0]
			if len(found) > 1:
				frappe.throw(frappe._("More than one Sales Invoice matches {0}").format(dashed))
		frappe.throw(frappe._("Sales Invoice not found for numDocSustento {0}").format(num_doc))

	def append_sales_withholding_lines(self, journal_entry):
		# One credit line per Sales Invoice (debit_to, Customer, reference), debits on the RET accounts.
		credits = {}
		for itemTax in self.taxes:
			si = self.find_sales_invoice(itemTax.numDocSustento)
			credits.setdefault(si.name, {"si": si, "amount": 0})["amount"] += itemTax.valorRetenido
		journal_entry.pay_to_recd_from = next(iter(credits.values()))["si"].customer
		for itemTax in self.taxes:
			line = {
				'account': itemTax.codigoRetencion,
				'debit': itemTax.valorRetenido,
				'debit_in_account_currency': itemTax.valorRetenido,
				'credit': 0,
				'credit_in_account_currency': 0,
			}
			# Payable/Receivable accounts require a party whose Party Type matches the account type
			# (a Customer is rejected on a Payable RET account), so keep the Supplier of the purchase flow.
			account_type = frappe.get_cached_value("Account", itemTax.codigoRetencion, "account_type")
			if account_type == "Payable":
				customer = self.find_sales_invoice(itemTax.numDocSustento).customer
				line['party_type'] = 'Supplier'
				line['party'] = customer if frappe.db.exists("Supplier", customer) else self.purchase_withholding_supplier
			elif account_type == "Receivable":
				line['party_type'] = 'Customer'
				line['party'] = self.find_sales_invoice(itemTax.numDocSustento).customer
			journal_entry.append('accounts', line)
		for row in credits.values():
			journal_entry.append('accounts', {
				'account': row["si"].debit_to,
				'debit': 0,
				'debit_in_account_currency': 0,
				'credit': row["amount"],
				'credit_in_account_currency': row["amount"],
				'party_type': 'Customer',
				'party': row["si"].customer,
				'reference_type': 'Sales Invoice',
				'reference_name': row["si"].name,
			})

	def create_journal_entry(self):
        # Define the necessary data for the journal entry
		journal_entry = frappe.new_doc('Journal Entry')
		journal_entry.voucher_type = 'Journal Entry'
		journal_entry.company = self.company
		journal_entry.pay_to_recd_from = self.purchase_withholding_supplier
		journal_entry.posting_date = self.get_posting_date()
		journal_entry.user_remark = f'Journal Entry for Purchase Withholding {self.name}'
		journal_entry.remark = f'Journal Entry for Purchase Withholding {self.name}'
		journal_entry.title = f'AUTO-{self.name}'
		journal_entry.write_off_based_on = "Accounts Receivable"

		#journal_entry.bill_no = "Accounts Receivable"
		#journal_entry.bill_date = "Accounts Receivable"
		#journal_entry.due_date = "Accounts Receivable"

		if self.is_sales_withholding():
			self.append_sales_withholding_lines(journal_entry)
			journal_entry.save(ignore_permissions=True)
			journal_entry.submit()
			return

		account_for_withHolding = frappe.get_cached_value(
			"Company", self.company, "default_payable_account"
		)
		if not account_for_withHolding:
			frappe.throw(
				frappe._("Please set Default Payable Account for Company {0}").format(
					self.company
				)
			)

		total_credit_in_account_currency = 0
		#Linea de cuenta de Acreedores
		for itemTax in self.taxes:			
			# Add entries to the journal entry
			total_credit_in_account_currency += itemTax.valorRetenido
			
		journal_entry.append('accounts', {
            'account': account_for_withHolding,
			'account_type':'Payable',
			"against_account": self.purchase_withholding_supplier,
			"doctype": "Journal Entry Account",
			'debit': 0,
            'debit_in_account_currency': 0,
			'credit': total_credit_in_account_currency,
            'credit_in_account_currency': total_credit_in_account_currency,
            'party_type': 'Supplier',
            'party': self.purchase_withholding_supplier  # Replace with the actual supplier field
        })

		for itemTax in self.taxes:			
			# Add entries to the journal entry
			journal_entry.append(
				'accounts', {
					'account': itemTax.codigoRetencion,
					'debit': itemTax.valorRetenido,
            		'debit_in_account_currency': itemTax.valorRetenido,
					'credit': 0,
					'credit_in_account_currency': 0,
					'party_type': 'Supplier',
					'party': self.purchase_withholding_supplier
				})


        # Save and submit the journal entry
		journal_entry.save(ignore_permissions=True)
		journal_entry.submit()

	def before_save(self):
		print('before_save')
        # Acceder a los datos del detalle y realizar acciones en función de los cambios
        #for row in self.table_fieldname:
            # Realizar acciones necesarias en función de los valores de los campos en el detalle
        #    if row.my_fieldname:
                # Realizar alguna acción si el campo my_fieldname tiene un valor específico
        #        pass

# <infoTributaria>
# 		<ambiente>2</ambiente>
# 	    <tipoEmision>1</tipoEmision>
# 	    <razonSocial>COBOS MERO VICTOR HUGO</razonSocial>
# 	    <nombreComercial>COBOS MERO VICTOR HUGO</nombreComercial>
# 	    <ruc>1205019688001</ruc>
# 	    <claveAcceso>1105202107120501968800120010010000000252443850112</claveAcceso>
# 	    <codDoc>07</codDoc>
# 	    <estab>001</estab>
# 	    <ptoEmi>001</ptoEmi>
# 	    <secuencial>000000025</secuencial>
# 	    <dirMatriz>GUAYAS / GUAYAQUIL / TARQUI / SOLAR 33	</dirMatriz>		
# 		<agenteRetencion>1</agenteRetencion>		
#  </infoTributaria>
#  <infoCompRetencion>
# 	    <fechaEmision>11/05/2021</fechaEmision>
# 	    <obligadoContabilidad>SI</obligadoContabilidad>
# 	    <tipoIdentificacionSujetoRetenido>04</tipoIdentificacionSujetoRetenido>
# 	    <razonSocialSujetoRetenido>Raul Vinicio Borbor Torres</razonSocialSujetoRetenido>
# 	    <identificacionSujetoRetenido>0915885404001</identificacionSujetoRetenido>
# 	    <periodoFiscal>05/2021</periodoFiscal>
#  </infoCompRetencion>