import type { Bootstrap, Engine, NarratorClient, RuntimeEvent } from "../types";
import { t } from "../i18n";
import { escape, icon, title, showError } from "../components/ui";

export function mountStudio(container: HTMLElement, client: NarratorClient) {
  let data: Bootstrap | null = null,
    busy = false,
    jobId = "",
    alive = true;
  const draftKey = "narrator.script";
  container.innerHTML =
    title("NARRATOR / STUDIO", t("studioTitle"), t("studioHint")) +
    `
 <div class="studio-grid"><section class="script-panel card"><div class="panel-heading"><span>${icon("align-left")}${t("script")}</span><span class="mini-badge">LOCAL</span></div>
 <textarea id="script-text" aria-label="${t("script")}" spellcheck="false" placeholder="${escape(t("placeholder"))}"></textarea><div class="script-footer"><span data-counter></span><span>${icon("shield-lock")}${t("local")}</span></div></section>
 <aside class="voice-panel card"><div class="panel-heading">${icon("adjustments-horizontal")}<span>${t("settings")}</span></div>
 <label for="engine">${t("engine")}</label><select id="engine"><option value="omnivoice">OmniVoice HQ</option><option value="qwen">Qwen3-TTS · 0.6B</option></select>
 <label for="voice">${t("voice")}</label><select id="voice"></select><label for="script-language">${t("language")}</label><select id="script-language"><option value="fr">Français</option><option value="en">English</option></select>
 <div data-omni><label for="speed">${t("speed")} <span data-speed>1.00×</span></label><input id="speed" type="range" min=".7" max="1.35" step=".05" value="1"><label for="quality">${t("quality")}</label><select id="quality"><option value="20">20 · Balanced</option><option value="24">24 · High</option><option value="32">32 · Maximum</option></select></div>
 <div class="setup-hint" data-setup>${icon("cpu")}${t("setup")}</div><div class="voice-decoration" aria-hidden="true"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div></aside></div>
 <section class="generation-bar card"><div class="job-summary"><span class="status-orb"></span><div><strong data-stage>${t("ready")}</strong><div class="progress-track"><div data-progress></div></div><small data-error role="status"></small></div></div><button class="btn btn-outline-secondary" data-cancel hidden>${t("cancel")}</button><button class="btn btn-primary generate-button" data-generate disabled>${icon("sparkles")}${t("generate")}</button></section><div data-result></div>`;
  const q = <T extends HTMLElement>(selector: string) =>
    container.querySelector<T>(selector)!;
  const text = q<HTMLTextAreaElement>("textarea"),
    engine = q<HTMLSelectElement>("#engine"),
    voice = q<HTMLSelectElement>("#voice"),
    button = q<HTMLButtonElement>("[data-generate]"),
    cancel = q<HTMLButtonElement>("[data-cancel]"),
    stage = q<HTMLElement>("[data-stage]");
  text.value = localStorage.getItem(draftKey) || "";
  function ready() {
    return (
      !!data &&
      (engine.value === "qwen"
        ? !!data.runtime.qwen_ready
        : !!data.runtime.python_exists && !!data.runtime.model_exists)
    );
  }
  function refresh() {
    button.disabled = busy || !ready() || !text.value.trim() || !voice.value;
    cancel.hidden = !busy;
    q("[data-setup]").hidden = ready();
    q("[data-omni]").hidden = engine.value === "qwen";
    q("[data-counter]").textContent =
      `${text.value.trim() ? text.value.trim().split(/\s+/).length : 0} ${t("words")} · ${text.value.length} ${t("characters")}`;
  }
  function voices() {
    const entries = engine.value === "qwen" ? data?.qwen_voices : data?.voices;
    voice.innerHTML =
      `<option value="">${t("selectVoice")}</option>` +
      (entries || [])
        .map(
          (v) =>
            `<option value="${escape(v.id || v.voice_id)}">${escape(v.name || v.id || v.voice_id)}</option>`,
        )
        .join("");
    if ((entries || []).length) voice.selectedIndex = 1;
    refresh();
  }
  text.oninput = () => {
    localStorage.setItem(draftKey, text.value);
    refresh();
  };
  engine.onchange = voices;
  voice.onchange = refresh;
  q<HTMLInputElement>("#speed").oninput = (event) => {
    q("[data-speed]").textContent =
      Number((event.target as HTMLInputElement).value).toFixed(2) + "×";
  };
  async function result(filename: string) {
    try {
      const url = await client.audioUrl(filename);
      if (!alive) return;
      const target = q("[data-result]");
      target.innerHTML = `<section class="result-card card"><div><span class="eyebrow">${t("complete")}</span><h3>${escape(filename)}</h3></div><audio controls preload="metadata"></audio><button class="btn btn-outline-secondary">${icon("download")}${t("export")}</button></section>`;
      target.querySelector("audio")!.src = url;
      target.querySelector("button")!.onclick = () => {
        void client
          .exportAudio(filename)
          .catch((e) => showError(q("[data-error]"), e));
      };
    } catch (error) {
      if (alive) showError(q("[data-error]"), error);
    }
  }
  const unsubscribe = client.subscribeRuntime((event: RuntimeEvent) => {
    if (!alive || event.event !== "job" || event.job_id !== jobId) return;
    busy = !!event.payload.running;
    stage.textContent = event.payload.stage || t("ready");
    q("[data-progress]").style.width =
      `${Math.max(0, Math.min(100, event.payload.progress || 0))}%`;
    q("[data-error]").textContent = event.payload.error || "";
    if (event.payload.result?.filename)
      void result(event.payload.result.filename);
    refresh();
  });
  button.onclick = async () => {
    if (button.disabled) return;
    busy = true;
    stage.textContent = t("preparing");
    q("[data-error]").textContent = "";
    refresh();
    try {
      const accepted = await client.generate({
        text: text.value,
        engine: engine.value as Engine,
        voice_id: voice.value,
        language: q<HTMLSelectElement>("#script-language").value,
        speed: Number(q<HTMLInputElement>("#speed").value),
        steps: Number(q<HTMLSelectElement>("#quality").value),
      });
      jobId = accepted.job_id;
    } catch (error) {
      busy = false;
      showError(q("[data-error]"), error);
      refresh();
    }
  };
  cancel.onclick = async () => {
    cancel.disabled = true;
    try {
      await client.cancelGenerate();
    } catch (error) {
      showError(q("[data-error]"), error);
    } finally {
      cancel.disabled = false;
    }
  };
  void client
    .bootstrap()
    .then((value) => {
      if (!alive) return;
      data = value;
      engine.value = value.active_engine || "omnivoice";
      busy = !!value.job?.running;
      jobId = value.job_id || "";
      stage.textContent = value.job?.stage || t("ready");
      q("[data-progress]").style.width =
        `${Math.max(0, Math.min(100, value.job?.progress || 0))}%`;
      q("[data-error]").textContent = value.job?.error || "";
      if (value.job?.result?.filename) void result(value.job.result.filename);
      voices();
    })
    .catch((error) => {
      if (alive) showError(q("[data-error]"), error);
    });
  refresh();
  return () => {
    alive = false;
    unsubscribe();
  };
}
