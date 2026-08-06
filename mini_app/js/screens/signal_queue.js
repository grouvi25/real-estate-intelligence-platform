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
      <div class="card${s.urgency === 'hot' ? ' card--hot' : ''}">
        <div class="between gap-2">
          <div class="row gap-2">${UI.scoreEl(s.intent_score)}
            <span class="chip">${UI.esc(UI.channel(s.origin_system || s.reply_channel))}</span></div>
          ${UI.statusChip(s.reply_status)}
        </div>
        <div class="item__sub clamp-3 mt-3" style="color:var(--fg)">${UI.esc(s.raw_text || '')}</div>
        <div class="field"><label for="d-${s.id}">Черновик ответа</label>
          <textarea id="d-${s.id}" rows="3" placeholder="Напишите или сгенерируйте черновик">${UI.esc(s.reply_draft || '')}</textarea></div>
        <button class="btn btn--block" data-send="${s.id}">${UI.icon('send')} Отправить</button>
        <div class="btn-row btn-row--equal mt-2">
          <button class="btn btn--secondary btn--sm" data-ai="${s.id}">${UI.icon('sparkles')} Черновик от AI</button>
          <button class="btn btn--secondary btn--sm" data-save="${s.id}">${UI.icon('check')} Сохранить</button>
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
