"""The design rules the Mini App is held to, checked against the stylesheet.

These are the things that are easy to break by accident in a hurry and hard to
notice in a screenshot: a hover that moves a card under the thumb, a button with
no pressed state, a tap target too small for a finger, a colour written by hand
instead of taken from a token.
"""
import re
from pathlib import Path

import pytest

CSS = Path(__file__).resolve().parent.parent / "mini_app" / "css" / "styles.css"
SCREENS = Path(__file__).resolve().parent.parent / "mini_app" / "js" / "screens"

# Only the funnel bar animates a size, and it animates on data, not on input.
GEOMETRY = ("transform", "scale", "height", "margin", "padding", "top", "left", "font-size")
ALLOWED_GEOMETRY_TRANSITIONS = {".funnel__bar"}


def _rules(css: str) -> list[tuple[str, str]]:
    return [(m.group(1).strip(), m.group(2)) for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css)]


@pytest.fixture(scope="module")
def css() -> str:
    return CSS.read_text(encoding="utf-8")


def test_nothing_moves_on_hover_or_press(css):
    """A list that shifts under the finger is worse than one that does nothing:
    the tap lands on the neighbour."""
    offenders = []
    for selector, body in _rules(css):
        for line in re.findall(r"transition:[^;]+;", body):
            if any(prop in line for prop in GEOMETRY):
                if not any(ok in selector for ok in ALLOWED_GEOMETRY_TRANSITIONS):
                    offenders.append(f"{selector}: {line.strip()}")
    assert offenders == [], f"анимируется геометрия: {offenders}"


def test_every_pressable_thing_has_a_pressed_state(css):
    """Without :active a tap gives no feedback at all on a phone, where there is
    no hover to fall back on."""
    for base in (".btn", ".card--tap", ".chip--btn", ".tile", ".nav__item",
                 ".header__btn", ".segmented__opt"):
        assert f"{base}:active" in css, f"нет состояния нажатия у {base}"


def test_hover_is_only_for_devices_that_have_one(css):
    """A :hover rule on a touch screen sticks after the tap."""
    for m in re.finditer(r"([^{}]*:hover[^{}]*)\{", css):
        before = css[:m.start()]
        assert before.rfind("@media (hover: hover)") > before.rfind("}\n\n"), \
            f"hover вне @media (hover: hover): {m.group(1).strip()}"


def test_focus_is_visible_for_the_keyboard(css):
    assert ":focus-visible" in css
    assert "outline" in css.split(":focus-visible")[1][:200]


def test_targets_are_at_least_44px(css):
    assert "--tap-min: 44px" in css
    assert "min-height: var(--tap-min)" in css


def test_motion_can_be_switched_off(css):
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_dark_theme_has_its_own_fallback(css):
    """Opened outside Telegram there are no theme variables to follow."""
    assert "@media (prefers-color-scheme: dark)" in css


def test_screens_do_not_hard_code_colours():
    """Colours come from tokens; a hex in a screen is a colour that will not
    follow the Telegram theme."""
    offenders = []
    for path in SCREENS.glob("*.js"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"#[0-9a-fA-F]{3,8}\b", line) and "var(--" not in line:
                offenders.append(f"{path.name}:{n}")
    assert offenders == [], f"цвет мимо токенов: {offenders}"


ROUTER = Path(__file__).resolve().parent.parent / "mini_app" / "js" / "router.js"


def test_a_telegram_launch_opens_the_dashboard_not_an_error():
    """Telegram appends its own payload to the URL (#tgWebAppData=...).

    The router used to split that on "/" and match it against the route table,
    which matched nothing — so the first screen a person ever saw was «Экран не
    найден». Only "#/…" is ours; everything else opens the home screen.
    """
    src = ROUTER.read_text(encoding="utf-8")
    assert 'startsWith(\'#/\')' in src or 'startsWith("#/")' in src, \
        "роутер снова разбирает любой хеш как маршрут"
    assert "segs.push(HOME)" in src, "пустой маршрут снова не ведёт на главную"


def test_depth_is_a_border_not_a_shadow(css):
    """Cards on soft shadows made every screen look like a feed of notifications.

    The only box-shadow allowed is the focus ring, which is a state.
    """
    offenders = [
        f"{selector}: {line.strip()}"
        for selector, body in _rules(css)
        for line in re.findall(r"box-shadow:[^;]+;", body)
        if "var(--ring)" not in line
    ]
    assert offenders == [], f"вернулись тени: {offenders}"


def _body(css: str, selector: str) -> str | None:
    """Body of one rule. The selector captured by _rules carries the comment
    that precedes it, so compare on the last line rather than the whole match."""
    for sel, body in _rules(css):
        if sel.strip().splitlines()[-1].strip() == selector:
            return body
    return None


def test_switcher_rows_do_not_sit_on_the_content(css):
    """A row of tabs or filters flush against the first card reads as one control."""
    for selector in (".segmented", ".chips"):
        body = _body(css, selector)
        assert body is not None, f"{selector} пропал из стилей"
        assert "margin-bottom" in body, f"{selector} снова прилипает к содержимому"


def test_the_way_out_of_a_screen_is_an_icon_not_a_button(css):
    """The gear and the sheet's close cross share .header__btn. A ring around
    them made two ways out look like the screen's own actions."""
    body = _body(css, ".header__btn")
    assert body is not None
    assert "border: 0" in body, "у кнопки в шапке снова обводка"
    assert "background: none" in body, "у кнопки в шапке снова заливка"
