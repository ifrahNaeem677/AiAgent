"""Order lookup connectors.

Every connector returns orders in the same simple shape so the agent
doesn't care which platform the store runs on:

    {
      "order_number": "1001",
      "email": "customer@example.com",
      "status": "Shipped / in transit",
      "created_at": "2026-10-20",
      "items": [{"name": "...", "quantity": 1}],
      "tracking": [{"carrier": "...", "number": "...", "url": "..."}],
      "estimated_delivery": "2026-10-23" | None,
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

import httpx

from .config import Settings


class OrderProvider(Protocol):
    def get_order(self, order_number: str) -> dict | None: ...


def normalise_order_number(raw: str) -> str:
    return raw.strip().lstrip("#").strip()


# --------------------------------------------------------------------------
# Mock: reads data/sample_orders.json. Use this until your store is connected.
# --------------------------------------------------------------------------
class MockOrderProvider:
    def __init__(self, path: Path):
        self.orders = {o["order_number"]: o for o in json.loads(path.read_text())}

    def get_order(self, order_number: str) -> dict | None:
        return self.orders.get(normalise_order_number(order_number))


# --------------------------------------------------------------------------
# Shopify Admin GraphQL API. Needs an app access token with `read_orders`.
# --------------------------------------------------------------------------
SHOPIFY_API_VERSION = "2025-07"
SHOPIFY_ORDER_QUERY = """
query OrderByName($q: String!) {
  orders(first: 1, query: $q) {
    nodes {
      name
      email
      createdAt
      cancelledAt
      displayFinancialStatus
      displayFulfillmentStatus
      lineItems(first: 50) { nodes { name quantity } }
      fulfillments(first: 10) {
        displayStatus
        estimatedDeliveryAt
        deliveredAt
        trackingInfo(first: 5) { company number url }
      }
    }
  }
}
"""


class ShopifyOrderProvider:
    def __init__(self, domain: str, token: str):
        if not domain or not token:
            raise ValueError("Set SHOPIFY_STORE_DOMAIN and SHOPIFY_ADMIN_TOKEN")
        self.url = f"https://{domain}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
        self.headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    def get_order(self, order_number: str) -> dict | None:
        number = normalise_order_number(order_number)
        resp = httpx.post(
            self.url,
            headers=self.headers,
            json={"query": SHOPIFY_ORDER_QUERY, "variables": {"q": f"name:#{number}"}},
            timeout=15,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("errors"):
            raise RuntimeError(f"Shopify error: {body['errors']}")
        nodes = body["data"]["orders"]["nodes"]
        if not nodes:
            return None
        o = nodes[0]

        status = (o.get("displayFulfillmentStatus") or "UNKNOWN").replace("_", " ").title()
        if o.get("cancelledAt"):
            status = "Cancelled"
        tracking, eta, delivered = [], None, None
        for f in o.get("fulfillments") or []:
            if f.get("displayStatus"):
                status = f["displayStatus"].replace("_", " ").title()
            eta = f.get("estimatedDeliveryAt") or eta
            delivered = f.get("deliveredAt") or delivered
            for t in f.get("trackingInfo") or []:
                tracking.append({"carrier": t.get("company"), "number": t.get("number"), "url": t.get("url")})

        return {
            "order_number": o["name"].lstrip("#"),
            "email": o.get("email") or "",
            "status": status,
            "payment_status": o.get("displayFinancialStatus"),
            "created_at": (o.get("createdAt") or "")[:10],
            "items": [{"name": li["name"], "quantity": li["quantity"]} for li in o["lineItems"]["nodes"]],
            "tracking": tracking,
            "estimated_delivery": (eta or "")[:10] or None,
            "delivered_at": (delivered or "")[:10] or None,
        }


# --------------------------------------------------------------------------
# WooCommerce REST API v3. Needs a Read-only consumer key/secret.
# --------------------------------------------------------------------------
WC_STATUS_LABELS = {
    "pending": "Awaiting payment",
    "processing": "Paid - being prepared for dispatch",
    "on-hold": "On hold",
    "completed": "Dispatched / completed",
    "cancelled": "Cancelled",
    "refunded": "Refunded",
    "failed": "Payment failed",
}


class WooCommerceOrderProvider:
    def __init__(self, url: str, key: str, secret: str):
        if not url or not key or not secret:
            raise ValueError("Set WC_STORE_URL, WC_CONSUMER_KEY and WC_CONSUMER_SECRET")
        self.base = url.rstrip("/") + "/wp-json/wc/v3"
        self.auth = (key, secret)

    def get_order(self, order_number: str) -> dict | None:
        number = normalise_order_number(order_number)
        if not number.isdigit():
            return None
        resp = httpx.get(f"{self.base}/orders/{number}", auth=self.auth, timeout=15)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        o = resp.json()

        # Tracking is stored by plugins; this reads the official
        # "WooCommerce Shipment Tracking" plugin's meta field if present.
        tracking = []
        for meta in o.get("meta_data", []):
            if meta.get("key") == "_wc_shipment_tracking_items":
                for t in meta.get("value") or []:
                    tracking.append({
                        "carrier": t.get("tracking_provider") or t.get("custom_tracking_provider"),
                        "number": t.get("tracking_number"),
                        "url": t.get("custom_tracking_link") or None,
                    })

        return {
            "order_number": str(o.get("number") or o["id"]),
            "email": (o.get("billing") or {}).get("email", ""),
            "status": WC_STATUS_LABELS.get(o.get("status"), o.get("status")),
            "created_at": (o.get("date_created") or "")[:10],
            "items": [{"name": li["name"], "quantity": li["quantity"]} for li in o.get("line_items", [])],
            "tracking": tracking,
            "estimated_delivery": None,
        }


def make_order_provider(s: Settings) -> OrderProvider:
    if s.order_backend == "shopify":
        return ShopifyOrderProvider(s.shopify_domain, s.shopify_token)
    if s.order_backend == "woocommerce":
        return WooCommerceOrderProvider(s.wc_url, s.wc_key, s.wc_secret)
    return MockOrderProvider(s.data_dir / "sample_orders.json")
