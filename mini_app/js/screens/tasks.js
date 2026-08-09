// Screen: manager task list (TZ 30 `/tasks`).
// Escalation and the sell-to-buy flow create tasks; this is where a manager
// actually works them — claim, open the lead, close or cancel.
window.Screens = window.Screens || {};

const TASK_TYPE_RU = {
  contact: 'Первый контакт',
  call: 'Звонок',
  document: 'Документы',
  meeting: 'Встреча',
  reply: 'Ответ',
  follow_up: 'Напоминание',
  showing: 'Показ',
  call_back: 'Перезвонить',
  referral_confirmation: 'Подтверждение реферала',
  alternative_sell: 'Альтернатива: продажа',
  alternative_buy: 'Альтернатива: покупка',
  escalation: 'Эскалация',
};

function taskDue(t) {
  if (!t.due_at) return '';
  const d = new Date(t.due_at);
  const txt = d.toLocaleString('ru-RU', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  return t.is_overdue
    ? `<span class="chip chip--hot">${UI.icon('clock')} просрочено · ${UI.esc(txt)}</span>`
    : `<span class="chip">${UI.icon('clock')} ${UI.esc(txt)}</span>`;
}

Screens.tasks = async function () {
  let filter = { status: 'pending' };

  async function draw() {
    UI.render(UI.skelList(3));
    let data, sum;
    try {
      [data, sum] = await Promise.all([API.tasks(filter), API.tasksSummary()]);
    } catch (e) {
      UI.render(UI.errorState(e.message), () => {
        document.getElementById('retry').onclick = draw;
      });
      return;
    }

    const tabs = `
      <div class="chips">
        <button class="chip chip--btn ${filter.status === 'pending' && !filter.only_urgent && !filter.only_mine ? 'chip--accent' : ''}" data-f="open">Открытые <span class="num">${sum.pending}</span></button>
        <button class="chip chip--btn ${filter.only_urgent ? 'chip--accent' : ''}" data-f="urgent">${UI.icon('flame')} Срочные <span class="num">${sum.urgent}</span></button>
        <button class="chip chip--btn ${filter.only_mine ? 'chip--accent' : ''}" data-f="mine">Мои</button>
        <button class="chip chip--btn ${filter.status === 'done' ? 'chip--accent' : ''}" data-f="done">Закрытые</button>
      </div>`;

    const body = UI.list(data.tasks, (t) => `
      <div class="card">
        <div class="row row--wrap gap-2">
          ${t.is_urgent ? `<span class="chip chip--hot">${UI.icon('flame')} срочно</span>` : ''}
          <span class="chip">${UI.esc(TASK_TYPE_RU[t.task_type] || t.task_type)}</span>
          ${taskDue(t)}
        </div>
        <div class="item__title mt-3">${UI.esc(t.title)}</div>
        ${t.description ? `<div class="item__sub mt-1">${UI.esc(t.description)}</div>` : ''}
        ${t.lead_name ? `<div class="meta-row mt-1">${UI.icon('leads')}${UI.esc(t.lead_name)}</div>` : ''}
        ${t.suggested_message ? `<div class="item__sub mt-2" style="font-style:italic">«${UI.esc(t.suggested_message)}»</div>` : ''}
        ${t.status === 'pending'
          ? `<button class="btn btn--block mt-3" data-done="${t.id}">${UI.icon('check')} Выполнено</button>
             <div class="btn-row btn-row--equal mt-2">
               ${t.lead_id ? `<button class="btn btn--secondary btn--sm" data-go="leads/${t.lead_id}">${UI.icon('leads')} Лид</button>` : ''}
               ${t.manager_id ? '' : `<button class="btn btn--secondary btn--sm" data-claim="${t.id}">${UI.icon('user')} Взять</button>`}
               <button class="btn btn--secondary btn--sm" data-cancel="${t.id}">${UI.icon('close')} Отменить</button>
             </div>`
          : `<div class="btn-row btn-row--equal mt-3">
               ${t.lead_id ? `<button class="btn btn--secondary btn--sm" data-go="leads/${t.lead_id}">${UI.icon('leads')} Лид</button>` : ''}
               <button class="btn btn--secondary btn--sm" data-reopen="${t.id}">${UI.icon('refresh')} Вернуть</button>
             </div>`}
      </div>`, { icon: 'check', title: 'Задач нет',
         sub: filter.status === 'done' ? 'Закрытых задач пока не было'
           : 'Здесь появятся напоминания и эскалации по лидам' });

    UI.render(tabs + body, () => {
      Router.bindGo();

      document.querySelectorAll('[data-f]').forEach((b) => {
        b.onclick = () => {
          const f = b.getAttribute('data-f');
          if (f === 'open') filter = { status: 'pending' };
          if (f === 'urgent') filter = { status: 'pending', only_urgent: true };
          if (f === 'mine') filter = { status: 'pending', only_mine: true };
          if (f === 'done') filter = { status: 'done' };
          draw();
        };
      });

      const act = (attr, body, msg) => document.querySelectorAll(`[${attr}]`).forEach((b) => {
        b.onclick = async () => {
          b.disabled = true;
          try { await API.updateTask(b.getAttribute(attr), body); UI.toast(msg); await draw(); }
          catch (e) { b.disabled = false; UI.toast('Не удалось: ' + e.message); }
        };
      });
      act('data-done', { status: 'done' }, 'Задача закрыта');
      act('data-cancel', { status: 'cancelled' }, 'Задача отменена');
      act('data-reopen', { status: 'pending' }, 'Задача возвращена в работу');
      act('data-claim', { assign_to_me: true }, 'Задача взята в работу');
    });
  }

  UI.setHeader('Задачи', 'Что сделать по лидам', { back: true });
  await draw();
};
