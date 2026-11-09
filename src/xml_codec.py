"""Small XML encoder/decoder for variant 26's flat input documents."""

import xml.etree.ElementTree as ET

NUMBER_FIELDS = {"key", "created", "profile", "query", "cache_hit", "count", "bytes"}


def response_xml(value):
    """Encode Python dictionaries and lists in one response/result tree."""
    root = ET.Element("response")
    append_element(root, "result", value)
    return ET.tostring(root, encoding="utf-8")


def append_element(parent, name, value):
    """Append a typed XML child while retaining JSON-like collection types."""
    element = ET.SubElement(parent, name)
    if isinstance(value, dict):
        for key, child in value.items():
            append_element(element, key, child)
    elif isinstance(value, list):
        element.set("type", "list")
        for child in value:
            append_element(element, "item", child)
    elif value is None:
        element.set("nil", "true")
    else:
        element.text = str(value)


def request_xml(data):
    """Serialize a flat mapping into a simple <data> payload."""
    root = ET.Element("data")
    for key, value in data.items():
        ET.SubElement(root, key).text = str(value)
    return ET.tostring(root, encoding="utf-8")


def parse_request(raw):
    """Decode a flat XML request to a dictionary of string values."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ValueError("Invalid XML") from exc
    if root.tag != "data" or any(list(child) for child in root):
        raise ValueError("Expected a flat <data> XML document")
    return {child.tag: child.text or "" for child in root}


def decode_element(element):
    """Restore primitive values and collections from XML response trees."""
    children = list(element)
    if element.get("type") == "list":
        return [decode_element(child) for child in children]
    if children:
        return {child.tag: decode_element(child) for child in children}
    if element.get("nil") == "true":
        return None
    if element.tag in NUMBER_FIELDS and element.text is not None:
        return int(element.text)
    return element.text or ""
