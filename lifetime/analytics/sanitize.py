"""Privacy boundary. Never persist the raw request or request body."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import ipaddress
import re
from urllib.parse import parse_qsl, urlsplit
import uuid

RULESET_VERSION = "2026-10-03.1"
VALIDITIES = {"valid", "invalid", "not_applicable", "unknown"}
CLIENTS = {"unknown", "likely_human", "claimed_bot", "verified_bot"}
SECURITY = {"normal", "suspicious", "unknown"}
OUTCOMES = {"success", "redirect", "client_error", "server_error", "interrupted"}
PROBES = (".env", "wp-admin", "wp-login", ".git", "phpmyadmin", "cgi-bin", "etc/passwd")
CRAWLERS = ("googlebot", "bingbot", "duckduckbot", "yandexbot", "baiduspider", "crawler", "spider", "bot")
SAFE_PATH = re.compile(
    r"^(?:/|/(?:uk|en|ukr|eng|rus)(?:/(?:countries|regions|sources|methodology|about|privacy|result))?/?|/(?:robots\.txt|sitemap\.xml|health|healthz|ready|readyz|translations))$"
)
SAFE_QUERY_KEYS = {"lang", "locale", "country", "sex", "group"}
SENSITIVE = re.compile(
    r"(?:\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|[\w.+-]+@[\w.-]+|(?:password|token|admin_key|authorization|secret|birth_date|dob)\s*[:=]|bearer\s+)",
    re.I,
)


def clean(value, limit):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value or ""))[:limit]


def canonical_ip(value):
    try:
        address = ipaddress.ip_address(str(value or ""))
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            address = address.ipv4_mapped
        return str(address), address.version
    except ValueError:
        return None, None


def trusted_address(environ, cidrs):
    """Trust only the socket peer; edge overwrites forwarding with one address."""
    direct = environ.get("werkzeug.proxy_fix.orig", {}).get("REMOTE_ADDR", environ.get("REMOTE_ADDR"))
    peer, _ = canonical_ip(direct)
    trusted = peer and any(ipaddress.ip_address(peer) in ipaddress.ip_network(c) for c in cidrs)
    if trusted:
        forwarded = environ.get("HTTP_X_FORWARDED_FOR", "")
        # Multiple values mean the edge overwrite contract was not fulfilled.
        address, family = canonical_ip(forwarded) if "," not in forwarded else (None, None)
        if address:
            return address, family, True
    address, family = canonical_ip(direct)
    return address, family, bool(trusted)


def safe_request_id(value):
    value = str(value or "")
    return value.lower() if re.fullmatch(r"[a-fA-F0-9]{32}|[a-fA-F0-9-]{36}", value) else None


@dataclass(frozen=True)
class Rules:
    version: str = RULESET_VERSION
    probe_paths: tuple = PROBES
    crawler_tokens: tuple = CRAWLERS
    safe_static_paths: tuple = ("/static/style.css", "/static/app.js", "/static/favicon.svg")


def sanitize_event(event, secret, app_version, store_raw_ip=False, rules=None):
    """Construct an allowlisted event from scratch, including for edge/spool input.

    A field whose origin cannot be established is discarded rather than copied.
    Classification sees bounded raw inputs in memory; only reason codes survive.
    """
    rules = rules or Rules()
    raw_path = str(event.get("path", ""))[:4096]
    lowered = raw_path.lower()
    reasons = []
    flags = []
    if any(probe in lowered for probe in rules.probe_paths):
        security = "suspicious"
        reasons.append("probe_path")
    else:
        security = "normal"
    raw_query = str(event.get("query_string", ""))[:4096]
    payload = (raw_path + raw_query).lower()
    if any(
        marker in payload
        for marker in (
            "union%20select",
            "union select",
            "<script",
            "%3cscript",
            "../",
            "%2e%2e",
            "or%201=1",
            "or 1=1",
        )
    ):
        security = "suspicious"
        reasons.append("injection_pattern")
    path = clean(raw_path.split("?", 1)[0], 256)
    known_location = (
        event.get("safe_path") == path or "known_location" in event.get("flags", [])
    ) and re.fullmatch(r"/(?:uk|en|ukr|eng)/[a-z][a-z-]{0,80}", path)
    known_probe = path in ("/.env", "/.git/config", "/wp-login.php", "/wp-admin", "/phpmyadmin", "/cgi-bin")
    if (
        (
            not SAFE_PATH.fullmatch(path)
            and not known_location
            and not known_probe
            and path not in rules.safe_static_paths
        )
        or SENSITIVE.search(path)
        or ".." in path
        or re.search(r"\d{4}[-/]\d{1,2}", path)
    ):
        path = "/[redacted]"
        flags.append("redacted")
    elif known_location:
        flags.append("known_location")
    if len(raw_path) > 256:
        flags.append("truncated")
    query = {}
    # Query values are never persisted. Keys are a fixed vocabulary too.
    if raw_query:
        query = (
            {
                key: "[redacted]"
                for key, _ in parse_qsl(raw_query, keep_blank_values=True, max_num_fields=100)
                if key in SAFE_QUERY_KEYS
            }
            if raw_query.count("&") < 100
            else {}
        )
        flags.append("redacted")
    elif isinstance(event.get("query"), dict):
        query = {key: "[redacted]" for key in event["query"] if key in SAFE_QUERY_KEYS}
    raw_ua = clean(event.get("user_agent"), 2048).lower()
    crawler = next((token for token in rules.crawler_tokens if token in raw_ua), None)
    if crawler:
        client = "claimed_bot"
        ua = "crawler:" + crawler
        reasons.append("crawler_ua_claim")
        confidence = 0.7
    else:
        client = "unknown"
        browser = next((item for item in ("firefox", "edg/", "chrome", "safari") if item in raw_ua), None)
        tool = next((item for item in ("curl", "python-requests", "wget") if item in raw_ua), None)
        ua = "browser:" + browser if browser else "tool:" + tool if tool else "other"
        reasons.append("browser_ua_not_proof" if browser else "unverified_client")
        confidence = 0.0
    # Already-sanitized events retain coarse UA class through spool replay.
    if raw_ua in {
        "other",
        "browser:firefox",
        "browser:edg/",
        "browser:chrome",
        "browser:safari",
        "tool:curl",
        "tool:python-requests",
        "tool:wget",
    }:
        ua = raw_ua
    # Never accept a caller-provided verified_bot label without external proof.
    if event.get("verified_bot_proof") is True and event.get("_trusted_verification") is True:
        client = "verified_bot"
        reasons.append("verified_provider_range")
        confidence = 1.0
    if len(str(event.get("user_agent", ""))) > 120:
        flags.append("truncated")
    if raw_ua and ua != raw_ua:
        flags.append("redacted")
    address, family = canonical_ip(event.get("ip") or event.get("raw_ip"))
    token = hmac.new(str(secret).encode(), address.encode(), hashlib.sha256).hexdigest() if address else None
    key_id = hashlib.sha256(str(secret).encode()).hexdigest()[:12] if address else None
    if not address and re.fullmatch(r"[a-f0-9]{64}", str(event.get("address_token", ""))):
        token = event["address_token"]
        family = event.get("address_family") if event.get("address_family") in (4, 6) else None
        key_id = (
            event.get("address_key_id")
            if re.fullmatch(r"[a-f0-9]{12}", str(event.get("address_key_id", "")))
            else None
        )
    referer = None
    try:
        parsed = urlsplit(str(event.get("referer", ""))[:2048])
        if (
            parsed.scheme in ("http", "https")
            and parsed.hostname
            and re.fullmatch(r"[a-zA-Z0-9.-]{1,180}", parsed.hostname)
        ):
            referer = parsed.scheme + "://" + parsed.hostname
    except ValueError:
        pass
    try:
        timestamp = datetime.fromisoformat(str(event.get("timestamp")))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc).isoformat(timespec="milliseconds")
    except ValueError, TypeError:
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    try:
        status = max(100, min(599, int(event.get("status", 500))))
        duration = max(0, min(86400000, float(event.get("duration_ms", 0))))
    except ValueError, TypeError:
        status, duration = 500, 0
    outcome = (
        "server_error"
        if status >= 500
        else "client_error"
        if status >= 400
        else "redirect"
        if status >= 300
        else "success"
    )
    if event.get("outcome") == "interrupted":
        outcome = "interrupted"
    validity = event.get("validity")
    if validity not in VALIDITIES:
        validity = (
            "invalid"
            if status in (400, 404, 405, 410, 413, 422)
            else "not_applicable"
            if path in ("/health", "/ready", "/healthz", "/readyz")
            else "unknown"
            if event.get("source") == "edge"
            else "valid"
            if status < 400
            else "unknown"
        )
    reasons.append(
        "http_input_or_route_error"
        if validity == "invalid"
        else "accepted_route"
        if validity == "valid"
        else "unknown_validity"
    )
    source = event.get("source") if event.get("source") in ("app", "edge", "legacy") else "app"
    if source == "edge":
        flags.append("edge_only")
    # Only enum/code strings can survive supplied annotations.
    allowed_reasons = {
        "probe_path",
        "injection_pattern",
        "crawler_ua_claim",
        "browser_ua_not_proof",
        "unverified_client",
        "verified_provider_range",
        "http_input_or_route_error",
        "accepted_route",
        "unknown_validity",
        "stream_interrupted",
        "app_exception",
        "input_validation",
        "route_missing",
        "unsupported_method",
        "edge_status",
    }
    reasons.extend(r for r in event.get("reasons", []) if r in allowed_reasons)
    flags.extend(
        f
        for f in event.get("flags", [])
        if f in {"redacted", "truncated", "edge_only", "proxy_trusted", "known_location"}
    )
    if any(reason in reasons for reason in ("probe_path", "injection_pattern")):
        security = "suspicious"
    edge_id = safe_request_id(event.get("edge_request_id"))
    event_id = ("edge:" + edge_id) if edge_id else safe_request_id(event.get("event_id")) or uuid.uuid4().hex
    route = clean(event.get("route"), 256)
    route = (
        route
        if re.fullmatch(r"/[a-zA-Z0-9_/<:>.{}-]{0,255}", route) and not SENSITIVE.search(route)
        else None
    )
    endpoint = clean(event.get("endpoint"), 100)
    endpoint = endpoint if re.fullmatch(r"[a-zA-Z_.]{1,100}", endpoint) else None
    dataset = clean(event.get("dataset_id"), 100)
    dataset = (
        dataset if re.fullmatch(r"[a-zA-Z0-9_.-]{1,100}", dataset) and not SENSITIVE.search(dataset) else None
    )
    response_bytes = event.get("response_bytes")
    response_bytes = (
        response_bytes if isinstance(response_bytes, int) and 0 <= response_bytes <= 2**63 - 1 else None
    )
    return {
        "event_id": event_id,
        "edge_request_id": edge_id,
        "timestamp": timestamp,
        "source": source,
        "method": clean(event.get("method", "GET"), 16)
        if re.fullmatch(r"[A-Z]{1,16}", str(event.get("method", "GET")))
        else "OTHER",
        "path": path,
        "route": route,
        "endpoint": endpoint,
        "query": query,
        "status": status,
        "duration_ms": duration,
        "response_bytes": response_bytes,
        "address_token": token,
        "address_key_id": key_id,
        "address_family": family,
        "raw_ip": address if store_raw_ip else None,
        "user_agent": ua,
        "referer": referer,
        "locale": event.get("locale") if event.get("locale") in ("uk", "en") else None,
        "dataset_id": dataset,
        "app_version": clean(app_version, 50),
        "validity": validity,
        "client_class": client,
        "security_class": security,
        "outcome": outcome,
        "reasons": sorted(set(reasons)),
        "ruleset_version": rules.version,
        "confidence": confidence,
        "flags": sorted(set(flags)),
    }
