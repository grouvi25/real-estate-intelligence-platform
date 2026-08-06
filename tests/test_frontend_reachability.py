"""Every feature must be reachable from the interface, and every UI call must hit
a real endpoint.

Written after an audit found the documents router (preliminary contract and
document checklist, TZ 35.9) shipped, tested and deployed with no button
anywhere -- a manager could not reach it at all. Nothing in the test suite could
have caught that: the backend tests passed and the front end never referenced it.

These tests parse the sources rather than run a browser, so they are cheap enough
to keep in CI and they fail the moment an endpoint or a screen is orphaned.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MINI_APP = ROOT / "mini_app"
JS = sorted(MINI_APP.rglob("*.js"))
SCREENS = sorted((MINI_APP / "js" / "screens").glob("*.js"))
API_CLIENT = (MINI_APP / "js" / "api_client.js").read_text(encoding="utf-8")
APP_JS = (MINI_APP / "js" / "app.js").read_text(encoding="utf-8")

# Reached without a manager pressing anything in the Mini App.
NOT_UI_REACHABLE = {
    "POST /api/auth/platform",          # the SPA bootstrap, in auth.js
    "POST /api/webhooks/telegram",      # called by Telegram
    "POST /api/webhooks/max",           # called by MAX
    "GET /api/health",                  # probes
    "GET /api/health/deep",
    "GET /api/referrals/{}/accept",     # magic links from a partner notification
    "GET /api/referrals/{}/reject",
    "GET /api/documents/{}",            # link inside a generated document response
    "POST /api/geo/agencies/{}/geo",    # onboarding path; the UI uses POST /geo
    "PATCH /api/leads/{}/matches/{}",   # superseded by POST .../feedback
    "GET /api/tasks/{}",                # the list carries every field the UI shows
}
# Public buyer-facing endpoints: TZ 30 lists 13 manager screens and none of them
# are lead magnets, which live on separate landing pages.
NOT_UI_PREFIXES = ("/api/lm/",)


def _norm(path: str) -> str:
    """Collapse both `${id}` (JS template literal) and `{lead_id}` (FastAPI) to `{}`."""
    path = re.sub(r"\$\{[^}]*\}", "{}", path)
    path = re.sub(r"\{[^}]*\}", "{}", path)
    return path.split("?")[0].rstrip("/")


def backend_endpoints() -> set[str]:
    main = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    prefixes = dict(
        re.findall(r'include_router\((\w+)\.router,\s*prefix="([^"]+)"', main)
    )
    out = set()
    for module, prefix in prefixes.items():
        src = (ROOT / "app" / "routers" / f"{module}.py").read_text(encoding="utf-8")
        for verb, path in re.findall(r'@router\.(get|post|patch|put|delete)\("([^"]*)"', src):
            out.add(f"{verb.upper()} {_norm(prefix + path)}")
    return out


def frontend_calls() -> set[str]:
    """Endpoints the API client actually calls, with their HTTP verb."""
    out = set()
    for m in re.finditer(
        r"api\.(?:request|requestText)\(\s*[`'\"]([^`'\"]+)[`'\"](.*?)(?:\n|$)", API_CLIENT
    ):
        path, tail = m.group(1), m.group(2)
        verb_match = re.search(r"'(GET|POST|PATCH|PUT|DELETE)'", tail)
        out.add(f"{verb_match.group(1) if verb_match else 'GET'} /api{_norm(path)}")
    # Multipart upload uses fetch() directly rather than the JSON helper.
    for m in re.finditer(r"[`'\"](/[a-z][^`'\"]*)[`'\"]", API_CLIENT):
        if "import" in m.group(1):
            out.add(f"POST /api{_norm(m.group(1))}")
    return out


def test_every_endpoint_is_reachable_from_the_interface():
    """The documents router was the case in point: shipped with no way in."""
    unreachable = sorted(
        e for e in backend_endpoints() - frontend_calls()
        if e not in NOT_UI_REACHABLE
        and not any(p in e for p in NOT_UI_PREFIXES)
    )
    assert not unreachable, (
        "эндпоинты без входа из интерфейса:\n  " + "\n  ".join(unreachable)
        + "\n\nдобавьте кнопку в Mini App или запишите в NOT_UI_REACHABLE с причиной"
    )


def test_every_ui_call_hits_a_real_endpoint():
    """Guards against a renamed or removed route leaving a dead button."""
    backend = backend_endpoints()
    broken = sorted(c for c in frontend_calls() if c not in backend)
    assert not broken, "фронт зовёт несуществующее:\n  " + "\n  ".join(broken)


def test_every_declared_screen_exists():
    declared = set(re.findall(r"Screens\.(\w+)", APP_JS))
    defined = set()
    for f in SCREENS:
        defined |= set(re.findall(r"^Screens\.(\w+)\s*=", f.read_text(encoding="utf-8"), re.M))
    missing = sorted(declared - defined)
    assert not missing, f"маршрут ведёт на несуществующий экран: {missing}"


def test_every_screen_is_registered_in_the_router():
    """A screen nobody routed to is dead code the manager can never open."""
    routed = set(re.findall(r"Screens\.(\w+)", APP_JS))
    defined = set()
    for f in SCREENS:
        defined |= set(re.findall(r"^Screens\.(\w+)\s*=", f.read_text(encoding="utf-8"), re.M))
    orphans = sorted(defined - routed)
    assert not orphans, f"экран есть, но маршрута нет: {orphans}"


def test_every_route_has_an_entry_point():
    """Tab bar, Router.go(...) or a data-go attribute -- some way to get there."""
    routes = {r for r, _ in re.findall(r"\['([\w/:]+)',\s*(\(?p?\)?\s*=>)", APP_JS)}
    sources = "\n".join(f.read_text(encoding="utf-8") for f in JS)

    tabs = set(re.findall(r"\['(\w+)',\s*'\w+',\s*'", APP_JS))
    programmatic = set(re.findall(r"Router\.go\(['\"`]([\w/${}.:]+)", sources))
    data_go = set(re.findall(r'data-go="([\w/${}.:]+)"', sources))

    def base(x: str) -> str:
        return re.sub(r"\$\{[^}]*\}", ":id", x)

    reachable = tabs | {base(x) for x in programmatic | data_go}
    # The bootstrap sends an empty hash to the dashboard.
    reachable.add("dashboard")

    orphans = sorted(r for r in routes if r not in reachable)
    assert not orphans, f"экран без входа: {orphans}"


@pytest.mark.parametrize("path", [f for f in JS])
def test_screens_bind_navigation_after_rendering(path: Path):
    """data-go only works once bindGo() has attached the handlers."""
    src = path.read_text(encoding="utf-8")
    if "data-go=" not in src:
        pytest.skip("no navigation markup")
    assert "Router.bindGo" in src, f"{path.name} рисует data-go, но не вызывает Router.bindGo()"


def test_screens_do_not_depend_on_each_other():
    """Screens are plain scripts sharing one global scope, so a helper defined in
    one screen silently works in another -- until load order changes or that
    screen is edited. Shared helpers belong in components.js / api_client.js.

    Caught docLinkSheet, which was defined in leads.js and called from
    properties.js.
    """
    # Only top-level declarations become globals.
    top_level: dict[str, str] = {}
    # Anything a file declares at any depth is its own -- a nested helper that
    # happens to share a name is not a cross-file dependency.
    own: dict[str, set[str]] = {}
    for f in SCREENS:
        src = f.read_text(encoding="utf-8")
        own[f.name] = set(re.findall(r"function (\w+)\s*\(", src))
        for name in re.findall(r"^function (\w+)\s*\(", src, re.M):
            top_level[name] = f.name

    leaks = []
    for f in SCREENS:
        src = f.read_text(encoding="utf-8")
        for name, owner in top_level.items():
            if owner == f.name or name in own[f.name]:
                continue
            if re.search(rf"(?<![\w.]){name}\s*\(", src):
                leaks.append(f"{f.name} вызывает {name}() из {owner}")

    assert not leaks, (
        "экраны зависят друг от друга:\n  " + "\n  ".join(sorted(leaks))
        + "\n\nперенесите общий помощник в components.js"
    )


def test_ui_helpers_used_by_screens_exist():
    """A typo in a UI.* call is invisible until that screen is opened."""
    components = (MINI_APP / "js" / "components.js").read_text(encoding="utf-8")
    available = set(re.findall(r"UI\.(\w+)\s*=", components))
    available |= set(re.findall(r"^\s*(\w+),?\s*$", components, re.M))
    # Names exposed through the object literal UI returns.
    available |= set(re.findall(r"(\w+)\s*[,:]", components))

    missing = set()
    for f in SCREENS:
        for name in re.findall(r"UI\.(\w+)\s*\(", f.read_text(encoding="utf-8")):
            if name not in available:
                missing.add(name)
    assert not missing, f"экран зовёт несуществующий UI-помощник: {sorted(missing)}"


def test_every_api_client_method_is_called():
    """A method nobody calls is a feature nobody can use.

    The endpoint-level check passes as soon as the API client mentions a route,
    so a client method wired to nothing still looked reachable. That is how
    acceptPartnerGeo sat unused: POST /api/geo answers a partner-covered city
    with 202 partner_offer, the UI reported "Город добавлен" for a city it had
    not created, and the offer could not be accepted anywhere.
    """
    client = (MINI_APP / "js" / "api_client.js").read_text(encoding="utf-8")
    callers = "\n".join(
        p.read_text(encoding="utf-8") for p in JS if p.name != "api_client.js"
    )

    unused = [
        name for name in re.findall(r"^\s{4}(\w+):\s*\(", client, re.M)
        if not re.search(rf"API\.{name}\b", callers)
    ]
    assert not unused, (
        "методы API-клиента, которые никто не вызывает:\n  " + "\n  ".join(unused)
        + "\n\nдобавьте вызов в экран или удалите метод"
    )
