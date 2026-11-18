import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from api import models as m
from api import services as svc


class TeamAccessApiTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.owner = user_model.objects.create(username="owner", email="owner@example.com")
        self.member = user_model.objects.create(username="member", email="member@example.com")
        self.other = user_model.objects.create(username="other", email="other@example.com")
        self.owner_token = svc.issue_token(self.owner)
        self.member_token = svc.issue_token(self.member)
        self.other_token = svc.issue_token(self.other)
        self.owner_settings = m.UserSettings.objects.create(
            owner=self.owner, business_name="Keynes Electronics",
        )
        m.UserSettings.objects.create(owner=self.member, business_name="Member business")
        m.UserSettings.objects.create(owner=self.other)

    def headers(self, token, workspace=None):
        headers = {"HTTP_AUTHORIZATION": "Bearer " + token}
        if workspace is not None:
            headers["HTTP_X_NEXA_WORKSPACE"] = str(workspace)
        return headers

    def post(self, url, data, headers):
        return self.client.post(url, data, content_type="application/json", **headers)

    def permissions(self, **grants):
        permissions = m.default_team_permissions()
        for scope, actions in grants.items():
            permissions[scope] = actions
        return permissions

    def test_workspace_selection_enforces_permissions_and_never_falls_back(self):
        self.owner_settings.team_sharing_enabled = True
        self.owner_settings.save(update_fields=["team_sharing_enabled"])
        product = m.Product.objects.create(
            owner=self.owner, name="Earbuds", price="24.00", cost="14.00",
        )
        m.TeamMembership.objects.create(
            owner=self.owner, member=self.member,
            permissions=self.permissions(inventory={"view": True, "edit": False}),
        )

        response = self.client.get(
            "/api/products/", **self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [product.pk])

        response = self.post(
            "/api/products/",
            {"name": "New product", "price": "10", "cost": "5"},
            self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(m.Product.objects.filter(owner=self.owner, name="New product").exists())

        response = self.client.get(
            "/api/products/", **self.headers(self.member_token, self.other.pk),
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.get(
            "/api/me/", **self.headers(self.member_token, self.other.pk),
        )
        self.assertEqual(response.status_code, 403)

        own_product = self.post(
            "/api/products/",
            {"name": "Own product", "price": "10", "cost": "5"},
            self.headers(self.member_token),
        )
        self.assertEqual(own_product.status_code, 201)
        self.assertEqual(m.Product.objects.filter(owner=self.member).count(), 1)

    @patch("api.team_access.svc._send_email", return_value=1)
    @patch("api.team_access.svc.email_delivery_configured", return_value=True)
    def test_invite_acceptance_keeps_personal_data_separate(self, email_configured, send_email):
        self.owner_settings.team_sharing_enabled = True
        self.owner_settings.email_verified = True
        self.owner_settings.save(update_fields=["team_sharing_enabled", "email_verified"])
        owner_product = m.Product.objects.create(
            owner=self.owner, name="Owner product", price="20.00", cost="10.00",
        )
        member_product = m.Product.objects.create(
            owner=self.member, name="Personal product", price="12.00", cost="6.00",
        )
        permissions = self.permissions(
            sales={"view": True, "edit": False},
            inventory={"view": True, "edit": False},
        )
        response = self.post(
            "/api/team/invitations/",
            {
                "email": self.member.email,
                "permissions": permissions,
                "can_manage_members": False,
            },
            self.headers(self.owner_token),
        )
        self.assertEqual(response.status_code, 201)
        raw_token = re.search(r"team_invite=([A-Za-z0-9_-]+)", send_email.call_args.args[1]).group(1)

        mismatch = self.post(
            "/api/team/invitations/accept/",
            {"token": raw_token},
            self.headers(self.other_token),
        )
        self.assertEqual(mismatch.status_code, 403)
        self.assertFalse(m.TeamMembership.objects.filter(owner=self.owner, member=self.other).exists())

        response = self.post(
            "/api/team/invitations/accept/",
            {"token": raw_token},
            self.headers(self.member_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["workspace"]["id"], self.owner.pk)
        membership = m.TeamMembership.objects.get(owner=self.owner, member=self.member)
        self.assertEqual(membership.permissions["sales"], {"view": True, "edit": False})
        replay = self.post(
            "/api/team/invitations/accept/",
            {"token": raw_token},
            self.headers(self.member_token),
        )
        self.assertEqual(replay.status_code, 404)

        personal = self.client.get("/api/products/", **self.headers(self.member_token))
        shared = self.client.get(
            "/api/products/", **self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual([item["id"] for item in personal.json()], [member_product.pk])
        self.assertEqual([item["id"] for item in shared.json()], [owner_product.pk])
        self.assertTrue(m.UserSettings.objects.get(owner=self.member).email_verified)

    def test_disabling_sharing_revokes_members_and_preserves_owner_data(self):
        self.owner_settings.team_sharing_enabled = True
        self.owner_settings.save(update_fields=["team_sharing_enabled"])
        m.TeamMembership.objects.create(owner=self.owner, member=self.member)
        m.TeamInvitation.objects.create(
            owner=self.owner, email="invitee@example.com", token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(days=7),
        )
        product = m.Product.objects.create(
            owner=self.owner, name="Still mine", price="20.00", cost="10.00",
        )

        response = self.client.patch(
            "/api/team/sharing/",
            data='{"team_sharing_enabled": false}',
            content_type="application/json",
            **self.headers(self.owner_token),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(m.TeamMembership.objects.filter(owner=self.owner).count(), 0)
        self.assertEqual(m.TeamInvitation.objects.filter(owner=self.owner).count(), 0)
        denied = self.client.get(
            "/api/products/", **self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual(denied.status_code, 403)
        self.assertTrue(m.Product.objects.filter(pk=product.pk, owner=self.owner).exists())

    def test_account_sessions_remain_scoped_to_signed_in_person(self):
        m.TeamMembership.objects.create(owner=self.owner, member=self.member)
        response = self.client.get(
            "/api/account/sessions/", **self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([session["id"] for session in response.json()], [
            token.pk for token in m.ApiToken.objects.filter(user=self.member)
        ])

    def test_registration_can_enable_team_sharing(self):
        response = self.post(
            "/api/auth/register/",
            {
                "username": "newbusiness",
                "email": "newbusiness@example.com",
                "password": "Str0ng-pass-92",
                "password2": "Str0ng-pass-92",
                "accepted_terms": True,
                "team_sharing_enabled": True,
            },
            {},
        )
        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username="newbusiness")
        self.assertTrue(m.UserSettings.objects.get(owner=user).team_sharing_enabled)

    def test_view_only_insights_allow_analysis_without_edit_access(self):
        self.owner_settings.team_sharing_enabled = True
        self.owner_settings.save(update_fields=["team_sharing_enabled"])
        m.TeamMembership.objects.create(
            owner=self.owner, member=self.member,
            permissions=self.permissions(insights={"view": True, "edit": False}),
        )
        response = self.post(
            "/api/assistant/analyze/",
            {"analysis": "profitability"},
            self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual(response.status_code, 200)

    @patch("api.team_access.svc._send_email", return_value=1)
    @patch("api.team_access.svc.email_delivery_configured", return_value=True)
    def test_team_manager_cannot_grant_permissions_they_do_not_have(self, email_configured, send_email):
        self.owner_settings.team_sharing_enabled = True
        self.owner_settings.email_verified = True
        self.owner_settings.save(update_fields=["team_sharing_enabled", "email_verified"])
        m.TeamMembership.objects.create(
            owner=self.owner, member=self.member, can_manage_members=True,
            permissions=self.permissions(inventory={"view": True, "edit": False}),
        )
        response = self.post(
            "/api/team/invitations/",
            {
                "email": "new-member@example.com",
                "permissions": self.permissions(inventory={"view": True, "edit": True}),
                "can_manage_members": False,
            },
            self.headers(self.member_token, self.owner.pk),
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(m.TeamInvitation.objects.filter(owner=self.owner).count(), 0)
        self.assertFalse(send_email.called)
