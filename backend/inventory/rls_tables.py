"""The tables RLS covers, in one place.

Both the migration that creates the policies and the ``setup_rls_role`` command
that FORCEs them need the same list. Keeping it here means the two can never
disagree --- a table added to the policies but forgotten by the command would
silently stay unforced, which is the one failure mode that looks like success.

It lives outside the ``migrations`` package on purpose: Django's migration
loader treats every module in that package as a migration and refuses to start
when one has no ``Migration`` class.
"""

#: Tables carrying ``organization_id`` directly.
DIRECT = [
    "inventory_pharmacy",
    "inventory_orgmembership",
    "inventory_staffinvitation",
    "inventory_auditlog",
    "inventory_invoice",
]

#: Tables reaching their organisation through ``pharmacy_id``.
VIA_PHARMACY = [
    "inventory_medicine",
    "inventory_batch",
    "inventory_sale",
    "inventory_stockmovement",
    "inventory_pharmacyapikey",
    "inventory_playpurchaseevent",
    "inventory_subscription",
    "inventory_signuprequest",
]

#: Tables reaching it through a parent row.
INDIRECT = [
    "inventory_saleline",
    "inventory_saleallocation",
    "inventory_invoiceline",
    "inventory_orgmembership_scoped_pharmacies",
]

#: Every table the policies cover, including the organisation registry itself.
COVERED_TABLES = [*DIRECT, *VIA_PHARMACY, *INDIRECT, "inventory_organization"]
