"""
CSRF protection for Flask using Sec-Fetch-Site header.

This module provides the SecFetchCSRF class which implements CSRF protection
by validating the Sec-Fetch-Site header sent by modern browsers, with a
fallback to Origin header validation for older browsers.

The implementation follows the algorithm recommended by Filippo Valsorda:
https://words.filippo.io/csrf/
"""

from urllib.parse import urlparse

from flask import Blueprint, current_app, request

from .exceptions import CSRFError


class SecFetchCSRF:
    """Enable CSRF protection using the Sec-Fetch-Site header.

    Modern browsers send the ``Sec-Fetch-Site`` header with every request,
    indicating whether the request originated from the same origin, same site,
    or a cross-site context. This extension validates that header to prevent
    CSRF attacks without requiring tokens.

    For browsers that don't support Sec-Fetch-Site (pre-2020), the extension
    falls back to validating the Origin header against the Host header.

    The algorithm follows Filippo Valsorda's recommendations:

    1. Allow safe methods (GET, HEAD, OPTIONS)
    2. Check trusted origins allowlist
    3. If Sec-Fetch-Site present: Allow same-origin or none, reject others
    4. If no Sec-Fetch-Site AND no Origin: Allow (non-browser client)
    5. If Origin present: Compare against Host header

    ::

        app = Flask(__name__)
        csrf = SecFetchCSRF(app)

    Or with the application factory pattern::

        csrf = SecFetchCSRF()

        def create_app():
            app = Flask(__name__)
            csrf.init_app(app)
            return app

    Exempt a view from protection::

        @csrf.exempt
        @app.route('/webhook', methods=['POST'])
        def webhook():
            return 'OK'

    Exempt a blueprint::

        api = Blueprint('api', __name__)
        csrf.exempt(api)

    :param app: The Flask application to protect.
    """

    # Safe HTTP methods that don't require CSRF protection
    SAFE_METHODS = frozenset(["GET", "HEAD", "OPTIONS", "TRACE"])

    def __init__(self, app=None):
        self._exempt_views = set()
        self._exempt_blueprints = set()

        if app is not None:
            self.init_app(app)

    def init_app(self, app):
        """Register CSRF protection with a Flask application.

        Sets up configuration defaults and registers a before_request
        handler to validate requests.

        :param app: The Flask application to protect.
        """
        app.config.setdefault(
            "SEC_FETCH_CSRF_METHODS", ["POST", "PUT", "PATCH", "DELETE"]
        )
        app.config.setdefault("SEC_FETCH_CSRF_ALLOW_SAME_SITE", False)
        app.config.setdefault("SEC_FETCH_CSRF_TRUSTED_ORIGINS", [])

        @app.before_request
        def sec_fetch_csrf_protect():
            # Step 1: Allow safe methods
            if request.method in self.SAFE_METHODS:
                return

            if request.method not in current_app.config["SEC_FETCH_CSRF_METHODS"]:
                return

            if request.endpoint is None:
                return

            if self._is_exempt():
                return

            self.protect()

    def _is_exempt(self):
        """Check if the current request is exempt from CSRF validation."""
        if request.blueprint in self._exempt_blueprints:
            return True

        view = current_app.view_functions.get(request.endpoint)
        if view is not None:
            view_location = f"{view.__module__}.{view.__name__}"
            if view_location in self._exempt_views:
                return True

        return False

    def protect(self):
        """Validate the current request for CSRF.

        This is called automatically for protected HTTP methods.
        Can also be called manually in views if needed.

        :raises CSRFError: If validation fails.
        """
        origin = request.headers.get("Origin")
        sec_fetch_site = request.headers.get("Sec-Fetch-Site")

        # Step 2: Check trusted origins allowlist
        trusted_origins = current_app.config["SEC_FETCH_CSRF_TRUSTED_ORIGINS"]
        if origin and origin in trusted_origins:
            return

        # Step 3: Evaluate Sec-Fetch-Site if present
        if sec_fetch_site:
            self._validate_sec_fetch_site(sec_fetch_site)
            return

        # Step 4: If no Sec-Fetch-Site AND no Origin, allow (non-browser client)
        if not origin:
            return

        # Step 5: Origin present, compare against Host header
        self._validate_origin(origin)

    def _validate_sec_fetch_site(self, sec_fetch_site):
        """Validate based on Sec-Fetch-Site header value.

        Allow same-origin or none, reject others.

        :param sec_fetch_site: The header value.
        :raises CSRFError: If validation fails.
        """
        sec_fetch_site = sec_fetch_site.lower().strip()

        # same-origin: Always allowed
        if sec_fetch_site == "same-origin":
            return

        # none: User-initiated navigation (bookmarks, typed URL)
        if sec_fetch_site == "none":
            return

        # same-site: Configurable (default: reject)
        if sec_fetch_site == "same-site":
            if current_app.config["SEC_FETCH_CSRF_ALLOW_SAME_SITE"]:
                return
            raise CSRFError("Same-site requests are not allowed.")

        # cross-site: Always blocked
        if sec_fetch_site == "cross-site":
            raise CSRFError("Cross-site requests are not allowed.")

        # Unknown value: Treat as suspicious
        raise CSRFError(f"Unknown Sec-Fetch-Site value: {sec_fetch_site}")

    def _validate_origin(self, origin):
        """Validate Origin header against Host header.

        :param origin: The Origin header value.
        :raises CSRFError: If validation fails.
        """
        target_host = self._get_target_host()
        origin_host = self._extract_host(origin)

        if origin_host != target_host:
            raise CSRFError(f"Origin mismatch: {origin}")

    def _get_target_host(self):
        """Get the target host from the request.

        Handles proxy setups via X-Forwarded-Host.
        """
        return request.headers.get("X-Forwarded-Host", request.host)

    def _extract_host(self, origin):
        """Extract host:port from an origin URL."""
        parsed = urlparse(origin)
        if parsed.port and parsed.port not in (80, 443):
            return f"{parsed.hostname}:{parsed.port}"
        return parsed.hostname

    def exempt(self, view):
        """Exempt a view or blueprint from CSRF protection.

        Can be used as a decorator on a view::

            @csrf.exempt
            @app.route('/webhook', methods=['POST'])
            def webhook():
                return 'OK'

        Or called directly on a blueprint::

            api = Blueprint('api', __name__)
            csrf.exempt(api)

        :param view: A view function or Blueprint to exempt.
        :return: The original view or blueprint.
        """
        if isinstance(view, Blueprint):
            self._exempt_blueprints.add(view.name)
        else:
            view_location = f"{view.__module__}.{view.__name__}"
            self._exempt_views.add(view_location)

        return view
