"""Standard-library XML HTTP API for asynchronous SHA-512 jobs."""

import argparse
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from src.jobs import JobRunner
from src.report import scan_report
from src.stores import FileStore, MissingRecord, SQLAlchemyStore, StorageError
from src.xml_codec import parse_request, response_xml

MAX_BODY = 200_000


class Dispatcher:
    """Map requests from table 26 to the same storage interface."""

    def __init__(self, handler):
        self.handler = handler
        self.store = handler.server.storage

    def dispatch(self):
        """Resolve a static route or pass it to the parameterized router."""
        method = self.handler.command
        path = urlsplit(self.handler.path).path
        fixed = {
            ("POST", "/api/profile/add"): self.add_profile,
            ("POST", "/api/profile/scan"): self.scan_profile,
            ("GET", "/api/profile/fetch"): self.fetch_profile,
            ("POST", "/api/query/add"): self.add_query,
            ("GET", "/api/query/fetch"): self.fetch_query,
            ("GET", "/api/feedback/fetch"): self.fetch_feedback,
            ("POST", "/api/report/scan"): self.scan_report,
        }
        operation = fixed.get((method, path))
        if operation is not None:
            return operation()
        return self.dynamic_route(method, path)

    def dynamic_route(self, method, path):
        """Dispatch updates and scans with path parameters."""
        update = re.fullmatch(r"/api/(profile|query)/update/(\d+)", path)
        if method == "PUT" and update:
            return self.update_record(*update.groups())
        query_scan = re.fullmatch(r"/api/query/scan/(\d+)", path)
        if method == "POST" and query_scan:
            return self.scan_related("query", "profile", query_scan.group(1))
        feedback_scan = re.fullmatch(r"/api/feedback/scan/(\d+)", path)
        if method == "POST" and feedback_scan:
            return self.scan_related("feedback", "query", feedback_scan.group(1))
        raise MissingRecord("Unknown API route")

    def params(self):
        """Read query parameters from the URL, taking the first value."""
        parsed = parse_qs(urlsplit(self.handler.path).query)
        return {key: values[0] for key, values in parsed.items()}

    def body(self):
        """Read and parse a bounded flat XML request body."""
        length = int(self.handler.headers.get("Content-Length", "0"))
        if length > MAX_BODY or length < 0:
            raise StorageError("Invalid request length")
        return parse_request(self.handler.rfile.read(length))

    def add_profile(self):
        """Create a client profile using data from XML."""
        return self.store.add("profile", self.body())

    def scan_profile(self):
        """Return profiles matching URL query-string filters."""
        return {"items": self.store.scan("profile", self.params())}

    def fetch_profile(self):
        """Read one profile by key."""
        return self.store.get("profile", self.params()["key"])

    def add_query(self):
        """Create a query and enqueue its digest computation."""
        data = self.body()
        data["status"] = "pending"
        query = self.store.add("query", data)
        self.handler.server.jobs.enqueue(query)
        return self.store.get("query", query["key"])

    def fetch_query(self):
        """Read one computation request and its current status."""
        return self.store.get("query", self.params()["key"])

    def fetch_feedback(self):
        """Read one completed computation result."""
        return self.store.get("feedback", self.params()["key"])

    def scan_related(self, kind, field, key):
        """Filter Query or Feedback using a foreign-key path component."""
        params = self.params()
        params[field] = int(key)
        return {"items": self.store.scan(kind, params)}

    def update_record(self, kind, key):
        """Update a record and optionally inject a demonstration-only bug."""
        changes = self.body()
        updated = self.store.update(kind, key, changes)
        if self.handler.server.mutate_tags and kind == "query":
            self.propagate_tag_bug(updated, changes)
        return updated

    def propagate_tag_bug(self, updated, changes):
        """Deliberately corrupt sibling queries for the mutation demo."""
        if "tags" not in changes:
            return
        siblings = self.store.scan("query", {"profile": updated["profile"]})
        for sibling in siblings:
            if sibling["key"] != updated["key"]:
                self.store.update("query", sibling["key"], {"tags": changes["tags"]})

    def scan_report(self):
        """Construct the relational-algebra report from expression (26)."""
        return scan_report(self.store)


class APIHandler(BaseHTTPRequestHandler):
    """Expose all eleven required endpoints using a standard HTTP server."""

    def log_message(self, message, *args):
        """Avoid flooding terminal output during property-based tests."""

    def reply(self, status, value):
        """Send a typed XML response with an explicit HTTP status."""
        body = response_xml(value)
        self.send_response(status)
        self.send_header("Content-Type", "text/xml; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def verify_headers(self):
        """Validate request headers in the exact order of the assignment."""
        if (
            self.command in ("POST", "PUT", "PATCH")
            and self.headers.get("Content-Type") != "text/xml"
        ):
            self.reply(415, {"error": "Content-Type must be text/xml"})
            return False
        if self.headers.get("Accept") != "text/xml":
            self.reply(406, {"error": "Accept must be text/xml"})
            return False
        if self.headers.get("Accept-Language") != "ru":
            self.reply(406, {"error": "Accept-Language must be ru"})
            return False
        return True

    def handle_api(self):
        """Validate, dispatch and consistently map exceptions to HTTP codes."""
        if not self.verify_headers():
            return
        try:
            result = Dispatcher(self).dispatch()
        except (MissingRecord, KeyError) as exc:
            self.reply(404, {"error": str(exc)})
        except (StorageError, TypeError, ValueError) as exc:
            self.reply(400, {"error": str(exc)})
        else:
            self.reply(200, result)

    def do_GET(self):
        """Handle a GET route."""
        self.handle_api()

    def do_POST(self):
        """Handle a POST route."""
        self.handle_api()

    def do_PUT(self):
        """Handle a PUT route."""
        self.handle_api()


def create_server(host, port, backend, database, test_mode=False, mutate_tags=False):
    """Choose JSON or SQLite storage and attach a computation job runner."""
    store_class = FileStore if backend == "file" else SQLAlchemyStore
    store = store_class(database)
    server = ThreadingHTTPServer((host, port), APIHandler)
    server.storage = store
    server.jobs = JobRunner(store, test_mode)
    server.mutate_tags = mutate_tags
    return server


def main(argv=None):
    """Start the HTTP API with configurable storage and test mode."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--backend", choices=("file", "sqlite"), default="sqlite")
    parser.add_argument("--database", default="data/app.sqlite3")
    parser.add_argument("--test-mode", action="store_true")
    args = parser.parse_args(argv)
    server = create_server(
        args.host, args.port, args.backend, Path(args.database), args.test_mode
    )
    print(f"API: http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.jobs.close()
        server.server_close()
        server.storage.close()


if __name__ == "__main__":
    main()
