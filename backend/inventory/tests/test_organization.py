"""Phase 1 tests: multi-tenancy, role-based access, seats, and pricing.

These are the tests that matter most in the whole suite. Everything else guards
a feature; these guard the boundary between two customers, and a bug here does
not produce a wrong number --- it shows one pharmacy's stock to another.

Four invariants are asserted deliberately and repeatedly, because each was a
real design decision and each is easy to break later by accident:

1. **A foreign row answers 404, never 403.** A 403 confirms the row exists, and
   existence is itself information the caller must not have.
2. **A role gate is enforced on the server, not in the client.** A viewer is
   refused an admin action even when the request is hand-crafted.
3. **Scope beats role.** A manager whose membership is pinned to one branch can
   manage that branch and cannot see the others, even though a manager is
   ordinarily allowed to see the whole organisation.
4. **Seats are counted, not assumed.** The plan says how many people may be
   active at once, and the API refuses the one that would exceed it rather than
   silently over-billing.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from inventory import org_billing, org_services
from inventory.models import (
    AuditLog,
    Organization,
    OrgMembership,
    Pharmacy,
    StaffInvitation,
)

User = get_user_model()

PASSWORD = "sup3r-secret-pw"


def make_org(name="Dhaka Pharma Ltd", slug="dhaka-pharma", **kw):
    return Organization.objects.create(name=name, slug=slug, **kw)


def make_user(email, **extra):
    return User.objects.create_user(username=email, email=email, password=PASSWORD, **extra)


def login(email, password=PASSWORD):
    """A client authenticated the way the console does it.

    Going through the real login endpoint rather than ``force_authenticate`` is
    deliberate: the login response is what carries ``org_id`` and ``role`` into
    the token, so a test that skipped it would not notice those claims breaking.
    """
    client = APIClient()
    response = client.post("/api/v1/auth/token/", {"username": email, "password": password}, format="json")
    assert response.status_code == 200, response.content
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.json()['access']}")
    return client


class OrgTestBase(TestCase):
    def setUp(self):
        self.org = make_org()
        self.owner_user = make_user("owner@dhaka.test")
        self.owner = OrgMembership.objects.create(organization=self.org, user=self.owner_user, role=OrgMembership.Role.OWNER)
        self.main_branch = Pharmacy.objects.create(name="Dhanmondi", organization=self.org, branch_code="DH-01")
        self.second_branch = Pharmacy.objects.create(name="Mirpur", organization=self.org, branch_code="MP-02")
        self.owner.scoped_pharmacies.add(self.main_branch, self.second_branch)

        self.rival_org = make_org(name="Rival Chemists", slug="rival-chemists")
        self.rival_branch = Pharmacy.objects.create(name="Rival Main", organization=self.rival_org)
        self.rival_user = make_user("rival@rival.test")
        OrgMembership.objects.create(organization=self.rival_org, user=self.rival_user, role=OrgMembership.Role.OWNER)

        self.client = login("owner@dhaka.test")

    def member(self, email, role, *branches):
        """A user with a membership in the fixture organisation."""
        user = make_user(email)
        membership = OrgMembership.objects.create(organization=self.org, user=user, role=role)
        if branches:
            membership.scoped_pharmacies.add(*branches)
        return user, membership


class TokenTests(OrgTestBase):
    def test_the_token_carries_the_organisation_and_the_role(self):
        import base64
        import json as jsonlib

        response = APIClient().post("/api/v1/auth/token/", {"username": "owner@dhaka.test", "password": PASSWORD}, format="json")
        payload = response.json()["access"].split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = jsonlib.loads(base64.urlsafe_b64decode(payload))
        self.assertEqual(claims["org_id"], str(self.org.pk))
        self.assertEqual(claims["role"], OrgMembership.Role.OWNER)

    def test_the_login_body_is_shaped_for_the_console(self):
        response = APIClient().post("/api/v1/auth/token/", {"username": "owner@dhaka.test", "password": PASSWORD}, format="json")
        body = response.json()
        self.assertEqual(body["organisation"]["role"], OrgMembership.Role.OWNER)
        self.assertEqual(body["organisation"]["locale"], "bn")
        self.assertEqual(body["user"]["email"], "owner@dhaka.test")

    def test_a_user_with_no_membership_still_receives_a_token(self):
        """Otherwise the invitation-acceptance screen is unreachable."""
        make_user("outsider@nowhere.test")
        response = APIClient().post("/api/v1/auth/token/", {"username": "outsider@nowhere.test", "password": PASSWORD}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["organisation"])

    def test_a_successful_login_is_audited(self):
        AuditLog.objects.all().delete()
        APIClient().post("/api/v1/auth/token/", {"username": "owner@dhaka.test", "password": PASSWORD}, format="json")
        entry = AuditLog.objects.filter(action=AuditLog.Action.LOGIN).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.organization, self.org)

    def test_an_anonymous_request_is_refused_with_401(self):
        response = APIClient().get("/api/v1/org/")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "not_authenticated")


class OrganisationScopeTests(OrgTestBase):
    def test_the_summary_is_scoped_to_the_callers_organisation(self):
        body = self.client.get("/api/v1/org/").json()
        self.assertEqual(body["id"], str(self.org.pk))
        self.assertEqual(body["slug"], "dhaka-pharma")

    def test_the_summary_never_names_another_tenant(self):
        body = self.client.get("/api/v1/org/").json()
        self.assertNotIn("rival", str(body).lower())

    def test_a_viewer_may_read_the_summary(self):
        """Everyone needs the currency and timezone to render a price or a date."""
        user, _ = self.member("viewer-read@dhaka.test", OrgMembership.Role.VIEWER)
        self.assertEqual(login(user.username).get("/api/v1/org/").status_code, 200)

    def test_rename_requires_admin_or_above(self):
        user, _ = self.member("staff-rename@dhaka.test", OrgMembership.Role.STAFF)
        response = login(user.username).patch("/api/v1/org/", {"name": "Nope"}, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "permission_denied")
        self.org.refresh_from_db()
        self.assertNotEqual(self.org.name, "Nope")

    def test_an_owner_can_rename_and_the_change_is_audited(self):
        response = self.client.patch("/api/v1/org/", {"name": "Dhaka Pharma Group"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.name, "Dhaka Pharma Group")
        entry = AuditLog.objects.filter(action=AuditLog.Action.UPDATE).first()
        self.assertIsNotNone(entry)
        self.assertIn("name", entry.changes)

    def test_a_vat_number_is_validated_not_merely_stored(self):
        self.assertEqual(self.client.patch("/api/v1/org/", {"bin": "abc"}, format="json").status_code, 400)
        self.assertEqual(self.client.patch("/api/v1/org/", {"bin": "12345"}, format="json").status_code, 400)
        accepted = self.client.patch("/api/v1/org/", {"bin": "001234567-0102"}, format="json")
        self.assertEqual(accepted.status_code, 200, accepted.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.bin, "0012345670102", "dashes and spaces are stripped so the invoice prints cleanly")
        # Both the current 13-digit BIN and the legacy 9-digit form are accepted;
        # a 12-digit number is not, because it would silently pass a typo of the
        # 13-digit format rather than being rejected as malformed.
        self.assertEqual(self.client.patch("/api/v1/org/", {"bin": "123456789"}, format="json").status_code, 200)
        self.assertEqual(self.client.patch("/api/v1/org/", {"bin": "123456789012"}, format="json").status_code, 400)

    def test_commercial_terms_cannot_be_self_served(self):
        """Plan and allowance are ours to change, not the tenant's."""
        response = self.client.patch("/api/v1/org/", {"plan": Organization.Plan.ENTERPRISE, "branch_allowance": 99}, format="json")
        # The field is simply not in the update serializer, so it is ignored.
        self.assertEqual(response.status_code, 200)
        self.org.refresh_from_db()
        self.assertNotEqual(self.org.plan, Organization.Plan.ENTERPRISE)
        self.assertNotEqual(self.org.branch_allowance, 99)

    def test_a_brand_colour_cannot_inject_css(self):
        response = self.client.patch("/api/v1/org/", {"brand_color": "red; background:url(x)"}, format="json")
        self.assertEqual(response.status_code, 400)


class BranchIsolationTests(OrgTestBase):
    def test_branches_are_listed_only_for_the_callers_org(self):
        body = self.client.get("/api/v1/org/branches/").json()
        self.assertEqual({row["name"] for row in body["results"]}, {"Dhanmondi", "Mirpur"})

    def test_a_rival_branch_answers_404_not_403(self):
        response = self.client.get(f"/api/v1/org/branches/{self.rival_branch.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_a_viewer_cannot_open_a_branch(self):
        user, _ = self.member("viewer-branch@dhaka.test", OrgMembership.Role.VIEWER)
        response = login(user.username).post("/api/v1/org/branches/", {"name": "New"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_open_a_branch_and_the_key_is_returned_once(self):
        response = self.client.post("/api/v1/org/branches/", {"name": "Uttara", "branch_code": "UT-03"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        branch = Pharmacy.objects.get(pk=body["id"])
        self.assertEqual(branch.organization, self.org)
        self.assertTrue(branch.api_keys.exists(), "a new branch needs a device key to be usable")
        self.assertIn("api_key", body)
        self.assertNotIn(body["api_key"], str(branch.api_keys.first().key_hash))

    def test_two_branches_cannot_share_a_code_within_one_organisation(self):
        response = self.client.post("/api/v1/org/branches/", {"name": "Clash", "branch_code": "DH-01"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_the_same_branch_code_is_fine_across_organisations(self):
        response = self.client.post("/api/v1/org/branches/", {"name": "Head Office", "branch_code": "01"}, format="json")
        self.assertEqual(response.status_code, 201)

    def test_a_branch_code_cannot_break_a_csv_export(self):
        response = self.client.post("/api/v1/org/branches/", {"name": "Bad", "branch_code": "A,1"}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_scope_beats_role_for_a_pinned_manager(self):
        user, _ = self.member("manager@dhaka.test", OrgMembership.Role.MANAGER, self.main_branch)
        client = login(user.username)
        body = client.get("/api/v1/org/branches/").json()
        self.assertEqual({row["name"] for row in body["results"]}, {"Dhanmondi"}, "scope was not applied")
        self.assertEqual(client.get(f"/api/v1/org/branches/{self.main_branch.pk}/").status_code, 200)
        self.assertEqual(client.get(f"/api/v1/org/branches/{self.second_branch.pk}/").status_code, 404)

    def test_closing_a_branch_deactivates_it_rather_than_deleting_it(self):
        """Deleting would cascade away the sales history an accountant needs."""
        response = self.client.delete(f"/api/v1/org/branches/{self.second_branch.pk}/")
        self.assertEqual(response.status_code, 204)
        self.second_branch.refresh_from_db()
        self.assertFalse(self.second_branch.is_active)
        self.assertEqual(Pharmacy.objects.filter(pk=self.second_branch.pk).count(), 1)

    def test_a_manager_may_edit_a_branch(self):
        user, _ = self.member("manager-edit@dhaka.test", OrgMembership.Role.MANAGER, self.main_branch)
        response = login(user.username).patch(f"/api/v1/org/branches/{self.main_branch.pk}/", {"phone": "01712345678"}, format="json")
        self.assertEqual(response.status_code, 200, response.content)


class MemberAndSeatTests(OrgTestBase):
    def test_the_members_list_shows_the_team(self):
        body = self.client.get("/api/v1/org/members/").json()
        self.assertEqual(body["results"][0]["email"], "owner@dhaka.test")

    def test_seat_status_reports_utilisation(self):
        body = self.client.get("/api/v1/org/seats/").json()
        self.assertEqual(body["used"], 1)
        self.assertEqual(body["limit"], org_billing.included_seats(self.org))
        self.assertFalse(body["is_full"])

    def test_a_viewer_cannot_change_a_role(self):
        user, membership = self.member("viewer-role@dhaka.test", OrgMembership.Role.VIEWER)
        response = login(user.username).patch(f"/api/v1/org/members/{membership.pk}/", {"role": "admin"}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_an_admin_can_promote_a_member_and_it_is_audited(self):
        _, target = self.member("promote-me@dhaka.test", OrgMembership.Role.VIEWER)
        response = self.client.patch(f"/api/v1/org/members/{target.pk}/", {"role": OrgMembership.Role.MANAGER}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        target.refresh_from_db()
        self.assertEqual(target.role, OrgMembership.Role.MANAGER)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.ROLE_CHANGED).exists())

    def test_an_admin_cannot_mint_another_owner(self):
        """Privilege escalation: an admin must not be able to outrank itself."""
        admin_user, _ = self.member("admin-esc@dhaka.test", OrgMembership.Role.ADMIN)
        _, target = self.member("wannabe-owner@dhaka.test", OrgMembership.Role.STAFF)
        response = login(admin_user.username).patch(f"/api/v1/org/members/{target.pk}/", {"role": OrgMembership.Role.OWNER}, format="json")
        self.assertEqual(response.status_code, 400)
        target.refresh_from_db()
        self.assertNotEqual(target.role, OrgMembership.Role.OWNER)

    def test_the_last_owner_cannot_be_demoted(self):
        response = self.client.patch(f"/api/v1/org/members/{self.owner.pk}/", {"role": OrgMembership.Role.ADMIN}, format="json")
        self.assertEqual(response.status_code, 409)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.role, OrgMembership.Role.OWNER)

    def test_an_admin_cannot_remove_itself(self):
        """The mistake that locks the only admin out of their own console."""
        admin_user, admin = self.member("admin-self@dhaka.test", OrgMembership.Role.ADMIN)
        response = login(admin_user.username).delete(f"/api/v1/org/members/{admin.pk}/")
        self.assertEqual(response.status_code, 409)

    def test_removing_a_member_deactivates_rather_than_deletes(self):
        _, target = self.member("leaver@dhaka.test", OrgMembership.Role.STAFF)
        response = self.client.delete(f"/api/v1/org/members/{target.pk}/")
        self.assertEqual(response.status_code, 204)
        self.assertFalse(OrgMembership.objects.get(pk=target.pk).is_active)

    def test_the_last_owner_cannot_be_removed(self):
        _, second_owner = self.member("owner2@dhaka.test", OrgMembership.Role.OWNER)
        # With two owners either may step down...
        self.assertEqual(self.client.delete(f"/api/v1/org/members/{second_owner.pk}/").status_code, 204)
        # ...and then the remaining one may not.
        response = self.client.delete(f"/api/v1/org/members/{self.owner.pk}/")
        self.assertEqual(response.status_code, 409)
        self.assertIn("owner", response.json()["error"]["detail"].lower())


class SeatLimitTests(OrgTestBase):
    """Seats are a billing display now — they never gate an invitation.

    DEPRECATED: these tests used to pin the server's 402 refusal when the
    plan's seat ceiling was reached (``seat_limit_reached``). Rakho is free for
    everyone, so they pin the opposite today: whatever the ceiling says, the
    server creates the invitation (and accepts the membership) without asking
    anyone to buy a seat. The ceiling itself still exists --- ``org_billing``
    and the quote/invoice screens read it unchanged.
    """

    def _set_ceiling(self, ceiling):
        """Pin the derived seat ceiling to an exact figure."""
        self.org.pharmacies.update(is_active=False)
        self.org.seat_addon_count = ceiling
        self.org.save(update_fields=["seat_addon_count"])
        with override_settings(INCLUDED_SEATS_PER_BRANCH=0):
            self.assertEqual(org_billing.included_seats(self.org), ceiling)

    def test_an_invitation_beyond_the_seat_ceiling_is_created(self):
        """No 402, no "buy a seat": the single occupied seat does not matter."""
        self._set_ceiling(1)  # the owner already occupies the single seat
        response = self.client.post("/api/v1/org/invitations/", {"email": "third@dhaka.test", "role": "staff"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(StaffInvitation.objects.filter(email="third@dhaka.test").exists())

    def test_pending_invitations_do_not_consume_a_shared_ceiling(self):
        """Two invites into a two-seat ceiling used to end in 402 on the
        second; now both are simply created."""
        self._set_ceiling(2)  # owner + one more
        first = self.client.post("/api/v1/org/invitations/", {"email": "first@dhaka.test", "role": "staff"}, format="json")
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post("/api/v1/org/invitations/", {"email": "second@dhaka.test", "role": "staff"}, format="json")
        self.assertEqual(second.status_code, 201, second.content)
        self.assertEqual(StaffInvitation.objects.filter(organization=self.org).count(), 2)

    def test_an_invitation_within_the_limit_is_created(self):
        response = self.client.post("/api/v1/org/invitations/", {"email": "colleague@dhaka.test", "role": "staff"}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        self.assertTrue(StaffInvitation.objects.filter(organization=self.org).exists())
        self.assertIn("token", body, "the raw token must be returned, because only its hash is stored")

    def test_a_duplicate_pending_invitation_is_refused(self):
        self.client.post("/api/v1/org/invitations/", {"email": "dup@dhaka.test", "role": "staff"}, format="json")
        second = self.client.post("/api/v1/org/invitations/", {"email": "dup@dhaka.test", "role": "staff"}, format="json")
        self.assertIn(second.status_code, (400, 409))

    def test_inviting_an_existing_member_is_refused(self):
        """A member does not need an invitation, and issuing one wastes a seat
        and confuses the team list with a duplicate."""
        response = self.client.post("/api/v1/org/invitations/", {"email": "owner@dhaka.test", "role": "staff"}, format="json")
        self.assertIn(response.status_code, (400, 409))

    def test_a_seat_freed_by_revoking_can_be_reused(self):
        """The reservation is released, not merely hidden: an owner who revokes
        by mistake must be able to invite someone else straight away."""
        self._set_ceiling(2)
        invite = self.client.post("/api/v1/org/invitations/", {"email": "first@dhaka.test", "role": "staff"}, format="json").json()
        self.assertEqual(self.client.delete("/api/v1/org/invitations/{}/".format(invite["id"])).status_code, 204)
        retry = self.client.post("/api/v1/org/invitations/", {"email": "replacement@dhaka.test", "role": "staff"}, format="json")
        self.assertEqual(retry.status_code, 201, retry.content)


class InvitationFlowTests(OrgTestBase):
    def invite(self, email="newhire@dhaka.test", role="staff"):
        response = self.client.post("/api/v1/org/invitations/", {"email": email, "role": role}, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def accept(self, email, token, accept=True):
        make_user(email) if not User.objects.filter(username=email).exists() else None
        client = login(email)
        return client.post("/api/v1/org/invitations/accept/", {"token": token, "accept": accept}, format="json")

    def test_accepting_creates_a_membership(self):
        invite = self.invite()
        response = self.accept("newhire@dhaka.test", invite["token"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(OrgMembership.objects.filter(organization=self.org, user__email="newhire@dhaka.test").exists())

    def test_a_token_is_single_use(self):
        invite = self.invite()
        self.assertEqual(self.accept("newhire@dhaka.test", invite["token"]).status_code, 200)
        self.assertEqual(self.accept("newhire@dhaka.test", invite["token"]).status_code, 410)

    def test_a_bogus_token_is_refused(self):
        response = self.accept("stranger@dhaka.test", "x" * 40)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "invalid_invitation")

    def test_an_anonymous_caller_is_told_to_sign_in_first(self):
        invite = self.invite()
        response = APIClient().post("/api/v1/org/invitations/accept/", {"token": invite["token"]}, format="json")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["error"]["code"], "authentication_required")

    def test_a_forwarded_link_does_not_admit_the_wrong_person(self):
        """The invitation names a person, not whoever holds the link."""
        invite = self.invite("intended@dhaka.test")
        response = self.accept("someone-else@dhaka.test", invite["token"])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"]["code"], "invitation_for_another_address")

    def test_declining_releases_the_seat_without_creating_a_membership(self):
        invite = self.invite("nothanks@dhaka.test")
        response = self.accept("nothanks@dhaka.test", invite["token"], accept=False)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "declined")
        self.assertFalse(OrgMembership.objects.filter(organization=self.org, user__email="nothanks@dhaka.test").exists())
        self.assertFalse(org_services.pending_invitation_count(self.org))

    def test_revoking_makes_the_token_useless(self):
        invite = self.invite("revoked@dhaka.test")
        self.assertEqual(self.client.delete("/api/v1/org/invitations/{}/".format(invite["id"])).status_code, 204)
        self.assertEqual(self.accept("revoked@dhaka.test", invite["token"]).status_code, 410)

    def test_only_the_hash_of_the_token_is_stored(self):
        invite = self.invite("hashed@dhaka.test")
        stored = StaffInvitation.objects.get(pk=invite["id"])
        self.assertNotIn(invite["token"], stored.token_hash)
        self.assertEqual(len(stored.token_hash), 64)


class InvitationJoinPageTests(OrgTestBase):
    """The email's link is /console/join?token=... --- the page and its two
    public endpoints are what made that link dead for two years: no route
    existed, so every invitation email pointed at a 404."""

    def invite(self, email="newhire@dhaka.test", role="staff"):
        response = self.client.post("/api/v1/org/invitations/", {"email": email, "role": role}, format="json")
        assert response.status_code == 201, response.content
        return response.json()

    def accept(self, email, token, accept=True):
        make_user(email) if not User.objects.filter(username=email).exists() else None
        client = login(email)
        return client.post("/api/v1/org/invitations/accept/", {"token": token, "accept": accept}, format="json")

    def test_the_join_page_renders_with_the_token_embedded_safely(self):
        invite = self.invite()
        response = self.client.get("/console/join", {"token": invite["token"]})
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"var TOKEN={json.dumps(invite['token'])}", response.content.decode())

    def test_a_crafted_token_cannot_break_out_of_the_join_script(self):
        response = self.client.get("/console/join", {"token": "</script><script>alert(1)</script>"})
        html = response.content.decode()
        self.assertEqual(html.count("</script>"), 1, "the only closing tag must be the page's own")

    def test_robots_blocks_the_console_join_page(self):
        body = __import__("config.urls", fromlist=["robots_txt"]).robots_txt(RequestFactory().get("/robots.txt")).content.decode()
        self.assertIn("Disallow: /console/", body)

    def test_the_info_endpoint_describes_the_invitation_without_spending_it(self):
        invite = self.invite(role="manager")
        response = APIClient().get(f"/api/v1/org/invitations/info/?token={invite['token']}")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["organisation"], self.org.display_name)
        self.assertEqual(body["role"], "manager")
        # Reading twice must not consume the single-use token.
        self.assertEqual(APIClient().get(f"/api/v1/org/invitations/info/?token={invite['token']}").status_code, 200)
        # And the invitation still accepts afterwards.
        self.assertEqual(self.accept("newhire@dhaka.test", invite["token"]).status_code, 200)

    def test_the_info_endpoint_masks_the_invited_address(self):
        """The info endpoint is open, so the full address must not be revealed
        to whoever holds the link --- only enough to recognise it."""
        invite = self.invite("person@dhaka.test")
        body = APIClient().get(f"/api/v1/org/invitations/info/?token={invite['token']}").json()
        self.assertNotIn("person@dhaka.test", json.dumps(body))
        self.assertIn("@dhaka.test", body["email_masked"])

    def test_an_unknown_or_spent_token_is_an_uninformative_404(self):
        self.invite("gone@dhaka.test")
        response = APIClient().get("/api/v1/org/invitations/info/?token=inv_not-a-real-token")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "invalid_invitation")

    def test_registration_creates_the_account_and_accepts_in_one_step(self):
        invite = self.invite()
        response = APIClient().post(
            "/api/v1/org/invitations/register/",
            {"token": invite["token"], "username": "newhire", "password": "a-thoroughly-long-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        user = User.objects.get(email="newhire@dhaka.test")
        self.assertEqual(user.username, "newhire")
        self.assertTrue(OrgMembership.objects.filter(organization=self.org, user=user, role=OrgMembership.Role.STAFF).exists())
        # The token is spent: a second registration attempt finds nothing.
        again = APIClient().post(
            "/api/v1/org/invitations/register/",
            {"token": invite["token"], "username": "other", "password": "a-thoroughly-long-password"},
            format="json",
        )
        self.assertEqual(again.status_code, 404)

    def test_registration_cannot_claim_the_seat_for_a_different_address(self):
        """The account's email is the invitation's email --- the form never
        asks, so a seat can only be claimed by the recipient."""
        invite = self.invite("intended@dhaka.test")
        response = APIClient().post(
            "/api/v1/org/invitations/register/",
            {"token": invite["token"], "username": "attacker", "password": "a-thoroughly-long-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(User.objects.get(username="attacker").email, "intended@dhaka.test")

    def test_registration_refuses_a_weak_password_with_the_site_validators(self):
        invite = self.invite()
        for weak in ("short", "123456789012345", "password123456"):
            with self.subTest(password=weak):
                response = APIClient().post(
                    "/api/v1/org/invitations/register/",
                    {"token": invite["token"], "username": f"u{weak[:4]}", "password": weak},
                    format="json",
                )
                self.assertEqual(response.status_code, 400)
                self.assertIn("password", response.json()["error"]["fields"])
        # And nothing was created: the invitation is still pending.
        self.assertTrue(StaffInvitation.objects.get(pk=invite["id"]).is_actionable)

    def test_registration_redirects_an_existing_account_to_sign_in(self):
        invite = self.invite("existing@dhaka.test")
        make_user("existing@dhaka.test")
        response = APIClient().post(
            "/api/v1/org/invitations/register/",
            {"token": invite["token"], "username": "some-other-name", "password": "a-thoroughly-long-password"},
            format="json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "account_exists")


class PricingTests(OrgTestBase):
    """M5: a base price per branch, plus a per-seat add-on."""

    def test_starter_is_charged_per_branch(self):
        quote = org_billing.quote(self.org)
        self.assertEqual(quote.currency, "BDT")
        self.assertEqual(len(quote.branches), 2)
        expected = org_billing.BRANCH_PRICE * quote.billable_branch_count
        self.assertEqual(sum(line.amount for line in quote.branches), expected)

    def test_the_first_seat_allowance_is_included(self):
        """A one-person shop must not be charged extra for being one person."""
        quote = org_billing.quote(self.org)
        self.assertEqual(quote.seats.active_seats, 1)
        self.assertEqual(quote.seats.billable_seats, 0)
        self.assertEqual(quote.seats.amount, 0)

    def test_extra_seats_are_billed_above_the_allowance(self):
        covered = org_billing.included_seats(self.org)
        for index in range(covered):
            self.member(f"extra{index}@dhaka.test", OrgMembership.Role.STAFF)
        quote = org_billing.quote(self.org)
        self.assertEqual(quote.seats.billable_seats, 1)
        self.assertEqual(quote.seats.amount, org_billing.SEAT_PRICE)

    def test_the_total_is_branches_plus_seats_plus_vat(self):
        covered = org_billing.included_seats(self.org)
        for index in range(covered):
            self.member(f"sitter{index}@dhaka.test", OrgMembership.Role.STAFF)
        quote = org_billing.quote(self.org)
        self.assertEqual(quote.total, quote.subtotal + quote.vat_amount)
        self.assertEqual(quote.subtotal, sum(line.amount for line in quote.branches) + quote.seats.amount)

    def test_vat_is_whole_taka(self):
        quote = org_billing.quote(self.org)
        self.assertIsInstance(quote.vat_amount, int)
        self.assertIsInstance(quote.total, int)

    def test_an_empty_branch_list_prices_no_branch_at_all(self):
        self.org.pharmacies.update(is_active=False)
        quote = org_billing.quote(self.org)
        self.assertEqual(quote.billable_branch_count, 0)
        self.assertEqual(sum(line.amount for line in quote.branches), 0)

    def test_the_quote_endpoint_requires_admin(self):
        user, _ = self.member("viewer-quote@dhaka.test", OrgMembership.Role.VIEWER)
        self.assertEqual(login(user.username).get("/api/v1/org/quote/").status_code, 403)

    def test_the_quote_endpoint_returns_the_itemised_bill(self):
        body = self.client.get("/api/v1/org/quote/").json()
        self.assertIn("branches", body)
        self.assertIn("seats", body)
        self.assertIn("total", body)

    def test_a_seat_addon_raises_the_ceiling_and_is_audited(self):
        response = self.client.post("/api/v1/org/seat-addon/", {"count": 3}, format="json")
        self.assertEqual(response.status_code, 200, response.content)
        self.org.refresh_from_db()
        self.assertEqual(self.org.seat_addon_count, 3)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PLAN_CHANGED).exists())

    def test_a_seat_addon_is_owner_only(self):
        user, _ = self.member("admin-addon@dhaka.test", OrgMembership.Role.ADMIN)
        response = login(user.username).post("/api/v1/org/seat-addon/", {"count": 2}, format="json")
        self.assertEqual(response.status_code, 403)

    def test_an_absurd_seat_request_is_refused(self):
        response = self.client.post("/api/v1/org/seat-addon/", {"count": 10_000}, format="json")
        self.assertEqual(response.status_code, 400)

    def test_a_seat_addon_cannot_drop_below_the_people_in_use(self):
        self.member("in-use-1@dhaka.test", OrgMembership.Role.STAFF)
        self.member("in-use-2@dhaka.test", OrgMembership.Role.STAFF)
        response = self.client.post("/api/v1/org/seat-addon/", {"count": 1}, format="json")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "below_active_seats")


class AuditTrailTests(OrgTestBase):
    def test_a_branch_creation_is_audited_with_the_actor(self):
        self.client.post("/api/v1/org/branches/", {"name": "Audited"}, format="json")
        entry = AuditLog.objects.filter(action=AuditLog.Action.CREATE).first()
        self.assertIsNotNone(entry)
        self.assertEqual(entry.actor_email, "owner@dhaka.test")
        self.assertEqual(entry.organization, self.org)

    def test_the_trail_is_readable_only_by_an_admin(self):
        user, _ = self.member("manager-audit@dhaka.test", OrgMembership.Role.MANAGER)
        self.assertEqual(login(user.username).get("/api/v1/org/audit/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/org/audit/").status_code, 200)

    def test_the_trail_never_shows_another_tenant(self):
        other = make_org(name="Outsider", slug="outsider")
        AuditLog.objects.create(organization=other, action=AuditLog.Action.UPDATE)
        body = self.client.get("/api/v1/org/audit/").json()
        self.assertTrue(all(row["id"] != str(AuditLog.objects.get(organization=other).pk) for row in body["results"]))

    def test_the_trail_can_be_filtered_by_action(self):
        self.client.post("/api/v1/org/branches/", {"name": "Filtered"}, format="json")
        body = self.client.get("/api/v1/org/audit/?action=create").json()
        self.assertTrue(body["results"])
        self.assertTrue(all(row["action"] == "create" for row in body["results"]))

    def test_an_entry_cannot_be_edited(self):
        """A trail that can be rewritten is not a trail."""
        entry = AuditLog.objects.create(organization=self.org, action=AuditLog.Action.UPDATE)
        entry.action = AuditLog.Action.DELETE
        with self.assertRaises(ValueError):
            entry.save()

    def test_an_entry_cannot_be_deleted(self):
        entry = AuditLog.objects.create(organization=self.org, action=AuditLog.Action.UPDATE)
        with self.assertRaises(ValueError):
            entry.delete()


class ProvisioningTests(TestCase):
    def test_signup_creates_a_tenant_with_the_shop_as_its_first_branch(self):
        pharmacy = Pharmacy.objects.create(name="Signup Pharmacy")
        organization, owner = org_services.provision_organization_for_signup(pharmacy=pharmacy, owner_name="Karim", contact_phone="01712345678")
        self.assertEqual(organization.pharmacies.count(), 1)
        self.assertIsNone(owner, "no console account is invented on the customer's behalf")
        pharmacy.refresh_from_db()
        self.assertEqual(pharmacy.organization, organization)
        self.assertTrue(organization.slug, "a slug is needed for console URLs")
        self.assertEqual(organization.plan, Organization.Plan.FREE)

    def test_slugs_stay_unique_across_organisations(self):
        first = Pharmacy.objects.create(name="Same Name")
        second = Pharmacy.objects.create(name="Same Name")
        org_a, _ = org_services.provision_organization_for_signup(pharmacy=first)
        org_b, _ = org_services.provision_organization_for_signup(pharmacy=second)
        self.assertNotEqual(org_a.slug, org_b.slug)

    def test_provisioning_is_safe_to_repeat(self):
        """A signup retried after a timeout must not create a second tenant."""
        pharmacy = Pharmacy.objects.create(name="Retry Pharmacy")
        first, _ = org_services.provision_organization_for_signup(pharmacy=pharmacy)
        second, _ = org_services.provision_organization_for_signup(pharmacy=pharmacy)
        self.assertEqual(first.pk, second.pk)
        self.assertEqual(Organization.objects.count(), 1)
