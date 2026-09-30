"""ЮKassa for onboarding payments. ТЗ «SaaS-слой» v1, разделы 5.5-5.6.

Two things the ТЗ version did not do and money needs:

- A notification is not trusted as it arrives. Anyone can POST
  {"event": "payment.succeeded", ...} to our URL; the payment is fetched back from
  the ЮKassa API with the shop's credentials and only a payment ЮKassa itself
  reports as succeeded, for the right amount, counts.
- The Idempotence-Key is the request id, so approving the same request twice
  returns the same payment instead of a second one to pay.
"""
from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog

from app.config import config

logger = structlog.get_logger()

API = "https://api.yookassa.ru/v3"
TIMEOUT = 30.0


class YookassaError(Exception):
    pass


def _auth() -> tuple[str, str]:
    if not config.billing_enabled:
        raise YookassaError("ЮKassa не настроена (YOOKASSA_SHOP_ID / YOOKASSA_SECRET_KEY)")
    return (str(config.yookassa_shop_id), str(config.yookassa_secret_key))


async def create_payment(request, plan) -> tuple[str, str]:
    """Payment for the connection fee. Returns (payment_id, confirmation_url)."""
    return_url = (config.platform_landing_url or config.base_url).rstrip("/")
    body = {
        "amount": {"value": f"{plan.one_time_price}.00", "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": f"REIP «{plan.name}» — {request.city_name} — {request.agency_name}"[:128],
        "metadata": {"request_id": str(request.id), "plan_id": plan.id},
    }
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(f"{API}/payments", json=body, auth=_auth(),
                                     headers={"Idempotence-Key": f"onboarding-{request.id}"})
    except httpx.HTTPError as e:
        raise YookassaError(f"ЮKassa не отвечает: {type(e).__name__}") from None
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400 or not data.get("id"):
        raise YookassaError(f"ЮKassa отказала: {data.get('description') or resp.status_code}")
    url = (data.get("confirmation") or {}).get("confirmation_url")
    if not url:
        raise YookassaError("ЮKassa не вернула ссылку на оплату")
    return data["id"], url


async def fetch_payment(payment_id: str) -> dict:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(f"{API}/payments/{payment_id}", auth=_auth())
    except httpx.HTTPError as e:
        raise YookassaError(f"ЮKassa не отвечает: {type(e).__name__}") from None
    if resp.status_code != 200:
        raise YookassaError(f"Платёж {payment_id} не найден в ЮKassa")
    return resp.json()


async def handle_notification(session, body: Any) -> Optional[str]:
    """Process a ЮKassa notification. Returns the request id it paid, or None.

    Idempotent: the unique index on (payment_method, payment_id) and the request
    status both make a repeated notification a no-op.
    """
    import uuid  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from app.models.billing import BillingEvent, OnboardingRequest, SubscriptionPlan  # noqa: PLC0415

    if not isinstance(body, dict) or body.get("event") != "payment.succeeded":
        return None
    payment_id = str((body.get("object") or {}).get("id") or "")
    if not payment_id:
        return None
    payment = await fetch_payment(payment_id)  # the only source we believe
    if payment.get("status") != "succeeded" or not payment.get("paid"):
        logger.warning("ЮKassa notification for an unpaid payment", payment_id=payment_id)
        return None
    request_id = (payment.get("metadata") or {}).get("request_id")
    try:
        request = await session.get(OnboardingRequest, uuid.UUID(str(request_id)))
    except ValueError:
        request = None
    if request is None:
        logger.warning("ЮKassa payment for an unknown request", payment_id=payment_id)
        return None
    already = await session.scalar(select(BillingEvent.id).where(
        BillingEvent.payment_method == "yookassa", BillingEvent.payment_id == payment_id))
    if already is not None or request.status in ("paid", "completed"):
        return None
    plan = await session.get(SubscriptionPlan, request.plan_id)
    amount = float((payment.get("amount") or {}).get("value") or 0)
    if plan is None or amount + 0.01 < plan.one_time_price:
        logger.error("ЮKassa payment amount does not cover the plan",
                     payment_id=payment_id, amount=amount, plan=request.plan_id)
        return None
    request.status = "paid"
    request.payment_id = payment_id
    session.add(BillingEvent(
        onboarding_request_id=request.id, event_type="payment", amount_rub=int(amount),
        payment_method="yookassa", payment_id=payment_id, created_by="webhook:yookassa",
        note=f"Оплата подключения по заявке {str(request.id)[:8]}",
    ))
    await session.commit()
    logger.info("Onboarding paid", request_id=str(request.id), payment_id=payment_id)
    return str(request.id)
