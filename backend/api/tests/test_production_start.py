import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

import start_production


class ProductionStartTests(TestCase):
    @patch("start_production.os.execvp")
    @patch("start_production.subprocess.run")
    def test_ready_database_starts_server(self, run, execvp):
        run.return_value = SimpleNamespace(returncode=0)
        with patch.dict(os.environ, {
            "NEXA_DATABASE_URL": "postgresql://user:password@db.example/nexa?sslmode=require",
            "PORT": "10000",
        }, clear=True):
            start_production.main()
        self.assertEqual(run.call_args.args[0][-2:], ["migrate", "--check"])
        execvp.assert_called_once()

    @patch("start_production.os.execvp")
    @patch("start_production.subprocess.run")
    def test_pending_migrations_prevent_server_start(self, run, execvp):
        run.return_value = SimpleNamespace(returncode=1)
        with patch.dict(os.environ, {
            "NEXA_DATABASE_URL": "postgresql://user:password@db.example/nexa?sslmode=verify-full",
            "PORT": "10000",
        }, clear=True):
            self.assertEqual(start_production.main(), 1)
        execvp.assert_not_called()

    @patch("start_production.os.execvp")
    @patch("start_production.subprocess.run")
    def test_missing_or_insecure_database_is_rejected(self, run, execvp):
        for url in (
            "", "postgresql://db.example/nexa", "postgresql://db.example/nexa?sslmode=disable",
            "postgresql://db.example/nexa?sslmode=require&sslmode=",
        ):
            with self.subTest(url=url), patch.dict(os.environ, {"NEXA_DATABASE_URL": url, "PORT": "10000"}, clear=True):
                self.assertEqual(start_production.main(), 1)
        run.assert_not_called()
        execvp.assert_not_called()
