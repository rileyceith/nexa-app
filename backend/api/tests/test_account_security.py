import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from api import models as m
from api import services as svc


@patch("api.services.email_delivery_configured", return_value=True)
class AccountSecurityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            username="owner", email="owner@example.com", password="old-Strong-Pass42",
        )
        m.UserSettings.objects.create(owner=self.user, email_verified=True)
        self.token = svc.issue_token(self.user, "Test browser")
        self.headers = {"HTTP_AUTHORIZATION": "Bearer " + self.token}
        self.other = get_user_model().objects.create_user(username="other", email="other@example.com")
        self.other_token = svc.issue_token(self.other)

    def post(self, url, data, headers=None):
        return self.client.post(url, data, content_type="application/json", **(headers or self.headers))

    def request_code(self, action, target=""):
        return self.post("/api/account/security/request/", {"action": action, "target": target})

    def confirm(self, action, code, **data):
        return self.post("/api/account/security/confirm/", {"action": action, "code": code, **data})

    def code(self):
        return re.search(r"\b\d{6}\b", mail.outbox[-1].body).group()

    def test_existing_app_can_create_session_without_user_agent_column(self, configured):
        now = timezone.now()
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO api_apitoken (user_id, key_hash, expires_at, created_at) VALUES (%s, %s, %s, %s)",
                [self.user.pk, svc._hash("legacy"), now + timedelta(days=1), now],
            )
        self.assertEqual(m.ApiToken.objects.get(key_hash=svc._hash("legacy")).user_agent, "")

    def test_username_and_sessions_are_account_scoped(self, configured):
        response = self.client.patch(
            "/api/account/profile/", {"username": "new-name"}, content_type="application/json", **self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.username, "new-name")
        sessions = self.client.get("/api/account/sessions/", **self.headers).json()
        self.assertEqual(len(sessions), 1)
        self.assertTrue(sessions[0]["current"])
        self.assertEqual(sessions[0]["device"], "Test browser")
        self.assertNotIn("key_hash", sessions[0])
        other_session = m.ApiToken.objects.get(user=self.other)
        self.assertEqual(self.request_code("device", str(other_session.pk)).status_code, 404)

    def test_email_change_requires_both_codes_and_revokes_other_sessions(self, configured):
        other_session = svc.issue_token(self.user)
        self.assertEqual(self.request_code("email", "new@example.com").status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ["owner@example.com"])
        old_code = self.code()
        self.assertEqual(self.confirm("email", old_code).json()["status"], "new_email")
        self.assertEqual(mail.outbox[-1].to, ["new@example.com"])
        self.assertEqual(self.confirm("email", old_code).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@example.com")
        new_code = self.code()
        self.assertEqual(self.confirm("email", new_code).json()["status"], "email_changed")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertTrue(m.UserSettings.objects.get(owner=self.user).email_verified)
        self.assertIsNone(svc.user_from_token(other_session))
        self.assertEqual(self.confirm("email", new_code).status_code, 400)

    def test_account_without_email_can_add_verified_address(self, configured):
        self.user.email = ""
        self.user.save(update_fields=["email"])
        self.user.preferences.email_verified = False
        self.user.preferences.save(update_fields=["email_verified"])
        other_session = svc.issue_token(self.user)
        response = self.post("/api/account/security/request/", {
            "action": "add_email", "target": "new@example.com", "current_password": "old-Strong-Pass42",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(mail.outbox[-1].to, ["new@example.com"])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")
        code = self.code()
        wrong_headers = {"HTTP_AUTHORIZATION": "Bearer " + other_session}
        self.assertEqual(self.post("/api/account/security/confirm/", {
            "action": "add_email", "code": code,
        }, wrong_headers).status_code, 400)
        self.assertEqual(self.confirm("add_email", code).json()["status"], "email_changed")
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "new@example.com")
        self.assertTrue(m.UserSettings.objects.get(owner=self.user).email_verified)
        self.assertIsNone(svc.user_from_token(other_session))
        self.assertIsNotNone(svc.user_from_token(self.token))
        self.assertEqual(self.confirm("add_email", code).status_code, 400)

    def test_add_email_requires_password_and_cannot_replace_existing_email(self, configured):
        data = {"action": "add_email", "target": "new@example.com", "current_password": "old-Strong-Pass42"}
        self.assertEqual(self.post("/api/account/security/request/", data).status_code, 400)
        self.user.email = ""
        self.user.save(update_fields=["email"])
        data["current_password"] = "wrong"
        self.assertEqual(self.post("/api/account/security/request/", data).status_code, 403)
        self.assertFalse(m.AccountSecurityChallenge.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
        data["current_password"] = "old-Strong-Pass42"
        data["target"] = self.other.email
        self.assertEqual(self.post("/api/account/security/request/", data).status_code, 409)

    def test_add_email_delivery_failure_does_not_change_account(self, configured):
        self.user.email = ""
        self.user.save(update_fields=["email"])
        with patch("api.services._send_email", side_effect=OSError("unavailable")):
            with self.assertLogs("api.services", level="ERROR"):
                response = self.post("/api/account/security/request/", {
                    "action": "add_email", "target": "new@example.com", "current_password": "old-Strong-Pass42",
                })
        self.assertEqual(response.status_code, 503)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "")
        self.assertFalse(m.AccountSecurityChallenge.objects.exists())

    def test_add_email_rejects_expired_or_stale_challenge(self, configured):
        self.user.email = ""
        self.user.save(update_fields=["email"])
        payload = {"action": "add_email", "target": "new@example.com", "current_password": "old-Strong-Pass42"}
        self.assertEqual(self.post("/api/account/security/request/", payload).status_code, 200)
        code = self.code()
        challenge = m.AccountSecurityChallenge.objects.get(owner=self.user)
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save(update_fields=["expires_at"])
        self.assertEqual(self.confirm("add_email", code).status_code, 400)
        challenge.expires_at = timezone.now() + timedelta(minutes=5)
        challenge.save(update_fields=["expires_at"])
        self.user.email = "added-elsewhere@example.com"
        self.user.save(update_fields=["email"])
        self.assertEqual(self.confirm("add_email", code).status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "added-elsewhere@example.com")

    def test_password_change_signs_out_all_sessions_and_invalidates_resets(self, configured):
        other_session = svc.issue_token(self.user)
        reset = m.PasswordResetToken.objects.create(
            owner=self.user, token_hash=svc._hash("reset"), expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.assertEqual(self.request_code("password").status_code, 200)
        result = self.confirm("password", self.code(), password="different-Strong-Pass88", password2="different-Strong-Pass88")
        self.assertEqual(result.json()["status"], "password_changed")
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("different-Strong-Pass88"))
        reset.refresh_from_db()
        self.assertIsNotNone(reset.used_at)
        self.assertIsNone(svc.user_from_token(self.token))
        self.assertIsNone(svc.user_from_token(other_session))

    def test_code_is_bound_to_session_and_locked_after_five_wrong_attempts(self, configured):
        self.assertEqual(self.request_code("password").status_code, 200)
        code = self.code()
        another_token = svc.issue_token(self.user)
        headers = {"HTTP_AUTHORIZATION": "Bearer " + another_token}
        self.assertEqual(self.post("/api/account/security/confirm/", {
            "action": "password", "code": code, "password": "different-Strong-Pass88", "password2": "different-Strong-Pass88",
        }, headers).status_code, 400)
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.confirm("password", wrong).status_code, 400)
        self.assertEqual(self.confirm("password", code).status_code, 400)
        self.assertEqual(m.AccountSecurityChallenge.objects.get(owner=self.user).attempts, 5)

    def test_device_signout_requires_code_and_preserves_current_session(self, configured):
        token = svc.issue_token(self.user)
        session = m.ApiToken.objects.get(key_hash=svc._hash(token))
        self.assertEqual(self.request_code("device", str(session.pk)).status_code, 200)
        self.assertEqual(self.confirm("device", self.code()).json()["status"], "device_signed_out")
        self.assertIsNone(svc.user_from_token(token))
        self.assertIsNotNone(svc.user_from_token(self.token))

    def test_expired_code_and_changed_email_cannot_authorize_actions(self, configured):
        self.assertEqual(self.request_code("password").status_code, 200)
        code = self.code()
        challenge = m.AccountSecurityChallenge.objects.get(owner=self.user)
        challenge.expires_at = timezone.now() - timedelta(seconds=1)
        challenge.save(update_fields=["expires_at"])
        self.assertEqual(self.confirm("password", code).status_code, 400)
        challenge.expires_at = timezone.now() + timedelta(minutes=5)
        challenge.save(update_fields=["expires_at"])
        self.user.email = "changed@example.com"
        self.user.save(update_fields=["email"])
        self.assertEqual(self.confirm("password", code).status_code, 400)

    def test_new_email_delivery_failure_does_not_change_address_or_advance_challenge(self, configured):
        self.assertEqual(self.request_code("email", "new@example.com").status_code, 200)
        with patch("api.services._send_email", side_effect=OSError("unavailable")):
            with self.assertLogs("api.services", level="ERROR"):
                self.assertEqual(self.confirm("email", self.code()).status_code, 503)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "owner@example.com")
        self.assertEqual(m.AccountSecurityChallenge.objects.get(owner=self.user).stage, "current")

    def test_unverified_email_and_delivery_failure_do_not_issue_codes(self, configured):
        self.user.preferences.email_verified = False
        self.user.preferences.save(update_fields=["email_verified"])
        self.assertEqual(self.request_code("password").status_code, 403)
        self.user.preferences.email_verified = True
        self.user.preferences.save(update_fields=["email_verified"])
        with patch("api.services._send_email", side_effect=OSError("unavailable")):
            with self.assertLogs("api.services", level="ERROR"):
                self.assertEqual(self.request_code("password").status_code, 503)
        self.assertFalse(m.AccountSecurityChallenge.objects.exists())
