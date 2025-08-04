"""HTTP utility functions for making web requests with consistent error handling."""

from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

import requests


class HTTPClient:
    """Centralized HTTP client with consistent headers and error handling."""

    DEFAULT_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    @classmethod
    def get(
        self,
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
        merged_headers = self.DEFAULT_HEADERS.copy()
        if headers:
            merged_headers.update(headers)

        response = requests.get(
            url, headers=merged_headers, timeout=timeout, stream=stream, **kwargs
        )
        response.raise_for_status()
        return response

    @classmethod
    def get_json(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        **kwargs,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """
        Make GET request and return JSON data with error handling.

        Returns:
            tuple[Optional[Dict], Optional[str]]: (json_data, error_message)
            If successful: (data, None)
            If error: (None, error_message)
        """
        try:
            response = self.get(url, headers=headers, timeout=timeout, **kwargs)
            return response.json(), None
        except requests.RequestException as e:
            return None, f"HTTP request failed: {str(e)}"
        except ValueError as e:
            return None, f"Invalid JSON response: {str(e)}"

    @classmethod
    def get_text(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        **kwargs,
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Make GET request and return text content with error handling.

        Returns:
            tuple[Optional[str], Optional[str]]: (text_content, error_message)
            If successful: (content, None)
            If error: (None, error_message)
        """
        try:
            response = self.get(url, headers=headers, timeout=timeout, **kwargs)
            return response.text, None
        except requests.RequestException as e:
            return None, f"HTTP request failed: {str(e)}"
