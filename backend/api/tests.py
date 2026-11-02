import re
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase

from . import models as m
from . import services as svc


class ApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create(username="a@x.com", email="a@x.com")
        self.h = {"HTTP_AUTHORIZATION": "Bearer " + svc.issue_token(self.user)}
        self.other = get_user_model().objects.create(username="b@x.com", email="b@x.com")
        self.other_h = {"HTTP_AUTHORIZATION": "Bearer " + svc.issue_token(self.other)}

    def post(self, url, data, headers=None):
        return self.client.post(url, data, content_type="application/json", **(headers or self.h))

    def product(self, **kw):
        body = {"name": "Earbuds", "price": "24", "cost": "14", "target_stock": 80, **kw}
        return self.post("/api/products/", body).json()

    def test_requires_auth(self):
        self.assertEqual(self.client.get("/api/products/").status_code, 401)

    def test_magic_link_flow_and_single_use(self):
        self.assertEqual(self.post("/api/auth/request-link/", {"email": "new@x.com"}, {}).status_code, 200)
        token = re.search(r"token=([\w-]+)", mail.outbox[0].body).group(1)
        r = self.post("/api/auth/verify/", {"token": token}, {})
        self.assertEqual(r.status_code, 200)
        key = r.json()["token"]
        self.assertEqual(self.client.get("/api/me/", HTTP_AUTHORIZATION="Bearer " + key).json()["email"], "new@x.com")
        self.assertEqual(self.post("/api/auth/verify/", {"token": token}, {}).status_code, 400)

    def test_invalid_email_rejected(self):
        self.assertEqual(self.post("/api/auth/request-link/", {"email": "nope"}, {}).status_code, 400)

    def test_register_and_login(self):
        body = {"username": "riley", "password": "Str0ng-pass-92", "password2": "Str0ng-pass-92", "accepted_terms": True}
        r = self.post("/api/auth/register/", body, {})
        self.assertEqual(r.status_code, 201)
        self.assertTrue(m.TermsAcceptance.objects.filter(user__username="riley").exists())
        self.assertEqual(self.post("/api/auth/register/", body, {}).status_code, 409)
        r = self.post("/api/auth/login/", {"username": "RILEY", "password": "Str0ng-pass-92"}, {})
        self.assertEqual(r.status_code, 200)
        me = self.client.get("/api/me/", HTTP_AUTHORIZATION="Bearer " + r.json()["token"])
        self.assertEqual(me.json()["username"], "riley")

    def test_register_validation(self):
        ok = {"username": "sam", "password": "Str0ng-pass-92", "password2": "Str0ng-pass-92", "accepted_terms": True}
        for change in ({"password2": "different"}, {"accepted_terms": False}, {"accepted_terms": "true"},
                       {"password": "123", "password2": "123"}, {"username": "a b"}):
            self.assertEqual(self.post("/api/auth/register/", {**ok, **change}, {}).status_code, 400, change)

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
        self.assertEqual(sorted(b.quantity_left for b in m.StockBatch.objects.all()), [0, 5])

    def test_cannot_oversell(self):
        p = self.product()
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 2, "unit_cost": "10"})
        r = self.post("/api/sales/", {"amount": "50", "product_id": p["id"], "quantity": 5})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(m.Sale.objects.count(), 0)

    def test_data_is_isolated_per_user(self):
        p = self.product()
        self.assertEqual(self.client.get("/api/products/", **self.other_h).json(), [])
        self.assertEqual(self.client.get(f"/api/products/{p['id']}/", **self.other_h).status_code, 404)

    def test_validation(self):
        self.assertEqual(self.post("/api/expenses/", {"category": "Rent", "amount": "-5"}).status_code, 400)
        self.assertEqual(self.post("/api/sales/", {"amount": "abc"}).status_code, 400)

    def test_dashboard_totals(self):
        self.post("/api/sales/", {"customer": "A", "amount": "100"})
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

    def test_cors_preflight(self):
        r = self.client.options("/api/sales/", HTTP_ORIGIN="null", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r["Access-Control-Allow-Origin"], "null")
        r = self.client.options("/api/sales/", HTTP_ORIGIN="http://evil.test", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", r)
