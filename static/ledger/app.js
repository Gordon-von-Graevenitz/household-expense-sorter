document.addEventListener("DOMContentLoaded", () => {
  const ratio = document.querySelector("#split-ratio");
  if (ratio) {
    const a = document.querySelector("[data-ratio-a]");
    const b = document.querySelector("[data-ratio-b]");
    ratio.addEventListener("input", () => {
      a.textContent = ratio.value;
      b.textContent = String(100 - Number(ratio.value));
    });
  }

  const tabs = [...document.querySelectorAll("[data-tab]")];
  const reviewPanel = document.querySelector("#review-panel");
  const settlementPanel = document.querySelector("#settlement-panel");
  const selectTab = (name) => {
    tabs.forEach((tab) => tab.setAttribute("aria-selected", String(tab.dataset.tab === name)));
    reviewPanel.hidden = name !== "review";
    settlementPanel.hidden = name !== "settlement";
  };
  tabs.forEach((tab) => tab.addEventListener("click", () => selectTab(tab.dataset.tab)));
  document.querySelector("[data-open-settlement]")?.addEventListener("click", () => selectTab("settlement"));

  document.querySelectorAll("input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      const label = input.closest(".file-drop")?.querySelector("strong");
      if (label && input.files.length) label.textContent = input.files[0].name;
    });
  });
});
