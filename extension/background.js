// Перехватываем Authorization: Bearer ... из запросов к api.faceit.com
// (cookie t HttpOnly/переименована, поэтому только так). Сохраняем токен,
// по клику на иконку открываем prompt.html, который копирует токен и ведёт к боту.

const FACEIT_API_HOST = "api.faceit.com";
const BOT_USERNAME = "csgo_faceit_stats_bot";
const STORAGE_KEY = "faceit_token";

let latestToken = null;

// На старте worker'а восстанавливаем из storage
chrome.storage?.session?.get?.(STORAGE_KEY).then((res) => {
  if (res && res[STORAGE_KEY]) latestToken = res[STORAGE_KEY];
}).catch(() => {});

function saveToken(token) {
  latestToken = token;
  chrome.storage?.session?.set?.({ [STORAGE_KEY]: token }).catch(() => {});
}

// === Перехват заголовков запросов к api.faceit.com ===
chrome.webRequest?.onBeforeSendHeaders?.addListener(
  (details) => {
    const url = details.url || "";
    if (!url.includes(FACEIT_API_HOST)) return;

    const headers = details.requestHeaders || [];
    for (const h of headers) {
      const name = (h.name || "").toLowerCase();
      if (name === "authorization") {
        const val = h.value || "";
        const m = val.match(/Bearer\s+(.+)/i);
        if (m && m[1] && m[1].length > 20) {
          const tok = m[1].trim();
          if (tok !== latestToken) saveToken(tok);
        }
        break;
      }
    }
  },
  { urls: ["https://api.faceit.com/*"] },
  ["requestHeaders"]
);

// Клик на иконку расширения
chrome.action.onClicked.addListener(async (tab) => {
  if (!latestToken) {
    try {
      const res = await chrome.storage?.session?.get?.(STORAGE_KEY);
      if (res && res[STORAGE_KEY]) latestToken = res[STORAGE_KEY];
    } catch {}
  }

  if (!latestToken) {
    // Токена нет — открываем faceit.com, чтобы залогинился и породил запросы.
    // После логина кликни по иконке расширения снова.
    await chrome.tabs.create({ url: "https://www.faceit.com/" });
    try {
      await chrome.action.setTitle?.({ title: "Логинься на faceit.com, потом кликни снова" });
    } catch {}
    return;
  }

  // Открываем нашу страницу — она копирует токен в буфер и ведёт к боту.
  await chrome.tabs.create({
    url: chrome.runtime.getURL(`prompt.html?t=${encodeURIComponent(latestToken)}`),
  });
});
