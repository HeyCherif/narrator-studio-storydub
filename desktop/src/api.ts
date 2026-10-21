import { invoke, convertFileSrc, isTauri } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import type {
  NarratorClient,
  RuntimeEvent,
  DownloadSnapshot,
  Bootstrap,
  GenerateRequest,
  HistoryEntry,
  Voice,
} from "./types";

export async function createClient(): Promise<NarratorClient> {
  const native = isTauri();
  const runtime = new Set<(v: RuntimeEvent) => void>(),
    downloads = new Set<(v: DownloadSnapshot[]) => void>();
  const recent = new Map<string, RuntimeEvent>();
  if (native) {
    await listen<RuntimeEvent>("runtime:event", (e) => {
      recent.set(e.payload.job_id, e.payload);
      if (recent.size > 16) recent.delete(recent.keys().next().value!);
      runtime.forEach((fn) => fn(e.payload));
    });
    await listen<DownloadSnapshot[]>("downloads:changed", (e) =>
      downloads.forEach((fn) => fn(e.payload)),
    );
  }
  const request = <T>(command: string, payload: unknown = {}): Promise<T> =>
    native
      ? invoke("runtime_request", { command, payload })
      : Promise.reject(
          new Error(
            "Ouvrez l’application Windows pour utiliser les moteurs locaux.",
          ),
        );
  async function start(command: string, payload: unknown) {
    const result = await request<{ job_id: string }>(command, payload);
    setTimeout(() => {
      const cached = recent.get(result.job_id);
      if (cached) runtime.forEach((fn) => fn(cached));
    }, 0);
    return result;
  }
  return {
    preview: !native,
    bootstrap: () =>
      native
        ? request<Bootstrap>("bootstrap")
        : Promise.resolve({
            active_engine: "omnivoice",
            voices: [],
            runtime: {},
          }),
    generate: (payload: GenerateRequest) => start("generate", payload),
    cancelGenerate: () => request("cancel_generate"),
    subscribeRuntime: (fn) => {
      runtime.add(fn);
      return () => runtime.delete(fn);
    },
    voices: () =>
      native
        ? request<{ omnivoice: Voice[]; qwen: Voice[] }>("voices")
        : Promise.resolve({ omnivoice: [], qwen: [] }),
    cloneVoice: (payload) => start("clone_voice", payload),
    history: () =>
      native ? request<HistoryEntry[]>("history") : Promise.resolve([]),
    audioUrl: async (filename) =>
      convertFileSrc(await invoke<string>("audio_path", { filename })),
    exportAudio: (filename) => invoke("export_audio", { filename }),
    openHistoryFolder: () => invoke("open_history_folder"),
    adoptLegacyLibrary: () => invoke("adopt_library"),
    choosePath: (kind) => invoke("choose_path", { kind }),
    configure: (value) => request("configure", value),
    downloads: () =>
      native ? invoke("download_snapshot") : Promise.resolve([]),
    downloadAction: (action, id) => invoke("download_action", { action, id }),
    subscribeDownloads: (fn) => {
      downloads.add(fn);
      return () => downloads.delete(fn);
    },
  };
}
