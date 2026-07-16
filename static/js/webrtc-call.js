/**
 * WebRTC 视频通话 — 全站来电监听 + 消息页发起
 */
let callPeerId = null;
let callPollTimer = null;
let incomingTimer = null;
let ringTimer = null;
let localStream = null;
let peerConnection = null;
let isCaller = false;
let incomingBanner = null;
let pendingCallerId = null;
let pendingIceCandidates = [];
const appliedIceKeys = new Set();

const rtcConfig = {
  iceServers: [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    { urls: 'stun:stun.cloudflare.com:3478' },
    { urls: 'turn:openrelay.metered.ca:80', username: 'openrelayproject', credential: 'openrelayproject' },
    { urls: 'turn:openrelay.metered.ca:443', username: 'openrelayproject', credential: 'openrelayproject' },
    { urls: 'turn:openrelay.metered.ca:443?transport=tcp', username: 'openrelayproject', credential: 'openrelayproject' },
  ],
  iceCandidatePoolSize: 10,
};

const callFetchOpts = { credentials: 'same-origin' };

function callJson(url, options = {}) {
  return fetch(url, { ...callFetchOpts, ...options });
}

function initVideoCall(currentUserId) {
  window.__currentUserId = currentUserId;
}

function updateCallButtons(username, userId) {
  const header = document.getElementById('chatHeader');
  if (!header || !userId) return;
  header.innerHTML = `
    <div class="d-flex align-items-center justify-content-between w-100 flex-wrap gap-2">
      <strong><i class="bi bi-person"></i> ${escapeCallHtml(username)}</strong>
      <button type="button" class="btn btn-sm btn-primary" onclick="startVideoCall(${userId})">
        <i class="bi bi-camera-video-fill"></i> 视频通话
      </button>
    </div>`;
}

function escapeCallHtml(s) {
  const d = document.createElement('div');
  d.textContent = s || '';
  return d.innerHTML;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function startRingTone() {
  stopRingTone();
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    ringTimer = setInterval(() => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      gain.gain.value = 0.08;
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
    }, 1200);
    ringTimer._audioCtx = ctx;
  } catch (e) { /* 静音环境忽略 */ }
}

function stopRingTone() {
  if (ringTimer) {
    clearInterval(ringTimer);
    if (ringTimer._audioCtx) ringTimer._audioCtx.close().catch(() => {});
    ringTimer = null;
  }
}

async function startVideoCall(peerId) {
  if (!peerId) {
    showToast('请先选择聊天对象', 'warning');
    return;
  }
  if (!navigator.mediaDevices?.getUserMedia) {
    showToast('当前浏览器不支持视频通话', 'error');
    return;
  }
  callPeerId = peerId;
  isCaller = true;
  showCallOverlay('正在呼叫…');
  try {
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    document.getElementById('localVideo').srcObject = localStream;
    const startRes = await callJson('/api/call/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: peerId }),
    });
    const startData = await startRes.json();
    if (!startData.success) throw new Error(startData.error || '无法发起通话');
    await createPeerConnection();
    const offer = await peerConnection.createOffer();
    await peerConnection.setLocalDescription(offer);
    const offerRes = await callJson('/api/call/offer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: peerId, sdp: offer }),
    });
    const offerData = await offerRes.json();
    if (!offerData.success) throw new Error('信令发送失败');
    startCallPolling();
  } catch (err) {
    showToast('无法启动视频通话: ' + err.message, 'error');
    endVideoCall();
  }
}

async function answerIncomingCall(callerId, offer) {
  hideIncomingBanner();
  callPeerId = callerId;
  isCaller = false;
  showCallOverlay('接听中…');
  try {
    localStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
    document.getElementById('localVideo').srcObject = localStream;
    await createPeerConnection();
    await peerConnection.setRemoteDescription(offer);
    const answer = await peerConnection.createAnswer();
    await peerConnection.setLocalDescription(answer);
    await flushPendingIce();
    const ansRes = await callJson('/api/call/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ caller_id: callerId, sdp: answer }),
    });
    const ansData = await ansRes.json();
    if (!ansData.success) throw new Error('接听失败');
    document.getElementById('callStatus').textContent = '通话中';
    startCallPolling();
  } catch (err) {
    showToast('接听失败: ' + err.message, 'error');
    endVideoCall();
  }
}

async function addIceCandidateSafe(candidate) {
  if (!peerConnection || !candidate) return;
  const key = JSON.stringify(candidate);
  if (appliedIceKeys.has(key)) return;
  if (!peerConnection.remoteDescription) {
    pendingIceCandidates.push(candidate);
    return;
  }
  try {
    await peerConnection.addIceCandidate(new RTCIceCandidate(candidate));
    appliedIceKeys.add(key);
  } catch (e) {
    console.warn('[WebRTC] ICE add failed:', e);
  }
}

async function flushPendingIce() {
  if (!peerConnection?.remoteDescription) return;
  const queue = pendingIceCandidates.splice(0);
  for (const c of queue) {
    await addIceCandidateSafe(c);
  }
}

function attachRemoteStream(ev) {
  const remote = document.getElementById('remoteVideo');
  if (!remote) return;
  const stream = ev.streams?.[0] || new MediaStream([ev.track]);
  if (remote.srcObject !== stream) {
    remote.srcObject = stream;
  }
  const playPromise = remote.play();
  if (playPromise) {
    playPromise.catch(() => {
      remote.muted = true;
      remote.play().finally(() => { remote.muted = false; }).catch(() => {});
    });
  }
}

async function createPeerConnection() {
  pendingIceCandidates = [];
  appliedIceKeys.clear();
  peerConnection = new RTCPeerConnection(rtcConfig);
  localStream.getTracks().forEach((track) => peerConnection.addTrack(track, localStream));
  peerConnection.ontrack = attachRemoteStream;
  peerConnection.onconnectionstatechange = () => {
    const st = peerConnection?.connectionState;
    const statusEl = document.getElementById('callStatus');
    if (st === 'connected' && statusEl) statusEl.textContent = '通话中';
    if (st === 'failed') showToast('视频连接失败，请重试', 'error');
  };
  peerConnection.onicecandidate = (ev) => {
    if (ev.candidate && callPeerId) {
      callJson('/api/call/ice', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ peer_id: callPeerId, candidate: ev.candidate.toJSON() }),
      });
    }
  };
}

function startCallPolling() {
  stopCallPolling();
  callPollTimer = setInterval(pollCallSignals, 1000);
}

function stopCallPolling() {
  if (callPollTimer) {
    clearInterval(callPollTimer);
    callPollTimer = null;
  }
}

async function pollCallSignals() {
  if (!callPeerId) return;
  try {
    const r = await callJson(`/api/call/poll?peer_id=${callPeerId}`);
    const d = await r.json();
    if (!d.success || !d.active) return;

    if (isCaller && d.answer && peerConnection && !peerConnection.currentRemoteDescription) {
      await peerConnection.setRemoteDescription(d.answer);
      document.getElementById('callStatus').textContent = '连接中…';
    }

    if (d.ice?.length && peerConnection) {
      for (const c of d.ice) await addIceCandidateSafe(c);
    }
    await flushPendingIce();

    if (peerConnection?.connectionState === 'connected') {
      document.getElementById('callStatus').textContent = '通话中';
    }
  } catch (e) { /* ignore */ }
}

function showCallOverlay(statusText) {
  const overlay = document.getElementById('videoCallOverlay');
  if (overlay) {
    overlay.style.display = 'flex';
    const st = document.getElementById('callStatus');
    if (st) st.textContent = statusText || '';
  }
}

function endVideoCall() {
  stopCallPolling();
  hideIncomingBanner();
  if (callPeerId) {
    callJson('/api/call/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: callPeerId }),
    });
  }
  if (peerConnection) {
    peerConnection.close();
    peerConnection = null;
  }
  if (localStream) {
    localStream.getTracks().forEach((t) => t.stop());
    localStream = null;
  }
  const overlay = document.getElementById('videoCallOverlay');
  if (overlay) overlay.style.display = 'none';
  const localV = document.getElementById('localVideo');
  const remoteV = document.getElementById('remoteVideo');
  if (localV) localV.srcObject = null;
  if (remoteV) remoteV.srcObject = null;
  callPeerId = null;
  isCaller = false;
  pendingIceCandidates = [];
  appliedIceKeys.clear();
}

function showIncomingBanner(callerId, callerName, offer) {
  hideIncomingBanner();
  pendingCallerId = callerId;
  const hasOffer = !!offer;
  incomingBanner = document.createElement('div');
  incomingBanner.className = 'incoming-call-banner incoming-call-ringing';
  incomingBanner.innerHTML = `
    <div class="incoming-call-inner">
      <div class="incoming-call-avatar"><i class="bi bi-camera-video-fill"></i></div>
      <div class="incoming-call-info">
        <strong>${escapeCallHtml(callerName)}</strong>
        <span>${hasOffer ? '邀请您视频通话' : '正在呼叫您…'}</span>
      </div>
      <div class="d-flex gap-2">
        <button type="button" class="btn btn-sm btn-success" id="acceptCallBtn" ${hasOffer ? '' : 'disabled'}>
          ${hasOffer ? '接听' : '连接中…'}
        </button>
        <button type="button" class="btn btn-sm btn-outline-light" id="rejectCallBtn">拒绝</button>
      </div>
    </div>`;
  document.body.appendChild(incomingBanner);
  startRingTone();

  document.getElementById('rejectCallBtn').onclick = () => {
    callJson('/api/call/end', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ peer_id: callerId }),
    });
    hideIncomingBanner();
  };

  if (hasOffer) {
    document.getElementById('acceptCallBtn').onclick = () => answerIncomingCall(callerId, offer);
  } else {
    waitForOfferThenEnable(callerId);
  }
}

async function waitForOfferThenEnable(callerId) {
  for (let i = 0; i < 40; i++) {
    await sleep(500);
    if (!incomingBanner || pendingCallerId !== callerId) return;
    try {
      const r = await callJson('/api/call/incoming');
      const d = await r.json();
      if (!d.success || !d.active) {
        hideIncomingBanner();
        return;
      }
      if (d.caller_id === callerId && d.offer) {
        const btn = document.getElementById('acceptCallBtn');
        if (btn) {
          btn.disabled = false;
          btn.textContent = '接听';
          btn.onclick = () => answerIncomingCall(callerId, d.offer);
        }
        const info = incomingBanner.querySelector('.incoming-call-info span');
        if (info) info.textContent = '邀请您视频通话';
        return;
      }
    } catch (e) { /* ignore */ }
  }
}

function hideIncomingBanner() {
  stopRingTone();
  pendingCallerId = null;
  if (incomingBanner) {
    incomingBanner.remove();
    incomingBanner = null;
  }
}

function startIncomingCallWatcher() {
  if (incomingTimer) return;
  incomingTimer = setInterval(async () => {
    if (callPeerId || incomingBanner) return;
    try {
      const r = await callJson('/api/call/incoming');
      const d = await r.json();
      if (d.success && d.active) {
        showIncomingBanner(d.caller_id, d.caller_name || '好友', d.offer || null);
        if (typeof showToast === 'function') {
          showToast(`${d.caller_name || '好友'} 向您发起视频通话`, 'warning');
        }
      }
    } catch (e) { /* ignore */ }
  }, 1000);
}

document.addEventListener('DOMContentLoaded', () => {
  if (window.__enableVideoCall || window.__currentUserId) {
    startIncomingCallWatcher();
  }
});
