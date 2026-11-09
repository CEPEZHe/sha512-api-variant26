"""HTTP client with method names matching the variant-26 API routes."""

import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.xml_codec import decode_element, request_xml


class APIError(Exception):
    """A non-success status returned by the HTTP server."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


class APIClient:
    """Typed wrapper around all eleven HTTP endpoints."""

    def __init__(self, base_url="http://127.0.0.1:8000"):
        self.base_url = base_url.rstrip("/")

    def _request(self, method, path, params=None, data=None):
        url = self.base_url + path
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "text/xml", "Accept-Language": "ru"}
        payload = request_xml(data) if data is not None else None
        if method in ("POST", "PUT"):
            headers["Content-Type"] = "text/xml"
            payload = b"" if payload is None else payload
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=5) as response:
                raw = response.read()
        except HTTPError as exc:
            raise APIError(exc.code, exc.read().decode()) from exc
        return decode_element(ET.fromstring(raw).find("result"))

    def api_profile_add(self, data):
        """Create a client profile."""
        return self._request("POST", "/api/profile/add", data=data)

    def api_profile_scan(self, **filters):
        """Filter client profiles."""
        return self._request("POST", "/api/profile/scan", filters)

    def api_profile_fetch(self, key):
        """Fetch a profile by its key."""
        return self._request("GET", "/api/profile/fetch", {"key": key})

    def api_profile_update_key(self, key, data):
        """Update one client profile."""
        return self._request("PUT", f"/api/profile/update/{key}", data=data)

    def api_query_add(self, data):
        """Submit a new hash computation."""
        return self._request("POST", "/api/query/add", data=data)

    def api_query_scan_profile(self, profile, **filters):
        """Scan hash queries belonging to a profile."""
        return self._request("POST", f"/api/query/scan/{profile}", filters)

    def api_query_fetch(self, key):
        """Fetch the status and metadata of one hash computation."""
        return self._request("GET", "/api/query/fetch", {"key": key})

    def api_query_update_key(self, key, data):
        """Edit one hash query's metadata."""
        return self._request("PUT", f"/api/query/update/{key}", data=data)

    def api_feedback_scan_query(self, query, **filters):
        """Find recorded feedback for a submitted hash query."""
        return self._request("POST", f"/api/feedback/scan/{query}", filters)

    def api_feedback_fetch(self, key):
        """Fetch an individual hash result."""
        return self._request("GET", "/api/feedback/fetch", {"key": key})

    def api_report_scan(self):
        """Fetch a report based on relational algebra expression (26)."""
        return self._request("POST", "/api/report/scan")
