/**
 * Agent 客户端动作执行 — 页面跳转、提示等（claw-code 风格）
 */
window.handleAgentResponse = function handleAgentResponse(data) {
  if (!data) return;
  const actions = data.actions || [];
  for (const a of actions) {
    if (a.action === 'navigate' && a.url) {
      const reason = a.reason || '正在为您打开页面…';
      if (typeof showToast === 'function') showToast(reason, 'info');
      const delay = a.delay_ms != null ? a.delay_ms : 1200;
      setTimeout(() => { window.location.href = a.url; }, delay);
    }
  }
};

window.formatAgentReply = function formatAgentReply(text, data) {
  let html = String(text || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
  if (data?.actions?.length) {
    const nav = data.actions.filter(a => a.action === 'navigate');
    if (nav.length) {
      html += '<div class="agent-nav-hint small text-muted mt-2"><i class="bi bi-box-arrow-up-right"></i> ' +
        nav.map(a => `将跳转至 ${a.url}`).join('；') + '</div>';
    }
  }
  if (data?.steps?.length) {
    html += '<div class="agent-steps small text-muted mt-1"><i class="bi bi-tools"></i> ' +
      data.steps.map(s => `${s.tool}${s.ok ? ' ✓' : ' ✗'}`).join(' → ') + '</div>';
  }
  return html;
};
