"""Generated state-machine tests: independent model versus real HTTP API."""

import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    Bundle,
    RuleBasedStateMachine,
    initialize,
    invariant,
    rule,
)

from src.api import create_server
from src.client import APIClient

LOCALES = st.sampled_from(["ru", "en", "fr"])
TAGS = st.sampled_from(["alpha", "beta", "critical", "review"])
FILES = st.sampled_from(["sample_files/alpha.txt", "sample_files/beta.txt"])


class BaseMachine(RuleBasedStateMachine):
    """Generate independent API operations and check a reference model."""

    profiles_bundle = Bundle("profiles")
    queries_bundle = Bundle("queries")
    backend = "file"
    mutation = False

    def __init__(self):
        super().__init__()
        self.tmp = tempfile.TemporaryDirectory()
        suffix = "json" if self.backend == "file" else "sqlite3"
        database = Path(self.tmp.name) / ("state." + suffix)
        self.server = create_server(
            "127.0.0.1",
            0,
            self.backend,
            database,
            test_mode=True,
            mutate_tags=self.mutation,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        address = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.client = APIClient(address)
        self.profiles = {}
        self.queries = {}

    def teardown(self):
        """Close one temporary server and the related database resources."""
        self.server.shutdown()
        self.thread.join(timeout=5)
        self.server.jobs.close()
        self.server.server_close()
        self.server.storage.close()
        self.tmp.cleanup()

    def create_profile(self, locale):
        """Apply a profile-add operation to the SUT and reference model."""
        values = {
            "ip": "127.0.0.1",
            "locale": locale,
            "platform": "Linux",
            "user_agent": "hypothesis",
        }
        result = self.client.api_profile_add(values)
        self.profiles[result["key"]] = values
        return result["key"]

    @initialize(target=profiles_bundle)
    def initial_profile(self):
        """Ensure the state machine always has a valid initial parent."""
        return self.create_profile("ru")

    @rule(target=profiles_bundle, locale=LOCALES)
    def add_profile(self, locale):
        """Generate independent profile creations."""
        return self.create_profile(locale)

    @rule(target=queries_bundle, profile=profiles_bundle, tags=TAGS, path=FILES)
    def add_query(self, profile, tags, path):
        """Submit a hash job and extend the model with a completed query."""
        values = {
            "profile": profile,
            "parameter": path,
            "description": "SHA-512 calculation",
            "tags": tags,
        }
        result = self.client.api_query_add(values)
        expected = {**values, "status": "done"}
        self.queries[result["key"]] = expected
        return result["key"]

    @rule(key=profiles_bundle, locale=LOCALES)
    def update_profile(self, key, locale):
        """Modify one generated profile without changing other profiles."""
        self.client.api_profile_update_key(key, {"locale": locale})
        self.profiles[key]["locale"] = locale

    @rule(key=queries_bundle, tags=TAGS)
    def update_query(self, key, tags):
        """Update one query; siblings must remain unaffected."""
        self.client.api_query_update_key(key, {"tags": tags})
        self.queries[key]["tags"] = tags

    @rule(key=profiles_bundle)
    def fetch_profile(self, key):
        """Check a randomly selected profile fetch operation."""
        self.assert_fields(self.client.api_profile_fetch(key), self.profiles[key])

    @rule(key=queries_bundle)
    def fetch_query(self, key):
        """Check a randomly selected query fetch operation."""
        self.assert_fields(self.client.api_query_fetch(key), self.queries[key])

    @rule(key=profiles_bundle)
    def scan_queries(self, key):
        """Compare the filtered scan with the independently tracked keys."""
        actual = self.client.api_query_scan_profile(key)["items"]
        expected = {q for q, value in self.queries.items() if value["profile"] == key}
        assert {row["key"] for row in actual} == expected

    @rule(key=queries_bundle)
    def scan_feedback(self, key):
        """Verify that a test-mode computation has one feedback row."""
        actual = self.client.api_feedback_scan_query(key)["items"]
        assert len(actual) == 1
        self.check_feedback(actual[0], key)

    @rule(key=queries_bundle)
    def fetch_feedback(self, key):
        """Verify the separate endpoint for fetching one feedback item."""
        items = self.client.api_feedback_scan_query(key)["items"]
        result = self.client.api_feedback_fetch(items[0]["key"])
        self.check_feedback(result, key)

    @rule()
    def scan_profiles(self):
        """Compare the complete profile listing with the model."""
        rows = self.client.api_profile_scan()["items"]
        assert {row["key"] for row in rows} == set(self.profiles)

    @rule()
    def scan_report(self):
        """Compare recent report contents against independent query tags."""
        report = self.client.api_report_scan()
        actual = {row["tags"] for row in report["items"]}
        expected = {row["tags"] for row in self.queries.values()}
        assert report["count"] == len(self.queries)
        assert actual == expected

    @rule(which=st.integers(min_value=0, max_value=2))
    def reject_incorrect_headers(self, which):
        """Generate invalid requests for the required 415 and 406 cases."""
        url = self.client.base_url + "/api/report/scan"
        headers = {"Accept": "text/xml", "Accept-Language": "ru"}
        method = "POST" if which == 0 else "GET"
        if which == 1:
            headers.pop("Accept")
        if which == 2:
            headers.pop("Accept-Language")
        payload = b"" if method == "POST" else None
        request = Request(url, data=payload, method=method, headers=headers)
        try:
            urlopen(request, timeout=5)
        except HTTPError as error:
            assert error.code == (415 if which == 0 else 406)
        else:
            raise AssertionError("An invalid request must be rejected")

    @staticmethod
    def assert_fields(record, expected):
        """Compare domain data without copying expected data from the SUT."""
        for field, value in expected.items():
            assert record[field] == value, (field, record, expected)
        assert isinstance(record["created"], int)

    @staticmethod
    def check_feedback(item, key):
        """Check the computation outcome for test mode independently."""
        assert item["query"] == key
        assert item["status"] == "done"
        assert item["exception"] == ""
        assert item["cache_hit"] == 0
        assert '"sha512": "' + "0" * 128 + '"' in item["response"]

    @invariant()
    def model_matches_server(self):
        """After EVERY generated action, verify all existing records."""
        items = self.client.api_profile_scan()["items"]
        assert len(items) == len(self.profiles)
        for item in items:
            self.assert_fields(item, self.profiles[item["key"]])
        for key, expected in self.queries.items():
            self.assert_fields(self.client.api_query_fetch(key), expected)


class FileMachine(BaseMachine):
    """Exercise stage 2 with a JSON file database."""

    backend = "file"


class SQLiteMachine(BaseMachine):
    """Exercise stage 3 with the SQLAlchemy ORM and SQLite."""

    backend = "sqlite"


TestFileAPI = FileMachine.TestCase
TestSQLiteAPI = SQLiteMachine.TestCase

TestFileAPI.settings = settings(max_examples=12, stateful_step_count=18, deadline=None)
TestSQLiteAPI.settings = settings(
    max_examples=12, stateful_step_count=18, deadline=None
)
