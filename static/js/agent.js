/**
 * AI Agent 工作台 v3
 * - 多会话管理 + 持久化
 * - 文件拖拽上传 + 附件预览（不自动发送）
 * - 自适应输入框
 * - 操作步骤可视化（参考 claw-code TranscriptStore / TurnResult）
 */
let agentModels = [];
let agentExtensions = [];
let agentPermissionMode = 'ask';
let agentRunMode = 'single';
let pendingPermissionTool = null;
let currentConversationId = null;
let pendingFile = null;  // 待发送的文件对象

document.addEventListener('DOMContentLoaded', () => {
  loadAgentModels();
  loadExtensions();
  loadWorkflows();
  loadFeishuStatus();
  loadModelStatus();
  initPermissionButtons();
  initRunModeButtons();
  loadConversations();
  initDragDrop();

  const webhookEl = document.getElementById('fsWebhookUrl');
  if (webhookEl) webhookEl.value = window.location.origin + '/api/feishu/webhook';
});

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 输入框自适应高度
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function autoResizeTextarea(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 拖拽上传
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function initDragDrop() {
  const zone = document.getElementById('agentChat');
  if (!zone) return;

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    e.stopPropagation();
    zone.classList.add('drag-over');
  });

  zone.addEventListener('dragleave', e => {
    e.preventDefault();
    e.stopPropagation();
    zone.classList.remove('drag-over');
  });

  zone.addEventListener('drop', e => {
    e.preventDefault();
    e.stopPropagation();
    zone.classList.remove('drag-over');
    const files = e.dataTransfer.files;
    if (files.length > 0) {
      attachFile(files[0]);
    }
  });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 文件附件（先预览，不自动发送）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function onFileSelected() {
  const input = document.getElementById('agentFileInput');
  const file = input.files[0];
  if (!file) return;
  attachFile(file);
  input.value = '';
}

function attachFile(file) {
  if (!file) return;
  const ext = file.name.split('.').pop().toLowerCase();
  const valid = ['csv', 'xls', 'xlsx', 'png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'];
  if (!valid.includes(ext)) {
    appendAgentMsg('bot', `不支持的文件格式: .${ext}（支持 ${valid.join(', ')}）`, false, true);
    return;
  }

  pendingFile = file;

  const sizeStr = file.size > 1024*1024 ? (file.size / 1024 / 1024).toFixed(1) + ' MB' : (file.size / 1024).toFixed(1) + ' KB';
  const icon = ['png','jpg','jpeg','gif','bmp','webp'].includes(ext) ? '🖼️' : '📄';
  const area = document.getElementById('attachPreviewArea');
  area.style.display = 'block';
  area.innerHTML = `
    <div class="file-attach-preview d-inline-flex">
      ${icon} <strong>${esc(file.name)}</strong> <span class="text-muted">${sizeStr}</span>
      <button class="btn btn-sm btn-primary py-0 px-1 ms-1" onclick="analyzeAttachedFile()" title="立即分析此文件">
        <i class="bi bi-search"></i> 分析
      </button>
      <span class="remove-attach" onclick="removeAttachment()" title="移除附件">&times;</span>
    </div>
    <span class="small text-muted ms-2">输入消息后点击发送，或点击"分析"直接处理</span>
  `;

  // focus input so user can type message
  document.getElementById('agentInput')?.focus();
}

function analyzeAttachedFile() {
  if (!pendingFile) return;
  uploadAttachedFile('');
}

function removeAttachment() {
  pendingFile = null;
  document.getElementById('attachPreviewArea').style.display = 'none';
  document.getElementById('attachPreviewArea').innerHTML = '';
  document.getElementById('agentFileInput').value = '';
}

function uploadAttachedFile(msg) {
  if (!pendingFile) return null;

  appendAgentMsg('user', `📎 ${pendingFile.name}`);
  appendAgentMsg('bot', '⏳ 处理文件中…', true);

  const formData = new FormData();
  formData.append('file', pendingFile);
  if (currentConversationId) formData.append('conversation_id', currentConversationId);

  const fileName = pendingFile.name;
  removeAttachment();

  return fetch('/api/agent/upload', { method: 'POST', body: formData })
    .then(r => r.json())
    .then(d => {
      removeTyping();
      if (d.success) {
        appendAgentMsg('bot', d.reply);
        loadConversations();
        if (d.conversation_id && !currentConversationId) {
          currentConversationId = d.conversation_id;
          loadConversations();
        }
        return true;
      } else {
        appendAgentMsg('bot', `处理失败: ${d.error || '未知错误'}`, false, true);
        return false;
      }
    })
    .catch(err => {
      removeTyping();
      appendAgentMsg('bot', `上传失败: ${err.message}`, false, true);
      return false;
    });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 会话管理
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function loadConversations() {
  fetch('/api/agent/conversations')
    .then(r => r.json())
    .then(d => {
      if (!d.success || !d.conversations?.length) return;
      const sel = document.getElementById('convSelect');
      if (!sel) return;
      const currentVal = sel.value;
      sel.innerHTML = '<option value="">+ 新建对话…</option>' +
        d.conversations.map(c =>
          `<option value="${c.id}" ${String(c.id) === currentVal ? 'selected' : ''}>
            ${esc(c.title || '无标题')} (${c.message_count || 0})
          </option>`
        ).join('');
    });
}

function switchConversation(convId) {
  if (!convId) { newConversation(); return; }
  currentConversationId = parseInt(convId);
  fetch(`/api/agent/conversations/${convId}`)
    .then(r => r.json())
    .then(d => {
      if (!d.success) return;
      const messages = d.conversation.messages || [];
      const box = document.getElementById('agentChat');
      if (!box) return;
      if (!messages.length) {
        box.innerHTML = '<div class="agent-msg bot"><div class="agent-bubble">开始新对话吧！</div></div>';
        return;
      }
      box.innerHTML = messages.map(m => {
        const role = m.role === 'user' ? 'user' : 'bot';
        const text = formatContent(m.content || '');
        return `<div class="agent-msg ${role}"><div class="agent-bubble">${text}</div></div>`;
      }).join('');
      box.scrollTop = box.scrollHeight;
    });
}

function newConversation() {
  currentConversationId = null;
  removeAttachment();
  const box = document.getElementById('agentChat');
  if (box) {
    box.innerHTML = `<div class="agent-msg bot"><div class="agent-bubble">新对话已开始！👤 单模型 · 🔮 Auto · 👥 多Agent<br>📎 拖拽文件到这里上传</div></div>`;
  }
  const sel = document.getElementById('convSelect');
  if (sel) sel.value = '';
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 发送消息
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function sendAgentMessage() {
  const input = document.getElementById('agentInput');
  const msg = (input?.value || '').trim();
  if (!msg && !pendingFile) return;

  // 如果有附件，先处理文件
  if (pendingFile) {
    const filePromise = uploadAttachedFile(msg);
    if (filePromise) {
      filePromise.then(ok => {
        // 文件处理完后，如果有消息内容再发送文本
        if (msg && ok) {
          _sendTextMessage(msg);
        }
      });
    }
    input.value = '';
    input.style.height = 'auto';
    return;
  }

  // 无附件，直接发文本
  if (msg) {
    _sendTextMessage(msg);
    input.value = '';
    input.style.height = 'auto';
  }
}

function _sendTextMessage(msg) {
  const model = document.getElementById('agentModel')?.value;
  const useTools = document.getElementById('agentUseTools')?.checked;

  appendAgentMsg('user', msg);
  appendAgentMsg('bot', '💭 思考中…', true);

  fetch('/api/agent/chat', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      message: msg, model, use_tools: useTools,
      permission_mode: agentPermissionMode,
      run_mode: agentRunMode,
      conversation_id: currentConversationId,
      current_page: document.body.dataset.currentPage || 'agent',
    }),
  })
    .then(r => r.json())
    .then(d => {
      removeTyping();
      if (!d.success) {
        appendAgentMsg('bot', `❌ 错误: ${esc(d.error || '未知错误')}`, false, true);
        return;
      }
      if (d.conversation_id && !currentConversationId) {
        currentConversationId = d.conversation_id;
        loadConversations();
      }
      if (d.needs_permission && d.permission_requests?.length) {
        pendingPermissionTool = d.pending_tool;
        _showPermissionCard(d.permission_requests[0]);
        return;
      }
      _renderFinalReply(d);
    })
    .catch(err => {
      removeTyping();
      appendAgentMsg('bot', `❌ 请求失败: ${esc(err.message)}`, false, true);
    });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 回复渲染 + 步骤可视化（参考 claw-code TurnResult）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function _renderFinalReply(d) {
  let html = '';

  // ── Auto 模式提示 ──
  if (d.run_mode === 'auto' && d.auto_model) {
    html += `<div class="step-duration"><i class="bi bi-magic"></i> Auto → ${esc(d.auto_model)}: ${esc(d.auto_reason || '自动路由')}</div>`;
  }

  // ── 多Agent 模式 ──
  if (d.run_mode === 'multi' && d.worker_results?.length) {
    html += '<div class="step-detail">';
    html += '<div class="step-detail-header" onclick="toggleStepDetail(this)"><i class="bi bi-people"></i> 多Agent协作 · ' +
      d.worker_results.length + ' 个Worker <span class="ms-auto"><i class="bi bi-chevron-down"></i></span></div>';
    html += '<div class="step-detail-body">';
    d.worker_results.forEach(w => {
      html += `<div class="small mb-1">${w.ok ? '✅' : '❌'} <b>${esc(w.role)}</b> (${esc(w.model)})</div>`;
    });
    html += '</div></div>';
  }

  // ── 工具调用步骤（参考 claw-code TranscriptStore）──
  if (d.steps?.length) {
    html += '<div class="step-detail">';
    html += '<div class="step-detail-header" onclick="toggleStepDetail(this)"><i class="bi bi-tools"></i> 操作流程 · ' +
      d.steps.length + ' 步 <span class="step-duration">' +
      d.steps.map(s => `${s.ok ? '✅' : '❌'} ${esc(s.tool)}`).join(' → ') +
      '</span> <span class="ms-auto"><i class="bi bi-chevron-down"></i></span></div>';
    html += '<div class="step-detail-body">';
    d.steps.forEach((s, i) => {
      html += `<div class="mb-2 pb-2 ${i < d.steps.length - 1 ? 'border-bottom' : ''}">`;
      html += `<b>${i + 1}. ${esc(s.tool)}</b>`;
      if (s.duration_ms) html += ` <span class="step-duration">(${s.duration_ms}ms)</span>`;
      html += s.ok ? ' ✅' : ' ❌';
      if (s.args && Object.keys(s.args).length > 0) {
        html += `<br><span class="text-muted">参数:</span> <code class="small">${esc(JSON.stringify(s.args))}</code>`;
      }
      if (s.result) {
        const resultStr = typeof s.result === 'string' ? s.result : JSON.stringify(s.result);
        html += `<br><span class="text-muted">结果:</span> <pre>${esc(resultStr.substring(0, 500))}${resultStr.length > 500 ? '…' : ''}</pre>`;
      }
      if (s.error) {
        html += `<br><span class="text-danger">错误: ${esc(s.error)}</span>`;
      }
      html += '</div>';
    });
    html += '</div></div>';
  }

  // ── AI 回复正文 ──
  const reply = d.reply || '';
  html += `<div>${formatContent(reply)}</div>`;

  appendAgentMsg('bot', html);
}

function toggleStepDetail(header) {
  const body = header.nextElementSibling;
  body.classList.toggle('open');
  const icon = header.querySelector('.bi-chevron-down, .bi-chevron-up');
  if (icon) {
    icon.classList.toggle('bi-chevron-down');
    icon.classList.toggle('bi-chevron-up');
  }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 通用消息渲染
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function appendAgentMsg(role, text, typing, isError) {
  const box = document.getElementById('agentChat');
  if (!box) return;
  const id = typing ? 'agentTyping' : '';
  const cls = role === 'user' ? 'user' : 'bot';
  const errCls = isError ? ' text-danger' : '';
  box.innerHTML += `<div class="agent-msg ${cls}" ${id ? `id="${id}"` : ''}>
    <div class="agent-bubble${errCls}">${typeof text === 'string' ? text : String(text)}</div>
  </div>`;
  box.scrollTop = box.scrollHeight;
}

function removeTyping() {
  const el = document.getElementById('agentTyping');
  if (el) el.remove();
}

// 内容格式化（处理换行、链接、代码块）
function formatContent(text) {
  if (!text) return '';
  let s = esc(String(text));
  // 换行
  s = s.replace(/\n/g, '<br>');
  // Markdown 代码块 ```...```
  s = s.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre class="bg-light p-2 rounded small" style="max-height:200px;overflow:auto">$2</pre>');
  // 行内代码 `...`
  s = s.replace(/`([^`]+)`/g, '<code class="bg-light px-1 rounded">$1</code>');
  // URL 自动链接
  s = s.replace(/(https?:\/\/[^\s<>]+)/g, '<a href="$1" target="_blank">$1</a>');
  // 导航链接
  s = s.replace(/(\/(dashboard|analysis|report|preview|history|chat|agent|edit|profile|search|models)\b)/g,
    '<a href="$1" target="_self" class="text-decoration-underline">$1</a>');
  return s;
}

function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 模型相关
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function loadAgentModels() {
  fetch('/api/agent/models')
    .then(r => r.json())
    .then(d => {
      if (!d.success) return;
      agentModels = d.models || [];
      const sel = document.getElementById('agentModel');
      if (!sel) return;
      sel.innerHTML = agentModels.map(m =>
        `<option value="${esc(m.id)}" ${m.is_default ? 'selected' : ''} ${m.available ? '' : 'disabled'}>
          ${esc(m.name)}${m.auto_discovered ? ' 🔍' : ''}${m.available ? '' : ' (未配置)'}
        </option>`
      ).join('');
      // show delete button
      const delBtn = document.getElementById('btnDeleteModel');
      if (delBtn && agentRunMode !== 'multi' && sel.value) delBtn.style.display = 'inline-block';
      sel.addEventListener('change', () => {
        if (delBtn && agentRunMode !== 'multi') delBtn.style.display = sel.value ? 'inline-block' : 'none';
      });
    });
}

function loadModelStatus() {
  const el = document.getElementById('modelStatus');
  if (!el) return;
  fetch('/api/agent/models')
    .then(r => r.json())
    .then(d => {
      if (!d.success) return;
      const models = d.models || [];
      const available = models.filter(m => m.available);
      el.innerHTML = `
        <div class="small mb-2" style="font-weight:700;">可用 <span style="color:var(--agent-green)">${available.length}</span> / ${models.length}</div>
        ${models.slice(0, 10).map(m => `
          <div class="model-mini-row">
            <span style="display:flex;align-items:center;gap:4px;max-width:165px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(m.id)}">
              <span class="dot ${m.available ? 'dot-ok' : 'dot-no'}"></span>${esc(m.name)}${m.is_default ? ' ⭐' : ''}
            </span>
            <button class="ag-btn-sm danger" style="padding:1px 5px;font-size:9px;border-width:1px;" onclick="deleteModelById('${esc(m.id)}')" title="删除">✕</button>
          </div>
        `).join('')}
        <div class="d-flex gap-1 mt-2">
          <button class="ag-btn-sm" style="flex:1;font-size:10px;" onclick="scanLocalModels()">🔍 扫描</button>
          <a href="/models" class="ag-btn-sm" style="flex:1;font-size:10px;text-align:center;text-decoration:none;">⚙ 管理</a>
        </div>`;
    });
}

function deleteModelById(modelId) {
  if (!confirm(`确定删除 "${modelId}"？`)) return;
  fetch(`/api/agent/models/${encodeURIComponent(modelId)}`, { method: 'DELETE' })
    .then(r => r.json()).then(d => {
      if (d.success) { loadModelStatus(); loadAgentModels(); }
      else appendAgentMsg('bot', `❌ ${d.error}`, false, true);
    });
}

function deleteCurrentModel() {
  const sel = document.getElementById('agentModel');
  if (sel?.value) deleteModelById(sel.value);
}

function scanLocalModels() {
  appendAgentMsg('bot', '🔍 扫描本地 AI 端点…', true);
  fetch('/api/agent/models/scan').then(r => r.json()).then(d => {
    removeTyping();
    if (!d.discovered?.length) { appendAgentMsg('bot', '未发现本地端点。请启动 Ollama/LM Studio。'); return; }
    appendAgentMsg('bot', `发现 ${d.count} 个模型，已加入列表。`);
    loadAgentModels(); loadModelStatus();
  }).catch(err => { removeTyping(); appendAgentMsg('bot', `扫描失败: ${err.message}`, false, true); });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// 扩展 & 工作流 & 权限 & 飞书（保持简洁）
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function loadExtensions() {
  fetch('/api/agent/extensions').then(r => r.json()).then(d => {
    if (!d.success) return;
    agentExtensions = d.extensions || [];
    renderExtensions(agentExtensions);
    renderToolList(d.tools || []);
  });
}

function renderExtensions(exts) {
  const el = document.getElementById('extList');
  if (!el) return;
  const groups = { skill: [], mcp: [], miniprogram: [], agent: [] };
  exts.forEach(e => { const t = e.type || 'skill'; (groups[t] = groups[t] || []).push(e); });
  const labels = { skill: 'Skill', mcp: 'MCP', miniprogram: '小程序', agent: 'Agent' };
  let html = '';
  for (const [type, items] of Object.entries(groups)) {
    if (!items.length) continue;
    html += `<div class="small text-muted mb-1 mt-2">${labels[type] || type}</div>`;
    items.forEach(item => {
      html += `<div class="agent-ext-item" onclick="useExtension('${esc(item.type)}','${esc(item.id)}')">
        <div class="d-flex justify-content-between"><strong class="small">${esc(item.name || item.id)}</strong><span class="badge bg-secondary">${esc(type)}</span></div>
        <div class="small text-muted mt-1">${esc(item.description || '')}</div></div>`;
    });
  }
  el.innerHTML = html || '<div class="text-muted small">暂无扩展</div>';
}

function renderToolList(tools) {
  const el = document.getElementById('toolList');
  if (!el) return;
  if (!tools?.length) { el.innerHTML = '<div class="text-muted">暂无工具</div>'; return; }
  const permIcons = { read: '📖', write: '✏️', export: '📤', danger: '⚠️' };
  el.innerHTML = tools.slice(0, 15).map(t =>
    `<div class="d-flex justify-content-between small mb-1" title="${esc(t.description||'')}"><span class="text-truncate">${permIcons[t.permission]||'🔧'} ${esc(t.name)}</span><span class="text-muted">${t.source||''}</span></div>`
  ).join('') + (tools.length > 15 ? `<div class="small text-muted">…及 ${tools.length - 15} 个</div>` : '');
}

function loadWorkflows() {
  const el = document.getElementById('workflowList');
  if (!el) return;
  fetch('/api/agent/workflows').then(r => r.json()).then(d => {
    const wfs = d.workflows || [];
    if (!wfs.length) { el.innerHTML = '<div class="text-muted small">暂无工作流</div>'; return; }
    el.innerHTML = wfs.map(w => `<div class="agent-ext-item"><strong class="small">${esc(w.name||w.id)}</strong>
      <div class="small text-muted">${esc(w.description||'')}</div>
      <button class="btn btn-sm btn-outline-primary mt-1" onclick="runWorkflow('${esc(w.id)}')"><i class="bi bi-play-fill"></i> 运行</button></div>`).join('');
  });
}

function useExtension(type, id) {
  if (type === 'miniprogram') {
    const mp = agentExtensions.find(e => e.id === id);
    if (mp?.prompts?.length) { document.getElementById('agentInput').value = mp.prompts[0]; sendAgentMessage(); }
    return;
  }
  document.getElementById('agentInput').value = `请使用 ${type}「${id}」帮我完成审计任务`;
  document.getElementById('agentInput').focus();
  autoResizeTextarea(document.getElementById('agentInput'));
}

function runWorkflow(wfId) {
  const model = document.getElementById('agentModel')?.value;
  appendAgentMsg('user', `▶️ 运行工作流: ${wfId}`);
  appendAgentMsg('bot', '⚙️ 工作流执行中…', true);
  fetch(`/api/agent/workflows/${encodeURIComponent(wfId)}/run`, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ model }),
  }).then(r => r.json()).then(d => {
    removeTyping();
    if (d.success) {
      appendAgentMsg('bot', `✅ 工作流完成\n${formatContent(typeof d.output === 'string' ? d.output : JSON.stringify(d.output, null, 2).substring(0, 1500))}`);
    } else {
      appendAgentMsg('bot', `❌ 工作流失败: ${d.error || '未知错误'}`, false, true);
    }
  }).catch(err => { removeTyping(); appendAgentMsg('bot', `请求失败: ${err.message}`, false, true); });
}

function initPermissionButtons() {
  document.querySelectorAll('.perm-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.perm-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      agentPermissionMode = this.dataset.mode;
    });
  });
}

function initRunModeButtons() {
  document.querySelectorAll('.mode-btn').forEach(btn => {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.mode-btn').forEach(b => b.classList.remove('active'));
      this.classList.add('active');
      agentRunMode = this.dataset.mode;
      const sel = document.getElementById('agentModel');
      const delBtn = document.getElementById('btnDeleteModel');
      if (agentRunMode === 'multi') { if (sel) sel.disabled = true; if (delBtn) delBtn.style.display = 'none'; }
      else { if (sel) sel.disabled = false; if (delBtn) delBtn.style.display = sel?.value ? 'inline-block' : 'none'; }
    });
  });
}

function _showPermissionCard(permReq) {
  const box = document.getElementById('agentChat');
  const cardId = 'permCard_' + Date.now();
  const labels = { read: '📖 只读', write: '✏️ 修改', export: '📤 导出', danger: '⚠️ 危险' };
  box.innerHTML += `<div class="agent-msg bot" id="${cardId}"><div class="agent-bubble perm-card">
    <strong>🤖 需要确认</strong><br>
    <span class="small">操作: <b>${esc(permReq.tool_name)}</b> · 权限: ${labels[permReq.perm_level] || permReq.perm_level}</span>
    <div class="mt-2">
      <button class="btn btn-sm btn-primary" onclick="approvePermission(true)">✅ 允许</button>
      <button class="btn btn-sm btn-outline-primary" onclick="approvePermission(true, true)">🔓 始终允许</button>
      <button class="btn btn-sm btn-outline-danger" onclick="approvePermission(false)">❌ 拒绝</button>
    </div></div></div>`;
  box.scrollTop = box.scrollHeight;
}

function approvePermission(allowed, remember) {
  document.querySelectorAll('[id^="permCard_"]').forEach(el => el.remove());
  if (!allowed) { appendAgentMsg('bot', '⛔ 已拒绝。请尝试其他方式。'); pendingPermissionTool = null; return; }
  if (remember && pendingPermissionTool) {
    fetch('/api/agent/permission/allow', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ tool_name: pendingPermissionTool.tool, remember: true }) });
  }
  appendAgentMsg('bot', '✅ 已批准，继续…');
  setTimeout(() => {
    const model = document.getElementById('agentModel')?.value;
    _sendTextMessage('继续执行之前的操作');
  }, 300);
  pendingPermissionTool = null;
}

function clearAgentChat() {
  const box = document.getElementById('agentChat');
  if (box) box.innerHTML = '<div class="agent-msg bot"><div class="agent-bubble">对话已清空。</div></div>';
}

function reloadExtensions() {
  fetch('/api/agent/extensions/reload', { method: 'POST' }).then(r => r.json()).then(d => { if (d.success) { loadExtensions(); loadWorkflows(); } });
}

function loadFeishuStatus() {
  const el = document.getElementById('feishuStatus');
  if (!el) return;
  fetch('/api/feishu/status').then(r => r.json()).then(d => {
    if (d.configured) el.innerHTML = '<div class="text-success small mb-2">✅ 已配置</div><a href="#" class="btn btn-sm btn-outline-primary w-100" data-bs-toggle="modal" data-bs-target="#feishuSetupModal">修改</a>';
    else el.innerHTML = '<div class="text-muted small mb-2">⚠️ 未配置</div><a href="#" class="btn btn-sm btn-outline-primary w-100" data-bs-toggle="modal" data-bs-target="#feishuSetupModal">配置飞书</a>';
  }).catch(() => el.innerHTML = '<div class="text-muted small">状态未知</div>');
}

function saveFeishuConfig() {
  fetch('/api/feishu/config', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ app_id: document.getElementById('fsAppId')?.value || '', app_secret: document.getElementById('fsAppSecret')?.value || '' }),
  }).then(r => r.json()).then(d => {
    if (d.success) { if (typeof bootstrap !== 'undefined') bootstrap.Modal.getInstance(document.getElementById('feishuSetupModal'))?.hide(); loadFeishuStatus(); }
  });
}
