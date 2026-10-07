"""Phase 5 (M6): Row-Level Security policies for every tenant-scoped table.

This migration is the database half of the tenancy rule. The application half
already exists --- every enterprise view resolves an ``OrgContext`` and filters
through it --- and this adds the same rule as a PostgreSQL policy, so a query
that forgets to scope still returns nothing.

The policy reads one session variable, ``app.current_org``, which the request
middleware sets with ``SET LOCAL`` inside a transaction. When the variable is
unset or empty the comparison is against ``NULL`` and is therefore never true,
so the default posture is *deny*: a connection with no tenant bound sees no
tenant rows at all.

Two deliberate choices, both explained in ``inventory/rls.py``:

* ``ENABLE`` rather than ``FORCE``. The policy applies to every role except the
  table owner, so a deployment whose application connects as the owner keeps
  working unchanged and RLS begins protecting the moment the application is
  moved onto the dedicated non-owner role that ``setup_rls_role`` creates.
  ``FORCE`` is applied by that command, once the move has actually happened.
* The catalog (``inventory_catalogmedicine``) is **not** covered. It is global
  reference data shared by every tenant, not tenant data, and filtering it would
  break the one thing it exists for.

The migration is a no-op on SQLite, which has no equivalent feature; the
``RunPython`` guards on the vendor so a developer's laptop and the test suite
are unaffected.
"""

from django.db import migrations

from inventory.rls_tables import DIRECT, INDIRECT, VIA_PHARMACY

#: The tenant expression every policy is built from. ``current_setting`` with
#: ``missing_ok=true`` returns NULL when the variable was never set and an empty
#: string when it was cleared; ``NULLIF`` collapses both to NULL, and a
#: comparison against NULL is never true --- which is exactly the deny-by-default
#: behaviour we want for an unbound connection.
ORG = "NULLIF(current_setting('app.current_org', true), '')::uuid"

#: The indirect tables and the subquery that reaches their organisation. The
#: chain is strictly downward --- pharmacy is the root and has a direct policy
#: --- so no policy can reference a table whose policy references it back, which
#: is what would make PostgreSQL report infinite recursion.
INDIRECT_EXPRESSIONS = {
    "inventory_saleline": f"sale_id IN (SELECT s.id FROM inventory_sale s JOIN inventory_pharmacy p ON p.id = s.pharmacy_id WHERE p.organization_id = {ORG})",
    "inventory_saleallocation": f"sale_line_id IN (SELECT sl.id FROM inventory_saleline sl JOIN inventory_sale s ON s.id = sl.sale_id JOIN inventory_pharmacy p ON p.id = s.pharmacy_id WHERE p.organization_id = {ORG})",
    "inventory_invoiceline": f"invoice_id IN (SELECT i.id FROM inventory_invoice i WHERE i.organization_id = {ORG})",
    "inventory_orgmembership_scoped_pharmacies": f"orgmembership_id IN (SELECT m.id FROM inventory_orgmembership m WHERE m.organization_id = {ORG})",
}


def _enable(cursor, table, expression):
    cursor.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
    cursor.execute(f"DROP POLICY IF EXISTS rls_{table} ON {table};")
    cursor.execute(f"CREATE POLICY rls_{table} ON {table} USING ({expression}) WITH CHECK ({expression});")


def apply_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    cursor = schema_editor.connection.cursor()

    for table in DIRECT:
        _enable(cursor, table, f"organization_id = {ORG}")

    for table in VIA_PHARMACY:
        _enable(cursor, table, f"pharmacy_id IN (SELECT id FROM inventory_pharmacy WHERE organization_id = {ORG})")

    for table in INDIRECT:
        _enable(cursor, table, INDIRECT_EXPRESSIONS[table])

    # The organisation table is the tenant registry rather than tenant data, so
    # it needs one extra allowance: a brand-new organisation is created by the
    # public signup flow *before* any tenant context exists, and a policy that
    # only permitted ``id = current_org`` would refuse that insert. Reading and
    # updating stay scoped to the caller's own row; only the insert is open,
    # which is the same action the public, rate-limited signup endpoint already
    # performs.
    cursor.execute("ALTER TABLE inventory_organization ENABLE ROW LEVEL SECURITY;")
    cursor.execute("DROP POLICY IF EXISTS rls_org_own ON inventory_organization;")
    cursor.execute(f"CREATE POLICY rls_org_own ON inventory_organization USING (id = {ORG}) WITH CHECK (id = {ORG});")
    cursor.execute("DROP POLICY IF EXISTS rls_org_signup ON inventory_organization;")
    cursor.execute("CREATE POLICY rls_org_signup ON inventory_organization FOR INSERT WITH CHECK (true);")


def drop_rls(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    cursor = schema_editor.connection.cursor()
    for table in [*DIRECT, *VIA_PHARMACY, *INDIRECT, "inventory_organization"]:
        cursor.execute(f"DROP POLICY IF EXISTS rls_{table} ON {table};")
        cursor.execute(f"DROP POLICY IF EXISTS rls_org_own ON {table};")
        cursor.execute(f"DROP POLICY IF EXISTS rls_org_signup ON {table};")
        cursor.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")


class Migration(migrations.Migration):
    dependencies = [
        ("inventory", "0009_invoice_invoiceline_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_rls, drop_rls),
    ]
