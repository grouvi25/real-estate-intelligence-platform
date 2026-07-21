// Screen: Signal reply queue (Signal Bus).
window.Screens = window.Screens || {};

Screens.queue = async function () {
  UI.setHeader('Очередь ответов', 'Signal Bus');
  UI.render(UI.skelList(3));
  const data = await API.signalQueue({ limit: 50 });
  UI.render(UI.list(data.signals, (s) => `
    <div class="card">
      <div class="row" style="gap:10px">${UI.scoreEl(s.intent_score)}
        <span class="chip">${UI.icon('signals')}${UI.esc(s.origin_system || s.reply_channel || '—')}</span>
        <span class="grow"></span>${UI.statusChip(s.reply_status)}</div>
      <div class="item__sub" style="margin:8px 0">${UI.esc((s.raw_text || '').slice(0, 160))}</div>
      <div class="field" style="margin:6px 0"><label>Черновик ответа</label>
        <textarea id="d-${s.id}" rows="3">${UI.esc(s.reply_draft || '')}</textarea></div>
      <div class="btn-row">
        <button class="btn btn--ghost btn--sm" data-ai="${s.id}">${UI.icon('sparkles')} AI-черновик</button>
        <button class="btn btn--secondary btn--sm" data-save="${s.id}">Сохранить</button>
        <button class="btn btn--sm" data-send="${s.id}">${UI.icon('send')} Отправить</button>
      </div>
    </div>`, { icon: 'queue', title: 'Очередь пуста', sub: 'Нет сигналов, ожидающих ответа' }),
    wire);

  function wire() {
    document.querySelectorAll('[data-ai]').forEach((b) => b.onclick = async () => {
      const id = b.getAttribute('data-ai'); b.disabled = true;
      try {
        const r = await API.generateReply(id);
        const txt = (r.reply && (r.reply.reply_text || r.reply.text)) || '';
        if (txt) document.getElementById('d-' + id).value = txt;
        UI.toast(txt ? 'Черновик сгенерирован' : 'AI не вернул текст');
      } catch (e) { UI.toast('AI недоступен: ' + e.message); }
      b.disabled = false;
    });
    document.querySelectorAll('[data-save]').forEach((b) => b.onclick = async () => {
      const id = b.getAttribute('data-save');
      try {
        await API.setReplyDraft(id, { reply_draft: document.getElementById('d-' + id).value });
        UI.toast('Сохранено');
      } catch (e) { UI.toast('Ошибка: ' + e.message); }
    });
    document.querySelectorAll('[data-send]').forEach((b) => b.onclick = async () => {
      const id = b.getAttribute('data-send'); b.disabled = true;
      try {
        await API.setReplyDraft(id, { reply_draft: document.getElementById('d-' + id).value });
        const r = await API.sendReply(id);
        UI.toast(r.reply_status === 'sent' ? 'Отправлено' : 'Статус: ' + r.reply_status);
        setTimeout(() => Router.resolve(), 500);
      } catch (e) { UI.toast('Ошибка: ' + e.message); b.disabled = false; }
    });
  }
};
