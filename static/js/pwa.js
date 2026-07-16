/**
 * PWA：注册 Service Worker，并提供「安装到桌面」按钮逻辑。
 */
(function () {
  if (!('serviceWorker' in navigator)) return;

  const swUrl = '/sw.js';
  window.addEventListener('load', () => {
    navigator.serviceWorker.register(swUrl).catch((err) => {
      console.warn('[PWA] SW register failed', err);
    });
  });

  let deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    document.querySelectorAll('[data-pwa-install]').forEach((el) => {
      el.style.display = '';
      el.disabled = false;
    });
  });

  window.addEventListener('appinstalled', () => {
    deferredPrompt = null;
    document.querySelectorAll('[data-pwa-install]').forEach((el) => {
      el.style.display = 'none';
    });
    if (typeof showToast === 'function') {
      showToast('已安装到桌面，以后可直接点图标打开', 'success');
    }
  });

  window.installFinanceApp = async function installFinanceApp() {
    if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone) {
      if (typeof showToast === 'function') showToast('已在 App 窗口中运行', 'info');
      return;
    }
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const choice = await deferredPrompt.userChoice;
      deferredPrompt = null;
      if (choice.outcome === 'accepted' && typeof showToast === 'function') {
        showToast('安装成功，可在桌面找到「财务系统」', 'success');
      }
      return;
    }
    // Edge / Chrome 手动安装提示
    const tip =
      '若未弹出安装框：请用 Chrome / Edge 打开本系统 → 地址栏右侧「安装」图标，' +
      '或菜单 → 应用 → 安装此网站。也可：菜单 → 更多工具 → 创建快捷方式 → 勾选「在窗口中打开」。';
    if (typeof showToast === 'function') showToast(tip, 'info');
    else alert(tip);
  };

  // 已安装则隐藏按钮
  if (window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone) {
    document.addEventListener('DOMContentLoaded', () => {
      document.querySelectorAll('[data-pwa-install]').forEach((el) => {
        el.style.display = 'none';
      });
    });
  }
})();
