// CloudBrowser test extension: proves extensions load in the remote browser.
// Runs on every page: marks the document and adds a small badge.
(function () {
  document.documentElement.setAttribute("data-cb-ext", "loaded");
  if (document.getElementById("cb-ext-badge")) return;
  var badge = document.createElement("div");
  badge.id = "cb-ext-badge";
  badge.textContent = "CloudBrowser Ext ON";
  badge.style.cssText = "position:fixed;right:8px;bottom:8px;z-index:2147483647;"
    + "background:#16a34a;color:#fff;font:12px sans-serif;padding:4px 8px;"
    + "border-radius:4px;pointer-events:none;";
  (document.body || document.documentElement).appendChild(badge);
})();
