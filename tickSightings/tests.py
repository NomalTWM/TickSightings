import datetime
from io import StringIO
from unittest.mock import Mock, patch

import requests
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from rest_framework.test import APITestCase

from tickSightings.management.commands import import_sightings
from tickSightings.models import Sighting
from tickSightings.regions import CITY_TO_REGION

# Where the importer looks up its fetch() function, so we can replace it.
FETCH = "tickSightings.management.commands.import_sightings.fetch"


def record(id="abc1", date="2020-01-01T12:00:00", location="London",
           species="Marsh tick", latin="Ixodes apronophorus"):
    """Build one raw record in the shape the upstream API returns."""
    return {"id": id, "date": date, "location": location,
            "species": species, "latinName": latin}


def run_import(records):
    """Run the importer against a fake feed and return what it printed."""
    out = StringIO()
    with patch(FETCH, return_value=records):
        call_command("import_sightings", stdout=out, stderr=StringIO())
    return out.getvalue()


# --------------------------------------------------------------------------
# Importer
# --------------------------------------------------------------------------

class ImportCommandTests(TestCase):

    def test_import_creates_records(self):
        run_import([record("a1"), record("b2", location="Glasgow")])
        self.assertEqual(Sighting.objects.count(), 2)

    def test_import_is_idempotent(self):
        feed = [record("a1"), record("b2")]
        run_import(feed)
        run_import(feed)
        self.assertEqual(Sighting.objects.count(), 2)

    def test_reimport_refreshes_changed_values(self):
        run_import([record("a1", location="London")])
        run_import([record("a1", location="Leeds")])
        self.assertEqual(Sighting.objects.count(), 1)
        self.assertEqual(Sighting.objects.get(pk="a1").location, "Leeds")

    def test_values_are_normalised(self):
        run_import([record("a1", location="  lONDON ", species=" Marsh tick ")])
        sighting = Sighting.objects.get(pk="a1")
        self.assertEqual(sighting.location, "London")
        self.assertEqual(sighting.species, "Marsh tick")

    def test_naive_timestamps_are_treated_as_utc(self):
        run_import([record("a1", date="2020-01-01T12:00:00")])
        expected = datetime.datetime(2020, 1, 1, 12, tzinfo=datetime.timezone.utc)
        self.assertEqual(Sighting.objects.get(pk="a1").date, expected)

    def test_invalid_records_are_rejected_but_valid_ones_still_import(self):
        missing_field = record("m1")
        del missing_field["location"]
        feed = [
            record("good"),
            missing_field,                      # required field absent
            record("m2", species="   "),        # required field blank
            record("m3", date="not-a-date"),    # unparseable date
            record(id=None),                    # null id
        ]
        output = run_import(feed)

        self.assertEqual(list(Sighting.objects.values_list("id", flat=True)), ["good"])
        self.assertIn("4 rejected", output)

    def test_duplicate_ids_in_feed_produce_one_row(self):
        feed = [record("dup", location="London"), record("dup", location="Leeds")]
        output = run_import(feed)

        self.assertEqual(Sighting.objects.count(), 1)
        self.assertEqual(Sighting.objects.get(pk="dup").location, "Leeds")  # last wins
        self.assertIn("1 duplicates in feed", output)

    def test_empty_feed_is_not_an_error(self):
        run_import([])
        self.assertEqual(Sighting.objects.count(), 0)

    def test_upstream_failure_raises_command_error_and_keeps_existing_data(self):
        run_import([record("keep")])
        with patch(FETCH, side_effect=requests.ConnectionError("boom")):
            with self.assertRaises(CommandError):
                call_command("import_sightings", stdout=StringIO())
        self.assertEqual(Sighting.objects.count(), 1)

    def test_http_error_status_is_treated_as_a_failure(self):
        bad_response = Mock()
        bad_response.raise_for_status.side_effect = requests.HTTPError("500")
        with patch.object(requests.Session, "get", return_value=bad_response):
            with self.assertRaises(requests.HTTPError):
                import_sightings.fetch()


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------

class ApiTestCase(APITestCase):
    """Shared fixture: four sightings with easy-to-check expected counts."""

    @classmethod
    def setUpTestData(cls):
        def make(id, year, month, day, location, species, latin):
            Sighting.objects.create(
                id=id,
                # midday UTC keeps every date away from timezone boundaries
                date=datetime.datetime(year, month, day, 12, tzinfo=datetime.timezone.utc),
                location=location,
                species=species,
                latin_name=latin,
            )

        make("a1", 2020, 1, 6, "London", "Marsh tick", "Ixodes apronophorus")
        make("b2", 2020, 1, 8, "London", "Fox/badger tick", "Ixodes canisuga")
        make("c3", 2021, 3, 15, "Glasgow", "Marsh tick", "Ixodes apronophorus")
        make("d4", 2022, 7, 4, "Cardiff", "Passerine tick", "Dermacentor frontalis")

    def get(self, path, **params):
        return self.client.get(path, params)

    def listed_ids(self, **params):
        response = self.get("/api/sightings/", **params)
        self.assertEqual(response.status_code, 200)
        return {item["id"] for item in response.json()["results"]}


class SightingListTests(ApiTestCase):

    def test_lists_all_sightings_newest_first(self):
        response = self.get("/api/sightings/")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["count"], 4)
        self.assertEqual([r["id"] for r in body["results"]], ["d4", "c3", "b2", "a1"])

    def test_filter_by_location_is_case_insensitive(self):
        self.assertEqual(self.listed_ids(location="london"), {"a1", "b2"})

    def test_filter_by_species(self):
        self.assertEqual(self.listed_ids(species="marsh tick"), {"a1", "c3"})

    def test_filter_by_date_range_is_inclusive(self):
        ids = self.listed_ids(date_from="2020-01-08", date_to="2021-03-15")
        self.assertEqual(ids, {"b2", "c3"})

    def test_filters_combine(self):
        self.assertEqual(self.listed_ids(location="London", species="Marsh tick"), {"a1"})

    def test_search_matches_latin_name_and_city(self):
        self.assertEqual(self.listed_ids(search="ixodes"), {"a1", "b2", "c3"})
        self.assertEqual(self.listed_ids(search="cardiff"), {"d4"})

    def test_ordering_can_be_reversed(self):
        response = self.get("/api/sightings/", ordering="date")
        self.assertEqual(response.json()["results"][0]["id"], "a1")

    def test_invalid_date_filter_returns_400(self):
        self.assertEqual(self.get("/api/sightings/", date_from="not-a-date").status_code, 400)

    def test_retrieve_one_sighting(self):
        response = self.get("/api/sightings/a1/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["location"], "London")

    def test_unknown_sighting_returns_404(self):
        self.assertEqual(self.get("/api/sightings/does-not-exist/").status_code, 404)

    def test_results_are_paginated(self):
        Sighting.objects.bulk_create([
            Sighting(id=f"x{i}", date=datetime.datetime(2023, 1, 1, 12, tzinfo=datetime.timezone.utc),
                     location="Leeds", species="Marsh tick", latin_name="Ixodes apronophorus")
            for i in range(60)
        ])
        body = self.get("/api/sightings/").json()
        self.assertEqual(body["count"], 64)
        self.assertLess(len(body["results"]), 64)
        self.assertIsNotNone(body["next"])

    def test_write_methods_are_not_allowed(self):
        self.assertEqual(self.client.post("/api/sightings/", {}).status_code, 405)


class ReportTests(ApiTestCase):

    # --- by city -----------------------------------------------------------

    def test_by_city_counts(self):
        data = self.get("/api/reports/by-city/").json()
        self.assertEqual(data, [
            {"location": "London", "count": 2},
            {"location": "Cardiff", "count": 1},
            {"location": "Glasgow", "count": 1},
        ])

    def test_by_city_respects_filters(self):
        data = self.get("/api/reports/by-city/", species="Marsh tick").json()
        self.assertEqual(data, [
            {"location": "Glasgow", "count": 1},
            {"location": "London", "count": 1},
        ])

    def test_by_city_with_no_matches_is_an_empty_list(self):
        self.assertEqual(self.get("/api/reports/by-city/", location="Nowhere").json(), [])

    # --- by region ---------------------------------------------------------

    def test_by_region_groups_cities_into_regions(self):
        data = self.get("/api/reports/by-region/").json()
        counts = {row["region"]: row["count"] for row in data}
        self.assertEqual(counts, {
            CITY_TO_REGION["London"]: 2,
            CITY_TO_REGION["Glasgow"]: 1,
            CITY_TO_REGION["Cardiff"]: 1,
        })
        self.assertEqual(data[0]["region"], CITY_TO_REGION["London"])  # highest first

    def test_unmapped_city_is_reported_as_unknown(self):
        Sighting.objects.create(
            id="z9", date=datetime.datetime(2023, 1, 1, 12, tzinfo=datetime.timezone.utc),
            location="Atlantis", species="Marsh tick", latin_name="Ixodes apronophorus")
        counts = {r["region"]: r["count"] for r in self.get("/api/reports/by-region/").json()}
        self.assertEqual(counts["Unknown"], 1)

    # --- trends ------------------------------------------------------------

    def test_monthly_trends(self):
        data = self.get("/api/reports/trends/", interval="monthly").json()
        self.assertEqual(data, [
            {"period": "2020-01-01", "count": 2},
            {"period": "2021-03-01", "count": 1},
            {"period": "2022-07-01", "count": 1},
        ])

    def test_interval_defaults_to_monthly(self):
        default = self.get("/api/reports/trends/").json()
        explicit = self.get("/api/reports/trends/", interval="monthly").json()
        self.assertEqual(default, explicit)

    def test_weekly_trends_group_by_week_starting_monday(self):
        # a1 (Mon 6 Jan 2020) and b2 (Wed 8 Jan 2020) fall in the same week
        data = self.get("/api/reports/trends/", interval="weekly").json()
        self.assertEqual(data[0], {"period": "2020-01-06", "count": 2})
        self.assertEqual(len(data), 3)

    def test_trends_respect_filters(self):
        data = self.get("/api/reports/trends/", location="Glasgow").json()
        self.assertEqual(data, [{"period": "2021-03-01", "count": 1}])

    def test_invalid_interval_returns_400(self):
        response = self.get("/api/reports/trends/", interval="daily")
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

    # --- bad input on every report ----------------------------------------

    def test_invalid_filter_value_returns_400_on_every_report(self):
        for path in ("/api/reports/by-city/", "/api/reports/by-region/", "/api/reports/trends/"):
            with self.subTest(path=path):
                self.assertEqual(self.get(path, date_from="not-a-date").status_code, 400)