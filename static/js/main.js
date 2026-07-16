/**
 * 财务审计工作台 — 前端公共逻辑
 */

const CHART_FONT = "'IBM Plex Sans', 'PingFang SC', sans-serif";

if (typeof Chart !== 'undefined') {
  Chart.defaults.font.family = CHART_FONT;
  Chart.defaults.color = '#5c6470';
  Chart.defaults.plugins.tooltip.backgroundColor = 'rgba(30, 36, 48, 0.92)';
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 4;
  Chart.defaults.borderColor = '#d9d4c8';
  Chart.defaults.scale.grid = { color: 'rgba(217, 212, 200, 0.6)' };
}

const CHART_COLORS = {
  bronze: 'rgba(166, 95, 26, 0.75)',
  bronzeBorder: '#a65f1a',
  ok: 'rgba(45, 106, 79, 0.75)',
  okBorder: '#2d6a4f',
  danger: '#9b2335',
  warn: '#9a6700',
  ink: '#3d5a73',
  slate: '#5c6470',
};

const CHART_PALETTE = [
  '#a65f1a', '#2d6a4f', '#3d5a73', '#9a6700', '#9b2335',
  '#6b7c93', '#4a6741', '#8b6914', '#5a4a42', '#2f4f6f',
];

function formatCurrency(value, decimals = 0) {
  if (value === null || value === undefined) return '--';
  if (Math.abs(value) >= 1e8) return '¥' + (value / 1e8).toFixed(2) + '亿';
  if (Math.abs(value) >= 1e4) return '¥' + (value / 1e4).toFixed(1) + '万';
  return '¥' + value.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function formatNumber(value) {
  if (value === null || value === undefined) return '--';
  return value.toLocaleString();
}

function formatPercent(value, decimals = 1) {
  if (value === null || value === undefined) return '--';
  return value.toFixed(decimals) + '%';
}

function createBarChart(canvasId, labels, datasets, options = {}) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || typeof Chart === 'undefined') return null;
  const existing = Chart.getChart(ctx);
  if (existing) existing.destroy();
  return new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'top' } }, ...options },
  });
}

function createDoughnutChart(canvasId, labels, data, colors) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || typeof Chart === 'undefined') return null;
  return new Chart(ctx, {
    type: 'doughnut',
    data: { labels, datasets: [{ data, backgroundColor: colors || CHART_PALETTE }] },
    options: { responsive: true, maintainAspectRatio: false },
  });
}

function createLineChart(canvasId, labels, datasets) {
  const ctx = document.getElementById(canvasId);
  if (!ctx || typeof Chart === 'undefined') return null;
  return new Chart(ctx, {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { position: 'top' } },
      scales: { y: { beginAtZero: false } },
    },
  });
}

function showToast(message, type = 'info') {
  const toast = document.createElement('div');
  toast.className = 'app-toast ' + type;
  toast.textContent = message;
  document.body.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transition = 'opacity 0.25s';
    setTimeout(() => toast.remove(), 250);
  }, 3200);
}

function exportTableToCSV(tableId, filename) {
  const table = document.getElementById(tableId);
  if (!table) return;
  const csv = [];
  table.querySelectorAll('tr').forEach(row => {
    const cols = row.querySelectorAll('td, th');
    csv.push(Array.from(cols).map(c => `"${c.textContent.replace(/"/g, '""')}"`).join(','));
  });
  const blob = new Blob(['\ufeff' + csv.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename || 'export.csv';
  a.click();
  URL.revokeObjectURL(url);
}

function startVoiceInput(options) {
  const { onResult, onError, onStart, onEnd, recordSeconds = 5 } = options;
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  if (SpeechRecognition) {
    const recognition = new SpeechRecognition();
    recognition.lang = 'zh-CN';
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onstart = () => { if (onStart) onStart(); };
    recognition.onresult = (event) => {
      const text = event.results[0][0].transcript.trim();
      if (text && onResult) onResult(text);
    };
    recognition.onerror = (event) => {
      if (event.error === 'not-allowed') { startServerVoiceInput(options); return; }
      if (onError) onError('语音识别失败: ' + (event.error || '未知错误'));
      if (onEnd) onEnd();
    };
    recognition.onend = () => { if (onEnd) onEnd(); };
    try { recognition.start(); } catch (err) { startServerVoiceInput(options); }
    return;
  }
  startServerVoiceInput(options);
}

function startServerVoiceInput(options) {
  const { onResult, onError, onStart, onEnd, recordSeconds = 5 } = options;
  if (!navigator.mediaDevices?.getUserMedia) {
    if (onError) onError('当前浏览器不支持麦克风录音');
    if (onEnd) onEnd();
    return;
  }
  navigator.mediaDevices.getUserMedia({ audio: true })
    .then((stream) => {
      if (onStart) onStart();
      const mediaRecorder = new MediaRecorder(stream);
      const chunks = [];
      mediaRecorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
      mediaRecorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks, { type: mediaRecorder.mimeType || 'audio/webm' });
        const formData = new FormData();
        formData.append('audio', blob, 'voice.webm');
        fetch('/api/voice/recognize', { method: 'POST', body: formData })
          .then((r) => r.json())
          .then((data) => {
            if (data.success && data.text) onResult(data.text);
            else if (onError) onError(data.error || '语音识别失败');
          })
          .catch((err) => { if (onError) onError('语音识别请求失败: ' + err.message); })
          .finally(() => { if (onEnd) onEnd(); });
      };
      mediaRecorder.onerror = () => {
        stream.getTracks().forEach((t) => t.stop());
        if (onError) onError('录音失败');
        if (onEnd) onEnd();
      };
      mediaRecorder.start();
      setTimeout(() => { if (mediaRecorder.state === 'recording') mediaRecorder.stop(); }, recordSeconds * 1000);
    })
    .catch(() => {
      if (onError) onError('无法访问麦克风，请检查权限');
      if (onEnd) onEnd();
    });
}

function bindVoiceButton(button, handlers) {
  if (!button) return;
  const defaultHtml = button.innerHTML;
  button.addEventListener('click', () => {
    startVoiceInput({
      recordSeconds: handlers.recordSeconds || 5,
      onStart: () => {
        button.classList.add('btn-danger');
        button.classList.remove('btn-outline-primary', 'btn-outline-secondary');
        if (handlers.onStart) handlers.onStart(button);
        else button.innerHTML = '<i class="bi bi-mic-fill"></i>';
      },
      onEnd: () => {
        button.classList.remove('btn-danger');
        button.classList.add('btn-outline-primary');
        button.innerHTML = defaultHtml;
        if (handlers.onEnd) handlers.onEnd(button);
      },
      onResult: (text) => { if (handlers.onResult) handlers.onResult(text, button); },
      onError: (msg) => {
        showToast(msg, 'error');
        if (handlers.onError) handlers.onError(msg, button);
      },
    });
  });
}

function initSidebar() {
  const sidebar = document.getElementById('appSidebar');
  const backdrop = document.getElementById('sidebarBackdrop');
  const toggle = document.getElementById('sidebarToggle');
  if (toggle && sidebar) {
    toggle.addEventListener('click', () => {
      sidebar.classList.toggle('open');
      backdrop?.classList.toggle('show');
    });
  }
  if (backdrop && sidebar) {
    backdrop.addEventListener('click', () => {
      sidebar.classList.remove('open');
      backdrop.classList.remove('show');
    });
  }
}

function initNavActive() {
  const currentPath = window.location.pathname;
  document.querySelectorAll('.nav-item[data-path]').forEach(link => {
    const path = link.getAttribute('data-path');
    if (path === currentPath || (path !== '/' && currentPath.startsWith(path))) {
      link.classList.add('active');
    }
  });
}

document.addEventListener('DOMContentLoaded', function() {
  initSidebar();
  initNavActive();
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(t => new bootstrap.Tooltip(t));
  initAiFloatingBtn();
  initUnreadPolling();
});

function initAiFloatingBtn() {
  const btn = document.getElementById('aiFloatingBtn');
  if (!btn) return;

  const saved = localStorage.getItem('aiFabPos');
  if (saved) {
    try {
      const { left, top } = JSON.parse(saved);
      btn.style.left = left;
      btn.style.top = top;
      btn.style.right = 'auto';
      btn.style.bottom = 'auto';
    } catch (_) { /* ignore */ }
  }

  let startX = 0;
  let startY = 0;
  let startLeft = 0;
  let startTop = 0;
  let moved = false;

  function savePos() {
    const rect = btn.getBoundingClientRect();
    localStorage.setItem('aiFabPos', JSON.stringify({
      left: `${rect.left}px`,
      top: `${rect.top}px`,
    }));
  }

  function onPointerDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    moved = false;
    startX = e.clientX;
    startY = e.clientY;
    const rect = btn.getBoundingClientRect();
    startLeft = rect.left;
    startTop = rect.top;
    btn.classList.add('dragging');
    btn.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  }

  function onPointerMove(e) {
    const dx = e.clientX - startX;
    const dy = e.clientY - startY;
    if (!moved && (Math.abs(dx) > 6 || Math.abs(dy) > 6)) moved = true;
    if (!moved) return;
    btn.style.left = Math.max(8, Math.min(window.innerWidth - btn.offsetWidth - 8, startLeft + dx)) + 'px';
    btn.style.top = Math.max(8, Math.min(window.innerHeight - btn.offsetHeight - 8, startTop + dy)) + 'px';
    btn.style.right = 'auto';
    btn.style.bottom = 'auto';
  }

  function onPointerUp(e) {
    btn.classList.remove('dragging');
    btn.releasePointerCapture?.(e.pointerId);
    if (moved) {
      savePos();
    } else {
      openAiWindow();
    }
    moved = false;
  }

  btn.addEventListener('pointerdown', onPointerDown);
  btn.addEventListener('pointermove', onPointerMove);
  btn.addEventListener('pointerup', onPointerUp);
  btn.addEventListener('pointercancel', onPointerUp);
}

function openAiWindow() {
  const win = document.getElementById('aiChatWindow');
  const btn = document.getElementById('aiFloatingBtn');
  if (!win) return;
  win.style.display = 'flex';
  if (btn) {
    const rect = btn.getBoundingClientRect();
    const winW = Math.min(420, window.innerWidth - 16);
    const winH = Math.min(520, window.innerHeight - 16);
    let left = rect.left - winW + btn.offsetWidth;
    let top = rect.top - winH - 12;
    if (left < 8) left = 8;
    if (top < 8) top = rect.bottom + 12;
    if (left + winW > window.innerWidth - 8) left = window.innerWidth - winW - 8;
    win.style.left = left + 'px';
    win.style.top = top + 'px';
    win.style.right = 'auto';
    win.style.bottom = 'auto';
  }
  document.getElementById('aiChatInput')?.focus();
}

function openAiWithQuestion(question) {
  openAiWindow();
  const input = document.getElementById('aiChatInput');
  if (input) input.value = question;
  sendAiMessage();
}

function toggleAiWindow() {
  const win = document.getElementById('aiChatWindow');
  if (!win) return;
  if (win.style.display === 'flex') {
    win.style.display = 'none';
  } else {
    openAiWindow();
  }
}

function closeAiWindow() {
  const win = document.getElementById('aiChatWindow');
  if (win) win.style.display = 'none';
}

function clearAiChat() {
  const body = document.getElementById('aiChatBody');
  if (body) body.innerHTML = '<div class="ai-message ai-bot"><div class="ai-bubble">对话已清空，有什么可以帮助你的？</div></div>';
  fetch('/api/ai/clear', { method: 'POST' }).catch(() => {});
}

function sendAiMessage() {
  const input = document.getElementById('aiChatInput');
  const body = document.getElementById('aiChatBody');
  if (!input || !body) return;
  const msg = input.value.trim();
  if (!msg) return;

  body.innerHTML += `<div class="ai-message ai-user"><div class="ai-bubble">${msg.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</div></div>`;
  body.innerHTML += '<div class="ai-message ai-bot"><div class="ai-bubble ai-typing">处理中</div></div>';
  body.scrollTop = body.scrollHeight;
  input.value = '';

  fetch('/api/ai/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ message: msg, use_agent: false }),
  })
    .then(async r => {
      const ct = r.headers.get('content-type') || '';
      if (!ct.includes('application/json')) {
        const text = await r.text();
        const hint = r.status === 404 ? '接口不存在，请 Ctrl+F5 刷新后重试'
          : r.status === 401 ? '登录已过期，请重新登录'
          : r.status >= 500 ? '服务繁忙，请稍后再试'
          : (text.slice(0, 80) || `HTTP ${r.status}`);
        throw new Error(hint);
      }
      return r.json();
    })
    .then(data => {
      body.querySelector('.ai-typing')?.parentElement?.remove();
      if (data.success) {
        const replyHtml = typeof formatAgentReply === 'function'
          ? formatAgentReply(data.reply, data)
          : data.reply.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g, '<br>');
        body.innerHTML += `<div class="ai-message ai-bot"><div class="ai-bubble">${replyHtml}</div></div>`;
        if (typeof handleAgentResponse === 'function') handleAgentResponse(data);
      } else {
        body.innerHTML += `<div class="ai-message ai-bot"><div class="ai-bubble text-danger">错误: ${data.error||'请求失败'}</div></div>`;
      }
      body.scrollTop = body.scrollHeight;
    })
    .catch(err => {
      body.querySelector('.ai-typing')?.parentElement?.remove();
      body.innerHTML += `<div class="ai-message ai-bot"><div class="ai-bubble text-danger">请求失败: ${err.message}</div></div>`;
      body.scrollTop = body.scrollHeight;
    });
}

function initUnreadPolling() {
  const badge = document.getElementById('unreadBadge');
  if (!badge) return;
  let lastMsgId = parseInt(localStorage.getItem('lastMsgPollId') || '0', 10) || 0;
  let lastUnread = 0;

  function check() {
    fetch(`/api/messages/poll?last_id=${lastMsgId}`, { credentials: 'same-origin' })
      .then(r => r.json())
      .then(d => {
        if (!d.success) return;
        if (d.unread > 0) {
          badge.style.display = 'inline';
          badge.textContent = d.unread > 99 ? '99+' : d.unread;
        } else {
          badge.style.display = 'none';
        }
        if (d.unread > lastUnread && d.messages?.length) {
          const latest = d.messages[d.messages.length - 1];
          const who = latest.sender_name || '好友';
          if (typeof showToast === 'function') {
            showToast(`${who} 发来新消息`, 'info');
          }
        }
        lastUnread = d.unread;
        if (d.last_id && d.last_id > lastMsgId) {
          lastMsgId = d.last_id;
          localStorage.setItem('lastMsgPollId', String(lastMsgId));
        }
        if (d.messages?.length && typeof window.onNewChatMessages === 'function') {
          window.onNewChatMessages(d.messages);
        }
      }).catch(() => {});
  }
  function tick() {
    if (document.hidden) return;
    check();
  }
  tick();
  setInterval(tick, 15000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) tick();
  });
}
