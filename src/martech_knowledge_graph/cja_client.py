"""Minimal client for the Adobe CJA API (OAuth Server-to-Server) -- stdlib only, no extra dependency."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

IMS_TOKEN_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
CJA_BASE_URL = "https://cja.adobe.io"
DEFAULT_SCOPES = "openid,AdobeID,read_organizations,additional_info.projectedProductContext"
PAGE_SIZE = 1000
MAX_PAGES = 50


class CjaError(Exception):
    """Raised with a message that is safe to show to the user (never contains the client secret)."""


def _request(method, url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        try:
            parsed = json.loads(body)
            body = parsed.get("error_description") or parsed.get("message") or parsed.get("error") or body
        except (json.JSONDecodeError, AttributeError):
            pass
        raise CjaError(f"HTTP {exc.code} from {urllib.parse.urlparse(url).netloc}: {body}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CjaError(f"Could not reach {urllib.parse.urlparse(url).netloc}: {getattr(exc, 'reason', exc)}") from None


class CjaClient:
    def __init__(self, client_id, client_secret, org_id, scopes=DEFAULT_SCOPES):
        self.client_id = client_id
        self.client_secret = client_secret
        self.org_id = org_id
        self.scopes = scopes
        self._token = None
        self._token_expiry = 0

    def token(self):
        if self._token and time.time() < self._token_expiry - 60:
            return self._token
        form = urllib.parse.urlencode({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
            "scope": self.scopes,
        }).encode("utf-8")
        result = _request("POST", IMS_TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"}, form)
        if not isinstance(result, dict) or "access_token" not in result:
            raise CjaError("Token response did not contain an access_token.")
        self._token = result["access_token"]
        expires_in = float(result.get("expires_in", 3600))
        if expires_in > 1_000_000:  # older IMS endpoints report milliseconds
            expires_in /= 1000
        self._token_expiry = time.time() + expires_in
        return self._token

    def _get(self, path, params=None):
        query = "?" + urllib.parse.urlencode(params) if params else ""
        return _request("GET", f"{CJA_BASE_URL}{path}{query}", {
            "Authorization": f"Bearer {self.token()}",
            "x-api-key": self.client_id,
            "x-gw-ims-org-id": self.org_id,
            "Accept": "application/json",
        })

    def _get_all(self, path):
        """Collect every item, tolerating either a bare list or a {"content": [...]} page envelope."""
        items, seen = [], set()
        for page in range(MAX_PAGES):
            result = self._get(path, {"limit": PAGE_SIZE, "page": page})
            batch = result.get("content", []) if isinstance(result, dict) else (result or [])
            new = [i for i in batch if isinstance(i, dict) and i.get("id") not in seen]
            if not new:
                break
            for i in new:
                seen.add(i.get("id"))
            items += new
            if len(batch) < PAGE_SIZE:
                break
        return items

    def list_data_views(self):
        return [{"id": d["id"], "name": d.get("name") or d["id"]} for d in self._get_all("/data/dataviews")]

    def list_components(self, data_view_id):
        """[{"id", "name", "type": "metric"|"dimension"}] for one data view."""
        dv = urllib.parse.quote(data_view_id, safe="")
        out = []
        for kind, ctype in (("metrics", "metric"), ("dimensions", "dimension")):
            for item in self._get_all(f"/data/dataviews/{dv}/{kind}"):
                cid = item.get("id")
                if cid:
                    out.append({"id": cid, "name": item.get("name") or item.get("title") or cid, "type": ctype})
        return out


def component_key(cja_id):
    """'metrics/page_views' -> 'page_views'; anything non-alphanumeric becomes '_'."""
    tail = cja_id.split("/", 1)[-1]
    return re.sub(r"[^a-z0-9]+", "_", tail.lower()).strip("_") or "component"
