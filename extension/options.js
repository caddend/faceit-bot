const WORKER_URL = "https://polished-mouse-4c9d.mishashlikov216.workers.dev";
const STORAGE_KEY = "faceit_bot_link_token";
const VERIFIED_KEY = "faceit_bot_verified";

function $(id) { return document.getElementById(id); }

chrome.storage.local.get([STORAGE_KEY, VERIFIED_KEY], (res) => {
  $("token").value = res[STORAGE_KEY] || "";
  if (res[VERIFIED_KEY]) $("ok").textContent = "Привязано. Открой faceit.com — расширение работает.";
});

$("save").addEventListener("click", async () => {
  const token = $("token").value.trim();
  if (!token) return;

  $("ok").style.display = "none";
  $("save").textContent = "Проверка...";

  try {
    const resp = await fetch(`${WORKER_URL}/api/verify-link`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ link_token: token }),
    });
    const data = await resp.json();
    if (resp.ok && data.ok) {
      await chrome.storage.local.set({ [STORAGE_KEY]: token, [VERIFIED_KEY]: true });
      $("ok").textContent = `Привязано к ${data.nickname}. Бот пришлёт подтверждение в Telegram.`;
      $("ok").style.display = "block";
      setTimeout(() => window.close(), 1500);
    } else {
      $("ok").textContent = `Ошибка: ${data.error || "токен не найден"}`;
      $("ok").style.display = "block";
    }
  } catch (e) {
    $("ok").textContent = `Сеть: ${e}`;
    $("ok").style.display = "block";
  }
  $("save").textContent = "Сохранить";
});
