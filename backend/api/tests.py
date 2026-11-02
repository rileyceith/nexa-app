import base64
import json
import re
from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from urllib.error import HTTPError

from . import assistant as ai
from . import models as m
from . import services as svc


def data_url(mime, raw):
    return f"data:{mime};base64," + base64.b64encode(raw).decode()


PNG_URL = data_url("image/png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
JPEG_URL = data_url("image/jpeg", b"\xff\xd8\xff\xe0" + b"\x00" * 8)


class ApiTests(TestCase):
    def setUp(self):
        cache.clear()
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
        self.assertEqual(Decimal(str(r.json()["cogs"])), Decimal("200.00"))
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

    def test_receive_stores_image_for_new_product(self):
        r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4, "image": PNG_URL})
        self.assertEqual(r.status_code, 201)
        product_id = r.json()["product"]["id"]
        self.assertEqual(r.json()["product"]["image"], PNG_URL)
        self.assertEqual(self.client.get(f"/api/products/{product_id}/", **self.h).json()["image"], PNG_URL)

    def test_new_product_without_image_has_empty_image(self):
        r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4})
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()["product"]["image"], "")

    def test_existing_product_image_is_replaced_kept_and_cleared(self):
        p = self.product()
        url = f"/api/products/{p['id']}/"
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 2, "unit_cost": "10", "image": PNG_URL})
        self.assertEqual(self.client.get(url, **self.h).json()["image"], PNG_URL)

        self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10"})
        self.assertEqual(self.client.get(url, **self.h).json()["image"], PNG_URL)

        self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10", "image": JPEG_URL})
        self.assertEqual(self.client.get(url, **self.h).json()["image"], JPEG_URL)

        r = self.client.patch(url, data=json.dumps({"image": ""}), content_type="application/json", **self.h)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.client.get(url, **self.h).json()["image"], "")

    def test_invalid_images_are_rejected_before_anything_is_written(self):
        invalid = {
            "svg": data_url("image/svg+xml", b"<svg/>"),
            "not a data url": "https://example.com/a.png",
            "malformed base64": "data:image/png;base64,@@@",
            "too large": data_url("image/png", b"0" * (1024 * 1024 + 1)),
        }
        for label, image in invalid.items():
            r = self.post("/api/receive/", {"new_product_name": "Mug", "price": "12", "unit_cost": "5", "quantity": 4, "image": image})
            self.assertEqual(r.status_code, 400, label)
        self.assertFalse(m.Product.objects.filter(owner=self.user).exists())
        self.assertFalse(m.StockBatch.objects.exists())

    def test_invalid_image_on_existing_product_keeps_current_image(self):
        p = self.product()
        url = f"/api/products/{p['id']}/"
        self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10", "image": PNG_URL})
        r = self.client.patch(url, data=json.dumps({"image": data_url("text/html", b"<h1>x</h1>")}), content_type="application/json", **self.h)
        self.assertEqual(r.status_code, 400)
        r = self.post("/api/receive/", {"product_id": p["id"], "quantity": 1, "unit_cost": "10", "image": "not-an-image"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.get(url, **self.h).json()["image"], PNG_URL)
        self.assertEqual(m.StockBatch.objects.filter(product_id=p["id"]).count(), 1)

    def test_cors_preflight(self):
        r = self.client.options("/api/sales/", HTTP_ORIGIN="null", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertEqual(r.status_code, 204)
        self.assertEqual(r["Access-Control-Allow-Origin"], "null")
        r = self.client.options("/api/sales/", HTTP_ORIGIN="http://evil.test", HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST")
        self.assertNotIn("Access-Control-Allow-Origin", r)

    def test_assistant_requires_authentication_and_valid_question(self):
        unauthenticated = self.client.post(
            "/api/assistant/chat/", {"question": "How am I doing?"}, content_type="application/json"
        )
        self.assertEqual(unauthenticated.status_code, 401)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": " "}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "x" * 1001}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "How am I doing?", "month": "Nov"}).status_code, 400)
        self.assertEqual(self.post("/api/assistant/chat/", {"question": "x" * 5000}).status_code, 413)

    @patch("api.assistant.generate_answer", return_value="Revenue was $120.")
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

    @override_settings(NEXA_OPENAI_API_KEY="")
    def test_assistant_reports_missing_provider_configuration(self):
        response = self.post("/api/assistant/chat/", {"question": "How am I doing?"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "The AI assistant is not configured yet.")

    @patch("api.assistant.generate_answer", return_value="Try tracking weekly costs.")
    def test_assistant_rate_limits_repeated_requests(self, generate_answer):
        body = {"question": "What should I focus on?"}
        responses = [self.post("/api/assistant/chat/", body) for _ in range(11)]
        self.assertEqual([response.status_code for response in responses[:10]], [200] * 10)
        self.assertEqual(responses[-1].status_code, 429)
        self.assertEqual(generate_answer.call_count, 10)

    @override_settings(NEXA_OPENAI_API_KEY="server-only-key", NEXA_OPENAI_MODEL="test-model")
    @patch("api.assistant.urlopen")
    def test_assistant_provider_uses_server_key_and_parses_response(self, urlopen):
        urlopen.return_value.__enter__.return_value.read.return_value = b'{"output_text":"A grounded answer."}'
        answer = ai.generate_answer("How did I do?", {"period": "2026-10", "currency": "USD"})

        self.assertEqual(answer, "A grounded answer.")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer server-only-key")
        self.assertIn("Question: How did I do?", request.data.decode())
        self.assertEqual(json.loads(request.data)["model"], "test-model")

    @override_settings(NEXA_OPENAI_API_KEY="server-only-key")
    @patch("api.assistant.urlopen", side_effect=HTTPError("https://api.openai.com", 429, "busy", {}, None))
    def test_assistant_provider_errors_are_sanitized(self, _urlopen):
        with self.assertRaises(svc.ServiceError) as error:
            ai.generate_answer("Question", {"period": "2026-10"})

        self.assertEqual(error.exception.status, 502)
        self.assertNotIn("server-only-key", error.exception.message)

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
        for analysis in ("profitability", "sales_trends", "expense_analysis", "product_rankings", "stock_cover"):
            response = self.post("/api/assistant/analyze/", {"analysis": analysis, "month": month})
            self.assertEqual(response.status_code, 200, analysis)
        profitability = self.post(
            "/api/assistant/analyze/", {"analysis": "profitability", "month": month}
        ).json()
        self.assertIsNone(profitability["metrics"][3]["value"])
        self.assertIsNone(profitability["metrics"][6]["value"])

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
        self.assertEqual(self.client.get("/api/settings/", **self.h).json(),
                         {"revenue_goal": None, "goal_period": "month", "progress": None})
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "900"}),
                          content_type="application/json", **self.h)
        self.assertIsNone(self.client.get("/api/settings/", **self.other_h).json()["revenue_goal"])

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
                self.assertEqual(total, Decimal("420"))
                self.assertEqual(total, Decimal(progress["revenue"]))

    def test_goal_series_counts_every_sale_in_the_period(self):
        today = timezone.localdate()
        m.Sale.objects.bulk_create([m.Sale(owner=self.user, amount=Decimal("1"), date=today) for _ in range(501)])
        self.client.patch("/api/settings/", json.dumps({"revenue_goal": "1000", "goal_period": "day"}),
                          content_type="application/json", **self.h)
        series = self.client.get("/api/settings/series/", **self.h).json()
        self.assertEqual(series["buckets"][series["current"]]["amount"], "501.00")
