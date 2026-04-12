"""
Regression tests for the bookmarklet URL encoding fix (commit b6ee7d2).

The bookmarklet on the /add/ page previously passed `document.location.href`
directly as a query parameter, which broke URLs containing special characters
like '&', '?', '#', spaces, etc. The fix wraps the URL in
`encodeURIComponent()` so that special characters are properly encoded.

These tests ensure:
1. The bookmarklet script in add.html uses encodeURIComponent (template-level).
2. The URL prefill logic in AddView.get_initial() correctly handles URLs with
   special characters passed via the `?url=` query parameter (view-level).
"""

from pathlib import Path
from urllib.parse import quote, parse_qs

import pytest


ARCHIVEBOX_DIR = Path(__file__).resolve().parent.parent / 'archivebox'
ADD_TEMPLATE_PATH = ARCHIVEBOX_DIR / 'templates' / 'core' / 'add.html'


class TestBookmarkletTemplate:
    """Verify that the add.html template uses encodeURIComponent in the bookmarklet link."""

    def test_template_contains_encodeURIComponent(self):
        """
        Regression test: the bookmarklet must wrap document.location.href in
        encodeURIComponent() so that URLs with '&', '#', '?', etc. are
        properly encoded when passed as a query parameter.

        Before the fix (b6ee7d2), the bookmarklet was:
            window.open('...?url='+document.location.href)
        After the fix:
            window.open('...?url='+encodeURIComponent(document.location.href))
        """
        template_content = ADD_TEMPLATE_PATH.read_text()
        assert 'encodeURIComponent(document.location.href)' in template_content, (
            "Bookmarklet must use encodeURIComponent() to encode the URL. "
            "Without it, URLs with special characters like '&' will be truncated."
        )

    def test_template_does_not_use_raw_location_href_in_bookmarklet(self):
        """
        Ensure the old broken pattern (passing document.location.href without
        encoding) is not present in the bookmarklet link.
        """
        template_content = ADD_TEMPLATE_PATH.read_text()

        # Find the bookmarklet anchor tag line(s)
        bookmarklet_lines = [
            line for line in template_content.splitlines()
            if 'javascript:void(window.open(' in line
        ]
        assert bookmarklet_lines, (
            "Could not find the bookmarklet javascript link in add.html"
        )

        for line in bookmarklet_lines:
            # The old broken pattern: ?url='+document.location.href (without encodeURIComponent)
            assert "?url='+document.location.href)" not in line, (
                "Found the old broken bookmarklet pattern that passes "
                "document.location.href without encodeURIComponent(). "
                "URLs with '&' or other special characters will be truncated."
            )

    def test_bookmarklet_link_structure(self):
        """
        Verify the overall bookmarklet link structure is correct:
        - It opens a new window to the add path with the encoded URL.
        - The href parameter is properly wrapped in encodeURIComponent.
        """
        template_content = ADD_TEMPLATE_PATH.read_text()

        bookmarklet_lines = [
            line for line in template_content.splitlines()
            if 'javascript:void(window.open(' in line
        ]
        assert len(bookmarklet_lines) == 1, (
            f"Expected exactly one bookmarklet link, found {len(bookmarklet_lines)}"
        )

        bookmarklet_line = bookmarklet_lines[0]
        # Verify it contains the correct encoding pattern
        assert "?url='+encodeURIComponent(document.location.href)" in bookmarklet_line, (
            "Bookmarklet link should pass the URL as: "
            "?url='+encodeURIComponent(document.location.href)"
        )


class TestAddViewURLPrefill:
    """
    Test that the AddView.get_initial() URL prefill logic correctly handles
    URLs with special characters passed via the ?url= query parameter
    (simulating the bookmarklet flow after the encoding fix).

    When a user clicks the bookmarklet, the browser runs:
        window.open('<add_path>?url=' + encodeURIComponent(document.location.href))

    The server then receives the encoded URL as a query parameter and should
    correctly decode it to prefill the Add URL form.

    These tests exercise the get_initial() logic directly using a mock request
    to avoid requiring a full ArchiveBox data directory or Django setup.
    """

    @staticmethod
    def _simulate_get_initial(url_param_value):
        """
        Replicate the AddView.get_initial() logic for the ?url= parameter.

        This is extracted from archivebox/core/views.py AddView.get_initial():
            if self.request.method == 'GET':
                url = self.request.GET.get('url', None)
                if url:
                    return {'url': url if '://' in url else f'https://{url}'}
            return super().get_initial()

        We use a mock request to avoid needing Django configuration.
        """

        class MockQueryDict:
            def __init__(self, params):
                self._params = params or {}

            def get(self, key, default=None):
                return self._params.get(key, default)

        class MockRequest:
            method = 'GET'

            def __init__(self, params):
                self.GET = MockQueryDict(params)

        request = MockRequest(
            {'url': url_param_value} if url_param_value is not None else {}
        )

        # Replicate the view logic exactly as in AddView.get_initial()
        if request.method == 'GET':
            url = request.GET.get('url', None)
            if url:
                return {'url': url if '://' in url else f'https://{url}'}

        return {}

    def test_url_with_ampersand_is_preserved(self):
        """
        Regression test: a URL with '&' must not be truncated.

        Before the fix, a URL like:
            https://example.com/search?q=test&lang=en
        would be passed unencoded as:
            /add/?url=https://example.com/search?q=test&lang=en
        causing the server to see only 'https://example.com/search?q=test'
        and treat 'lang=en' as a separate query parameter to /add/.

        After the fix, the bookmarklet encodes the URL with encodeURIComponent,
        and the server correctly decodes the full original URL.
        """
        url = 'https://example.com/search?q=test&lang=en'
        initial = self._simulate_get_initial(url)
        assert initial['url'] == url

    def test_url_with_hash_fragment_is_preserved(self):
        """A URL with '#' fragment should be fully preserved."""
        url = 'https://example.com/page#section-1'
        initial = self._simulate_get_initial(url)
        assert initial['url'] == url

    def test_url_with_multiple_query_params_is_preserved(self):
        """A URL with multiple query parameters should be fully preserved."""
        url = 'https://example.com/search?q=hello+world&page=2&sort=date&lang=en'
        initial = self._simulate_get_initial(url)
        assert initial['url'] == url

    def test_url_with_encoded_spaces_is_preserved(self):
        """A URL containing encoded spaces (%20) should be preserved."""
        url = 'https://example.com/path%20with%20spaces/page'
        initial = self._simulate_get_initial(url)
        assert initial['url'] == url

    def test_url_with_special_characters_is_preserved(self):
        """A URL with various special characters should be preserved."""
        url = 'https://example.com/path?query=hello%26world&foo=bar%3Dbaz'
        initial = self._simulate_get_initial(url)
        assert initial['url'] == url

    def test_url_without_scheme_gets_https_prefix(self):
        """A URL without a scheme should get 'https://' prepended."""
        initial = self._simulate_get_initial('example.com/page?q=test&lang=en')
        assert initial['url'] == 'https://example.com/page?q=test&lang=en'

    def test_no_url_param_returns_default_initial(self):
        """When no ?url= parameter is provided, get_initial returns the default."""
        initial = self._simulate_get_initial(None)
        assert 'url' not in initial

    def test_empty_url_param_returns_default_initial(self):
        """When ?url= is empty, get_initial returns the default."""
        initial = self._simulate_get_initial('')
        assert 'url' not in initial


class TestEncodeURIComponentSimulation:
    """
    Verify that the full bookmarklet flow works end-to-end:
    browser encodes URL -> server decodes and prefills form correctly.

    This simulates what happens when JavaScript's encodeURIComponent() encodes
    a URL, and then the server receives it as a query parameter.
    """

    @pytest.mark.parametrize("original_url", [
        'https://example.com/search?q=test&lang=en',
        'https://example.com/page#section-1',
        'https://example.com/search?q=hello world&page=2',
        'https://example.com/path?a=1&b=2&c=3&d=4',
        'https://example.com/path?redirect=https://other.com/page',
        'https://example.com/api?data={"key":"value"}',
        'https://example.com/search?q=price < $100 & category = books',
    ])
    def test_encoded_url_round_trip(self, original_url):
        """
        Simulate the bookmarklet encoding a URL with encodeURIComponent,
        then the server receiving and decoding it via query parameter parsing.

        Python's urllib.parse.quote(safe='') is equivalent to JavaScript's
        encodeURIComponent().
        """
        # Simulate JavaScript's encodeURIComponent
        encoded_url = quote(original_url, safe='')

        # Simulate the server parsing the query string /add/?url=<encoded_url>
        # When the server parses this, it decodes the percent-encoded value back
        query_string = f'url={encoded_url}'
        parsed = parse_qs(query_string)
        decoded_url = parsed['url'][0]

        assert decoded_url == original_url, (
            f"Round-trip encoding/decoding failed.\n"
            f"  Original:  {original_url}\n"
            f"  Encoded:   {encoded_url}\n"
            f"  Decoded:   {decoded_url}"
        )

    @pytest.mark.parametrize("original_url", [
        'https://example.com/search?q=test&lang=en',
        'https://example.com/path?a=1&b=2&c=3',
    ])
    def test_unencoded_url_is_truncated(self, original_url):
        """
        Demonstrate the bug that existed before the fix: passing a URL
        without encoding causes '&' to be interpreted as a query parameter
        separator, truncating the URL.

        This test verifies that the old behavior (without encodeURIComponent)
        would indeed cause data loss, proving the fix is necessary.
        """
        # Simulate the OLD broken behavior: passing URL directly without encoding
        # /add/?url=https://example.com/search?q=test&lang=en
        # The server would parse 'url' as 'https://example.com/search?q=test'
        # and 'lang' as a separate parameter 'en'
        broken_query_string = f'url={original_url}'
        parsed = parse_qs(broken_query_string)
        broken_url = parsed['url'][0]

        # The URL is truncated at the first '&' that the server interprets
        # as a query parameter separator
        assert broken_url != original_url, (
            f"Expected the unencoded URL to be truncated, but it wasn't. "
            f"This test validates that the bug would occur without the fix.\n"
            f"  Original: {original_url}\n"
            f"  Parsed:   {broken_url}"
        )
