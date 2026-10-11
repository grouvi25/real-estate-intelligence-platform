"""DemoDataGenerator: синтетический кабинет агентства для демо. ТЗ «Сигналы» 7.4.

Shapes are copied from the real endpoints (the screens render them unchanged),
values are made up:

* names are bare common first names, never a real person's full name;
* phones are +7 900 000-XX-XX -- the 900 000 block is not issued to anyone;
* no links to real chats or listings (signal_url is empty);
* every record carries is_demo=True and demo_label.

Deterministic per city (a seeded random), so a visitor sees the same agency on
every refresh. Stored in Redis without TTL under a versioned key -- bump
DATA_VERSION when the shapes change. Timestamps are produced at response time
from stored minute offsets, and every five minutes another signal becomes
«только что»: the activity looks live without anything being written.
"""
from __future__ import annotations

import json
import re
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

DEMO_CITIES = ["Краснодар", "Геленджик", "Новороссийск", "Анапа", "Сочи"]
DATA_VERSION = 1
DEMO_LABEL = "Демонстрационные данные"
_NS = uuid.UUID("5b3f1c6e-0d1a-4b8e-9a52-6f0c9d2e7a11")
_IN = {"Краснодар": "Краснодаре", "Геленджик": "Геленджике", "Новороссийск": "Новороссийске",
       "Анапа": "Анапе", "Сочи": "Сочи"}

NAMES = ["Анна", "Сергей", "Ольга", "Дмитрий", "Марина", "Игорь", "Екатерина", "Алексей",
         "Наталья", "Павел", "Юлия", "Андрей", "Светлана", "Максим", "Ирина", "Роман",
         "Елена", "Виктор", "Татьяна", "Николай"]
MANAGERS = ["Алина (демо)", "Григорий (демо)", "Вера (демо)"]

# (text template, segment, category, score range)
SIGNAL_TEMPLATES = [
    ("Ищем двушку в {in_city} для семьи с ребёнком, бюджет до {b} млн, ипотека одобрена", "family", "purchase", (80, 95)),
    ("Куплю квартиру в {in_city} под сдачу, рассматриваю новостройки, до {b} млн", "investor", "purchase", (75, 92)),
    ("Переезжаем в {city} из Сибири весной, присматриваемся к районам — где лучше с детьми?", "relocant", "purchase", (55, 75)),
    ("Подскажите, реально ли купить дом в {in_city} до {b} млн? Нужен участок от 4 соток", "family", "purchase", (60, 85)),
    ("Рассматриваю студию в {in_city} как вложение, кто брал в рассрочку у застройщика?", "investor", "purchase", (50, 70)),
    ("Хотим перебраться в {city} на пенсию, ищем однушку у моря, наличные {b} млн", "relocant", "purchase", (70, 90)),
    ("Работаю удалённо, хочу купить квартиру в {in_city}, чтобы жить у моря круглый год", "remote_worker", "purchase", (60, 80)),
    ("Какой первоначальный взнос нужен на семейную ипотеку в {in_city}? Планируем покупку", "family", "purchase", (45, 65)),
    ("Ставку по льготной ипотеке снова поменяли, что это значит для покупателей в {in_city}?", "investor", "news", (40, 50)),
    ("Новый закон о долевом строительстве — кто разбирался, как он коснётся сделок?", "investor", "news", (40, 48)),
    ("Ищу квартиру в {in_city}: сниму на полгода, а потом, возможно, куплю", "relocant", "rental", (40, 55)),
    ("Кто знает, где в {in_city} хороший нотариус для сделки?", "family", "other", (40, 52)),
]
REPLY_DRAFT = ("Добрый день! В {in_city} под ваш запрос сейчас есть несколько вариантов в "
               "пределах {b} млн. Могу прислать подборку и подсказать районы, где проще уложиться.")
PROPERTY_TITLES = ["2-к. квартира, 54 м², 4/9 эт.", "1-к. квартира, 38 м², 7/12 эт.",
                   "Дом 120 м² на участке 5 сот.", "Студия, 26 м², 3/16 эт.",
                   "3-к. квартира, 78 м², 2/5 эт.", "Таунхаус 96 м², 2 эт."]
SOURCES = [("telegram", "Telegram"), ("vk", "ВКонтакте"), ("youtube", "YouTube"),
           ("rss", "Новостные ленты"), ("direct", "Прямые обращения")]


def _id(city: str, kind: str, i: int) -> str:
    return str(uuid.uuid5(_NS, f"{city}:{kind}:{i}"))


def _phone(i: int) -> str:
    return f"+7 900 000-{i // 100 % 100:02d}-{i % 100:02d}"


def _mark(obj: dict) -> dict:
    obj["is_demo"] = True
    obj["demo_label"] = DEMO_LABEL
    return obj


def build(city: str) -> dict:
    """Everything the demo screens read, for one city. Pure function."""
    if city not in DEMO_CITIES:
        city = DEMO_CITIES[0]
    rnd = random.Random(f"reip-demo:{city}:{DATA_VERSION}")
    fmt = {"city": city, "in_city": _IN.get(city, city)}

    signals = []
    for i in range(50):
        tpl, segment, category, (lo, hi) = SIGNAL_TEMPLATES[i % len(SIGNAL_TEMPLATES)]
        budget = rnd.choice([6, 7, 8, 9, 11, 12, 15, 18])
        score = rnd.randint(lo, hi)
        signals.append(_mark({
            "id": _id(city, "signal", i),
            "raw_text": tpl.format(b=budget, **fmt),
            "intent_score": score,
            "segment": segment,
            "urgency": "hot" if score >= 80 else ("warm" if score >= 60 else "cold"),
            "status": "qualified" if i % 7 == 0 else "new",
            "geo_location_id": _id(city, "geo", 0),
            "offset_min": 15 + i * rnd.randint(20, 70),
            "signal_url": None,
            "source_name": f"Демо-чат «Недвижимость {city}»" if i % 3 else f"Демо-группа «{city}: жильё»",
            "source_type": "telegram_chat" if i % 3 else "vk_group",
            "origin_system": "reip_scouting",
            "reply_channel": "telegram" if i % 3 else "vk_api",
            "reply_status": "pending" if i % 4 else "sent",
            "reply_draft": REPLY_DRAFT.format(b=budget, **fmt) if i % 5 == 0 else None,
            "score_reason": "прямой запрос на покупку" if category == "purchase" else "косвенный интерес",
            "triage_reason": None,
            "signal_category": category,
            "signal_category_label": {"purchase": "Покупка", "rental": "Аренда", "news": "Новости",
                                      "other": "Прочее", "competitor": "Конкуренты"}[category],
            "lead_id": _id(city, "lead", i // 7) if i % 7 == 0 else None,
        }))

    leads = []
    statuses = ["new"] * 8 + ["in_progress"] * 5 + ["qualified"] * 4 + ["deal"] * 2 + ["archived"]
    for i in range(20):
        budget = rnd.choice([6, 7, 8, 9, 11, 12, 15, 18]) * 1_000_000
        segment = rnd.choice(["family", "investor", "relocant", "remote_worker"])
        matches = [_mark({
            "property_id": _id(city, "property", i * 3 + k),
            "title": f"{rnd.choice(PROPERTY_TITLES)} (демо)",
            "price": int(budget * rnd.uniform(0.82, 1.0) / 10_000) * 10_000,
            "match_score": rnd.randint(62, 94),
            "pitch": f"Подходит по бюджету и району, {fmt['in_city']} — 10 минут до моря.",
            "status": "suggested",
        }) for k in range(rnd.randint(1, 3))]
        leads.append(_mark({
            "id": _id(city, "lead", i),
            "name": NAMES[i % len(NAMES)],
            "phone": _phone(i + 1),
            "telegram_username": None,
            "segment": segment,
            "status": statuses[i],
            "intent_score": rnd.randint(55, 96),
            "budget_min": None,
            "budget_max": budget,
            "urgency": rnd.choice(["hot", "warm", "warm", "cold"]),
            "offset_min": 60 + i * rnd.randint(90, 300),
            "email": None,
            "source_type": "signal",
            "source_platform": "telegram",
            "purchase_goal": {"investor": "invest", "relocant": "relocate"}.get(segment, "own"),
            "lead_type": "buyer",
            "buyer_profile": {},
            "consent_given": True,
            "signal_id": _id(city, "signal", i * 7) if i * 7 < 50 else None,
            "topnlab_client_id": None,
            "matches": matches,
        }))

    by_status: dict[str, int] = {}
    for lead in leads:
        by_status[lead["status"]] = by_status.get(lead["status"], 0) + 1
    deals = by_status.get("deal", 0) + 2
    months = []
    today = datetime.now(timezone.utc).date().replace(day=1)
    for back in range(5, -1, -1):
        month = (today - timedelta(days=back * 31)).replace(day=1)
        d = rnd.randint(0, 3)
        months.append({"month": month.isoformat(), "deals": d, "commission": d * rnd.randint(180, 320) * 1000})
    managers = [{"manager_id": _id(city, "manager", k), "name": name,
                 "deals": rnd.randint(2, 9), "deals_won": rnd.randint(1, 3),
                 "commission": rnd.randint(200, 700) * 1000} for k, name in enumerate(MANAGERS)]
    total = len(leads)
    stages = {"new": by_status.get("new", 0), "in_progress": by_status.get("in_progress", 0),
              "qualified": by_status.get("qualified", 0), "deal": by_status.get("deal", 0)}

    return {
        "city": city,
        "signals": signals,
        "leads": leads,
        "overview": _mark({
            "total_leads": total, "active_properties": rnd.randint(28, 46),
            "urgent_tasks": rnd.randint(2, 5), "deals_won": deals, "deals_lost": rnd.randint(1, 3),
            "total_commission": sum(m["commission"] for m in months),
            "setup": {"done": 4, "total": 4, "steps": []},
        }),
        "funnel": _mark({
            "total": total, "stages": stages, "by_status": by_status,
            "conversion": {
                "new_to_progress": round(100 * (total - stages["new"]) / total, 1),
                "progress_to_qualified": round(100 * (stages["qualified"] + stages["deal"])
                                               / max(1, total - stages["new"]), 1),
                "qualified_to_deal": round(100 * stages["deal"] / max(1, stages["qualified"] + stages["deal"]), 1),
                "overall": round(100 * stages["deal"] / total, 1)},
        }),
        "managers": _mark({"managers": managers}),
        "timeline": _mark({"months": months}),
        "source_roi": _mark({"sources": [
            {"source": key, "leads": rnd.randint(2, 9), "deals_won": rnd.randint(0, 2),
             "commission": rnd.randint(0, 4) * 150_000, "conversion_pct": round(rnd.uniform(5, 25), 1)}
            for key, _ in SOURCES]}),
        "matching_weights": _mark({"weights": {"budget_weight": 30, "segment_weight": 25,
                                               "location_weight": 20, "priorities_weight": 15,
                                               "urgency_weight": 10},
                                   "source": "default", "updated_at": None}),
        "tasks_summary": _mark({"pending": rnd.randint(4, 9), "urgent": rnd.randint(1, 3), "overdue": 0}),
    }


# ---------------------------------------------------------------- response time

def _at(offset_min: int, now: datetime) -> str:
    return (now - timedelta(minutes=offset_min)).isoformat()


def _live(signals: list[dict], now: datetime) -> list[dict]:
    """Every 5 minutes another signal is the newest one."""
    bucket = int(now.timestamp() // 300)
    fresh = bucket % min(10, len(signals))
    out = []
    for i, s in enumerate(signals):
        s = dict(s)
        offset = 2 if i == fresh else s.pop("offset_min", 30) + (0 if i > fresh else 5)
        s.pop("offset_min", None)
        s["created_at"] = _at(offset, now)
        out.append(s)
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


SIGNAL_LIST_FIELDS = ("id", "raw_text", "intent_score", "segment", "urgency", "status",
                      "geo_location_id", "created_at", "signal_url", "source_name", "source_type",
                      "origin_system", "reply_channel", "reply_status", "triage_reason",
                      "signal_category", "signal_category_label", "is_demo", "demo_label")
QUEUE_FIELDS = ("id", "raw_text", "intent_score", "segment", "origin_system", "reply_channel",
                "reply_status", "reply_draft", "signal_url", "score_reason", "urgency", "created_at",
                "is_demo", "demo_label")
LEAD_LIST_FIELDS = ("id", "name", "phone", "telegram_username", "segment", "status", "intent_score",
                    "budget_min", "budget_max", "urgency", "created_at", "is_demo", "demo_label")


def _pick(obj: dict, fields) -> dict:
    return {k: obj.get(k) for k in fields}


NOT_FOUND = {"__demo_not_found__": True}
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def respond(data: dict, path: str, query: dict, agency_city: str, now: Optional[datetime] = None):
    """The JSON a demo GET gets, NOT_FOUND for a card the dataset does not have,
    or None when the path is not part of the demo."""
    now = now or datetime.now(timezone.utc)
    limit = max(1, min(int(query.get("limit") or 50), 200)) if str(query.get("limit") or "50").isdigit() else 50
    signals = _live(data["signals"], now)
    if path == "/api/signals":
        cats = [c for c in (query.get("category") or "").split(",") if c]
        items = [s for s in signals if not cats or s["signal_category"] in cats]
        items = [_pick(s, SIGNAL_LIST_FIELDS) for s in items][:limit]
        return {"count": len(items), "signals": items}
    if path == "/api/signals/queue":
        items = [_pick(s, QUEUE_FIELDS) for s in signals if s["reply_status"] == "pending"][:limit]
        return {"count": len(items), "signals": items}
    if path.startswith("/api/signals/"):
        sid = path.rsplit("/", 1)[-1]
        if not _UUID.match(sid) or path.count("/") != 3:
            return None  # /api/signals/<id>/something: not a card
        for s in signals:
            if s["id"] == sid:
                return {**_pick(s, SIGNAL_LIST_FIELDS), "lead_id": s.get("lead_id")}
        return NOT_FOUND
    if path in ("/api/leads", "/api/leads/") or path.startswith("/api/leads/"):
        leads = []
        for lead in data["leads"]:
            lead = dict(lead)
            lead["created_at"] = _at(lead.pop("offset_min", 60), now)
            leads.append(lead)
        if path.rstrip("/") == "/api/leads":
            status = query.get("status")
            items = [ld for ld in leads if not status or ld["status"] == status]
            return {"count": len(items[:limit]), "leads": [_pick(ld, LEAD_LIST_FIELDS) for ld in items[:limit]]}
        lid = path.rsplit("/", 1)[-1]
        if not _UUID.match(lid) or path.count("/") != 3:
            return None  # /api/leads/export and the like: not part of the demo
        return next((ld for ld in leads if ld["id"] == lid), NOT_FOUND)
    simple = {
        "/api/analytics/overview": "overview", "/api/analytics/funnel": "funnel",
        "/api/analytics/managers": "managers", "/api/analytics/timeline": "timeline",
        "/api/analytics/source-roi": "source_roi", "/api/analytics/matching-weights": "matching_weights",
        "/api/tasks/summary": "tasks_summary",
    }
    if path in simple:
        return data[simple[path]]
    if path == "/api/agency/signal-filter":
        return {"enabled_cats": ["purchase", "rental", "news", "competitor", "other"],
                "categories": [{"key": k, "label": v} for k, v in (
                    ("purchase", "Покупка"), ("rental", "Аренда"), ("news", "Новости"),
                    ("competitor", "Конкуренты"), ("other", "Прочее"))],
                "competitor_names": [], "competitors_found": [], "is_demo": True}
    if path == "/api/auth/config":
        return {"maps_key": None, "brand": None, "is_demo": True,
                "agency": {"id": "demo", "name": f"Демо-агентство · {agency_city}", "city": agency_city},
                "manager": {"id": "demo", "role": "demo", "name": "Гость"}}
    return None


def dumps(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False)
