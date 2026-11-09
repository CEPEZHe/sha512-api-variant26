"""Full outer join required by relational algebra expression (26)."""

import time

WINDOW_SECONDS = 8 * 60


def project(query, feedback):
    """Select report fields from an optional pair of records."""
    return {
        "cache_hit": None if feedback is None else feedback["cache_hit"],
        "exception": None if feedback is None else feedback["exception"],
        "tags": None if query is None else query["tags"],
    }


def _recent_queries(store, moment):
    """Select queries created within the last eight minutes."""
    return [
        row for row in store.scan("query") if row["created"] > moment - WINDOW_SECONDS
    ]


def _join_recent_queries(queries, feedback):
    """Build matched pairs and track used feedback records."""
    results = []
    used = set()

    for query in queries:
        matches = [item for item in feedback if item["query"] == query["key"]]

        if not matches:
            results.append(project(query, None))

        for item in matches:
            results.append(project(query, item))
            used.add(item["key"])

    return results, used


def scan_report(store, now=None):
    """Project a full outer join of recent Query and Feedback rows."""
    moment = int(time.time()) if now is None else now
    recent = _recent_queries(store, moment)
    feedback = store.scan("feedback")

    results, used = _join_recent_queries(recent, feedback)

    results.extend(project(None, item) for item in feedback if item["key"] not in used)

    return {"items": results, "count": len(results)}
