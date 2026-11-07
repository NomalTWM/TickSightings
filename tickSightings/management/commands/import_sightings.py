# sightings/management/commands/import_sightings.py
import datetime
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from tickSightings.models import Sighting

URL = "https://dev-task.elancoapps.com/data/tick-sightings"
REQUIRED = ("id", "date", "location", "species", "latinName")


def fetch():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retry))
    resp = session.get(URL, timeout=15)
    resp.raise_for_status()
    return resp.json()


class Command(BaseCommand):
    help = "Import tick sightings from the Elanco API (safe to re-run)"

    def handle(self, *args, **opts):
        try:
            raw = fetch()
        except requests.RequestException as e:
            raise CommandError(f"Upstream API failed: {e}")

        clean, rejected = {}, []
        for rec in raw:
            try:
                if any(not str(rec.get(f, "")).strip() for f in REQUIRED):
                    raise ValueError("missing field")
                dt = parse_datetime(rec["date"])
                if dt is None:
                    raise ValueError("bad date")
                if timezone.is_naive(dt):
                    dt = timezone.make_aware(dt, datetime.timezone.utc)
                clean[rec["id"].strip()] = Sighting(  # dict deduplicates on id
                    id=rec["id"].strip(),
                    date=dt,
                    location=rec["location"].strip().title(),
                    species=rec["species"].strip(),
                    latin_name=rec["latinName"].strip(),
                )
            except (ValueError, AttributeError, TypeError) as e:
                rejected.append((rec, str(e)))

        existing = set(
            Sighting.objects.filter(id__in=clean.keys())
            .values_list("id", flat=True)
        )
        created = len(clean) - len(existing)

        Sighting.objects.bulk_create(
            clean.values(),
            batch_size=500,
            update_conflicts=True,
            unique_fields=["id"],
            update_fields=["date", "location", "species", "latin_name"],
        )

        self.stdout.write(self.style.SUCCESS(
            f"{len(raw)} fetched | {created} created | {len(existing)} already present "
            f"(refreshed) | {len(raw) - len(clean) - len(rejected)} duplicates in feed | "
            f"{len(rejected)} rejected"
        ))