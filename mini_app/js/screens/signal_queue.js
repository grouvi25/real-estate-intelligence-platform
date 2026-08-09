// Screen: Signal reply queue (Signal Bus).
window.Screens = window.Screens || {};

Screens.queue = async function () {
  UI.setHeader('Очередь ответов', 'Кому написать первым', { back: true });

  const skeleton = Array.from({ length: 2 }, () =>
    `<div class="card"><div class="row gap-2"><div class="skel skel-chip" style="width:58px"></div>
       <div class="skel skel-chip"></div></div>
     <div class="mt-3"><div class="skel skel-line lg"></div><div class="skel skel-line md"></div></div>
     <div class="mt-3"><div class="skel" style="height:76px;border-radius:12px"></div></div>
     <div class="mt-3"><div class="skel skel-btn"></div></div></div>`).join('');

  UI.load(skeleton, () => API.signalQueue({ limit: 50 }), (data) => {
    UI.render(UI.list(data.signals, (s) => `
      <div class="card">
        <div class="between gap-2">
          <div class="row gap-2">${UI.scoreEl(s.intent_score)}
            <span class="chip">${UI.esc(UI.channel(s.origin_system || s.reply_channel))}</span></div>
          ${UI.statusChip(s.reply_status)}
        </div>
        <div class="item__sub clamp-3 mt-3" style="color:var(--fg)">${UI.esc(s.raw_text || '')}</div>
        <div class="between mt-2">
          <span class="item__meta">${s.created_at ? UI.esc(UI.ago(s.created_at)) : ''}</span>
          ${s.signal_url ? `<a class="btn btn--ghost btn--sm" href="${UI.esc(s.signal_url)}"
             target="_blank" rel="noopener">${UI.icon('link')} Исходник</a>` : ''}
        </div>
        ${s.score_reason ? `<div class="item__sub mt-2">${UI.icon('sparkles')} ${UI.esc(s.score_reason)}</div>` : ''}
        <div class="field"><label for="d-${s.id}">Черновик ответа</label>
          <textarea id="d-${s.id}" rows="3" placeholder="Напишите или сгенерируйте черновик">${UI.esc(s.reply_draft || '')}</textarea></div>
        <button class="btn btn--block" data-send="${s.id}">${UI.icon('send')} Отправить</button>
        <div class="btn-row btn-row--equal mt-2">
          <button class="btn btn--secondary btn--sm" data-ai="${s.id}">${UI.icon('sparkles')} Черновик от AI</button>
          <button class="btn btn--secondary btn--sm" data-save="${s.id}">${UI.icon('check')} Сохранить</button>
        </div>
        <div class="btn-row btn-row--equal mt-2">
          <button class="btn btn--secondary btn--sm" data-lead="${s.id}">${UI.icon('leads')} В лид</button>
          <button class="btn btn--secondary btn--sm" data-esc="${s.id}">${UI.icon('flame')} Старшему</button>
          <button class="btn btn--danger btn--sm" data-dis="${s.id}">${UI.icon('close')} Не наш</button>
        </div>
      </div>`, { icon: 'queue', title: 'Очередь пуста',
                 sub: 'Здесь появятся сигналы, на которые стоит ответить' }),
      wire);
  });

  function wire() {
    document.querySelectorAll('[data-ai]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
      const id = b.getAttribute('data-ai');
      try {
        const r = await API.generateReply(id);
        const txt = (r.reply && (r.reply.reply_text || r.reply.text)) || '';
        if (txt) document.getElementById('d-' + id).value = txt;
        UI.toast(txt ? 'Черновик готов' : 'AI не вернул текст');
      } catch (e) { UI.toast('AI недоступен: ' + e.message); }
    }));
    document.querySelectorAll('[data-save]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
      const id = b.getAttribute('data-save');
      try {
        await API.setReplyDraft(id, { reply_draft: document.getElementById('d-' + id).value });
        UI.toast('Сохранено');
      } catch (e) { UI.toast('Не удалось: ' + e.message); }
    }));
    // Triage straight from the queue: §5.1 puts all four actions on the card,
    // and until now only «Ответить» was there.
    document.querySelectorAll('[data-lead]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
      try {
        const r = await API.createLead(b.getAttribute('data-lead'),
          { consent_text: 'Согласие получено в чате (152-ФЗ)' });
        UI.toast(r && r.already_exists ? 'Лид уже был создан' : 'Лид создан');
        Router.go('leads');
      } catch (e) { UI.toast('Не удалось: ' + e.message); }
    }));
    document.querySelectorAll('[data-esc]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
      try {
        await API.escalateSignal(b.getAttribute('data-esc'), 'Передан из очереди');
        UI.toast('Передано старшему менеджеру');
        Router.resolve();
      } catch (e) { UI.toast('Не удалось: ' + e.message); }
    }));
    document.querySelectorAll('[data-dis]').forEach((b) => b.onclick = () => {
      if (!confirm('Убрать сигнал из очереди как нерелевантный?')) return;
      UI.busy(b, async () => {
        try {
          await API.dismissSignal(b.getAttribute('data-dis'), 'Нерелевантный');
          UI.toast('Убрано из очереди');
          Router.resolve();
        } catch (e) { UI.toast('Не удалось: ' + e.message); }
      });
    });
    document.querySelectorAll('[data-send]').forEach((b) => b.onclick = () => UI.busy(b, async () => {
      const id = b.getAttribute('data-send');
      const text = document.getElementById('d-' + id).value.trim();
      if (!text) { UI.toast('Сначала напишите ответ'); return; }
      try {
        await API.setReplyDraft(id, { reply_draft: text });
        const r = await API.sendReply(id);
        UI.toast(r.reply_status === 'sent' ? 'Отправлено' : 'Статус: ' + r.reply_status);
        setTimeout(() => Router.resolve(), 400);
      } catch (e) { UI.toast('Не удалось: ' + e.message); }
    }));
  }
};
