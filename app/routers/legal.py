"""Public legal pages: the privacy policy the bots link to (152-FZ).

The bot asks for consent with a link to /privacy, so the page has to exist and
name the operator. The operator's details come from config (PRIVACY_*).
"""
import html

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.config import config

router = APIRouter()

EDITION = "12 октября 2026 г."

_PAGE = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Политика обработки персональных данных — REIP</title>
<style>
  :root {{ color-scheme: light; }}
  body {{ margin: 0; background: #f7f7f5; color: #1b1b1b;
         font: 16px/1.6 -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }}
  main {{ max-width: 760px; margin: 0 auto; padding: 32px 16px 64px; }}
  h1 {{ font-size: 26px; line-height: 1.25; margin: 0 0 4px; }}
  h2 {{ font-size: 19px; margin: 32px 0 8px; }}
  p, li {{ margin: 0 0 8px; }}
  ul {{ padding-left: 22px; }}
  .muted {{ color: #666; font-size: 14px; }}
  .card {{ background: #fff; border: 1px solid #e3e3df; border-radius: 10px; padding: 16px; }}
  a {{ color: #1a5fb4; }}
</style>
</head>
<body>
<main>
<h1>Политика обработки персональных данных</h1>
<p class="muted">Сервис REIP · редакция от {edition}</p>

<div class="card">
  <p><b>Оператор:</b> {operator}</p>
  <p>ИНН {inn} · ОГРНИП {ogrn}</p>
  <p><b>Обращения по персональным данным:</b> {contact}</p>
</div>

<h2>1. О чём эта политика</h2>
<p>REIP — сервис для агентств недвижимости: он находит запросы на покупку и аренду жилья,
помогает агентству ответить на них и вести заявки. Политика объясняет, какие персональные
данные обрабатывает сервис, зачем, кому они передаются и как их удалить. Она действует для
ботов агентств в Telegram, VK и MAX, для приложения REIP (Mini App) и для бота подключения
к сервису.</p>

<h2>2. Чьи данные и какие</h2>
<ul>
  <li><b>Люди, которые ищут жильё</b> и пишут боту агентства или оставляют запрос в открытых
  чатах и каналах: имя и ник в мессенджере, идентификатор аккаунта, текст сообщений и
  параметры поиска (город, район, бюджет, тип жилья), телефон — только если человек сам его
  сообщил.</li>
  <li><b>Сотрудники агентств</b>, работающие в приложении: имя, идентификатор Telegram,
  должность и роль в агентстве, действия с заявками.</li>
  <li><b>Представители агентств</b>, оставившие заявку на подключение: имя, название
  агентства, телефон, идентификатор Telegram.</li>
</ul>
<p>Паспортные данные, документы и платёжные реквизиты физических лиц сервис не запрашивает.</p>

<h2>3. Зачем</h2>
<ul>
  <li>подобрать варианты жилья и передать запрос специалисту агентства;</li>
  <li>дать агентству вести заявки, задачи и сделки;</li>
  <li>рассмотреть заявку агентства на подключение и связаться с ним;</li>
  <li>обеспечить работу и безопасность сервиса.</li>
</ul>

<h2>4. Основания</h2>
<p>Бот агентства сохраняет заявку только после того, как человек нажмёт «Согласен» под
запросом согласия. Данные сотрудников и представителей агентств обрабатываются для
исполнения договора с агентством. Запросы из открытых чатов и каналов используются только
для того, чтобы агентство могло на них ответить, и удаляются по первому требованию.</p>

<h2>5. Кому передаются</h2>
<ul>
  <li><b>Агентству недвижимости</b>, к которому относится запрос, — его сотрудникам в
  приложении и, если агентство это настроило, в его CRM-систему.</li>
  <li><b>Сервисам искусственного интеллекта</b>, которые помогают разобрать запрос и составить
  ответ. Перед отправкой в зарубежные сервисы имена, телефоны и другие персональные данные
  удаляются из текста.</li>
</ul>
<p>Данные не продаются и не передаются для рекламы.</p>

<h2>6. Где и сколько хранятся</h2>
<p>Данные хранятся на серверах в России. Они хранятся, пока нужны для целей из раздела 3:
запрос — пока агентство работает с ним, данные сотрудников и агентств — пока действует
договор с агентством. После этого, а также после отзыва согласия данные удаляются или
обезличиваются, если закон не требует хранить их дольше.</p>

<h2>7. Как отозвать согласие и удалить данные</h2>
<ul>
  <li>Напишите боту агентства «стоп» — бот перестанет вам писать.</li>
  <li>Чтобы узнать, какие данные о вас есть, исправить или удалить их, отзовите согласие
  обращением по контакту выше. Ответим в течение 10 рабочих дней.</li>
</ul>

<h2>8. Как данные защищены</h2>
<p>Доступ к данным есть только у сотрудников своего агентства в пределах их роли. Соединения
шифруются, доступ к серверам ограничен, резервные копии хранятся там же, в России.</p>

<h2>9. Изменения</h2>
<p>Политика может обновляться. Действующая редакция всегда на этой странице.</p>
</main>
</body>
</html>
"""


def _contact() -> str:
    email = (config.privacy_contact_email or "").strip()
    if email:
        safe = html.escape(email)
        return f'<a href="mailto:{safe}">{safe}</a>'
    bot = (config.platform_onboarding_bot_username or "").strip().lstrip("@")
    if bot:
        safe = html.escape(bot)
        return f'Telegram <a href="https://t.me/{safe}">@{safe}</a>'
    return "через агентство, с которым вы общались"


def render_privacy() -> str:
    return _PAGE.format(
        edition=EDITION,
        operator=html.escape(config.privacy_operator_name),
        inn=html.escape(config.privacy_operator_inn),
        ogrn=html.escape(config.privacy_operator_ogrn),
        contact=_contact(),
    )


@router.get("/privacy", response_class=HTMLResponse, include_in_schema=False)
async def privacy() -> HTMLResponse:
    return HTMLResponse(render_privacy())
