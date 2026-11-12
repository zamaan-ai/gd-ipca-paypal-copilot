"""
GD-IPCA PayPal Developer Platform Service
Supports real PayPal REST API v2 (OAuth2, Orders v2, Capture, Payouts v1) in Sandbox/Live
with deterministic sandbox simulation fallback when credentials are unconfigured.
"""
from __future__ import annotations
import base64
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import httpx

from app.core.config import settings
from app.services.cache import cache

logger = logging.getLogger("gdipca.paypal")

_PLACEHOLDERS = {"", "your_paypal_sandbox_client_id", "your_paypal_sandbox_client_secret"}


class PayPalService:
    def __init__(self) -> None:
        self.base_url = settings.PAYPAL_BASE_URL.rstrip("/")

    def is_live_configured(self) -> bool:
        if settings.PAYPAL_MODE.lower() in ("sim", "simulation", "sandbox_simulation", "mock"):
            return False
        cid = (settings.PAYPAL_CLIENT_ID or "").strip()
        sec = (settings.PAYPAL_CLIENT_SECRET or "").strip()
        return bool(cid and sec and cid not in _PLACEHOLDERS and sec not in _PLACEHOLDERS)

    def current_mode(self) -> str:
        if self.is_live_configured():
            return "live" if settings.PAYPAL_MODE.lower() == "live" else "sandbox_live"
        return "sandbox_simulation"

    def get_access_token(self) -> str:
        """Obtain PayPal OAuth2 Bearer Token via client_credentials grant."""
        cached = cache.get("paypal:oauth:token")
        if cached:
            return cached

        if not self.is_live_configured():
            raise RuntimeError("PayPal Sandbox credentials are not configured.")

        creds = f"{settings.PAYPAL_CLIENT_ID}:{settings.PAYPAL_CLIENT_SECRET}"
        encoded = base64.b64encode(creds.encode("utf-8")).decode("utf-8")
        headers = {
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        with httpx.Client(timeout=12.0) as client:
            resp = client.post(
                f"{self.base_url}/v1/oauth2/token",
                headers=headers,
                data={"grant_type": "client_credentials"},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"PayPal OAuth2 failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        token = data["access_token"]
        expires_in = max(60, int(data.get("expires_in", 3600)) - 120)
        cache.set("paypal:oauth:token", token, ttl=expires_in)
        return token

    def create_order(
        self,
        amount: float,
        currency: str = "USD",
        description: str = "GD-IPCA Goal Funding Deposit",
        reference_id: Optional[str] = None,
        return_url: str = "http://localhost:5173/?paypal=success",
        cancel_url: str = "http://localhost:5173/?paypal=cancel",
    ) -> Dict[str, Any]:
        """Create a PayPal Orders v2 payment intent (CAPTURE)."""
        formatted_amount = f"{round(float(amount), 2):.2f}"
        ref = reference_id or f"GDIPCA-{uuid.uuid4().hex[:8].upper()}"

        if not self.is_live_configured():
            sim_order_id = f"PP-SIM-{uuid.uuid4().hex[:10].upper()}"
            return {
                "id": sim_order_id,
                "status": "CREATED",
                "mode": "sandbox_simulation",
                "intent": "CAPTURE",
                "amount": float(formatted_amount),
                "currency": currency,
                "approval_url": f"https://www.sandbox.paypal.com/checkoutnow?token={sim_order_id}",
                "raw": {
                    "id": sim_order_id,
                    "status": "CREATED",
                    "intent": "CAPTURE",
                    "purchase_units": [
                        {
                            "reference_id": ref,
                            "description": description,
                            "amount": {"currency_code": currency, "value": formatted_amount},
                        }
                    ],
                    "links": [
                        {
                            "href": f"https://www.sandbox.paypal.com/checkoutnow?token={sim_order_id}",
                            "rel": "approve",
                            "method": "GET",
                        }
                    ],
                    "create_time": datetime.now(timezone.utc).isoformat(),
                },
            }

        token = self.get_access_token()
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "reference_id": ref,
                    "description": description[:127],
                    "amount": {"currency_code": currency, "value": formatted_amount},
                }
            ],
            "application_context": {
                "brand_name": "GD-IPCA Wealth Copilot",
                "user_action": "PAY_NOW",
                "return_url": return_url,
                "cancel_url": cancel_url,
            },
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "PayPal-Request-Id": f"req-{uuid.uuid4().hex[:12]}",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{self.base_url}/v2/checkout/orders", headers=headers, json=payload)

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"PayPal Create Order failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        approve_url = next((l["href"] for l in data.get("links", []) if l.get("rel") == "approve"), None)
        return {
            "id": data["id"],
            "status": data.get("status", "CREATED"),
            "mode": self.current_mode(),
            "intent": "CAPTURE",
            "amount": float(formatted_amount),
            "currency": currency,
            "approval_url": approve_url,
            "raw": data,
        }

    def capture_order(self, order_id: str) -> Dict[str, Any]:
        """Capture an approved PayPal Orders v2 order."""
        if not self.is_live_configured() or order_id.startswith("PP-SIM-"):
            cap_id = f"CAP-SIM-{uuid.uuid4().hex[:10].upper()}"
            return {
                "id": order_id,
                "capture_id": cap_id,
                "status": "COMPLETED",
                "mode": "sandbox_simulation",
                "raw": {
                    "id": order_id,
                    "status": "COMPLETED",
                    "purchase_units": [
                        {
                            "payments": {
                                "captures": [
                                    {
                                        "id": cap_id,
                                        "status": "COMPLETED",
                                        "final_capture": True,
                                        "create_time": datetime.now(timezone.utc).isoformat(),
                                    }
                                ]
                            }
                        }
                    ],
                },
            }

        token = self.get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{self.base_url}/v2/checkout/orders/{order_id}/capture", headers=headers)

        if resp.status_code not in (200, 201):
            err_data = {}
            try:
                err_data = resp.json()
            except Exception:
                pass
            issue = ""
            if isinstance(err_data, dict) and "details" in err_data and err_data["details"]:
                issue = err_data["details"][0].get("issue", "")
            if issue == "ORDER_NOT_APPROVED":
                raise RuntimeError(
                    f"PayPal Order {order_id} has not been approved yet. "
                    "Please click 'Open PayPal Checkout', log in with your Sandbox Buyer account, "
                    "complete the approval, and then click 'Capture Order'."
                )
            raise RuntimeError(f"PayPal Capture failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        capture_id = None
        try:
            capture_id = data["purchase_units"][0]["payments"]["captures"][0]["id"]
        except (KeyError, IndexError, TypeError):
            capture_id = data.get("id")

        return {
            "id": data.get("id", order_id),
            "capture_id": capture_id,
            "status": data.get("status", "COMPLETED"),
            "mode": self.current_mode(),
            "raw": data,
        }

    def create_payout(
        self,
        recipient_email: str,
        amount: float,
        currency: str = "USD",
        note: str = "GD-IPCA Goal Milestone Disbursement",
    ) -> Dict[str, Any]:
        """Disburse funds to a PayPal recipient via Payouts API v1."""
        formatted_amount = f"{round(float(amount), 2):.2f}"
        batch_sender_id = f"GDIPCA-BATCH-{uuid.uuid4().hex[:10].upper()}"

        if not self.is_live_configured():
            sim_batch_id = f"PAYOUT-SIM-{uuid.uuid4().hex[:10].upper()}"
            return {
                "payout_batch_id": sim_batch_id,
                "status": "SUCCESS",
                "mode": "sandbox_simulation",
                "recipient_email": recipient_email,
                "amount": float(formatted_amount),
                "currency": currency,
                "raw": {
                    "batch_header": {
                        "payout_batch_id": sim_batch_id,
                        "batch_status": "SUCCESS",
                        "sender_batch_header": {"sender_batch_id": batch_sender_id},
                    }
                },
            }

        token = self.get_access_token()
        payload = {
            "sender_batch_header": {
                "sender_batch_id": batch_sender_id,
                "email_subject": "GD-IPCA Portfolio Disbursement",
                "email_message": note[:250],
            },
            "items": [
                {
                    "recipient_type": "EMAIL",
                    "amount": {"value": formatted_amount, "currency": currency},
                    "note": note[:250],
                    "sender_item_id": f"ITEM-{uuid.uuid4().hex[:8].upper()}",
                    "receiver": recipient_email,
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(f"{self.base_url}/v1/payments/payouts", headers=headers, json=payload)

        if resp.status_code not in (200, 201):
            raise RuntimeError(f"PayPal Payout failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        header = data.get("batch_header", {})
        return {
            "payout_batch_id": header.get("payout_batch_id", batch_sender_id),
            "status": header.get("batch_status", "PENDING"),
            "mode": self.current_mode(),
            "recipient_email": recipient_email,
            "amount": float(formatted_amount),
            "currency": currency,
            "raw": data,
        }


paypal_service = PayPalService()
