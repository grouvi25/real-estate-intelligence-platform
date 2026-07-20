// Screen: Signal reply queue (Signal Bus addendum). TZ section 30 + addendum.
window.Screens = window.Screens || {};

Screens.queue = async function () {
  UI.setHeader('Очередь ответов', 'Signal Bus');
  UI.render(UI.spinner());
  const data = await API.signalQueue({ limit: 50 });
  const body = UI.list(data.signals, (s) => `
    <div class="card">
      <div class="row">
        <span class="score">${s.intent_score == null ? '—' : s.intent_score}</span>
        <span class="badge ghost">${UI.esc(s.origin_system || s.reply_channel || '—')}</span>
      </div>
      <div class="muted" style="margin:6px 0">${UI.esc((s.raw_text || '').slice(0, 140))}</div>
      <label>Черновик ответа</label>
      <textarea id="draft-${s.id}" rows="3">${UI.esc(s.reply_draft || '')}</textarea>
      <div class="row">
        <button class="btn secondary" data-save="${s.id}">Сохранить</button>
        <button class="btn" data-send="${s.id}">Отправить</button>
      </div>
      <div class="muted" style="margin-top:6px">Статус: <span id="st-${s.id}">${UI.esc(s.reply_status)}</span></div>
    </div>`, 'Очередь пуста');
  UI.render(body, () => {
    document.querySelectorAll('[data-save]').forEach((b) => {
      b.onclick = async () => {
        const id = b.getAttribute('data-save');
        const draft = document.getElementById('draft-' + id).value;
        try {
          const r = await API.setReplyDraft(id, { reply_draft: draft });
          document.getElementById('st-' + id).textContent = r.reply_status;
          UI.toast('Черновик сохранён');
        } catch (e) { UI.toast('Ошибка: ' + e.message); }
      };
    });
    document.querySelectorAll('[data-send]').forEach((b) => {
      b.onclick = async () => {
        const id = b.getAttribute('data-send');
        const draft = document.getElementById('draft-' + id).value;
        b.disabled = true;
        try {
          await API.setReplyDraft(id, { reply_draft: draft });
          const r = await API.sendReply(id);
          document.getElementById('st-' + id).textContent = r.reply_status;
          UI.toast(r.reply_status === 'sent' ? 'Отправлено' : 'Не отправлено: ' + r.reply_status);
        } catch (e) { UI.toast('Ошибка: ' + e.message); }
        b.disabled = false;
      };
    });
  });
};
