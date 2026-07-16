/** 消息提醒 */
function initNotificationCenter() {
  const bell = document.getElementById('notifyBell');
  const panel = document.getElementById('notifyPanel');
  const list = document.getElementById('notifyList');
  const badge = document.getElementById('notifyBadge');
  if (!bell || !panel) return;

  function render(items) {
    if (!list) return;
    if (!items.length) {
      list.innerHTML = '<div class="notify-empty">暂无提醒</div>';
      return;
    }
    list.innerHTML = items.map((n) => {
      const unread = n.is_read ? '' : ' unread';
      const isCall = n.type === 'call';
      const isCollab = n.type === 'collab';
      const callClass = isCall ? ' notify-item-call' : (isCollab ? ' notify-item-collab' : '');
      const icon = isCall ? '<i class="bi bi-camera-video-fill text-danger me-1"></i>'
        : (isCollab ? '<i class="bi bi-people-fill text-primary me-1"></i>' : '');
      const link = n.link ? `onclick="location.href='${n.link}'"` : '';
      return `<div class="notify-item${unread}${callClass}" ${link}>
        <strong>${icon}${escapeHtml(n.title)}</strong>
        ${n.body ? `<p>${escapeHtml(n.body)}</p>` : ''}
        <small>${escapeHtml(n.created_at || '')}</small>
      </div>`;
    }).join('');
  }

  function refresh() {
    fetch('/api/notifications/unread-count')
      .then((r) => r.json())
      .then((d) => {
        if (d.success && d.count > 0) {
          badge.style.display = 'inline';
          badge.textContent = d.count > 99 ? '99+' : d.count;
        } else {
          badge.style.display = 'none';
        }
      })
      .catch(() => {});

    if (panel.classList.contains('show')) {
      fetch('/api/notifications')
        .then((r) => r.json())
        .then((d) => { if (d.success) render(d.notifications || []); });
    }
  }

  bell.addEventListener('click', (e) => {
    e.stopPropagation();
    panel.classList.toggle('show');
    if (panel.classList.contains('show')) {
      fetch('/api/notifications')
        .then((r) => r.json())
        .then((d) => {
          if (d.success) render(d.notifications || []);
          fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
          badge.style.display = 'none';
        });
    }
  });

  document.getElementById('notifyMarkRead')?.addEventListener('click', () => {
    fetch('/api/notifications/read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    badge.style.display = 'none';
    list.querySelectorAll('.notify-item.unread').forEach((el) => el.classList.remove('unread'));
  });

  document.addEventListener('click', () => panel.classList.remove('show'));
  panel.addEventListener('click', (e) => e.stopPropagation());

  function pollWhenVisible(fn, intervalMs) {
    fn();
    setInterval(() => { if (!document.hidden) fn(); }, intervalMs);
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) fn();
    });
  }

  pollWhenVisible(refresh, 15000);
  pollWhenVisible(checkCallNotifications, 10000);
  pollWhenVisible(checkMessageNotifications, 15000);
}

let _lastMsgToastAt = 0;

function checkMessageNotifications() {
  fetch('/api/notifications?unread=1', { credentials: 'same-origin' })
    .then((r) => r.json())
    .then((d) => {
      if (!d.success) return;
      const msgN = (d.notifications || []).find((n) => n.type === 'message' && !n.is_read);
      if (!msgN) return;
      const now = Date.now();
      if (now - _lastMsgToastAt < 6000) return;
      _lastMsgToastAt = now;
      showToast(msgN.title + ' — 点击查看', 'info');
      const bell = document.getElementById('notifyBell');
      if (bell) bell.classList.add('notify-bell-ringing');
      setTimeout(() => bell?.classList.remove('notify-bell-ringing'), 4000);
    })
    .catch(() => {});
}

let _lastCallToastAt = 0;

function checkCallNotifications() {
  fetch('/api/notifications?unread=1')
    .then((r) => r.json())
    .then((d) => {
      if (!d.success) return;
      const callN = (d.notifications || []).find((n) => n.type === 'call' && !n.is_read);
      if (!callN) return;
      const now = Date.now();
      if (now - _lastCallToastAt < 8000) return;
      _lastCallToastAt = now;
      showToast(callN.title + ' — 页面顶部可接听', 'warning');
      const bell = document.getElementById('notifyBell');
      if (bell) bell.classList.add('notify-bell-ringing');
      setTimeout(() => bell?.classList.remove('notify-bell-ringing'), 6000);
    })
    .catch(() => {});
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

/** 用户反馈悬浮窗 */
function initFeedbackWidget() {
  const btn = document.getElementById('feedbackFloatingBtn');
  const win = document.getElementById('feedbackWindow');
  if (!btn || !win) return;

  btn.addEventListener('click', () => {
    win.style.display = win.style.display === 'none' ? 'flex' : 'none';
  });

  document.getElementById('feedbackClose')?.addEventListener('click', () => {
    win.style.display = 'none';
  });

  document.getElementById('feedbackSubmit')?.addEventListener('click', () => {
    const msg = document.getElementById('feedbackMessage')?.value?.trim();
    if (!msg) {
      showToast('请填写反馈内容', 'warning');
      return;
    }
    const rating = document.querySelector('input[name="feedbackRating"]:checked')?.value || 0;
    fetch('/api/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: msg, rating: parseInt(rating, 10), page: location.pathname }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.success) {
          showToast('感谢反馈，我们已收到', 'success');
          document.getElementById('feedbackMessage').value = '';
          win.style.display = 'none';
        } else {
          showToast(d.error || '提交失败', 'error');
        }
      });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initNotificationCenter();
  initFeedbackWidget();
});
