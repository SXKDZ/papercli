"""HTTP utility functions for making web requests with consistent error handling."""

from typing import Dict, Optional

import requests

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}


def get(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
    stream: bool = False,
    **kwargs,
) -> requests.Response:
    """
    Make GET request with consistent headers and error handling.

    Args:
        url: The URL to request
        headers: Additional headers (merged with defaults)
        timeout: Request timeout in seconds
        stream: Whether to stream the response
        **kwargs: Additional arguments passed to requests.get

    Returns:
        requests.Response object

    Raises:
        requests.RequestException: On HTTP errors
    """
    merged_headers = DEFAULT_HEADERS.copy()
    if headers:
        merged_headers.update(headers)

    response = requests.get(
        url, headers=merged_headers, timeout=timeout, stream=stream, **kwargs
    )
    response.raise_for_status()
    return response
