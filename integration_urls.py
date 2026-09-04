from urllib.parse import urlparse


def validated_https_url(value):
    """Return a normalized external HTTPS URL or None for unsafe input."""
    candidate = str(value or '').strip()
    if not candidate:
        return None

    parsed = urlparse(candidate)
    if (
        parsed.scheme != 'https'
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        return None

    return candidate.rstrip('/')
