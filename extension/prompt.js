// Показываем токен, кнопка копирует в буфер и открывает бота.

const BOT_USERNAME = "csgo_faceit_stats_bot";
const STORAGE_KEY = "faceit_token";

function $(id) { return document.getElementById(id); }

async function loadToken() {
  // Из storage.session (MV3)
  try {
    const res = await chrome.storage.session.get(STORAGE_KEY);
    const tok = res && res[STORAGE_KEY];
    if (tok) {
      $("token").value = tok;
      await tryCopyAndOpen(tok);
      return;
    }
  } catch (e) {}

  // Фолбэк: читаем из URL ?t=... (если background прислал так)
  const u = new URLSearchParams(location.search);
  const fromUrl = u.get("t");
  if (fromUrl) {
    $("token").value = fromUrl;
    await tryCopyAndOpen(fromUrl);
  }
}

async function tryCopyAndOpen(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch (e) {
    $("token").select();
    document.execCommand("copy");
  }
  // Открываем чат бота
  setTimeout(() => {
    window.open(`https://t.me/${BOT_USERNAME}`, "_blank");
  }, 300);
}

$("copy").addEventListener("click", async () => {
  const tok = $("token").value;
  if (!tok) return;
  try {
    await navigator.clipboard.writeText(tok);
    window.open(`https://t.me/${BOT_USERNAME}`, "_blank");
  } catch (e) {
    $("token").select();
    document.execCommand("copy");
    window.open(`https://t.me/${BOT_USERNAME}`, "_blank");
  }
});

loadToken();
