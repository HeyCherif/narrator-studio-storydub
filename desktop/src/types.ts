export type Engine = "omnivoice" | "qwen";
export interface Voice {
  id?: string;
  voice_id?: string;
  name?: string;
  language?: string;
  prompt_exists?: boolean;
  reference_exists?: boolean;
}
export interface HistoryEntry {
  id?: string;
  filename: string;
  text?: string;
  voice_name?: string;
  engine?: string;
  created_at?: string;
  duration?: number;
  duration_seconds?: number;
  available?: boolean;
}
export interface Job {
  running?: boolean;
  stage?: string;
  progress?: number;
  error?: string;
  result?: HistoryEntry;
}
export interface RuntimeEvent {
  event: string;
  job_id: string;
  payload: Job;
}
export interface Bootstrap {
  version?: string;
  library_root?: string;
  active_engine: Engine;
  voices: Voice[];
  qwen_voices?: Voice[];
  job_id?: string;
  job?: Job;
  runtime: {
    python_exists?: boolean;
    model_exists?: boolean;
    qwen_ready?: boolean;
    qwen_python_exists?: boolean;
    qwen_model_exists?: boolean;
    [key: string]: unknown;
  };
}
export interface DownloadSnapshot {
  id: string;
  state: string;
  bytes_done: number;
  total_bytes: number | null;
  speed_bps: number | null;
  eta_seconds: number | null;
  error?: string;
  model?: string;
}
export interface GenerateRequest {
  text: string;
  engine: Engine;
  voice_id: string;
  language: string;
  speed?: number;
  steps?: number;
}
export interface NarratorClient {
  preview?: boolean;
  bootstrap(): Promise<Bootstrap>;
  generate(value: GenerateRequest): Promise<{ job_id: string }>;
  cancelGenerate(): Promise<unknown>;
  subscribeRuntime(fn: (event: RuntimeEvent) => void): () => void;
  voices(): Promise<{ omnivoice: Voice[]; qwen: Voice[] }>;
  cloneVoice(payload: {
    name: string;
    language: string;
    filename: string;
    audio_base64: string;
  }): Promise<{ job_id: string }>;
  history(): Promise<HistoryEntry[]>;
  audioUrl(filename: string): Promise<string>;
  exportAudio(filename: string): Promise<unknown>;
  openHistoryFolder(): Promise<unknown>;
  adoptLegacyLibrary(): Promise<boolean>;
  choosePath(kind: string): Promise<string | null>;
  configure(value: Record<string, string>): Promise<unknown>;
  downloads(): Promise<DownloadSnapshot[]>;
  downloadAction(action: string, id?: string): Promise<unknown>;
  subscribeDownloads(fn: (value: DownloadSnapshot[]) => void): () => void;
}
