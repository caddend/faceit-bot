const STORAGE_KEY = "faceit_bot_link_token";

function $(id) { return document.getElementById(id); }

chrome.storage.local.get(STORAGE_KEY, (res) => {
  $("token").value = res[STORAGE_KEY] || "";
});

$("save").addEventListener("click", () => {
  const token = $("token").value.trim();
  chrome.storage.local.set({ [STORAGE_KEY]: token }, () => {
    $("ok").style.display = "block";
    setTimeout(() => window.close(), 1200);
  });
});
