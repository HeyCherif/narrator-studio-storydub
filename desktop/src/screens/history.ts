import type { NarratorClient, HistoryEntry } from "../types";
import { t } from "../i18n";
import { escape, icon, title, showError } from "../components/ui";
export function mountHistory(container: HTMLElement, client: NarratorClient) {
  let alive = true,
    entries: HistoryEntry[] = [];
  container.innerHTML =
    title("NARRATOR / ARCHIVE", t("historyTitle"), t("historyHint")) +
    `<div class="toolbar"><input class="form-control" aria-label="${t("search")}" placeholder="${t("search")}"><button class="btn btn-outline-secondary" data-folder>${icon("folder")}${t("folder")}</button></div><p data-error role="status"></p><div class="history-list"></div>`;
  const list = container.querySelector<HTMLElement>(".history-list")!,
    error = container.querySelector<HTMLElement>("[data-error]")!;
  function render() {
    const query = container.querySelector("input")!.value.toLocaleLowerCase();
    const filtered = entries.filter((e) =>
      (e.text + " " + e.filename + " " + e.voice_name)
        .toLocaleLowerCase()
        .includes(query),
    );
    list.innerHTML = filtered.length
      ? filtered
          .map(
            (e, i) =>
              `<article class="history-card card"><div class="history-icon">${icon(e.available === false ? "file-off" : "wave-sine")}</div><div class="history-copy"><h3>${escape(e.voice_name || e.filename)}</h3><p>${escape(e.text || e.filename)}</p><small>${escape(e.engine || "")} · ${escape(e.created_at || "")}</small></div>${e.available === false ? `<span class="mini-badge">${t("unavailable")}</span>` : `<button class="btn btn-outline-secondary" data-play="${i}" aria-label="${t("listen")} ${escape(e.filename)}">${icon("player-play")}</button><button class="btn btn-outline-secondary" data-export="${i}" aria-label="${t("export")} ${escape(e.filename)}">${icon("download")}</button>`}</article>`,
          )
          .join("")
      : `<div class="empty-state">${icon("headphones")}<h3>${t("emptyHistory")}</h3></div>`;
    list.querySelectorAll<HTMLButtonElement>("[data-play]").forEach(
      (b) =>
        (b.onclick = async () => {
          try {
            const url = await client.audioUrl(
              filtered[Number(b.dataset.play)].filename,
            );
            if (!alive) return;
            list.querySelectorAll("audio").forEach((a) => a.remove());
            const audio = document.createElement("audio");
            audio.controls = true;
            audio.src = url;
            b.parentElement!.append(audio);
            await audio.play();
          } catch (e) {
            if (alive) showError(error, e);
          }
        }),
    );
    list.querySelectorAll<HTMLButtonElement>("[data-export]").forEach(
      (b) =>
        (b.onclick = () => {
          void client
            .exportAudio(filtered[Number(b.dataset.export)].filename)
            .catch((e) => showError(error, e));
        }),
    );
  }
  container.querySelector("input")!.oninput = render;
  container.querySelector<HTMLButtonElement>("[data-folder]")!.onclick = () => {
    void client.openHistoryFolder().catch((e) => showError(error, e));
  };
  void client
    .history()
    .then((data) => {
      if (alive) {
        entries = data;
        render();
      }
    })
    .catch((e) => {
      if (alive) showError(error, e);
    });
  return () => {
    alive = false;
    container.querySelectorAll("audio").forEach((a) => a.pause());
  };
}
