/**
 * Agent 扩展开发工作室
 */
let devType = 'skill';
let currentPath = '';
let currentSkillId = '';

const TYPE_LABELS = {
  skill: 'Skill',
  mcp: 'MCP',
  workflow: '工作流',
  agent: 'Agent',
  miniprogram: '小程序',
};

document.addEventListener('DOMContentLoaded', () => {
  loadFileList();
});

function switchDevType(type, btn) {
  devType = type;
  currentPath = '';
  currentSkillId = '';
  document.querySelectorAll('.dev-tabs .btn').forEach(b => b.classList.remove('active'));
  btn?.classList.add('active');
  document.getElementById('fileListTitle').textContent = TYPE_LABELS[type] + ' 列表';
  document.getElementById('editorTitle').textContent = '选择或新建扩展';
  document.getElementById('devEditor').value = '';
  document.getElementById('editorPath').textContent = '';
  document.getElementById('btnSaveFile').disabled = true;
  document.getElementById('btnReloadFile').disabled = true;
  document.getElementById('skillTestArea').style.display = type === 'skill' ? 'block' : 'none';
  loadFileList();
}

function loadFileList() {
  fetch(`/api/agent/develop/files?type=${devType}`, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(d => {
      const el = document.getElementById('devFileList');
      if (!d.success || !d.files.length) {
        el.innerHTML = `<div class="text-muted small">暂无${TYPE_LABELS[devType]}，点 + 新建</div>`;
        return;
      }
      el.innerHTML = d.files.map(f => {
        const label = f.id;
        const mainPath = f.path;
        let extra = '';
        if (f.handler) {
          extra = `<div class="dev-file-item ms-2" onclick="openFile('${esc(f.handler)}')"><i class="bi bi-file-code"></i> handler.py</div>`;
        }
        return `<div class="dev-file-item ${currentPath === mainPath ? 'active' : ''}" onclick="openFile('${esc(mainPath)}','${esc(f.id)}')">
          <i class="bi bi-file-earmark"></i> ${esc(label)}
        </div>${extra}`;
      }).join('');
    });
}

function openFile(path, skillId) {
  currentPath = path;
  if (skillId) currentSkillId = skillId;
  fetch(`/api/agent/develop/file?path=${encodeURIComponent(path)}`, { credentials: 'same-origin' })
    .then(r => r.json())
    .then(d => {
      if (!d.success) { showToast(d.error, 'error'); return; }
      document.getElementById('devEditor').value = d.content;
      document.getElementById('editorTitle').textContent = d.name;
      document.getElementById('editorPath').textContent = d.path;
      document.getElementById('btnSaveFile').disabled = false;
      document.getElementById('btnReloadFile').disabled = false;
      if (devType === 'skill' && path.endsWith('skill.json')) currentSkillId = skillId || guessSkillId(d.content);
      loadFileList();
    });
}

function guessSkillId(content) {
  try { return JSON.parse(content).id || ''; } catch { return ''; }
}

function loadCurrentFile() {
  if (currentPath) openFile(currentPath, currentSkillId);
}

function saveCurrentFile() {
  if (!currentPath) return;
  const content = document.getElementById('devEditor').value;
  fetch('/api/agent/develop/file', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ path: currentPath, content }),
  })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        showToast('已保存并重新扫描扩展', 'success');
        document.getElementById('devTestOutput').textContent = JSON.stringify(d.counts, null, 2);
      } else {
        showToast(d.error || '保存失败', 'error');
      }
    });
}

function showScaffoldModal() {
  document.getElementById('scaffoldModalTitle').textContent = `新建 ${TYPE_LABELS[devType]}`;
  document.getElementById('scaffoldId').value = '';
  document.getElementById('scaffoldName').value = '';
  document.getElementById('scaffoldDesc').value = '';
  document.getElementById('scaffoldUrl').value = '';
  document.getElementById('scaffoldDescWrap').style.display = devType === 'skill' ? 'block' : 'none';
  document.getElementById('scaffoldUrlWrap').style.display = devType === 'mcp' ? 'block' : 'none';
  new bootstrap.Modal(document.getElementById('scaffoldModal')).show();
}

function createScaffold() {
  const id = document.getElementById('scaffoldId').value.trim();
  const name = document.getElementById('scaffoldName').value.trim();
  if (!id) { showToast('请填写 ID', 'warning'); return; }
  const body = {
    type: devType,
    id,
    name,
    description: document.getElementById('scaffoldDesc').value.trim(),
    url: document.getElementById('scaffoldUrl').value.trim(),
  };
  fetch('/api/agent/develop/scaffold', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body),
  })
    .then(r => r.json())
    .then(d => {
      if (!d.success) { showToast(d.error, 'error'); return; }
      bootstrap.Modal.getInstance(document.getElementById('scaffoldModal'))?.hide();
      showToast('创建成功', 'success');
      const path = d.skill_path || d.path;
      loadFileList();
      if (path) openFile(path, d.skill_id || id);
    });
}

function testCurrentSkill() {
  const skillId = currentSkillId;
  if (!skillId) { showToast('请先打开 skill.json', 'warning'); return; }
  let args = {};
  try {
    args = JSON.parse(document.getElementById('skillTestArgs').value || '{}');
  } catch (e) {
    showToast('参数 JSON 格式错误', 'error');
    return;
  }
  document.getElementById('devTestOutput').textContent = '运行中…';
  fetch('/api/agent/develop/test-skill', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ skill_id: skillId, args }),
  })
    .then(r => r.json())
    .then(d => {
      document.getElementById('devTestOutput').textContent = d.success
        ? JSON.stringify(d.result, null, 2)
        : '错误: ' + (d.error || '未知');
    });
}

function reloadAllExtensions() {
  fetch('/api/agent/extensions/reload', { method: 'POST', credentials: 'same-origin' })
    .then(r => r.json())
    .then(d => {
      if (d.success) {
        showToast('扩展已重新扫描', 'success');
        loadFileList();
      }
    });
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/</g,'&lt;');
}
