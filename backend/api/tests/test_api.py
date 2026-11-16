import base64
import csv
import gzip
import importlib
import io
import json
import os
import re
import runpy
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.core.cache.backends.db import DatabaseCache
from django.core import mail
from django.core.management import call_command
from django.db import IntegrityError, OperationalError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image
from urllib.error import HTTPError

from api import assistant as ai
from api import images
from api import models as m
from api import services as svc


def data_url(mime, raw):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


def encoded(fmt, size):
    buffer = io.BytesIO()
    Image.new("RGB", size, (200, 80, 40)).save(buffer, fmt)
    return buffer.getvalue()


PNG_URL = data_url("image/png", encoded("PNG", (1200, 900)))
JPEG_URL = data_url("image/jpeg", encoded("JPEG", (64, 64)))


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_root, True)
        media = override_settings(MEDIA_ROOT=self.media_root)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create(username="a@x.com", email="a@x.com")
        self.h = {"HTTP_AUTHORIZATION": "Bearer " + svc.issue_token(self.user)}
        self.other = get_user_model().objects.create(username="b@x.com", email="b@x.com")
        self.other_h = {"HTTP_AUTHORIZATION": "Bearer " + svc.issue_token(self.other)}
        m.UserSettings.objects.create(owner=self.user)
        m.UserSettings.objects.create(owner=self.other)

    def post(self, url, data, headers=None):
        return self.client.post(url, data, content_type="application/json", **(headers or self.h))

    def product(self, **kw):
        body = {"name": "Earbuds", "price": "24", "cost": "14", "target_stock": 80, **kw}
        return self.post("/api/products/", body).json()

    def upload(self, image=PNG_URL):
        r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4, "image": image})
        self.assertEqual(r.status_code, 201)
        return r.json()["product"]["image_url"]

    def stored_images(self):
        folder = Path(self.media_root, "products")
        return sorted(folder.iterdir()) if folder.exists() else []

    def image_status(self, url):
        response = self.client.get(url)
        response.close()
        return response.status_code

    def test_requires_auth(self):
        self.assertEqual(self.client.get("/api/products/").status_code, 401)

    def test_health_checks_report_dependency_failure_without_details(self):
        live = self.client.get("/api/health/live/")
        self.assertEqual((live.status_code, live.json()), (200, {"status": "ok"}))
        ready = self.client.get("/api/health/ready/")
        self.assertEqual((ready.status_code, ready.json()), (200, {"status": "ready"}))
        self.assertEqual(ready["Cache-Control"], "no-store")
        with patch("api.views.cache.get", side_effect=OperationalError("private diagnostic")):
            response = self.client.get("/api/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private diagnostic", response.content.decode())
        self.assertEqual(self.client.post("/api/health/ready/").status_code, 405)

    @patch("api.services.email_delivery_configured", return_value=True)
    def test_magic_link_flow_and_single_use(self, email_configured):
        self.assertEqual(self.post("/api/auth/request-link/", {"email": "new@x.com"}, {}).status_code, 200)
        token = re.search(r"token=([\w-]+)", mail.outbox[0].body).group(1)
        r = self.post("/api/auth/verify/", {"token": token}, {})
        self.assertEqual(r.status_code, 200)
        key = r.json()["token"]
        self.assertEqual(self.client.get("/api/me/", HTTP_AUTHORIZATION="Bearer " + key).json()["email"], "new@x.com")
        self.assertEqual(self.post("/api/auth/verify/", {"token": token}, {}).status_code, 400)

    def test_invalid_email_rejected(self):
        self.assertEqual(self.post("/api/auth/request-link/", {"email": "nope"}, {}).status_code, 400)

    def test_magic_links_never_fall_back_to_console_in_production(self):
        with override_settings(DEBUG=False, EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"):
            response = self.post("/api/auth/request-link/", {"email": "new@example.com"}, {})
        self.assertEqual(response.status_code, 503)
        self.assertFalse(m.MagicLink.objects.filter(email="new@example.com").exists())

    def test_resend_requires_api_key_and_explicit_sender(self):
        with override_settings(
            DEBUG=False, EMAIL_BACKEND="anymail.backends.resend.EmailBackend",
            RESEND_API_KEY="", DEFAULT_FROM_EMAIL="Nexa <onboarding@resend.dev>",
        ):
            self.assertFalse(svc.email_delivery_configured())
            with override_settings(RESEND_API_KEY="test-key", DEFAULT_FROM_EMAIL="Nexa <no-reply@nexa.local>"):
                self.assertFalse(svc.email_delivery_configured())
            with override_settings(RESEND_API_KEY="test-key"):
                self.assertTrue(svc.email_delivery_configured())

    @override_settings(
        DEBUG=False, EMAIL_BACKEND="anymail.backends.resend.EmailBackend",
        RESEND_API_KEY="test-key", DEFAULT_FROM_EMAIL="Nexa <onboarding@resend.dev>",
    )
    @patch("requests.sessions.Session.request")
    def test_resend_sends_magic_link_over_https(self, request):
        import requests
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"id":"test-message"}'
        request.return_value = response
        result = self.post("/api/auth/request-link/", {"email": "new@example.com"}, {})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(request.call_args.kwargs["url"], "https://api.resend.com/emails")
        self.assertEqual(request.call_args.kwargs["method"], "POST")
        self.assertTrue(m.MagicLink.objects.filter(email="new@example.com").exists())

    @override_settings(
        DEBUG=False, EMAIL_BACKEND="anymail.backends.resend.EmailBackend",
        RESEND_API_KEY="test-key", DEFAULT_FROM_EMAIL="Nexa <onboarding@resend.dev>",
    )
    @patch("requests.sessions.Session.request")
    def test_resend_failures_clean_up_tokens_and_keep_reset_generic(self, request):
        import requests
        response = requests.Response()
        response.status_code = 403
        response.reason = "Forbidden"
        response._content = b'{"message":"sensitive provider detail"}'
        request.return_value = response
        with self.assertLogs("api.services", level="ERROR") as logs:
            magic = self.post("/api/auth/request-link/", {"email": "new@example.com"}, {})
            reset = self.post("/api/auth/password-reset/", {"email": self.user.email}, {})
        self.assertEqual(magic.status_code, 503)
        self.assertEqual(reset.status_code, 200)
        self.assertFalse(m.MagicLink.objects.filter(email="new@example.com").exists())
        self.assertFalse(m.PasswordResetToken.objects.filter(owner=self.user).exists())
        self.assertNotIn("sensitive provider detail", "\n".join(logs.output))

    @patch("api.services.email_delivery_configured", return_value=True)
    def test_password_reset_request_is_generic_and_emails_only_existing_accounts(self, email_configured):
        response = self.post("/api/auth/password-reset/", {"email": self.user.email}, {})
        unknown = self.post("/api/auth/password-reset/", {"email": "unknown@example.com"}, {})
        detail = "If an account exists for that email, password reset instructions will be sent."
        self.assertEqual(response.status_code, 200)
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(response.json()["detail"], detail)
        self.assertEqual(unknown.json()["detail"], detail)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.user.email])
        token = re.search(r"password_reset=([\w-]+)", mail.outbox[0].body).group(1)
        reset_token = m.PasswordResetToken.objects.get(owner=self.user)
        self.assertNotEqual(reset_token.token_hash, token)
        self.assertEqual(reset_token.token_hash, svc._hash(token))

    @patch("api.services.email_delivery_configured", return_value=False)
    def test_password_reset_request_stays_generic_without_secure_email(self, email_configured):
        response = self.post("/api/auth/password-reset/", {"email": self.user.email}, {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), self.post(
            "/api/auth/password-reset/", {"email": "unknown@example.com"}, {},
        ).json())
        self.assertFalse(m.PasswordResetToken.objects.exists())

    @patch("api.services.email_delivery_configured", return_value=True)
    def test_password_reset_requests_are_rate_limited_and_delivery_failures_stay_generic(self, email_configured):
        for _ in range(4):
            response = self.post("/api/auth/password-reset/", {"email": self.user.email}, {})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 3)

        with patch("api.services.send_mail", side_effect=OSError("mail unavailable")):
            response = self.post("/api/auth/password-reset/", {"email": self.other.email}, {})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(m.PasswordResetToken.objects.filter(owner=self.other).exists())

    def test_password_reset_validates_policy_then_revokes_sessions_and_is_single_use(self):
        raw_token = "one-time-password-reset-token"
        second_session = svc.issue_token(self.user)
        reset_token = m.PasswordResetToken.objects.create(
            owner=self.user, token_hash=svc._hash(raw_token), expires_at=timezone.now() + timedelta(minutes=30),
        )
        response = self.post("/api/auth/password-reset/confirm/", {
            "token": raw_token, "password": "short", "password2": "short",
        }, {})
        self.assertEqual(response.status_code, 400)
        reset_token.refresh_from_db()
        self.assertIsNone(reset_token.used_at)

        password = "Y3llow!Skies_90"
        response = self.post("/api/auth/password-reset/confirm/", {
            "token": raw_token, "password": password, "password2": password,
        }, {})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(get_user_model().objects.get(pk=self.user.pk).check_password(password))
        self.assertIsNone(svc.user_from_token(self.h["HTTP_AUTHORIZATION"][7:]))
        self.assertIsNone(svc.user_from_token(second_session))
        self.assertTrue(svc.user_from_token(self.other_h["HTTP_AUTHORIZATION"][7:]))
        reset_token.refresh_from_db()
        self.assertIsNotNone(reset_token.used_at)
        self.assertEqual(self.post("/api/auth/password-reset/confirm/", {
            "token": raw_token, "password": password, "password2": password,
        }, {}).status_code, 400)

    def test_password_reset_rejects_mismatched_and_expired_tokens(self):
        raw_token = "another-password-reset-token"
        reset_token = m.PasswordResetToken.objects.create(
            owner=self.user, token_hash=svc._hash(raw_token), expires_at=timezone.now() + timedelta(minutes=30),
        )
        mismatch = self.post("/api/auth/password-reset/confirm/", {
            "token": raw_token, "password": "Y3llow!Skies_90", "password2": "different",
        }, {})
        self.assertEqual(mismatch.status_code, 400)
        reset_token.refresh_from_db()
        self.assertIsNone(reset_token.used_at)
        m.PasswordResetToken.objects.filter(pk=reset_token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        expired = self.post("/api/auth/password-reset/confirm/", {
            "token": raw_token, "password": "Y3llow!Skies_90", "password2": "Y3llow!Skies_90",
        }, {})
        self.assertEqual(expired.status_code, 400)

    def test_register_and_login(self):
        body = {"username": "riley", "email": "Riley@example.com", "password": "Str0ng-pass-92", "password2": "Str0ng-pass-92", "accepted_terms": True}
        r = self.post("/api/auth/register/", body, {})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(m.TermsAcceptance.objects.filter(user__username="riley").exists())
        self.assertEqual(get_user_model().objects.get(username="riley").email, "riley@example.com")
        self.assertEqual(self.post("/api/auth/register/", body, {}).status_code, 409)
        r = self.post("/api/auth/login/", {"username": "RILEY", "password": "Str0ng-pass-92"}, {})
        self.assertEqual(r.status_code, 200)
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION="Bearer " + r.json()["token"])
        self.assertEqual(me.json()["username"], "riley")
        self.assertFalse(me.json()["is_staff"])
        get_user_model().objects.filter(username="riley").update(is_staff=True)
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION="Bearer " + r.json()["token"])
        self.assertTrue(me.json()["is_staff"])

    def test_register_validation(self):
        ok = {"username": "sam", "email": "sam@example.com", "password": "Str0ng-pass-92", "password2": "Str0ng-pass-92", "accepted_terms": True}
        for change in ({"email": ""}, {"email": "not-an-email"}, {"password2": "different"}, {"accepted_terms": False}, {"accepted_terms": "true"},
                       {"password": "123", "password2": "123"}, {"username": "a b"}, {"username": "éclair"}):
            self.assertEqual(self.post("/api/auth/register/", {**ok, **change}, {}).status_code, 400, change)

    def test_registration_initializes_empty_account_and_rejects_duplicate_email(self):
        body = {"username": "sam", "email": " Sam@example.com ", "password": "Str0ng-pass-92", "password2": "Str0ng-pass-92", "accepted_terms": True}
        response = self.post("/api/auth/register/", body, {})
        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(username="sam")
        self.assertTrue(m.UserSettings.objects.filter(owner=user).exists())
        self.assertFalse(m.Product.objects.filter(owner=user).exists())
        self.assertFalse(m.StockBatch.objects.filter(owner=user).exists())
        self.assertEqual(self.post("/api/auth/register/", {**body, "username": "another", "email": "SAM@example.com"}, {}).status_code, 409)
        self.assertEqual(get_user_model().objects.filter(email="sam@example.com").count(), 1)

    def test_registration_rolls_back_all_records_when_initialization_fails(self):
        with patch("api.services.initialize_business_data", side_effect=RuntimeError("setup failed")):
            with self.assertRaisesRegex(RuntimeError, "setup failed"):
                svc.register("sam", "sam@example.com", "Str0ng-pass-92", "Str0ng-pass-92", True)
        self.assertFalse(get_user_model().objects.filter(username="sam").exists())
        self.assertFalse(m.UserSettings.objects.filter(owner__username="sam").exists())
        self.assertFalse(m.TermsAcceptance.objects.filter(user__username="sam").exists())
        self.assertFalse(m.ApiToken.objects.filter(user__username="sam").exists())

    def test_registration_rolls_back_when_token_creation_fails(self):
        with patch("api.services.issue_token", side_effect=RuntimeError("token failed")):
            with self.assertRaisesRegex(RuntimeError, "token failed"):
                svc.register("sam", "sam@example.com", "Str0ng-pass-92", "Str0ng-pass-92", True)
        self.assertFalse(get_user_model().objects.filter(username="sam").exists())
        self.assertFalse(m.UserSettings.objects.filter(owner__username="sam").exists())
        self.assertFalse(m.TermsAcceptance.objects.filter(user__username="sam").exists())

    def test_database_enforces_account_identity_uniqueness(self):
        User = get_user_model()
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(username="another", email=" A@X.COM ")
        with self.assertRaises(IntegrityError), transaction.atomic():
            User.objects.create(username="A@X.COM", email="unique@example.com")

    @patch("api.services.email_delivery_configured", return_value=True)
    def test_magic_link_signs_into_existing_email_account(self, email_configured):
        body = {"username": "sam", "email": "sam@example.com", "password": "Str0ng-pass-92", "password2": "Str0ng-pass-92", "accepted_terms": True}
        registration = self.post("/api/auth/register/", body, {}).json()
        owner_headers = {"HTTP_AUTHORIZATION": "Bearer " + registration["token"]}
        self.post("/api/products/", {"name": "Private stock", "price": "10", "cost": "5"}, owner_headers)
        self.assertEqual(self.post("/api/auth/request-link/", {"email": "SAM@example.com"}, {}).status_code, 200)
        token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
        response = self.post("/api/auth/verify/", {"token": token}, {})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["id"], registration["user"]["id"])
        headers = {"HTTP_AUTHORIZATION": "Bearer " + response.json()["token"]}
        self.assertEqual(self.client.get("/api/products/", **headers).json()[0]["name"], "Private stock")
        self.assertEqual(get_user_model().objects.filter(email="sam@example.com").count(), 1)
        self.assertEqual(self.client.get("/api/products/", **self.other_h).json(), [])

    @patch("api.services.email_delivery_configured", return_value=True)
    def test_magic_link_does_not_use_another_users_matching_username(self, email_configured):
        User = get_user_model()
        unrelated = User.objects.create(username="new@example.com", email="different@example.com")
        self.post("/api/auth/request-link/", {"email": "new@example.com"}, {})
        token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
        response = self.post("/api/auth/verify/", {"token": token}, {})
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response.json()["user"]["id"], unrelated.id)
        self.assertTrue(m.UserSettings.objects.filter(owner_id=response.json()["user"]["id"]).exists())

    @patch("api.services.email_delivery_configured", return_value=True)
    def test_magic_link_initialization_failure_does_not_consume_link(self, email_configured):
        self.post("/api/auth/request-link/", {"email": "new@example.com"}, {})
        token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
        with patch("api.services.initialize_business_data", side_effect=RuntimeError("setup failed")):
            with self.assertRaisesRegex(RuntimeError, "setup failed"):
                svc.verify_magic_link(token)
        self.assertFalse(get_user_model().objects.filter(email="new@example.com").exists())
        self.assertIsNone(m.MagicLink.objects.get(email="new@example.com").used_at)
        self.assertEqual(self.post("/api/auth/verify/", {"token": token}, {}).status_code, 200)

    def test_login_wrong_password_and_lockout(self):
        get_user_model().objects.create_user(username="lee", password="Str0ng-pass-92")
        for _ in range(5):
            self.assertEqual(self.post("/api/auth/login/", {"username": "lee", "password": "bad"}, {}).status_code, 401)
        self.assertEqual(self.post("/api/auth/login/", {"username": "lee", "password": "Str0ng-pass-92"}, {}).status_code, 429)

    def test_sale_consumes_oldest_stock_first_and_computes_cogs(self):
        p = self.product()
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 10, "unit_cost": "10"})
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 10, "unit_cost": "20"})
        r = self.post("/api/sales/", {"customer": "Tendai", "amount": "300", "product_id": p["id"], "quantity": 15})
        self.assertEqual(r.status_code, 201)
        sale = m.Sale.objects.get()
        self.assertEqual(sale.cogs, Decimal("200.00"))  # 10 x 10 + 5 x 20
        self.assertEqual(Decimal(str(r.json()["cogs"])), Decimal("200.00"))
        self.assertEqual(sorted(b.quantity_left for b in m.StockBatch.objects.all()), [0, 5])

    def test_cannot_oversell(self):
        p = self.product()
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 2, "unit_cost": "10"})
        r = self.post("/api/sales/", {"amount": "50", "product_id": p["id"], "quantity": 5})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(m.Sale.objects.count(), 0)

    def test_stock_ledger_reconciles_with_batches(self):
        p = self.product()
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 10, "unit_cost": "10"})
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 10, "unit_cost": "20"})
        self.post("/api/sales/", {"amount": "300", "product_id": p["id"], "quantity": 15})
        product = m.Product.objects.get(pk=p["id"])
        self.assertEqual(svc.stock_of(product), 5)
        self.assertEqual(svc.ledger_balance(product), 5)
        sale_moves = m.StockMovement.objects.filter(kind=m.StockMovement.SALE)
        self.assertEqual(sorted(mv.quantity for mv in sale_moves), [-10, -5])
        self.assertTrue(all(mv.sale_id for mv in sale_moves))

    def test_ledger_backfill_matches_existing_batches(self):
        migration = importlib.import_module("api.migrations.0005_stockmovement")
        p = self.product()
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 10, "unit_cost": "10"})
        self.post("/api/sales/", {"amount": "50", "product_id": p["id"], "quantity": 4})
        product = m.Product.objects.get(pk=p["id"])
        m.StockMovement.objects.all().delete()
        migration.backfill_from_batches(apps, None)
        self.assertEqual(svc.ledger_balance(product), svc.stock_of(product))

    def stock_up(self, name, supplier=None):
        p = m.Product.objects.create(owner=self.user, name=name, price=Decimal("10"), cost=Decimal("4"),
                                     target_stock=20, supplier=supplier)
        svc.receive_stock(self.user, product=p, quantity=5, unit_cost=Decimal("4"), supplier=supplier)
        return p

    def query_count(self, url):
        with CaptureQueriesContext(connection) as ctx:
            self.assertEqual(self.client.get(url, **self.h).status_code, 200)
        return len(ctx)

    def test_list_queries_do_not_grow_with_catalogue_size(self):
        supplier = m.Supplier.objects.create(owner=self.user, name="Acme")
        self.stock_up("Earbuds", supplier)
        urls = ["/api/products/", "/api/stock/", "/api/customers/", "/api/insights/", "/api/dashboard/"]
        before = {url: self.query_count(url) for url in urls}
        for i in range(6):
            p = self.stock_up(f"Item {i}", supplier)
            svc.record_sale(self.user, amount=Decimal("10"), customer_name=f"Buyer {i}", product=p)
        self.assertEqual({url: self.query_count(url) for url in urls}, before)

    def test_customer_lists_each_product_once_across_repeat_orders(self):
        product = self.stock_up("Earbuds")
        for day in (1, 2):
            svc.record_sale(self.user, amount=Decimal("10"), customer_name="Repeat", product=product, on=date(2026, 1, day))
        customers = self.client.get("/api/customers/", **self.h).json()
        self.assertEqual(customers[0]["products"], ["Earbuds"])

    def test_hot_query_indexes_exist(self):
        expected = {
            "api_sale": "sale_owner_date_idx",
            "api_expense": "expense_owner_date_idx",
            "api_purchase": "purchase_owner_status_idx",
            "api_stockbatch": "batch_owner_product_idx",
            "api_stockmovement": "movement_owner_product_idx",
        }
        with connection.cursor() as cursor:
            for table, index in expected.items():
                self.assertIn(index, connection.introspection.get_constraints(cursor, table), table)

    def test_json_responses_are_gzipped_when_accepted(self):
        for i in range(10):
            self.product(name=f"Gzip item {i}")
        r = self.client.get("/api/products/", HTTP_ACCEPT_ENCODING="gzip", **self.h)
        self.assertEqual(r["Content-Encoding"], "gzip")
        self.assertEqual(len(json.loads(gzip.decompress(r.content))), 10)
        plain = self.client.get("/api/products/", **self.h)
        self.assertFalse(plain.has_header("Content-Encoding"))

    def test_list_endpoints_page_with_limit_offset_and_total_header(self):
        for name in ("P0", "P1", "P2", "P3", "P4"):
            self.product(name=name)
        r = self.client.get("/api/products/?limit=2&offset=1", **self.h)
        self.assertEqual([p["name"] for p in r.json()], ["P1", "P2"])
        self.assertEqual(r["X-Total-Count"], "5")
        r = self.client.get("/api/products/", HTTP_ORIGIN="null", **self.h)
        self.assertEqual(len(r.json()), 5)
        self.assertEqual(r["X-Total-Count"], "5")
        self.assertEqual(r["Access-Control-Expose-Headers"], "X-Total-Count")

        for amount in ("10", "20", "30"):
            self.post("/api/sales/", {"amount": amount, "customer": "Tendai"})
        r = self.client.get("/api/sales/?limit=2", **self.h)
        self.assertEqual(len(r.json()), 2)
        self.assertEqual(r["X-Total-Count"], "3")

        for amount in ("5", "7", "9"):
            self.post("/api/expenses/", {"category": "Rent", "amount": amount})
        r = self.client.get("/api/expenses/?limit=2", **self.h)
        body = r.json()
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(r["X-Total-Count"], "3")
        self.assertEqual(Decimal(str(body["total"])), Decimal("21"))

        p = self.product(name="Bulb")
        for qty in (1, 2, 3):
            self.post("/api/receive/", {"product_id": p["id"], "quantity": qty, "unit_cost": "10"})
        r = self.client.get("/api/batches/?limit=2", **self.h)
        self.assertEqual(len(r.json()), 2)
        self.assertEqual(r["X-Total-Count"], "3")

        for _ in range(3):
            self.post("/api/purchases/", {"product_id": p["id"]})
        total = m.Purchase.objects.filter(owner=self.user).count()  # receipts also log a delivered purchase
        r = self.client.get("/api/purchases/?limit=1&offset=2", **self.h)
        self.assertEqual(len(r.json()), 1)
        self.assertEqual(r["X-Total-Count"], str(total))

    def test_page_parameters_are_validated_and_clamped(self):
        self.product(name="First")
        self.product(name="Second")
        for query in ("limit=abc", "limit=-1", "offset=-1", "offset=x"):
            self.assertEqual(self.client.get(f"/api/products/?{query}", **self.h).status_code, 400, query)
        with patch("api.views.MAX_PAGE_SIZE", 1):
            self.assertEqual(len(self.client.get("/api/products/?limit=50", **self.h).json()), 1)

    def test_data_is_isolated_per_user(self):
        p = self.product()
        self.assertEqual(self.client.get("/api/products/", **self.other_h).json(), [])
        self.assertEqual(self.client.get(f"/api/products/{p['id']}/", **self.other_h).status_code, 404)

    def test_validation(self):
        self.assertEqual(self.post("/api/expenses/", {"category": "Rent", "amount": "-5"}).status_code, 400)
        self.assertEqual(self.post("/api/sales/", {"amount": "abc"}).status_code, 400)

    def test_dashboard_totals(self):
        self.post("/api/sales/", {"customer": "A", "amount": "100"})
        m.Sale.objects.create(owner=self.user, amount=Decimal("50"), cogs=Decimal("30"), status=m.Sale.PENDING)
        self.post("/api/expenses/", {"category": "Rent", "amount": "30"})
        d = self.client.get("/api/dashboard/", **self.h).json()
        self.assertEqual(Decimal(d["revenue"]), 100)
        self.assertEqual(Decimal(d["expenses"]), 30)
        self.assertEqual(Decimal(d["net_profit"]), Decimal("100") - Decimal("60") - 30)
        self.assertIn("Expected", d["forecast"])

    def test_purchase_receive_flow(self):
        p = self.product()
        order = self.post("/api/purchases/", {"product_id": p["id"], "quantity": 20}).json()
        self.assertEqual(order["status"], "Ordered")
        self.assertEqual(self.post(f"/api/purchases/{order['id']}/receive/", {}).json()["status"], "Delivered")
        self.assertEqual(self.post(f"/api/purchases/{order['id']}/receive/", {}).status_code, 409)
        self.assertEqual(self.client.get("/api/stock/", **self.h).json()[0]["in_stock"], 20)

    def test_double_receive_does_not_duplicate_stock(self):
        p = self.product()
        order = self.post("/api/purchases/", {"product_id": p["id"], "quantity": 20}).json()
        self.post(f"/api/purchases/{order['id']}/receive/", {})
        self.post(f"/api/purchases/{order['id']}/receive/", {})
        self.assertEqual(m.StockBatch.objects.count(), 1)
        self.assertEqual(svc.stock_of(m.Product.objects.get(pk=p["id"])), 20)

    def test_duplicate_product_race_returns_409(self):
        self.product()
        with patch("api.views.m.Product.objects.filter") as filtered:
            filtered.return_value.exists.return_value = False
            r = self.post("/api/products/", {"name": "Earbuds", "price": "24", "cost": "14"})
        self.assertEqual(r.status_code, 409)

    def test_duplicate_new_product_race_returns_409(self):
        self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4})
        with patch("api.views.m.Product.objects.filter") as filtered:
            filtered.return_value.first.return_value = None
            r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(m.StockBatch.objects.count(), 1)

    def test_unexpected_errors_return_json_500_and_are_logged(self):
        self.product()
        with patch("api.services.with_stock", side_effect=RuntimeError("boom")), self.assertLogs("api", level="ERROR"):
            r = self.client.get("/api/products/", **self.h)
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r["Content-Type"], "application/json")
        self.assertIn("error", r.json())

    def test_money_fields_are_two_decimal_strings_even_when_empty(self):
        self.assertEqual(self.client.get("/api/expenses/", **self.h).json()["total"], "0.00")
        self.assertEqual(self.client.get("/api/dashboard/", **self.h).json()["pending_payments"]["total"], "0.00")
        self.post("/api/sales/", {"amount": "50", "customer": "Ada"})
        self.assertEqual(self.client.get("/api/customers/", **self.h).json()[0]["spent"], "50.00")

    def test_receive_stores_image_for_new_product(self):
        r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4, "image": PNG_URL})
        self.assertEqual(r.status_code, 201)
        product_id = r.json()["product"]["id"]
        image_url = r.json()["product"]["image_url"]
        self.assertNotIn("image", r.json()["product"])
        self.assertTrue(image_url.startswith("/api/images/"))
        self.assertEqual(self.client.get(f"/api/products/{product_id}/", **self.h).json()["image_url"], image_url)
        self.assertEqual(self.client.get(image_url).status_code, 200)
        self.assertEqual(len(self.stored_images()), 1)

    def test_new_product_without_image_has_empty_image(self):
        r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["product"]["image_url"], "")

    def test_receiving_existing_product_name_adds_batch_to_existing_product(self):
        product = self.product(name="Mug", price="12")
        response = self.post("/api/receive/", {
            "new_product_name": "  mug  ", "quantity": 4, "unit_cost": "5", "supplier": "Acme",
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["product"]["id"], product["id"])
        self.assertEqual(response.json()["product"]["name"], "Mug")
        self.assertEqual(m.Product.objects.filter(owner=self.user, name__iexact="Mug").count(), 1)
        self.assertEqual(m.StockBatch.objects.filter(owner=self.user, product_id=product["id"]).count(), 1)
        self.assertEqual(m.StockBatch.objects.get(product_id=product["id"]).quantity_left, 4)

    def test_existing_product_image_is_replaced_kept_and_cleared(self):
        p = self.product()
        url = f"/api/products/{p['id']}/"
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 2, "unit_cost": "10", "image": PNG_URL})
        first = self.client.get(url, **self.h).json()["image_url"]
        self.assertEqual(self.image_status(first), 200)

        self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10"})
        self.assertEqual(self.client.get(url, **self.h).json()["image_url"], first)

        self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10", "image": JPEG_URL})
        second = self.client.get(url, **self.h).json()["image_url"]
        self.assertNotEqual(second, first)
        self.assertEqual(self.image_status(second), 200)
        self.assertEqual(self.image_status(first), 404)
        self.assertEqual(len(self.stored_images()), 1)

        r = self.client.patch(url, data=json.dumps({"image": ""}), content_type="application/json", **self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(url, **self.h).json()["image_url"], "")
        self.assertEqual(self.image_status(second), 404)
        self.assertEqual(self.stored_images(), [])

    def test_invalid_images_are_rejected_before_anything_is_written(self):
        invalid = {
            "svg": data_url("image/svg+xml", b"<svg/>"),
            "not a data url": "https://example.com/a.png",
            "malformed base64": "data:image/png;base64,@@@",
            "too large": data_url("image/png", b"0" * (1024 * 1024 + 1)),
            "undecodable": data_url("image/png", b"not really a png"),
        }
        for label, image in invalid.items():
            r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4, "image": image})
            self.assertEqual(r.status_code, 400, label)
        self.assertFalse(m.Product.objects.filter(owner=self.user).exists())
        self.assertFalse(m.StockBatch.objects.exists())
        self.assertEqual(self.stored_images(), [])

    def test_invalid_image_on_existing_product_keeps_current_image(self):
        p = self.product()
        url = f"/api/products/{p['id']}/"
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10", "image": PNG_URL})
        current = self.client.get(url, **self.h).json()["image_url"]
        r = self.client.patch(url, data=json.dumps({"image": data_url("text/html", b"<h1>x</h1>")}), content_type="application/json", **self.h)
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10", "image": "not-an-image"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(url, **self.h).json()["image_url"], current)
        self.assertEqual(self.client.get(current).status_code, 200)
        self.assertEqual(m.StockBatch.objects.filter(product_id=p["id"]).count(), 1)
        self.assertEqual(len(self.stored_images()), 1)

    def test_renaming_onto_an_existing_product_returns_409_and_leaves_no_new_image(self):
        self.product(name="Mug")
        p = self.product(name="Plate")
        url = f"/api/products/{p['id']}/"
        r = self.client.patch(url, data=json.dumps({"name": "Mug"}), content_type="application/json", **self.h)
        self.assertEqual(r.status_code, 409)
        r = self.client.patch(url, data=json.dumps({"name": "Mug", "image": PNG_URL}), content_type="application/json", **self.h)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.stored_images(), [])
        self.assertEqual(self.client.get(url, **self.h).json()["name"], "Plate")

    def test_product_payloads_expose_image_url_not_inline_data(self):
        self.upload()
        product = self.client.get("/api/products/", **self.h).json()[0]
        self.assertNotIn("image", product)
        self.assertTrue(product["image_url"].startswith("/api/images/"))
        self.assertNotIn("data:image", json.dumps(product))

    def test_image_endpoint_serves_webp_at_the_requested_size(self):
        image_url = self.upload()
        cases = {None: 400, 50: 120, 120: 120, 400: 400, 900: 1000, 5000: 1000}
        for requested, expected in cases.items():
            params = {} if requested is None else {"size": requested}
            r = self.client.get(image_url, params)
            self.assertEqual(r.status_code, 200, requested)
            self.assertEqual(r["Content-Type"], "image/webp")
            picture = Image.open(io.BytesIO(b"".join(r.streaming_content)))
            self.assertEqual(picture.format, "WEBP")
            self.assertEqual(max(picture.size), expected, requested)

    def test_image_endpoint_is_public_cacheable_and_supports_etags(self):
        image_url = self.upload()
        key = image_url.strip("/").split("/")[-1]
        r = self.client.get(image_url, {"size": 120})
        self.assertEqual(r["ETag"], f'"{key}-120"')
        self.assertEqual(r["Cache-Control"], "public, max-age=86400")
        r = self.client.get(image_url, {"size": 120}, HTTP_IF_NONE_MATCH=f'"{key}-120"')
        self.assertEqual(r.status_code, 304)

    def test_image_endpoint_rejects_unknown_keys_and_bad_sizes(self):
        image_url = self.upload()
        self.assertEqual(self.client.get("/api/images/not-a-key/").status_code, 404)
        self.assertEqual(self.client.get("/api/images/" + "0" * 32 + "/").status_code, 404)
        self.assertEqual(self.client.get(image_url, {"size": "big"}).status_code, 400)

    def test_cors_preflight(self):
        r = self.client.options("/api/sales/", HTTP_ORIGIN="null", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r["Access-Control-Allow-Origin"], "null")
        r = self.client.options("/api/sales/", HTTP_ORIGIN="http://evil.test", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", r)

    @override_settings(CORS_ALLOW_LOCAL_DEV=True)
    def test_cors_allows_any_localhost_port_in_development(self):
        for origin in ("http://localhost:5173", "http://127.0.0.1:3000", "http://localhost"):
            r = self.client.options("/api/sales/", HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
            self.assertEqual(r["Access-Control-Allow-Origin"], origin)
        for origin in ("http://localhost.evil.test", "http://evil.test:5500", "https://localhost:abc"):
            r = self.client.options("/api/sales/", HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
            self.assertNotIn("Access-Control-Allow-Origin", r)

    @override_settings(CORS_ALLOW_LOCAL_DEV=False)
    def test_cors_rejects_unlisted_localhost_ports_in_production(self):
        r = self.client.options("/api/sales/", HTTP_ORIGIN="http://localhost:5173", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", r)

    @override_settings(CORS_ALLOW_LOCAL_DEV=False, CORS_ALLOWED_ORIGINS=["https://localhost", "capacitor://localhost"])
    def test_mobile_origins_are_allowed_only_when_configured(self):
        for origin in ("https://localhost", "capacitor://localhost"):
            r = self.client.options("/api/sales/", HTTP_ORIGIN=origin, HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
            self.assertEqual(r["Access-Control-Allow-Origin"], origin)
            self.assertIn("Authorization", r["Access-Control-Allow-Headers"])
        r = self.client.options("/api/sales/", HTTP_ORIGIN="https://other.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", r)

    def test_frontend_is_served_by_django_in_development(self):
        for url in ("/", "/Nexa.html"):
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r["Content-Type"], "text/html; charset=utf-8")
            html = r.content.decode()
            self.assertIn("<title>Nexa", html)
            self.assertIn('window.NEXA_API = location.origin + "/api";', html)
            self.assertIn('href="Nexa.css"', html)
            self.assertIn('src="Nexa.js"', html)

    def test_frontend_assets_are_served_by_django(self):
        for path, content_type, marker in (
            ("/Nexa.css", "text/css; charset=utf-8", b"--bg:"),
            ("/Nexa.js", "application/javascript; charset=utf-8", b"createRoot"),
        ):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response["Content-Type"], content_type)
            self.assertEqual(response["Cache-Control"], "no-cache")
            self.assertIn(marker, b"".join(response.streaming_content))
            response.close()
        self.assertEqual(self.client.get("/Nexa.jsx").status_code, 404)

    @override_settings(ADMIN_LOCAL_ONLY=True)
    def test_admin_is_hidden_from_tunnelled_requests_when_local_only(self):
        self.assertEqual(self.client.get("/admin/login/").status_code, 200)
        for header in ("HTTP_CF_CONNECTING_IP", "HTTP_X_FORWARDED_FOR"):
            self.assertEqual(self.client.get("/admin/login/", **{header: "203.0.113.9"}).status_code, 404)
        self.assertEqual(self.client.get("/api/me/", HTTP_CF_CONNECTING_IP="203.0.113.9").status_code, 401)

    @override_settings(ADMIN_LOCAL_ONLY=False)
    def test_admin_is_reachable_through_a_proxy_when_not_local_only(self):
        self.assertEqual(self.client.get("/admin/login/", HTTP_X_FORWARDED_FOR="203.0.113.9").status_code, 200)

    def test_assistant_requires_authentication_and_valid_question(self):
        unauthenticated = self.client.post(
            "/api/assistant/chat/", {"question": "How am I doing?"}, content_type="application/json"
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": " "}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "x" * 1001}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "How am I doing?", "month": "Nov"}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "x" * 5000}).status_code, 413)

    @patch("api.insights.assistant.generate_answer", return_value="Steady.")
    def test_assistant_rate_limit_persists_in_database_cache(self, _):
        self.assertIsInstance(caches["default"], DatabaseCache)
        for _ in range(10):
            self.assertEqual(self.post("/api/assistant/chat/", {"question": "How am I doing?"}).status_code, 200)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "How am I doing?"}).status_code, 429)

    @patch("api.insights.assistant.generate_answer", return_value="Revenue was $120.")
    def test_assistant_uses_only_requesting_owners_aggregated_financial_context(self, generate_answer):
        self.post("/api/sales/", {"amount": "100", "customer": "Private customer"})
        product = self.product(name="Private product", category="Footwear")
        self.post("/api/receive/", {"product_id": product["id"], "quantity": 1, "unit_cost": "10"})
        self.post("/api/sales/", {"amount": "20", "product_id": product["id"], "quantity": 1})
        self.post("/api/expenses/", {"category": "Rent", "amount": "30"})
        self.post("/api/sales/", {"amount": "9000"}, self.other_h)

        response = self.post("/api/assistant/chat/", {
            "question": "How did I do this month?",
            "month": timezone.localdate().strftime("%Y-%m"),
        })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "answer": "Revenue was $120.",
            "period": timezone.localdate().strftime("%Y-%m"),
        })
        question, context = generate_answer.call_args.args
        self.assertEqual(question, "How did I do this month?")
        self.assertEqual(context["summary"]["revenue"], "120.00")
        self.assertEqual(context["summary"]["expenses"], "30.00")
        self.assertIsNone(context["change_vs_previous_pct"]["revenue"])
        self.assertEqual(context["top_product_categories"][0]["category"], "Footwear")
        self.assertNotIn("9000", str(context))
        self.assertNotIn("Private customer", str(context))
        self.assertNotIn("Private product", str(context))

    @override_settings(NEXA_AI_API_KEY="")
    def test_assistant_reports_missing_provider_configuration(self):
        response = self.post("/api/assistant/chat/", {"question": "How am I doing?"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "The AI assistant is not configured yet.")

    @patch("api.insights.assistant.generate_answer", return_value="Try tracking weekly costs.")
    def test_assistant_rate_limits_repeated_requests(self, generate_answer):
        body = {"question": "What should I focus on?"}
        responses = [self.post("/api/assistant/chat/", body) for _ in range(11)]
        self.assertEqual([response.status_code for response in responses[:10]], [200] * 10)
        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(generate_answer.call_count, 10)

    @override_settings(NEXA_AI_API_KEY="server-only-key", NEXA_AI_MODEL="test-model")
    @patch("api.insights.assistant.urlopen")
    def test_assistant_provider_uses_server_key_and_parses_response(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = (
            b'{"choices":[{"message":{"content":"A grounded answer."}}]}'
        )
        answer = ai.generate_answer("How did I do?", {"period": "2026-10", "currency": "USD"})

        self.assertEqual(answer, "A grounded answer.")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer server-only-key")
        self.assertEqual(
            request.full_url,
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertIn("Question: How did I do?", request.data.decode())
        self.assertEqual(json.loads(request.data)["model"], "test-model")

    @override_settings(NEXA_AI_API_KEY="server-only-key")
    @patch("api.insights.assistant.urlopen", side_effect=HTTPError("https://generativelanguage.googleapis.com", 429, "busy", {}, None))
    def test_assistant_provider_errors_are_sanitized(self, _urlopen):
        with self.assertRaises(svc.ServiceError) as error:
            ai.generate_answer("Question", {"period": "2026-10"})

        self.assertEqual(error.exception.status, 502)
        self.assertNotIn("server-only-key", error.exception.message)

    @override_settings(NEXA_AI_API_KEY="server-only-key")
    @patch("api.insights.assistant.urlopen")
    def test_assistant_provider_rejects_responses_without_answer_text(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"choices":[{"message":{"content":null}}]}'
        with self.assertRaises(svc.ServiceError) as error:
            ai.generate_answer("Question", {"period": "2026-10"})

        self.assertEqual(error.exception.status, 502)

    def test_algorithm_endpoint_requires_authentication_and_valid_analysis(self):
        response = self.client.post(
            "/api/assistant/analyze/",
            {"analysis": "profitability"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.post("/api/assistant/analyze/", {"analysis": "unknown"}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/analyze/", {"analysis": "profitability", "month": "Nov"}).status_code, 400)

    def test_algorithm_analyses_handle_empty_periods_without_division_errors(self):
        month = timezone.localdate().strftime("%Y-%m")
        for analysis in ("profitability", "sales_trends", "expense_analysis", "product_rankings", "stock_cover",
                         "reorder_planning", "aging_inventory", "break_even", "customer_concentration", "cash_indicators"):
            response = self.post("/api/assistant/analyze/", {"analysis": analysis, "month": month})
            self.assertEqual(response.status_code, 200, analysis)
        profitability = self.post(
            "/api/assistant/analyze/", {"analysis": "profitability", "month": month}
        ).json()
        self.assertIsNone(profitability["metrics"][3]["value"])
        self.assertIsNone(profitability["metrics"][6]["value"])

    @patch("api.insights.algorithms.timezone.localdate", return_value=date(2026, 11, 10))
    def test_new_analyses_calculate_values_and_preserve_owner_isolation(self, today):
        product = m.Product.objects.create(owner=self.user, name="Widget", price="20", cost="5")
        foreign = m.Product.objects.create(owner=self.other, name="Other stock", price="20", cost="5")
        m.StockBatch.objects.create(owner=self.user, product=product, quantity_received=10, quantity_left=10, unit_cost="5", received_on=date(2026, 9, 25))
        m.StockBatch.objects.create(owner=self.user, product=product, quantity_received=3, quantity_left=3, unit_cost="8", received_on=date(2026, 9, 26))
        m.StockBatch.objects.create(owner=self.other, product=foreign, quantity_received=100, quantity_left=100, unit_cost="20", received_on=date(2026, 1, 1))
        m.Purchase.objects.create(owner=self.user, product=product, quantity=5, unit_cost="5")
        customer = m.Customer.objects.create(owner=self.user, name="Alice")
        m.Sale.objects.create(owner=self.user, customer=customer, product=product, quantity=10, amount="200", cogs="80", date=date(2026, 11, 1))
        m.Sale.objects.create(owner=self.user, product=product, quantity=10, amount="100", cogs="40", status=m.Sale.PENDING, date=date(2026, 11, 2))
        m.Sale.objects.create(owner=self.user, amount="100", cogs="60", date=date(2026, 11, 3))
        m.Sale.objects.create(owner=self.other, amount="9000", cogs="100", date=date(2026, 11, 1))
        m.Expense.objects.create(owner=self.user, amount="80", date=date(2026, 11, 2))
        m.Expense.objects.create(owner=self.other, amount="9999", date=date(2026, 11, 2))

        def report(name):
            response = self.post("/api/assistant/analyze/", {"analysis": name, "month": "2026-11"})
            self.assertEqual(response.status_code, 200, response.content)
            self.assertNotIn("Other stock", str(response.json()))
            return response.json()

        reorder = report("reorder_planning")["reorders"][0]
        self.assertEqual((reorder["stock"], reorder["incoming"], reorder["units_sold"]), (13, 5, 20))
        self.assertEqual((reorder["reorder_point"], reorder["suggested_quantity"]), (42, 56))
        inventory = report("aging_inventory")
        self.assertEqual([x["value"] for x in inventory["metrics"]], ["74.00", "50.00", "10"])
        self.assertEqual(inventory["inventory"][0]["aged_units"], 10)
        breakeven = report("break_even")
        self.assertEqual([x["value"] for x in breakeven["metrics"]], ["300.00", "53.3", "80.00", "150.00"])
        concentration = report("customer_concentration")
        self.assertEqual([x["value"] for x in concentration["metrics"]], ["300.00", "66.7", "66.7", "100.00"])
        self.assertEqual(concentration["customer_rows"][0]["customer"], "Alice")
        cash = report("cash_indicators")
        self.assertEqual([x["value"] for x in cash["metrics"]], ["300.00", "80.00", "220.00", "100.00"])

    @patch("api.insights.algorithms.timezone.localdate", return_value=date(2026, 11, 10))
    def test_reorder_future_no_demand_and_orders_cover_threshold(self, today):
        product = m.Product.objects.create(owner=self.user, name="Widget", price="20", cost="5")
        m.Sale.objects.create(owner=self.user, product=product, quantity=10, amount="100", date=date(2026, 11, 1))
        m.Sale.objects.create(owner=self.user, product=product, quantity=900, amount="100", date=date(2026, 11, 20))
        m.Purchase.objects.create(owner=self.user, product=product, quantity=21, unit_cost="5")
        future = self.post("/api/assistant/analyze/", {"analysis": "reorder_planning", "month": "2026-12"}).json()
        self.assertIsNone(future["reorders"][0]["reorder_point"])
        self.assertEqual(future["reorders"][0]["status"], "No demand data")
        current = self.post("/api/assistant/analyze/", {"analysis": "reorder_planning", "month": "2026-11"}).json()
        self.assertEqual(current["reorders"][0]["units_sold"], 10)
        self.assertEqual(current["reorders"][0]["suggested_quantity"], 16)
        m.Purchase.objects.create(owner=self.user, product=product, quantity=1, unit_cost="5")
        current = self.post("/api/assistant/analyze/", {"analysis": "reorder_planning", "month": "2026-11"}).json()
        self.assertEqual(current["reorders"][0]["suggested_quantity"], 0)

    def test_break_even_unavailable_when_margin_not_positive(self):
        today = timezone.localdate()
        m.Sale.objects.create(owner=self.user, amount="100", cogs="120", date=today)
        response = self.post("/api/assistant/analyze/", {"analysis": "break_even", "month": today.strftime("%Y-%m")})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["metrics"][3]["value"])

    def test_expense_analysis_reports_unchanged_categories_without_false_direction(self):
        today = timezone.localdate()
        previous_year, previous_month = svc.previous_month(today.year, today.month)
        previous_date = timezone.datetime(previous_year, previous_month, 1).date()
        m.Expense.objects.create(owner=self.user, date=previous_date, category="Rent", amount="20")
        m.Expense.objects.create(owner=self.user, date=today, category="Rent", amount="20")

        response = self.post("/api/assistant/analyze/", {
            "analysis": "expense_analysis",
            "month": today.strftime("%Y-%m"),
        })

        self.assertEqual(response.status_code, 200)
        self.assertTrue(any("Rent was unchanged" in insight for insight in response.json()["insights"]))

    def test_algorithm_analyses_are_deterministic_and_owner_scoped(self):
        today = timezone.localdate()
        year, month = today.year, today.month
        previous_year, previous_month = svc.previous_month(year, month)
        previous_date = timezone.datetime(previous_year, previous_month, 1).date()
        product_a = self.product(name="Alpha", category="Shoes")
        product_b = self.product(name="Beta", category="Accessories")
        foreign_product = m.Product.objects.create(
            owner=self.other, name="Foreign product", category="Other", price="50", cost="20"
        )
        m.Sale.objects.create(owner=self.user, date=previous_date, amount="100", cogs="50")
        m.Expense.objects.create(owner=self.user, date=previous_date, category="Rent", amount="20")
        m.Sale.objects.create(
            owner=self.user, product_id=product_a["id"], date=today, amount="120", cogs="60", quantity=2
        )
        m.Sale.objects.create(
            owner=self.user, product_id=product_b["id"], date=today, amount="80", cogs="40", quantity=1
        )
        m.Sale.objects.create(
            owner=self.other, product=foreign_product, date=today, amount="500", cogs="200", quantity=10
        )
        m.Expense.objects.create(owner=self.user, date=today, category="Rent", amount="30")
        m.Sale.objects.create(
            owner=self.user, product_id=product_a["id"], date=today, amount="300", cogs="150", quantity=3,
            status=m.Sale.PENDING,
        )
        m.Expense.objects.create(owner=self.user, date=today, category="Transport", amount="10")
        request = {"month": today.strftime("%Y-%m")}

        profitability = self.post(
            "/api/assistant/analyze/", {**request, "analysis": "profitability"}
        ).json()
        self.assertEqual(profitability["metrics"][2]["value"], "60.00")
        self.assertEqual(profitability["metrics"][4]["value"], "30.0")
        self.assertEqual(profitability["metrics"][5]["value"], "20.0")
        self.assertEqual(profitability["metrics"][6]["value"], "100.0")

        trends = self.post(
            "/api/assistant/analyze/", {**request, "analysis": "sales_trends"}
        ).json()
        self.assertEqual(len(trends["series"]), 6)
        self.assertEqual(trends["metrics"][0]["value"], "200.00")
        self.assertEqual(trends["metrics"][3]["value"], "100.00")

        expenses = self.post(
            "/api/assistant/analyze/", {**request, "analysis": "expense_analysis"}
        ).json()
        self.assertEqual(expenses["categories"][0]["category"], "Rent")
        self.assertEqual(expenses["categories"][0]["change_pct"], "50.0")
        self.assertEqual(expenses["metrics"][0]["value"], "40.00")

        products = self.post(
            "/api/assistant/analyze/", {**request, "analysis": "product_rankings"}
        ).json()
        self.assertEqual(products["products"][0]["product"], "Alpha")
        self.assertEqual(products["products"][0]["gross_profit"], "60.00")
        self.assertEqual(products["products"][0]["revenue"], "120.00")
        self.assertEqual(products["products"][0]["units"], 2)
        self.assertNotIn("Foreign product", str(products))
        self.assertNotIn("500.00", str(products))

    def test_stock_cover_projects_reorder_from_sales_rate(self):
        ids = {name: self.product(name=name)["id"] for name in ("Alpha", "Gamma", "Epsilon", "Beta")}
        for name, quantity in {"Alpha": 100, "Gamma": 46, "Epsilon": 500}.items():
            self.post("/api/receive/", {"product_id": ids[name], "quantity": quantity, "unit_cost": "5"})
        for name, quantity in {"Alpha": 62, "Gamma": 31, "Epsilon": 31}.items():
            svc.record_sale(
                self.user, amount=Decimal("100"), product=m.Product.objects.get(pk=ids[name]),
                quantity=quantity, on=date(2025, 10, 15),
            )
        svc.record_sale(
            self.user, amount=Decimal("10"), product=m.Product.objects.get(pk=ids["Gamma"]),
            quantity=10, on=date(2025, 11, 2),
        )

        response = self.post("/api/assistant/analyze/", {"analysis": "stock_cover", "month": "2025-10"})

        self.assertEqual(response.status_code, 200)
        report = response.json()
        self.assertEqual(report["period"], "2025-10")
        self.assertEqual([row["product"] for row in report["stock"]], ["Beta", "Gamma", "Alpha", "Epsilon"])
        rows = {row["product"]: row for row in report["stock"]}
        self.assertEqual(rows["Alpha"]["stock"], 38)
        self.assertEqual(rows["Alpha"]["daily_rate"], "2.0")
        self.assertEqual(rows["Alpha"]["days_cover"], "19.0")
        self.assertEqual(rows["Alpha"]["status"], "Watch")
        self.assertEqual(rows["Alpha"]["reorder_qty"], 22)
        self.assertEqual(rows["Gamma"]["stock"], 5)
        self.assertEqual(rows["Gamma"]["status"], "Reorder now")
        self.assertEqual(rows["Gamma"]["reorder_qty"], 25)
        self.assertEqual(rows["Epsilon"]["status"], "Healthy")
        self.assertEqual(rows["Epsilon"]["reorder_qty"], 0)
        self.assertEqual(rows["Beta"]["status"], "Out of stock")
        self.assertIsNone(rows["Beta"]["days_cover"])
        self.assertEqual([metric["value"] for metric in report["metrics"]], ["4", "2", "124"])
        self.assertIn("Sales rates use 31 day(s) of 2025-10. Reorder when cover is under 14 days, aiming for 30 days.", report["insights"])
        self.assertIn("Beta is out of stock.", report["insights"])
        self.assertIn("Gamma has 5.0 days of cover. Reorder about 25 units.", report["insights"])

    def test_stock_cover_waits_for_a_month_that_has_started(self):
        self.product(name="Alpha")
        report = self.post("/api/assistant/analyze/", {"analysis": "stock_cover", "month": "2999-01"}).json()
        self.assertIn("2999-01 has not started yet, so there are no sales to measure.", report["insights"])
        self.assertTrue(all(row["days_cover"] is None for row in report["stock"]))

    def test_goal_bounds_for_each_period(self):
        today = date(2026, 10, 14)  # a Wednesday
        self.assertEqual(svc.goal_bounds("day", today), (date(2026, 10, 14), date(2026, 10, 14)))
        self.assertEqual(svc.goal_bounds("week", today), (date(2026, 10, 12), date(2026, 10, 18)))
        self.assertEqual(svc.goal_bounds("month", today), (date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(svc.goal_bounds("year", today), (date(2026, 1, 1), date(2026, 12, 31)))

    def test_revenue_goal_defaults_and_is_per_owner(self):
        settings_response = self.client.get("/api/settings/", **self.h).json()
        self.assertEqual(
            (settings_response["revenue_goal"], settings_response["goal_period"], settings_response["progress"]),
            (None, "month", None),
        )
        self.assertEqual(settings_response["currency"], "USD")
        self.assertEqual(settings_response["theme"], "light")
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "900"}),
                          content_type="application/json", **self.h)
        self.assertIsNone(self.client.get("/api/settings/", **self.other_h).json()["revenue_goal"])

    def test_settings_validate_and_persist_preferences_per_owner(self):
        def save(body):
            return self.client.patch(
                "/api/settings/", json.dumps(body), content_type="application/json", **self.h,
            )

        self.assertEqual(save({"low_stock_threshold": "1.1"}).status_code, 400)
        self.assertEqual(save({"currency": "EUR"}).status_code, 400)
        saved = save({
            "theme": "dark", "currency": "EUR", "confirm_currency_change": True,
            "time_zone": "UTC", "business_name": "North Shop", "low_stock_threshold": "0.5",
            "slow_stock_days": 60, "reorder_lead_days": 10, "safety_stock_days": 5,
            "reorder_target_days": 24,
        })
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["currency"], "EUR")
        self.assertEqual(saved.json()["theme"], "dark")
        self.assertEqual(saved.json()["time_zone"], "UTC")
        self.assertEqual(saved.json()["business_name"], "North Shop")
        self.assertEqual(Decimal(saved.json()["low_stock_threshold"]), Decimal("0.500"))
        other = self.client.get("/api/settings/", **self.other_h).json()
        self.assertEqual(other["currency"], "USD")
        self.assertEqual(other["time_zone"], "Africa/Harare")

    def test_business_logo_upload_replace_remove_and_owner_isolation(self):
        def save(body):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.patch("/api/settings/", json.dumps(body), content_type="application/json", **self.h)

        response = save({"business_name": "North Shop", "business_logo": PNG_URL})
        self.assertEqual(response.status_code, 200)
        first_url = response.json()["business_logo_url"]
        self.assertEqual(response.json()["business_name"], "North Shop")
        self.assertEqual(self.image_status(first_url), 200)
        self.assertEqual(self.client.get("/api/settings/", **self.h).json()["business_logo_url"], first_url)
        self.assertEqual(self.client.get("/api/settings/", **self.other_h).json()["business_logo_url"], "")

        invalid = save({"business_name": "Wrong", "business_logo": "data:image/png;base64,invalid!"})
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(self.client.get("/api/settings/", **self.h).json()["business_name"], "North Shop")
        self.assertEqual(self.image_status(first_url), 200)

        response = save({"business_logo": JPEG_URL})
        second_url = response.json()["business_logo_url"]
        self.assertNotEqual(first_url, second_url)
        self.assertEqual(self.image_status(first_url), 404)
        self.assertEqual(self.image_status(second_url), 200)
        self.assertEqual(save({"business_logo": ""}).json()["business_logo_url"], "")
        self.assertEqual(self.image_status(second_url), 404)

    @override_settings(STORAGES={
        "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    })
    def test_company_logo_uses_configured_nonfilesystem_storage(self):
        from django.core.files.storage import default_storage

        with self.captureOnCommitCallbacks(execute=True):
            uploaded = self.client.patch(
                "/api/settings/", json.dumps({"business_logo": PNG_URL}), content_type="application/json", **self.h,
            )
        self.assertEqual(uploaded.status_code, 200)
        url = uploaded.json()["business_logo_url"]
        key = m.UserSettings.objects.get(owner=self.user).business_logo_key
        self.assertTrue(default_storage.exists(f"products/{key}/400.webp"))
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(b"".join(response.streaming_content))
        response.close()
        with self.captureOnCommitCallbacks(execute=True):
            removed = self.client.patch(
                "/api/settings/", json.dumps({"business_logo": ""}), content_type="application/json", **self.h,
            )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(default_storage.exists(f"products/{key}/400.webp"))
        self.assertEqual(self.image_status(url), 404)

    def test_partial_image_write_is_cleaned_up(self):
        names = []

        def save(name, content):
            if names:
                raise OSError("storage unavailable")
            names.append(name)
            return name

        with patch("api.images.default_storage") as storage:
            storage.save.side_effect = save
            with self.assertRaisesRegex(OSError, "storage unavailable"):
                images.save({120: b"first", 400: b"second"})
            storage.delete.assert_called_once_with(names[0])

    def test_scalability_storage_and_cache_configuration(self):
        settings_file = Path(__file__).resolve().parents[2] / "nexa" / "settings.py"
        environment = {
            "NEXA_MEDIA_STORAGE": "r2",
            "NEXA_R2_BUCKET": "test-bucket",
            "NEXA_R2_ENDPOINT": "https://example.r2.cloudflarestorage.com",
            "NEXA_R2_ACCESS_KEY_ID": "test-key",
            "NEXA_R2_SECRET_ACCESS_KEY": "test-secret",
            "NEXA_REDIS_URL": "redis://localhost:6379/0",
        }
        with patch.dict(os.environ, environment):
            settings_data = runpy.run_path(str(settings_file))
            self.assertEqual(settings_data["STORAGES"]["default"]["BACKEND"], "storages.backends.s3.S3Storage")
            self.assertEqual(settings_data["CACHES"]["default"]["BACKEND"], "django.core.cache.backends.redis.RedisCache")
            with patch.dict(os.environ, {"NEXA_R2_ENDPOINT": "http://example.test"}):
                with self.assertRaisesRegex(RuntimeError, "HTTPS origin"):
                    runpy.run_path(str(settings_file))
            with patch.dict(os.environ, {"NEXA_REDIS_URL": "http://example.test"}):
                with self.assertRaisesRegex(RuntimeError, "NEXA_REDIS_URL"):
                    runpy.run_path(str(settings_file))

    def test_logo_framing_is_saved_per_account_and_validated(self):
        def save(body):
            return self.client.patch("/api/settings/", json.dumps(body), content_type="application/json", **self.h)

        defaults = self.client.get("/api/settings/", **self.h).json()
        self.assertEqual(
            (defaults["business_logo_zoom"], defaults["business_logo_x"], defaults["business_logo_y"]),
            (100, 0, 0),
        )
        values = {"business_logo_zoom": 300, "business_logo_x": -100, "business_logo_y": 100}
        self.assertEqual(save(values).status_code, 200)
        persisted = self.client.get("/api/settings/", **self.h).json()
        self.assertEqual({field: persisted[field] for field in values}, values)
        other = self.client.get("/api/settings/", **self.other_h).json()
        self.assertEqual((other["business_logo_zoom"], other["business_logo_x"], other["business_logo_y"]), (100, 0, 0))
        for field, value in (
            ("business_logo_zoom", 99), ("business_logo_zoom", 301), ("business_logo_x", -101),
            ("business_logo_y", 101), ("business_logo_y", 1.5), ("business_logo_x", True),
            ("business_logo_zoom", "100"),
        ):
            with self.subTest(field=field, value=value):
                self.assertEqual(save({field: value, "business_name": "Must not save"}).status_code, 400)
        persisted = self.client.get("/api/settings/", **self.h).json()
        self.assertEqual({field: persisted[field] for field in values}, values)
        self.assertEqual(persisted["business_name"], "")

    def test_company_names_are_unique_across_accounts_and_released_on_change(self):
        def save(body, headers):
            return self.client.patch("/api/settings/", json.dumps(body), content_type="application/json", **headers)

        self.assertEqual(save({"business_name": "North Shop"}, self.h).status_code, 200)
        duplicate = save({"business_name": "  NORTH   shop "}, self.other_h)
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("company name is already in use", duplicate.json()["error"])
        self.assertEqual(self.client.get("/api/settings/", **self.other_h).json()["business_name"], "")
        fingerprint = m.UserSettings.objects.get(owner=self.user).business_name_fingerprint
        with self.assertRaises(IntegrityError), transaction.atomic():
            m.UserSettings.objects.filter(owner=self.other).update(business_name_fingerprint=fingerprint)
        self.assertEqual(save({"business_name": " north shop "}, self.h).status_code, 200)
        self.assertEqual(save({"business_name": ""}, self.h).status_code, 200)
        self.assertEqual(save({"business_name": "North Shop"}, self.other_h).status_code, 200)

    def test_company_logo_conflict_preserves_settings_and_cleans_upload(self):
        def save(body, headers):
            with self.captureOnCommitCallbacks(execute=True):
                return self.client.patch("/api/settings/", json.dumps(body), content_type="application/json", **headers)

        first = save({"business_logo": PNG_URL}, self.h)
        self.assertEqual(first.status_code, 200)
        before = self.stored_images()
        duplicate = save({"business_name": "Other Shop", "business_logo": PNG_URL}, self.other_h)
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("company logo is already in use", duplicate.json()["error"])
        self.assertEqual(self.stored_images(), before)
        self.assertEqual(self.client.get("/api/settings/", **self.other_h).json()["business_name"], "")
        self.assertEqual(save({"business_logo": PNG_URL}, self.h).status_code, 200)
        self.assertEqual(save({"business_logo": ""}, self.h).status_code, 200)
        self.assertEqual(save({"business_logo": PNG_URL}, self.other_h).status_code, 200)

    def test_identity_migration_stops_on_existing_duplicates_or_missing_logo(self):
        migration = importlib.import_module("api.migrations.0013_unique_business_identity")
        manager = m.UserSettings.objects
        manager.filter(owner=self.user).update(business_name="North Shop")
        manager.filter(owner=self.other).update(business_name=" north  SHOP ")
        with self.assertRaisesRegex(RuntimeError, "Duplicate company names"):
            migration.populate_fingerprints(apps, SimpleNamespace(connection=connection))
        self.assertFalse(manager.filter(business_name_fingerprint__isnull=False).exists())
        manager.filter(owner=self.other).update(business_name="", business_logo_key="a" * 32)
        with self.assertRaisesRegex(RuntimeError, "company logo cannot be read"):
            migration.populate_fingerprints(apps, SimpleNamespace(connection=connection))
        self.assertFalse(manager.filter(business_name_fingerprint__isnull=False).exists())
        variants = images.render(encoded("PNG", (64, 64)))
        first_key, second_key = images.save(variants), images.save(variants)
        manager.filter(owner=self.user).update(business_logo_key=first_key)
        manager.filter(owner=self.other).update(business_logo_key=second_key)
        with self.assertRaisesRegex(RuntimeError, "Duplicate company logos"):
            migration.populate_fingerprints(apps, SimpleNamespace(connection=connection))
        self.assertFalse(manager.filter(business_name_fingerprint__isnull=False).exists())
        manager.filter(owner=self.other).update(business_logo_key="")
        migration.populate_fingerprints(apps, SimpleNamespace(connection=connection))
        first = manager.get(owner=self.user)
        self.assertEqual(first.business_name_fingerprint, m.business_name_fingerprint("North Shop"))
        self.assertTrue(first.business_logo_fingerprint)

    def test_configured_low_stock_threshold_drives_product_and_dashboard_flags(self):
        product = self.product(target_stock=100)
        self.post("/api/receive/", {"product_id": product["id"], "quantity": 40, "unit_cost": "5"})
        self.client.patch(
            "/api/settings/", json.dumps({"low_stock_threshold": "0.5"}),
            content_type="application/json", **self.h,
        )
        products = self.client.get("/api/products/", **self.h).json()
        self.assertTrue(products[0]["low_stock"])
        dashboard = self.client.get("/api/dashboard/", **self.h).json()
        self.assertEqual(dashboard["low_stock"], ["Earbuds"])

    def test_account_export_requires_email_confirmation_and_is_owner_scoped(self):
        prefs, _ = m.UserSettings.objects.get_or_create(owner=self.user)
        prefs.email_verified = True
        prefs.business_logo_zoom = 150
        prefs.save(update_fields=["email_verified", "business_logo_zoom"])
        m.Product.objects.create(owner=self.user, name="Mine", price=10, cost=5)
        m.Product.objects.create(owner=self.other, name="Not mine", price=10, cost=5)
        with patch.object(svc, "email_delivery_configured", return_value=True), override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ):
            self.assertEqual(self.post("/api/account/confirm/", {"action": "export"}).status_code, 200)
            token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
            response = self.post(
                "/api/account/export/", {"token": token, "confirmation": "EXPORT"}, {},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mine", response.content.decode())
        self.assertNotIn("Not mine", response.content.decode())
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        settings_row = next(row for row in rows if row["record_type"] == "settings")
        self.assertEqual(json.loads(settings_row["data"])["business_logo_zoom"], 150)
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(self.post(
            "/api/account/export/", {"token": token, "confirmation": "EXPORT"}, {},
        ).status_code, 403)

    @patch("api.views.timezone.localdate", return_value=date(2026, 2, 10))
    def test_reports_preserve_monthly_totals_and_owner_isolation(self, today):
        m.Sale.objects.create(owner=self.user, date=date(2025, 12, 1), status="Paid", amount=100, cogs=40)
        m.Sale.objects.create(owner=self.user, date=date(2026, 1, 5), status="Pending", amount=500, cogs=50)
        m.Sale.objects.create(owner=self.user, date=date(2026, 2, 20), status="Paid", amount=50, cogs=20)
        m.Sale.objects.create(owner=self.other, date=date(2025, 12, 1), status="Paid", amount=9000, cogs=0)
        m.Expense.objects.create(owner=self.user, date=date(2025, 12, 3), amount=10)
        m.Expense.objects.create(owner=self.user, date=date(2026, 1, 3), amount=7)
        m.Expense.objects.create(owner=self.other, date=date(2025, 12, 3), amount=999)
        response = self.client.get("/api/reports/", **self.h)
        self.assertEqual(response.status_code, 200)
        rows = response.json()
        self.assertEqual([row["month"] for row in rows], ["2025-12", "2026-01", "2026-02"])
        self.assertEqual(
            [tuple(Decimal(row[k]) for k in ("revenue", "expenses", "gross_profit", "net_profit")) for row in rows],
            [(100, 10, 60, 50), (0, 7, 0, -7), (50, 0, 30, 30)],
        )

    @patch("api.views.timezone.localdate", return_value=date(2026, 2, 10))
    def test_reports_queries_do_not_grow_with_history(self, today):
        sale = m.Sale.objects.create(owner=self.user, date=date(2026, 2, 1), amount=100, cogs=40)
        recent_queries = self.query_count("/api/reports/")
        sale.date = date(2020, 1, 1)
        sale.save(update_fields=["date"])
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get("/api/reports/", **self.h)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 74)
        self.assertEqual(len(queries), recent_queries)
        self.assertLessEqual(len(queries), 6)

    @patch("api.views.timezone.localdate", return_value=date(2026, 2, 10))
    def test_reports_without_sales_and_with_only_future_sales(self, today):
        m.Expense.objects.create(owner=self.user, date=date(2026, 2, 5), amount=7)
        row = self.client.get("/api/reports/", **self.h).json()[0]
        self.assertEqual((row["month"], Decimal(row["expenses"]), Decimal(row["net_profit"])), ("2026-02", 7, -7))
        m.Sale.objects.create(owner=self.user, date=date(2026, 3, 1), amount=100, cogs=40)
        self.assertEqual(self.client.get("/api/reports/", **self.h).json(), [])

    def test_month_summary_weekly_sales_include_paid_and_pending(self):
        for day, amount, status in (
            (1, 10, "Paid"), (7, 20, "Pending"), (8, 30, "Paid"),
            (15, 40, "Paid"), (22, 50, "Paid"), (31, 60, "Pending"),
        ):
            m.Sale.objects.create(owner=self.user, date=date(2026, 1, day), amount=amount, cogs=0, status=status)
        m.Sale.objects.create(owner=self.other, date=date(2026, 1, 1), amount=999, cogs=0)
        result = svc.month_summary(self.user, 2026, 1)
        self.assertEqual(result["weekly_sales"], [30, 30, 40, 110])
        self.assertEqual(result["revenue"], 130)

    def test_account_deletion_requires_confirmed_email_link(self):
        prefs, _ = m.UserSettings.objects.get_or_create(owner=self.user)
        prefs.email_verified = True
        prefs.save(update_fields=["email_verified"])
        image_url = self.upload()
        logo_response = self.client.patch(
            "/api/settings/", json.dumps({"business_logo": PNG_URL}), content_type="application/json", **self.h,
        )
        self.assertEqual(logo_response.status_code, 200)
        logo_url = logo_response.json()["business_logo_url"]
        m.MagicLink.objects.create(email=self.user.email, token_hash="a" * 64, expires_at=timezone.now())
        m.LoginAttempt.objects.create(username=self.user.username)
        with patch.object(svc, "email_delivery_configured", return_value=True), override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ):
            self.assertEqual(self.post("/api/account/confirm/", {"action": "delete"}).status_code, 200)
            token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
            self.assertEqual(self.post(
                "/api/account/delete/", {"token": token, "confirmation": "NO"}, {},
            ).status_code, 400)
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(
                    "/api/account/delete/", {"token": token, "confirmation": "DELETE"}, {},
                )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(pk=self.user.pk).exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.other.pk).exists())
        self.assertFalse(m.MagicLink.objects.filter(email__iexact=self.user.email).exists())
        self.assertFalse(m.LoginAttempt.objects.filter(username__iexact=self.user.username).exists())
        self.assertEqual(self.image_status(image_url), 404)
        self.assertEqual(self.image_status(logo_url), 404)

    def test_email_alerts_are_opt_in_and_deduplicated_until_resolved(self):
        prefs, _ = m.UserSettings.objects.get_or_create(owner=self.user)
        prefs.email_verified = True
        prefs.revenue_goal = Decimal("10")
        prefs.notify_goal_reached = True
        prefs.save()
        m.Sale.objects.create(owner=self.user, amount=Decimal("10"), date=timezone.localdate())
        with patch.object(svc, "email_delivery_configured", return_value=True), override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.get("/api/dashboard/", **self.h)
                self.client.get("/api/dashboard/", **self.h)
            self.assertEqual(len(mail.outbox), 1)

    @override_settings(NEXA_ASYNC_ALERTS=True)
    def test_queued_alerts_retry_and_do_not_block_requests(self):
        prefs = m.UserSettings.objects.get(owner=self.user)
        prefs.email_verified = True
        prefs.revenue_goal = Decimal("10")
        prefs.notify_goal_reached = True
        prefs.save()
        m.Sale.objects.create(owner=self.user, amount=Decimal("10"), date=timezone.localdate())
        with patch.object(svc, "email_delivery_configured", return_value=True), override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ):
            self.assertEqual(self.client.get("/api/dashboard/", **self.h).status_code, 200)
            self.assertEqual(self.client.get("/api/dashboard/", **self.h).status_code, 200)
            self.assertEqual(m.NotificationDelivery.objects.count(), 1)
            self.assertEqual(len(mail.outbox), 0)
            with patch.object(svc, "send_mail", side_effect=OSError("temporary failure")):
                self.assertTrue(svc.process_alert_delivery())
            delivery = m.NotificationDelivery.objects.get(owner=self.user)
            self.assertEqual(delivery.attempts, 1)
            self.assertGreater(delivery.available_at, timezone.now())
            self.assertFalse(svc.process_alert_delivery())
            m.NotificationDelivery.objects.filter(pk=delivery.pk).update(available_at=timezone.now())
            self.assertTrue(svc.process_alert_delivery())
            self.assertFalse(m.NotificationDelivery.objects.exists())
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(self.client.get("/api/dashboard/", **self.h).status_code, 200)
            self.assertFalse(m.NotificationDelivery.objects.exists())

    @override_settings(NEXA_ASYNC_ALERTS=True)
    def test_alert_queue_rolls_back_with_notification_state(self):
        prefs = m.UserSettings.objects.get(owner=self.user)
        prefs.email_verified = True
        prefs.revenue_goal = Decimal("10")
        prefs.notify_goal_reached = True
        prefs.save()
        m.Sale.objects.create(owner=self.user, amount=Decimal("10"), date=timezone.localdate())
        with self.assertRaises(RuntimeError), transaction.atomic():
            svc.sync_email_notifications(self.user)
            self.assertEqual(m.NotificationDelivery.objects.count(), 1)
            raise RuntimeError("roll back")
        self.assertFalse(m.NotificationDelivery.objects.exists())
        self.assertFalse(m.NotificationState.objects.filter(owner=self.user).exists())

    def test_alert_worker_reclaims_expired_leases(self):
        delivery = m.NotificationDelivery.objects.create(
            owner=self.user, email=self.user.email, currency="USD", time_zone="UTC",
            messages={"goal": "Goal reached"}, lease_token="old", locked_until=timezone.now() + timedelta(minutes=1),
        )
        with patch.object(svc, "deliver_email_notifications") as send:
            self.assertFalse(svc.process_alert_delivery())
            send.assert_not_called()
            m.NotificationDelivery.objects.filter(pk=delivery.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
            call_command("run_alert_worker", "--once")
            send.assert_called_once()
        self.assertFalse(m.NotificationDelivery.objects.filter(pk=delivery.pk).exists())

    def test_settings_email_verification_marks_the_account_email_verified(self):
        with patch.object(svc, "email_delivery_configured", return_value=True), override_settings(
            EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        ):
            self.assertEqual(self.post("/api/settings/verify-email/", {}).status_code, 200)
            token = re.search(r"token=([\w-]+)", mail.outbox[-1].body).group(1)
            self.assertEqual(self.post("/api/auth/verify/", {"token": token}, {}).status_code, 200)
        self.assertTrue(m.UserSettings.objects.get(owner=self.user).email_verified)

    def test_revenue_goal_validation_and_clearing(self):
        def save(body, headers=None):
            return self.client.patch("/api/settings/", json.dumps(body), content_type="application/json",
                                     **(headers or self.h))

        self.assertEqual(save({"goal_period": "quarter"}).status_code, 400)
        self.assertEqual(save({"revenue_goal": "-5"}).status_code, 400)
        self.assertEqual(save({"revenue_goal": "abc"}).status_code, 400)
        r = save({"revenue_goal": "2000", "goal_period": "year"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Decimal(r.json()["revenue_goal"]), Decimal("2000"))
        self.assertEqual(r.json()["goal_period"], "year")
        r = save({"revenue_goal": None})
        self.assertIsNone(r.json()["revenue_goal"])
        self.assertIsNone(r.json()["progress"])
        self.assertEqual(r.json()["goal_period"], "year")

    def test_revenue_goal_progress_counts_sales_in_the_current_period(self):
        today = timezone.localdate()
        m.Sale.objects.create(owner=self.user, amount=Decimal("300"), date=today)
        m.Sale.objects.create(owner=self.user, amount=Decimal("400"), date=date(today.year - 1, 12, 31))
        m.Sale.objects.create(owner=self.other, amount=Decimal("999"), date=today)
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "1000", "goal_period": "day"}),
                          content_type="application/json", **self.h)
        progress = self.client.get("/api/settings/", **self.h).json()["progress"]
        self.assertEqual(progress["period"], "day")
        self.assertEqual(progress["start"], today.isoformat())
        self.assertEqual(progress["end"], today.isoformat())
        self.assertEqual(Decimal(progress["revenue"]), Decimal("300"))
        self.assertEqual(progress["percent"], 30.0)
        self.assertEqual(Decimal(progress["remaining"]), Decimal("700"))

    def test_revenue_goal_progress_caps_remaining_at_zero(self):
        m.Sale.objects.create(owner=self.user, amount=Decimal("1500"), date=timezone.localdate())
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "1000", "goal_period": "month"}),
                          content_type="application/json", **self.h)
        progress = self.client.get("/api/settings/", **self.h).json()["progress"]
        self.assertEqual(progress["percent"], 150.0)
        self.assertEqual(Decimal(progress["remaining"]), Decimal("0"))

    def test_goal_series_buckets_for_each_period(self):
        today = date(2026, 10, 14)  # a Wednesday
        goal = Decimal("1200")

        day = svc.goal_series(self.user, goal, "day", today)
        self.assertEqual(len(day["buckets"]), 31)
        self.assertEqual(day["buckets"][0]["start"], "2026-10-01")
        self.assertEqual(day["buckets"][-1]["end"], "2026-10-31")
        self.assertEqual(day["current"], 13)
        self.assertEqual(day["target"], "1200.00")

        week = svc.goal_series(self.user, goal, "week", today)
        self.assertEqual(len(week["buckets"]), 8)
        self.assertEqual(week["buckets"][0]["start"], "2026-08-24")
        self.assertEqual(week["buckets"][-1], {"start": "2026-10-12", "end": "2026-10-18", "amount": "0.00"})
        self.assertEqual(week["current"], 7)

        month = svc.goal_series(self.user, goal, "month", today)
        self.assertEqual([b["start"] for b in month["buckets"]],
                         ["2026-05-01", "2026-06-01", "2026-07-01", "2026-08-01", "2026-09-01", "2026-10-01"])
        self.assertEqual(month["buckets"][-1]["end"], "2026-10-31")
        self.assertEqual(month["current"], 5)
        self.assertEqual(month["target"], "1200.00")

        year = svc.goal_series(self.user, goal, "year", today)
        self.assertEqual(len(year["buckets"]), 12)
        self.assertEqual(year["buckets"][0]["start"], "2026-01-01")
        self.assertEqual(year["buckets"][-1]["end"], "2026-12-31")
        self.assertEqual(year["current"], 9)

    def test_goal_series_year_target_is_a_twelfth_of_the_goal(self):
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "1000", "goal_period": "year"}),
                          content_type="application/json", **self.h)
        series = self.client.get("/api/settings/series/", **self.h).json()
        self.assertEqual(series["target"], "83.33")
        self.assertEqual(len(series["buckets"]), 12)

    def test_goal_series_is_null_without_a_goal(self):
        response = self.client.get("/api/settings/series/", **self.h)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json())

    def test_goal_series_totals_match_goal_progress_for_each_period(self):
        today = timezone.localdate()
        m.Sale.objects.create(owner=self.user, amount=Decimal("300"), date=today)
        m.Sale.objects.create(owner=self.user, amount=Decimal("120"), date=today, status=m.Sale.PENDING)
        m.Sale.objects.create(owner=self.other, amount=Decimal("999"), date=today)
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "1000"}),
                          content_type="application/json", **self.h)
        for period in ("day", "week", "month", "year"):
            with self.subTest(period=period):
                self.client.patch("/api/settings/", json.dumps({"goal_period": period}),
                                  content_type="application/json", **self.h)
                series = self.client.get("/api/settings/series/", **self.h).json()
                progress = self.client.get("/api/settings/", **self.h).json()["progress"]
                if period == "year":
                    total = sum(Decimal(b["amount"]) for b in series["buckets"])
                else:
                    total = Decimal(series["buckets"][series["current"]]["amount"])
                self.assertEqual(total, Decimal("300"))
                self.assertEqual(total, Decimal(progress["revenue"]))

    def test_goal_series_counts_every_paid_sale_in_the_period(self):
        today = timezone.localdate()
        m.Sale.objects.bulk_create([m.Sale(owner=self.user, amount=Decimal("1"), date=today) for _ in range(501)])
        m.Sale.objects.create(owner=self.user, amount=Decimal("50"), date=today, status=m.Sale.PENDING)
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "1000", "goal_period": "day"}),
                          content_type="application/json", **self.h)
        series = self.client.get("/api/settings/series/", **self.h).json()
        self.assertEqual(series["buckets"][series["current"]]["amount"], "501.00")
