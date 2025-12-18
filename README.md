# flask-sec-fetch-csrf

CSRF protection for Flask using the `Sec-Fetch-Site` header.

This extension protects your Flask application from Cross-Site Request Forgery (CSRF) attacks by validating the `Sec-Fetch-Site` header sent by modern browsers. Unlike token-based CSRF protection, this approach requires no form modifications, no session storage, and no JavaScript integration.

## Motivation

### The HTMX Problem

If you've used [HTMX](https://htmx.org/) with Flask-WTF's CSRF protection, you know the pain:

```html
<!-- Every HTMX element needs the token -->
<button hx-post="/api/action"
        hx-headers='{"X-CSRFToken": "{{ csrf_token() }}"}'>
    Click me
</button>
```

Or you set up global headers:

```html
<meta name="csrf-token" content="{{ csrf_token() }}">
<script>
  document.body.addEventListener('htmx:configRequest', (event) => {
    event.detail.headers['X-CSRFToken'] = document.querySelector('meta[name="csrf-token"]').content;
  });
</script>
```

This is tedious, error-prone, and breaks when tokens expire. With `Sec-Fetch-Site`, HTMX just works:

```html
<!-- No token needed. The browser handles it. -->
<button hx-post="/api/action">Click me</button>
```

### Token Fatigue

Traditional CSRF tokens create ongoing friction:

- **Cached pages** serve stale tokens
- **Expired sessions** invalidate tokens mid-form
- **AJAX requests** need manual token injection
- **Multi-tab usage** can cause token mismatches
- **API clients** need special handling to skip tokens

The `Sec-Fetch-Site` header eliminates all of this. The browser sends it automatically, it never expires, and it works consistently across all request types.

## Inspiration

This extension was inspired by:

- [**Rails PR #56350**](https://github.com/rails/rails/pull/56350) — Rails 8.2 is adopting `Sec-Fetch-Site` as its primary CSRF defense, moving away from tokens
- [**Flask-WTF**](https://flask-wtf.readthedocs.io/) — The established Flask CSRF solution, whose API patterns influenced this extension
- [**Filippo Valsorda's "CSRF"**](https://words.filippo.io/csrf/) — The algorithm and rationale behind header-based CSRF protection

## What is CSRF?

Cross-Site Request Forgery (CSRF) is an attack that tricks users into performing unwanted actions on a website where they're authenticated.

**How it works:**

1. You log into your bank at `bank.example.com`
2. Your browser stores a session cookie
3. You visit a malicious site that contains:
   ```html
   <form action="https://bank.example.com/transfer" method="POST">
     <input type="hidden" name="to" value="attacker">
     <input type="hidden" name="amount" value="10000">
   </form>
   <script>document.forms[0].submit();</script>
   ```
4. Your browser sends the request **with your session cookie**
5. The bank processes the transfer because it looks like a legitimate request

The key insight is that browsers automatically include cookies with requests, even when those requests originate from other sites.

## How This Extension Protects You

Modern browsers send the `Sec-Fetch-Site` header with every request, indicating where the request originated:

| Value | Meaning | Action |
|-------|---------|--------|
| `same-origin` | Request from same origin (scheme + host + port) | ✅ Allow |
| `none` | User typed URL or used bookmark | ✅ Allow |
| `same-site` | Request from same site (e.g., subdomain) | ❌ Deny by default |
| `cross-site` | Request from different site | ❌ Deny |

This extension implements the algorithm recommended by [Filippo Valsorda](https://words.filippo.io/csrf/):

1. **Allow safe methods** — GET, HEAD, OPTIONS don't modify state
2. **Check trusted origins** — Explicitly allowed cross-origin sources
3. **Validate Sec-Fetch-Site** — Allow `same-origin` or `none`, reject others
4. **Handle missing header** — Allow if no `Origin` header either (non-browser client)
5. **Fallback to Origin** — For older browsers, compare `Origin` against `Host`

## Installation

```bash
pip install flask-sec-fetch-csrf
```

## Quick Start

```python
from flask import Flask
from flask_sec_fetch_csrf import SecFetchCSRF

app = Flask(__name__)
csrf = SecFetchCSRF(app)

@app.route('/transfer', methods=['POST'])
def transfer():
    # Protected automatically
    return 'Transfer complete'
```

Or with the application factory pattern:

```python
from flask_sec_fetch_csrf import SecFetchCSRF

csrf = SecFetchCSRF()

def create_app():
    app = Flask(__name__)
    csrf.init_app(app)
    return app
```

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `SEC_FETCH_CSRF_METHODS` | `["POST", "PUT", "PATCH", "DELETE"]` | HTTP methods to protect |
| `SEC_FETCH_CSRF_ALLOW_SAME_SITE` | `False` | Allow requests from same site (subdomains) |
| `SEC_FETCH_CSRF_TRUSTED_ORIGINS` | `[]` | Origins allowed for cross-site requests |

### Protecting Specific Methods

By default, POST, PUT, PATCH, and DELETE requests are protected:

```python
# Only protect POST requests
app.config['SEC_FETCH_CSRF_METHODS'] = ['POST']
```

### Allowing Same-Site Requests

If you trust all subdomains of your site:

```python
# Allow requests from *.example.com to example.com
app.config['SEC_FETCH_CSRF_ALLOW_SAME_SITE'] = True
```

⚠️ **Warning:** Only enable this if you trust all subdomains. A compromised subdomain could perform CSRF attacks.

### Trusted Origins

For legitimate cross-origin requests (e.g., from a separate frontend):

```python
app.config['SEC_FETCH_CSRF_TRUSTED_ORIGINS'] = [
    'https://app.example.com',
    'https://admin.example.com',
]
```

## Exempting Routes

### Exempt a View

Use the `@csrf.exempt` decorator for endpoints that need to accept cross-origin requests (e.g., webhooks):

```python
@csrf.exempt
@app.route('/webhook', methods=['POST'])
def webhook():
    # Accepts requests from anywhere
    return 'OK'
```

### Exempt a Blueprint

```python
from flask import Blueprint

api = Blueprint('api', __name__)
csrf.exempt(api)

@api.route('/data', methods=['POST'])
def api_data():
    # All routes in this blueprint are exempt
    return {'status': 'ok'}
```

## Error Handling

CSRF failures raise `CSRFError` (a 403 Forbidden response). Customize the response:

```python
from flask_sec_fetch_csrf import CSRFError

@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    return {'error': 'CSRF validation failed'}, 403
```

## Browser Support

The `Sec-Fetch-Site` header is [supported in all modern browsers](https://caniuse.com/mdn-http_headers_sec-fetch-site):

| Browser | Version | Release Date |
|---------|---------|--------------|
| Chrome | 76+ | July 2019 |
| Edge | 79+ | January 2020 |
| Firefox | 90+ | July 2021 |
| Safari | 16.4+ | March 2023 |

For older browsers without `Sec-Fetch-Site` support, the extension falls back to `Origin` header validation.

## API Clients and Non-Browser Requests

Requests without browser headers (no `Sec-Fetch-Site` and no `Origin`) are allowed. This permits:

- API clients (requests, httpx, curl)
- Server-to-server communication
- Mobile apps using native HTTP clients

If a request has an `Origin` header but no `Sec-Fetch-Site`, the extension validates that the `Origin` matches the `Host` header.

## Comparison with Token-Based CSRF

| Aspect | Token-Based | Sec-Fetch-Site |
|--------|-------------|----------------|
| Form modifications | Required | None |
| Session storage | Required | None |
| JavaScript integration | Often needed | None |
| Setup complexity | Moderate | Minimal |
| Browser support | Universal | Modern (with fallback) |
| Protection strength | Strong | Strong |

## Security Considerations

1. **HTTPS Required** — `Sec-Fetch-Site` is only sent on secure connections (HTTPS, localhost)

2. **Defense in Depth** — Consider combining with `SameSite` cookies:
   ```python
   app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
   ```

3. **XSS Defeats CSRF Protection** — If your site has XSS vulnerabilities, attackers can bypass any CSRF protection

4. **Subdomain Trust** — Keep `SEC_FETCH_CSRF_ALLOW_SAME_SITE` disabled unless you trust all subdomains

## Migrating from Flask-WTF

If you're currently using Flask-WTF's `CSRFProtect`, migration is straightforward:

### Before (Flask-WTF)

```python
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)
```

```html
<form method="POST">
    <input type="hidden" name="csrf_token" value="{{ csrf_token() }}">
    <!-- form fields -->
</form>
```

### After (flask-sec-fetch-csrf)

```python
from flask_sec_fetch_csrf import SecFetchCSRF

csrf = SecFetchCSRF(app)
```

```html
<form method="POST">
    <!-- No token needed! -->
    <!-- form fields -->
</form>
```

### Key Differences

| Flask-WTF | flask-sec-fetch-csrf |
|-----------|---------------------|
| Requires `{{ csrf_token() }}` in forms | No form changes needed |
| Uses `WTF_CSRF_*` config keys | Uses `SEC_FETCH_CSRF_*` config keys |
| Returns 400 Bad Request on failure | Returns 403 Forbidden on failure |
| `@csrf.exempt` decorator | `@csrf.exempt` decorator (same API) |

### Migration Checklist

1. Replace `from flask_wtf.csrf import CSRFProtect` with `from flask_sec_fetch_csrf import SecFetchCSRF`
2. Rename config keys from `WTF_CSRF_*` to `SEC_FETCH_CSRF_*`
3. Update error handlers to expect 403 instead of 400
4. Remove `{{ csrf_token() }}` from templates
5. Remove any JavaScript that handles CSRF tokens in AJAX requests

## Examples

See the [examples directory](examples/README.md) for a demo application that shows CSRF protection in action, including how to simulate cross-site attacks.

## References

- [Filippo Valsorda: "CSRF"](https://words.filippo.io/csrf/) — The algorithm this extension implements
- [MDN: Cross-Site Request Forgery](https://developer.mozilla.org/en-US/docs/Web/Security/Attacks/CSRF)
- [MDN: Sec-Fetch-Site](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Sec-Fetch-Site)
- [OWASP: CSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html)

## License

BSD-3-Clause License. See [LICENSE](LICENSE) for details.
