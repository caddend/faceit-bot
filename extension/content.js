// Content script (изолированный мир). Инжектит inject.js в main-world страницы,
// чтобы перехватить fetch/XHR к api.faceit.com. Принимает матч через postMessage
// и POST'ит его на Worker (endpoint /api/match-event).

const WORKER_URL = "https://polished-mouse-4c9d.mishashlikov216.workers.dev";
const STORAGE_KEY = "faceit_bot_link_token";
const SENT_KEY = "faceit_bot_sent_matches"; // дедуп: match_id, уже отправленные

(function inject() {
  const s = document.createElement("script");
  s.src = chrome.runtime.getURL("inject.js");
  s.onload = () => s.remove();
  (document.head || document.documentElement).appendChild(s);
})();

// postMessage из inject.js (main world) → сюда
window.addEventListener("message", async (ev) => {
  if (ev.source !== window) return;
  const data = ev.data;
  if (!data || data.__faceit_bot !== true) return;

  const match = data.match;
  if (!match || !match.match_id) return;

  const linkToken = await getLinkToken();
  if (!linkToken) {
    console.warn("[FaceitBot] link_token не задан — открой настройки расширения (клик по иконке).");
    return;
  }

  // Дедуп локально — не шлём один матч дважды за сессию
  const sent = (await getSent()) || [];
  if (sent.includes(match.match_id)) return;

  try {
    const resp = await fetch(`${WORKER_URL}/api/match-event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ link_token: linkToken, match }),
    });
    if (resp.ok) {
      sent.push(match.match_id);
      await chrome.storage.local.set({ [SENT_KEY]: sent });
      console.log("[FaceitBot] матч отправлен боту:", match.match_id);
    }
  } catch (e) {
    console.warn("[FaceitBot] не удалось отправить матч:", e);
  }
});

async function getLinkToken() {
  return new Promise((resolve) => {
    chrome.storage.local.get(STORAGE_KEY, (res) => {
      resolve(res[STORAGE_KEY] || "");
    });
  });
}

async function getSent() {
  return new Promise((resolve) => {
    chrome.storage.local.get(SENT_KEY, (res) => {
      resolve(res[SENT_KEY] || []);
    });
  });
}
