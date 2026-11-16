import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from api.services import process_alert_delivery


class Command(BaseCommand):
    help = "Deliver queued business alerts, retrying failures."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process at most one alert and exit.")
        parser.add_argument("--poll-interval", type=float, default=2)

    def handle(self, *args, **options):
        interval = options["poll_interval"]
        if interval <= 0:
            raise CommandError("--poll-interval must be positive.")
        while True:
            close_old_connections()
            processed = process_alert_delivery()
            if options["once"]:
                return
            if not processed:
                time.sleep(interval)
