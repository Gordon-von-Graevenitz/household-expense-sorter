document.addEventListener("DOMContentLoaded", () => {
  const transactionScrollKey = "household-split:transaction-scroll";
  const savedTransactionScroll = sessionStorage.getItem(transactionScrollKey);
  if (savedTransactionScroll) {
    sessionStorage.removeItem(transactionScrollKey);
    try {
      const saved = JSON.parse(savedTransactionScroll);
      requestAnimationFrame(() => requestAnimationFrame(() => {
        const row = document.getElementById(saved.rowId);
        if (row && Number.isFinite(saved.rowTop)) {
          window.scrollBy(0, row.getBoundingClientRect().top - saved.rowTop);
        } else if (Number.isFinite(saved.scrollY)) {
          window.scrollTo(0, saved.scrollY);
        }
      }));
    } catch (_error) {
      sessionStorage.removeItem(transactionScrollKey);
    }
  }

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

  document.querySelectorAll("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (!window.confirm(form.dataset.confirm)) event.preventDefault();
    });
  });

  document.querySelectorAll("form[data-preserve-scroll]").forEach((form) => {
    form.addEventListener("submit", () => {
      const row = form.closest("[data-transaction-row]");
      sessionStorage.setItem(transactionScrollKey, JSON.stringify({
        rowId: row?.id,
        rowTop: row?.getBoundingClientRect().top,
        scrollY: window.scrollY,
      }));
    });
  });

  const cleanSpreadsheetCell = (value) => String(value ?? "").replace(/[\t\r\n]+/g, " ").trim();

  const copyText = async (value) => {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = value;
    textarea.setAttribute("readonly", "");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    document.body.appendChild(textarea);
    textarea.select();
    const copied = document.execCommand("copy");
    textarea.remove();
    if (!copied) throw new Error("Clipboard copy was not available.");
  };

  document.querySelectorAll("[data-copy-table]").forEach((button) => {
    button.addEventListener("click", async () => {
      const table = document.getElementById(button.dataset.copyTable);
      const rows = [...(table?.querySelectorAll("[data-export-row]") ?? [])];
      const status = button.closest(".copy-sheets-control")?.querySelector(".copy-sheets-status");

      if (!rows.length) {
        if (status) status.textContent = "No included rows to copy.";
        return;
      }

      const spreadsheetText = rows
        .map((row) => [
          row.dataset.exportDate,
          row.dataset.exportCategory,
          row.dataset.exportDetails,
          row.dataset.exportAmount,
        ].map(cleanSpreadsheetCell).join("\t"))
        .join("\n");

      try {
        await copyText(spreadsheetText);
        if (status) status.textContent = `Copied ${rows.length} included ${rows.length === 1 ? "row" : "rows"}.`;
      } catch (_error) {
        if (status) status.textContent = "Could not copy. Please allow clipboard access and try again.";
      }
    });
  });
});
