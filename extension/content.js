// Content script (изолированный мир). inject.js грузится в MAIN world отдельно
// (см. manifest content_scripts world:MAIN) и перехватывает fetch/XHR к api.faceit.com.
// Здесь: слушаем postMessage из inject.js, POST'ит на Worker, модифицируем страницу.

const WORKER_URL = "https://polished-mouse-4c9d.mishashlikov216.workers.dev";
const BOT_URL = "https://t.me/Faceitxdxdtrackbot";
const STORAGE_KEY = "faceit_bot_link_token";
const SENT_KEY = "faceit_bot_sent_matches";
const VERIFIED_KEY = "faceit_bot_verified";
const STATS_KEY = "faceit_bot_last_stats";

// Fallback: если MAIN-world скрипт не загрузился (старый Firefox), инжектим вручную.
let _injectReady = false;
window.addEventListener("message", (ev) => {
  if (ev.source === window && ev.data && ev.data.__faceit_bot_inject_ready) {
    _injectReady = true;
  }
});
setTimeout(() => {
  if (!_injectReady) {
    console.warn("[FaceitBot] MAIN-world inject не сработал, пробую fallback...");
    const injectFallback = () => {
      try {
        const s = document.createElement("script");
        s.src = chrome.runtime.getURL("inject.js");
        s.onload = () => s.remove();
        (document.head || document.documentElement).appendChild(s);
      } catch (e) {
        console.warn("[FaceitBot] fallback inject не удался:", e);
      }
    };

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', injectFallback);
    } else {
      injectFallback();
    }
  }
}, 1500);

// === UI: floating-кнопка в бота + блок статистики ===
function injectUI() {
  if (document.getElementById("fb-side-button")) return;

  const btn = document.createElement("a");
  btn.id = "fb-side-button";
  btn.href = BOT_URL;
  btn.target = "_blank";
  btn.title = "Открыть Telegram-бота";
  btn.innerHTML = "Бот";
  document.body.appendChild(btn);

  const style = document.createElement("style");
  style.textContent = `
    #fb-side-button{position:fixed;right:16px;bottom:16px;z-index:999999;
      background:#000;color:#fff;padding:10px 16px;border-radius:12px;
      font:600 13px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
      text-decoration:none;box-shadow:0 4px 16px rgba(0,0,0,.3);cursor:pointer;
      transition:transform .15s,background .15s}
    #fb-side-button:hover{transform:scale(1.05);background:#222}
    #fb-stats-box{margin:16px 0;padding:16px;background:#141414;border:1px solid rgba(255,255,255,.08);
      border-radius:14px;color:#fff;font:13px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
    #fb-stats-box h3{margin:0 0 10px;font-size:14px;font-weight:700}
    #fb-stats-box .row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px solid rgba(255,255,255,.05)}
    #fb-stats-box .row:last-child{border:none}
    #fb-stats-box .label{color:#808080}
    #fb-stats-box .value{font-weight:700}
  `;
  document.head.appendChild(style);
}

// Блок статистики вставляется на страницу профиля рядом с ELO/уровнем.
let statsPanel = null;
function renderStatsBox(payload) {
  injectUI();

  // Создаём/обновляем панель
  if (!statsPanel) {
    statsPanel = document.createElement("div");
    statsPanel.id = "fb-stats-box";
    statsPanel.innerHTML = "<h3>Расширенная статистика (из бота)</h3>";
    // Пытаемся вставить рядом с основным контентом профиля
    const host = document.querySelector("[class*='main-content'], [class*='profile'], main, #main-container");
    (host || document.body).insertAdjacentElement("afterbegin", statsPanel);
  }

  const rows = [];
  if (payload.rating_3_0 != null) rows.push(["Rating 3.0", payload.rating_3_0]);
  if (payload.swing != null) rows.push(["Swing", payload.swing]);
  if (payload.elo_history && payload.elo_history.length) {
    const last = payload.elo_history[payload.elo_history.length - 1];
    rows.push(["ELO (последний)", last]);
  }
  if (!rows.length) return;

  statsPanel.innerHTML = "<h3>Расширенная статистика (из бота)</h3>" +
    rows.map(r => `<div class="row"><span class="label">${r[0]}</span><span class="value">${r[1]}</span></div>`).join("");
}

// === Обработка postMessage из inject.js ===
window.addEventListener("message", async (ev) => {
  if (ev.source !== window) return;
  const data = ev.data;

  // --- Идущий матч ---
  if (data && data.__faceit_bot === true) {
    const match = data.match;
    if (!match || !match.match_id) return;
    const linkToken = await getLinkToken();
    if (!linkToken) { console.warn("[FaceitBot] link_token не задан."); return; }
    const sent = (await getSent()) || [];
    if (sent.includes(match.match_id)) return;
    try {
      const resp = await fetch(`${WORKER_URL}/api/match-event`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ link_token: linkToken, match }),
      });
      if (resp.ok) { sent.push(match.match_id); await chrome.storage.local.set({ [SENT_KEY]: sent }); }
    } catch (e) { console.warn("[FaceitBot] матч:", e); }
    return;
  }

  // --- Скрап статистики ---
  if (data && data.__faceit_bot_stats === true) {
    const { type, payload } = data;
    if (!type || !payload) return;

    // Показываем на странице
    renderStatsBox(payload);
    // Кешируем локально для options/UI
    await chrome.storage.local.set({ [STATS_KEY]: payload });

    const linkToken = await getLinkToken();
    if (!linkToken) return;
    try {
      await fetch(`${WORKER_URL}/api/scrape-data`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ link_token: linkToken, type, payload }),
      });
    } catch (e) { console.warn("[FaceitBot] скрап:", e); }
    return;
  }
});

// === При вводе токена в options — verify-link, бот шлёт подтверждение ===
async function verifyLinkToken(token) {
  try {
    const resp = await fetch(`${WORKER_URL}/api/verify-link`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ link_token: token }),
    });
    const data = await resp.json();
    if (resp.ok && data.ok) {
      await chrome.storage.local.set({ [STORAGE_KEY]: token, [VERIFIED_KEY]: true });
      return { ok: true, nickname: data.nickname };
    }
    return { ok: false, error: data.error || "Токен не найден" };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

// Инициализация UI при загрузке (ждём DOM)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    injectUI();
    chrome.storage.local.get(STATS_KEY, (res) => {
      if (res[STATS_KEY]) renderStatsBox(res[STATS_KEY]);
    });
  });
} else {
  injectUI();
  chrome.storage.local.get(STATS_KEY, (res) => {
    if (res[STATS_KEY]) renderStatsBox(res[STATS_KEY]);
  });
}

async function getLinkToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(STORAGE_KEY, (res) => { resolve(res[STORAGE_KEY] || ""); });
  });
}
async function getSent() {
  return new Promise((resolve) => {
    chrome.storage.local.get(SENT_KEY, (res) => { resolve(res[SENT_KEY] || []); });
  });
}
