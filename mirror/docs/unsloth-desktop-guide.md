# Unsloth Desktop on pc-host — capability map and setup guide

2026-09-23. Scope: Unsloth Desktop 0.1.815-beta on pc-host (Windows 11 Pro, RTX 4060 Ti 8 GB = 8188 MiB, i5-12600KF, 47.8 GB RAM, Docker Desktop stack alongside with a 28 GB WSL cap).

How this was built:
- Six research agents read the installed source (the authority for 0.1.815-beta), unsloth.ai/docs and GitHub, without touching the running server.
- A second, adversarial pass checked every claim, and its corrections are applied.
- Live results from OP UNSLOTH ALPHA (same day; `handoffs/2026-09-09-op-unsloth-migration-plan.md` §6, evidence in `deliverables/evidence/2026-09-23-op-unsloth-alpha/`) replace research inferences wherever they differ. Those places are marked **(ALPHA)**.
- Anything inferred or not probed is marked **(unverified)** or **(inferred)**.
- Citation prefixes (`B/`, `F/`, `GH815/`, `D/`) are defined in the Sources section.

## Bottom line

- **Unsloth Desktop can take over LM Studio's job on this box.** Every chosen model gets a pinned, persistent config: the saved per-model row that Unsloth applies whenever a request names the model. `scripts/unsloth-model-config.py` plans that row from the model file and free VRAM, writes it, and verifies it with a real load **(ALPHA: qwen3.5-4b and ministral-3b done)**. The Chat load panel's "Remember for this model" writes the same row.
- **Keep "Switch model by request" ON** (the operator's setting). Saved rows only apply to loads that Unsloth starts itself, and LiteLLM will need the switch later. One cost: a keyed request that names a different model replaces the resident one.
- **Keyless access** (ruling: ON) works for local processes that call `127.0.0.1` or `localhost` without an Origin header. Browser and Electron clients, possibly Msty, are refused (7.2, 8.3). It also works for any Docker container that sets `Host: localhost` **(ALPHA p27)**. Keyless callers get inference only: no tools, no model switching. LiteLLM must use an `sk-unsloth(-)` key, because only keyed callers auto-switch.
- **Keep ≥1 GiB of VRAM free.** After Unsloth's default auto-fit loads, ALPHA measured only 661–689 MiB free, with ~0.7 GiB spilled to shared memory, and qwen decode swung between ~7 and 55 tok/s (medians 12.7–21.7). A pinned per-model context avoids that.
- **Hugging Face:** UI-session downloads use your user `HF_TOKEN`. The account is `clduab11` (checked with `hf auth whoami` after ALPHA), and the running Unsloth backend has the variable. Gated downloads are untested. API-key and keyless callers never use it. **Pushing to the Hub needs a write token saved in Unsloth's Settings**; Export never falls back to `HF_TOKEN`.
- **Kaggle** has **no** integration in Unsloth. Kaggle notebooks → HF Hub → Unsloth is the path.
- **In-app fine-tuning** covers the SFT family (QLoRA, LoRA, full, continued pretraining) for text, vision, audio and embeddings, plus diffusion LoRA. There is no GRPO or DPO; those run on Kaggle. On 8 GB, QLoRA up to about 4B is comfortable and 7–9B is borderline.
- **Security items:**
  - The tool permission mode: never "Run automatically" or "Full access".
  - Two plaintext files: `auth/.desktop_secret` and `auth/.bootstrap_password`.
  - Before any LiteLLM route moves to Unsloth, a LiteLLM pre-call hook must strip Unsloth's tool, permission and `provider_*` fields. LiteLLM forwards 28 of 29 of them in `extra_body` (ALPHA p17); `provider_*` would make Unsloth call an outside provider. See 7.1.

---

## 1. What Unsloth Desktop is on this box

| Component | Value | Evidence |
|---|---|---|
| Desktop shell | 0.1.815-beta (Tauri app, NSIS install under `%LOCALAPPDATA%\Unsloth Studio (Desktop)`) | HKCU Uninstall DisplayVersion; `GH815/studio/src-tauri` |
| Backend | Python package `unsloth` 2026.9.11 in the venv `~/.unsloth/studio/unsloth_studio`. The shell bakes this in as a **floor** (`UNSLOTH_DESKTOP_BACKEND_VERSION`), not a pin. | exe strings; `GH815/studio/src-tauri/src/preflight/version.rs:176-177` |
| Inference engine | llama.cpp `b11115-mix-a6922cc`, bundle `cuda13-older`, from Unsloth's fork `unslothai/llama.cpp` (not ggml-org upstream), in `~/.unsloth/llama.cpp` | `~/.unsloth/llama.cpp/UNSLOTH_PREBUILT_INFO.json` |
| API | `http://127.0.0.1:8888`. Plain HTTP, loopback only. 8888 is the default, and the pid files show earlier backends on 8888. If 8888 is taken, the shell moves up to 8889–8908, so confirm the port in Settings > API. | `B/run.py:872,961,2524-2541`; `GH815/studio/src-tauri/src/desktop_backend_owner.rs:27-28` |
| Data root | `~/.unsloth/studio` | `B/utils/paths/storage_roots.py:230-340` |

**How it runs.** The shell starts `unsloth studio --api-only -H 127.0.0.1 -p <port>` and shows the UI in its own webview. The port serves no web UI. The backend exits if the shell dies. Close-to-tray is ON on this box, so closing the window keeps the API up. Quitting from the tray takes it down. Launch at login is OFF (`GH815/studio/src-tauri/src/process.rs:3494-3506`; `B/utils/parent_watchdog.py:20`; `%APPDATA%\ai.unsloth.studio\close-to-tray-v1`).

**the operator's starting position.** He removed most LM Studio models on purpose. LM Studio keeps three models for the Locally iPhone app. New local models will be chosen and downloaded inside Unsloth.

**Training stack in the venv.** These versions were read from dist-info folders and not re-checked separately: torch 2.11.0+cu130, transformers 5.5.0 (plus per-family sidecar venvs `.venv_t5_530`, `_550`, `_510` that the worker activates automatically), trl 0.23.1, peft 0.18.1, bitsandbytes 0.50.2, xformers 0.0.35, datasets 4.3.0, unsloth_zoo 2026.9.7, huggingface_hub 1.31.0, hf_xet 1.6.0, triton_windows 3.6.0.post26.

**Settings tab names in 0.1.815.** Use these; some docs use older ones. General, Profile, Appearance, **System** (internal id `resources`), Chat, API, **Remote & LAN**, Connections, Accounts, Agents, Voice, Data, Shortcuts, **Logs** (internal id `debugging`), About (`GH815/studio/frontend/src/features/settings/settings-dialog.tsx:187-254`).

---

## 2. Capability map

"Where" gives the UI path first, then the API route. All routes live on the backend port. "Notes" apply to this box.

### 2.1 Inference and models

| Feature | What it does | Where (UI / API) | Notes for this box |
|---|---|---|---|
| Hub search and download | Search runs in the webview straight against the HF API. The backend downloads a repo plus one GGUF quant, or a safetensors snapshot, over Xet or HTTPS, into the HF cache (`~/.cache/huggingface/hub`). | Hub page. `POST /api/hub/download {repo_id, gguf_variant, transport_mode}`; `GET /api/hub/download-status`; `POST /api/hub/download/cancel`; `GET /api/hub/gguf-variants` | Use GGUF. MLX repos cannot run on Windows/CUDA. Safetensors models load through Transformers in 4-bit by default, and most tuning knobs are GGUF-only. On Windows an interrupted HTTPS download restarts the file from zero (see 2.3). |
| Other model folders | On every scan, reads LM Studio's download folder (`downloadsFolder` in `~/.lmstudio/settings.json`, `~/.lmstudio/models`, `~/.cache/lm-studio/models`), Ollama, Hermes and any custom folders. Files are used where they are. | Model picker folder button; `GET/POST/DELETE /api/models/scan-folders` | The 3 LM Studio models kept for the iPhone will appear here and can be loaded. No setting excludes the LM Studio folder. Unsloth can delete only HF-cache models, so it cannot remove them. `/v1/models` shows clean ids, not paths. |
| Chat page load and eject | Model picker with Load model, Reload model and Eject model, a load panel, and "Remember for this model". Also Model Arena (loads one model, then the other), the Thinking toggle, web search, code execution, tool-call healing, attachments and an API monitor. | Chat page. `POST /load`, `POST /unload`, `GET /status`, `GET /load-progress`, `POST /estimate-memory`, `GET /llama-flags`, mounted under both `/api/inference` and `/v1` | Holds one chat GGUF at a time; loading another replaces it. A load while chats are generating returns 409 unless `force_cancel_active` is set. Training, image generation and video generation evict the chat model even with Keep resident on. |
| Per-model load settings | Context, KV type, GPU memory mode, GPU layers, MoE layers on CPU, parallel slots, batch and ubatch, speculative decoding, load mode, context checkpoints, prompt-cache RAM, vision off, chat template, reasoning budget, extra llama.cpp arguments. | Chat load panel; LoadRequest body | Recommended values are in 3.4. |
| Saved per-model config | "Remember for this model" saves to browser localStorage and copies the row to the server (app setting `openai_api_auto_switch_overrides` in `studio.db`), separately for each model and each quant. | Load panel toggle; `GET/PUT /api/settings/openai-auto-switch/overrides` | Only loads that Unsloth starts itself read the server row (3.3). |
| Auto-switch, auto-download, idle unload | "Switch model by request" loads the downloaded model that a /v1 request names, using its saved row. "Download missing models" fetches a named GGUF repo. "Idle auto-unload" takes seconds (minimum 60, 0 = never). All three are off by default. | Settings > API > Model auto-switch; `PUT /api/settings/openai-auto-switch` | Keep resident blocks idle unload but **not** a switch. With the switch on, a keyed request that names another model evicts the resident one. Keyless callers can never switch or download. |
| Model memory | "Keep model in GPU memory" vetoes idle unload and mlocks whatever part of the model sits in host RAM. "Don't reserve system RAM for the model" drops mlock and no-mmap, and uses DirectIO on Windows when the model is fully offloaded to the GPU. | Settings > System > Model memory; `PUT /api/settings/model-memory` | Both ON since 2026-09-23 (the operator). With Keep resident alone, any load that does not fit wholly on the GPU runs `--load-mode mmap+mlock` and pins the whole file: LFM2.5 took 5.3 GB of host RAM for 574 MiB of CPU experts. No-reserve drops the lock and keeps experts on the pageable mapping; fully offloaded loads switch to `--load-mode dio`. Keep resident still blocks idle unload. Both apply from the next load. |
| VRAM budget | The fraction of each GPU a load may use in Auto mode. Range 0.80–1.00, default 0.97. Also shifts `--fit-target`. | Settings, VRAM Budget slider; `PUT /api/settings/vram-budget` | Stored **0.95** since 2026-09-23 (the operator; revisit at the performance evaluation). Unsloth takes the reserve off nvidia-smi's `memory.free`, which already leaves out the driver's reserved 239 MiB. The script and every ALPHA figure count free as total − used, so by that measure a budget keeps its reserve + 239 MiB: 0.97–0.98 ~485 MiB, 0.95 ~648, **0.904 ~1,025 (the 1 GiB rule)**, 0.875 ~1,263 (`B/core/inference/llama_cpp.py` `_vram_usable_mib`, source-read 09-23). ALPHA measured 661–689 MiB free after auto-fit loads at 0.98, ~190 MiB above that floor. The reserve comes off free VRAM, so other GPU processes shrink it further. |
| OpenAI- and Anthropic-compatible API | `/v1/chat/completions`, `/completions`, `/responses`, `/embeddings`, `/messages`, `/messages/count_tokens`, `/chat/count_tokens`, `/audio/speech`, `/audio/transcriptions`, `/audio/generate`, `/images/generations`, `/videos`, `/models`, `/models/{id}`, plus `/props`, `/v1/props` and `/version`. | Base URL `http://127.0.0.1:8888/v1` | No Ollama `/api/tags`. Server-side tools run only if a request sets `enable_tools`, because the Desktop launch installs no tools default. |
| `/v1/models` and substitution | Lists the loaded model plus the local catalog, each with a `loaded` flag. With the switch off, a downloaded but unloaded name returns 404 `model_not_found`. A name the server does not recognise at all is **answered by the loaded model**. `response.model` always carries the loaded model's public id. | — | Always check `response.model`, but its form varies **(ALPHA §6.3)**: the repo id on plain chat, the directory basename on tool calls, the file stem after a path load, and never `:QUANT`. Strip `:QUANT` and accept all three. Bare foreign names, including today's `mistralai/ministral-3-3b` route string, get HTTP 200 from the resident model (p2, p18), so use explicit `repo:QUANT` ids. `system_fingerprint` can appear on passthrough paths; its value was not captured **(unverified)**. Never use it for identity. |
| Sampling defaults for API callers | For any field a /v1 client omits, the server fills in: the model's own YAML, then family defaults, then temperature 0.6, top_p 0.95, top_k 20, min_p 0.01. `UNSLOTH_SAMPLING_*` environment pins override even values the client sent. | Environment variables | `/v1/completions` does not fill these in. UI chat presets never reach API callers, so have LiteLLM send sampling values. |
| Context overflow | By default a request that overflows gets a 400 `context_length_exceeded` (`--no-context-shift`). A request may opt into `context_overflow: truncate_middle` or `truncate_oldest`. `UNSLOTH_CONTEXT_OVERFLOW` changes the default. | Request field | The clean error is useful for LiteLLM fallback chains. |
| Embeddings | `/v1/embeddings` goes to the configured embedder (default `unsloth/bge-small-en-v1.5`, 384 dims per its model card) when the request names it or no GGUF is loaded. Otherwise it goes to the loaded GGUF, if that model can pool. | Settings > General > embedding model; `PUT /api/settings/embedding-model` | `legacy/embed` does NOT move to Unsloth. Per plan D1 and the §6.6 BRAVO spec it goes to a CPU-only `praxen-embed` container, because Unsloth's embedder refuses inputs over its 512-token micro-batch. Leave Unsloth's embedder at its CPU default (bge-small, 384 dims). A GGUF embedder would take the GPU whenever ≥1024 MiB is free, which is exactly the reserve the saved rows keep. With the switch on, never send a different embedder name: it evicts the chat model and then errors. |
| Vision, audio, image, video | Vision GGUFs load their mmproj file automatically, and `disable_vision` runs them text-only to save VRAM. Text-to-speech, speech-to-text (whisper sidecar), image generation and video generation have their own pages and endpoints. | Chat, Images, Video and Audio pages | All compete for the 8 GB card. Image and video generation evict the chat model (2.5). |
| Sizing helpers | Estimate memory and KV cache before saving a config. | `POST /api/inference/estimate-memory`; `GET /api/models/kv-cache-estimate`, `/api/models/check-vision/{model}`, `/api/models/check-embedding/{model}` | Use these before picking a context length. |
| Delete models | Deletes a cached HF model and previews the bytes reclaimed. | Hub bin icon; `DELETE /api/hub/delete-cached`; `POST /api/hub/delete-impact`; `GET /api/hub/orphan-companions` | Works on HF-cache models only. |
| External providers | Chat can use outside providers, including a custom OpenAI-compatible base URL, llama.cpp, Ollama and vLLM. | Settings > Connections | LM Studio stays only as the Locally host; do not point Unsloth at it (it would JIT-load onto the shared card). Load those models in Unsloth with their saved rows instead (3.3). Billing notes are in 2.5. |
| Windows thread default | On Windows, a model that is fully offloaded to the GPU gets `--threads 2` unless you set `--threads` yourself. | automatic | Relevant when comparing tokens/s against LM Studio. |

### 2.2 Fine-tuning

| Feature | What it does | Where (UI / API) | Notes for this box |
|---|---|---|---|
| Training methods | QLoRA (4-bit base), LoRA (16-bit base), Full fine-tuning, Continued Pretraining. Picking CPT presets rank 128, alpha 32, RS-LoRA and raw text, and adds `embed_tokens` and `lm_head` to the targets. Default learning rates: 2e-4 (LoRA/QLoRA), 2e-5 (Full), 5e-5 (CPT). | Train page > Training Method; `POST /api/train/start` (`training_type`, `load_in_4bit`) | All four run on CUDA. Full FT is realistic only up to about 0.6B here. The docs list three methods; CPT ships in the UI. |
| No RL | No GRPO, DPO, ORPO or KTO in the UI or the API. PR #9310, which added GRPO, was closed unmerged on 2026-09-22. Issue #8777 is still open. | — | Use Unsloth Core notebooks on Kaggle, Colab or HF Jobs (2.4). |
| Model types | Text SFT. Vision-language, with layer toggles and image size 256–2048. Text-to-speech (Orpheus, CSM, Spark-TTS, OuteTTS). Speech-to-text (Whisper, hardcoded to English and transcribe). Embeddings (SentenceTransformerTrainer, MultipleNegativesRankingLoss). | Train page > Model Type | CSM, Whisper, BiCodec and DAC are forced to 16-bit, and their fit on 8 GB is unmeasured. DoRA is disabled while vision layers are being trained. |
| Diffusion LoRA | Image families: sdxl, flux.1, qwen-image, z-image, krea-2, flux.2-klein, flux.2-dev. Video families: ltx-2, minimax-h3. `base_precision` defaults to nf4; 'auto' chooses by free VRAM. | Diffusion training UI; `/api/train/diffusion/*` | Which families fit in 8 GB is unmeasured. SDXL is the likeliest. |
| Trainable bases | Repos with safetensors or `.bin` weights (sharded index files are checked for completeness). A GGUF-only repo is refused as "inference-only". An adapter repo is refused as a base. Gated models are pre-checked with the HF token. trust_remote_code needs an approval pinned to a code fingerprint. | Train page model picker | Chat GGUFs cannot be trained. Pull the safetensors or bnb-4bit repo of the same base. |
| Presets | 78 YAML presets (including `default.yaml`) fill in hyperparameters when a model is picked. `default.yaml`: batch 2, grad accumulation 4, max_steps 30, save_steps 30, warmup_ratio 0.1, r16/alpha16, dropout 0, train_on_completions true. | Applied on model pick; Reset reverts | Every preset sets save_steps equal to max_steps, so a run writes only a final checkpoint until you lower Save Steps. |
| Hyperparameters | Global UI values, which a preset replaces on model pick: epochs 3, max steps 60, context 2048, LR 2e-4, r16, alpha 32, dropout 0.05, batch 4, GA 8, weight decay 0.001, warmup 5, gradient checkpointing 'unsloth', seed 3407. LoRA variants: LoRA, RS-LoRA, LoftQ, DoRA. CUDA optimizers: adamw_8bit, paged_adamw_8bit, adamw_bnb_8bit, paged_adamw_32bit, adamw_torch, adamw_torch_fused. Schedulers: linear, cosine. Context options go up to 262144. | Train page > Hyperparameters; Save and Upload YAML | On 8 GB keep adamw_8bit and 'unsloth' checkpointing. adamw_torch and paged_adamw_32bit use 1.5–2x the optimizer memory. |
| Dataset sources | HF Hub (subset, splits, streaming, row slicing). Local upload of `.csv`, `.json`, `.jsonl`, `.parquet` (500 MB default, adjustable 1–8192 MB). S3. There is no Kaggle source. | Train > Dataset > HuggingFace Hub or Local tab; `/api/hub/datasets/*` | The docs say the Train page accepts PDF and DOCX. The installed upload rejects them; those formats go through Data Recipes instead. |
| Formatting | auto, alpaca, chatml, sharegpt, raw; a column-mapping dialog. Chat template fallback: Unsloth's template, then the tokenizer's, then ChatML. train_on_completions and packing. AI Assist uses a helper GGUF (`unsloth/Qwen3.5-4B-MTP-GGUF`, UD-Q4_K_XL, n_ctx 2048). | Dataset > format selector | The helper also runs **automatically** during dataset processing (VLM instructions, dataset warnings, conversion advice) and downloads itself on first use. `UNSLOTH_HELPER_MODEL_DISABLE=1` turns every one of those paths off. |
| Data Recipes | A NeMo Data Designer 0.5.4 graph editor. Blocks: sampler, llm-text, llm-structured, llm-code, llm-judge, expression, validation. Seeds: HF datasets, local CSV/JSON/JSONL, PDF/DOCX/TXT/MD, GitHub repos. MCP tool profiles. Results appear in the Train dataset picker and can be published to an HF dataset repo. | Sidebar > Data Recipes; `/api/data-recipe/*` | The model can be the loaded Chat model (one per run, thinking off) or any OpenAI-compatible provider. On the owner account, the LiteLLM proxy at `http://localhost:4000/v1` works. Recipes live in browser IndexedDB. Export is "Copy recipe JSON"; import is a paste dialog. |
| VRAM estimator | Estimate = weights + LoRA + optimizer + gradients + activations + 1.4 GiB CUDA overhead. The picker shows "~X GB", Tight and OOM badges and chooses LoRA or QLoRA automatically. At start, a resident chat model is kept only if free VRAM ≥ required × 1.15 + 4 GB. | Train model picker | On 8 GB that rule almost never passes, so starting training unloads Unsloth's chat model. Models held by LM Studio are invisible to the estimator; unload them first. `UNSLOTH_GPU_MEM_FRACTION` caps the training worker, which should raise OOM before a WDDM spill **(inferred)**. |
| Monitoring | SSE progress (loss, LR, grad norm, ETA, eval loss) with replay after reconnect. Four charts, a GPU monitor, W&B and TensorBoard logging, run history. | Train page; `POST /api/train/progress`; `/api/train/runs` | The docs' `/api/train/stream` route is out of date. |
| Checkpoints and resume | save_steps > 0 writes checkpoints. Stop and Save or Cancel. Resume picks the newest checkpoint if the structural fields match. Outputs go to `~/.unsloth/studio/outputs`. | Training History; `resume_from_checkpoint` | Set Save Steps well below total steps on this memory-tight box. |
| Evaluation | Eval loss only. Uses a named HF split first (eval, validation, valid, val, test, if it has ≥16 rows), otherwise auto-splits 5% (16–128 rows, needs ≥32). No benchmark harness. | Dataset > Eval split; Eval Steps | For a qualitative check, load the adapter in Chat > Fine-tuned tab. |
| Headless training | `unsloth train --config <file>.yaml` runs in-process. REST `/api/train/*` runs a spawned worker. The opt-in MCP has `start_training`. | CLI, REST, MCP | — |
| Windows caveats | torch.compile needs Triton plus MSVC headers; otherwise the worker sets `TORCHDYNAMO_DISABLE=1`. causal-conv1d is skipped on Windows (affects its fast path for Qwen3.5/3.6/Next, LFM2, granite hybrids, mamba-family). Qwen3.5 gated-delta layers still use vendored FLA kernels. For nemotron-h, falcon-h1 and granite-4.0-h the worker tries to pip-install mamba-ssm (no Windows guard) before logging it is unavailable. | Training log | Look for "Triton available — torch.compile enabled" in the first log. VS 18 BuildTools, VS 18 Community and SDK 10.0.26100 are installed; whether Triton finds them is **(unverified)**. `UNSLOTH_STUDIO_SKIP_FAST_PATH_HOOKS=1` stops the install attempts. |

### 2.3 Export and Hugging Face

| Feature | What it does | Where (UI / API) | Notes for this box |
|---|---|---|---|
| Export source | Loads a training checkpoint, an HF repo id (a remote LoRA works too) or a local folder into a separate export subprocess. | Export page; `POST /api/export/load-checkpoint` | Export does **not** unload the chat model, so unload it by hand first. When the source is an HF or local model, the UI loads full 16-bit weights, which fits only small models (about 3B by estimate). Training-run checkpoints use the backend default (4-bit for adapters). The API can send `load_in_4bit: true`. |
| Merged model | Merges the LoRA and saves 16-bit, or compressed-tensors: FP8, INT8 (W8A8), FP8 Static, INT8 (W8A16), MXFP8, INT4 (W4A16), MXFP4, NVFP4. | Export > Merged Model; `POST /api/export/export/merged` | On NVIDIA the UI hides the torchao "portable" FP8 and INT8 formats (API only). torchao INT8 had a save failure (PR #10943) and no fix was found. bitsandbytes 4-bit is API only. A Hub push takes one merged format at a time. |
| LoRA only | Adapter plus tokenizer. Optionally a GGUF LoRA (q8_0, f16, bf16, f32) for `llama-cli --lora`. | Export > LoRA Only; `POST /api/export/export/lora` | GGUF is refused for DoRA adapters. |
| GGUF | One or more quants from a single load. UI list: IQ2_XXS, IQ2_M, IQ3_XXS, IQ4_XS, Q2_K_L, Q3_K_M, Q4_K_M (recommended), Q5_K_M, Q6_K, Q8_0, BF16, F16. Optional imatrix, downloaded automatically from `unsloth/<base>-GGUF`. Optional Ollama Modelfile. | Export > GGUF / Llama.cpp; `POST /api/export/export/gguf` | Scratch space is a full 16-bit merge in `_tmp_model_*` inside the save folder. It stays on disk if the GGUF cannot be moved, so clean it up. A custom `imatrix_path` works only through the API or MCP (UI PR #11350 is open). |
| Base / full fine-tune | `save_pretrained` for non-PEFT checkpoints. | `POST /api/export/export/base` | A Hub push **overwrites the repo README** every time. If the base is a local folder, the push can fail before any weights upload; set `base_model_id`. |
| Push to Hub | Creates or reuses the repo and enforces `private`: it refuses to upload if it cannot confirm the repo is private. Uploads only this export's files and adds a model card. | Export dialog > Hub (HF username, model name, HF Write Token, Private) | Needs an explicit write token. An empty field fails with "Repository ID and Hugging Face token required", even though the dialog hint and the docs say a CLI login is enough, and the failure comes only after the whole local export has run. Making an existing public repo private needs the `write:repo_settings` scope. |
| Load exports back | `~/.unsloth/studio/exports` and `outputs` appear in Chat > Fine-tuned tab. | `GET /api/models/loras` | Serve GGUF exports through llama.cpp, the light path here. Open issue #9286 (vision GGUF mmproj detection) may affect vision exports. |
| HF token in Settings | One installation-wide token, AES-GCM encrypted in `studio.db`. It pre-fills the Export token field. | Settings > General > Account > Hugging Face token; `GET/PUT/DELETE /api/settings/hugging-face-token` | Any UI session can read it back in plaintext. It is not written to the hf CLI token file. |
| Token validation | Checks the token with whoami: missing, valid, invalid, rate_limited or unavailable. At most 3 network checks per hour. | Automatic; `POST /api/hub/token/validate` | Checks identity, not write scope. |
| Ambient HF credential | UI sessions with no saved token fall back to the `HF_TOKEN` environment variable, then the `hf auth login` token file. API-key and keyless callers never do, and Export push never does. | — | `HF_TOKEN` **is** set as a Windows user environment variable here, and it outranks the login file. The account is `clduab11` (`hf auth whoami`, checked after ALPHA). Confirm its scopes. No token file exists today. |
| Gated or private downloads | Accept the model's license on huggingface.co first. The token travels with each request. | Hub page | A /v1 auto-download never uses the server's HF identity, so download gated models from the UI. |
| HF cache location | Moves the hub and xet caches to another folder. Earlier locations stay in the scan list. | Settings (owner only); `PUT /api/settings/hugging-face-cache` | Editable here because `HF_HOME` and `HF_HUB_CACHE` are unset. Existing files are not moved. Restart the app afterwards, because in-process reads keep the old path. |
| Download transport | auto, xet or http. Auto picks Xet unless RAM is under pressure, and a stalled Xet download falls back to HTTP. | Settings, Download transport; `/api/settings/download-transport` | On this Windows install an interrupted HTTPS download does **not** resume the file in flight; the UI hint is wrong. Files that already finished are kept. |
| Hub inventory routes | Local and cached listings, deletes, orphan companions. | `/api/hub/*` | API-key and keyless callers get host paths redacted but still see repo ids and sizes. |
| Data Recipe publish | Publishes a finished recipe dataset as an HF dataset repo. | Data Recipes > Executions > publish | The only Hub write path that uses the ambient identity. |

### 2.4 Kaggle and cloud

| Feature | What it does | Where (UI / API) | Notes for this box |
|---|---|---|---|
| Kaggle inside Unsloth Desktop | None: no Kaggle login, picker, push or runner. | — | The HF Hub is the bridge (section 5). |
| Kaggle credential shielding | Tool subprocesses get KAGGLE_KEY and KAGGLE_CONFIG_DIR stripped; the default mode builds their environment from a whitelist. Any folder with `.kaggle` in its path is refused as a model or RAG folder. | Automatic | No Kaggle-specific rule stops agent code reading `~/.kaggle/access_token` by absolute path in "Run automatically" or "Full access" mode. Whether another gate catches it is **(unverified)**. |
| Official Kaggle notebooks | Standard SFT; GRPO (Qwen3 4B, Gemma 3 1B, Llama 3.1 8B, Phi-4 14B, Qwen2.5 3B, Qwen2.5-VL vision GRPO, Muse Glimmer 30B); TTS and STT; vision; DPO, ORPO, CPT, tool calling, Ollama export. | `https://www.kaggle.com/notebooks/welcome?src=https://github.com/unslothai/notebooks/blob/main/nb/Kaggle-<name>.ipynb&accelerator=nvidiaTeslaT4`; full list at github.com/unslothai/notebooks | Run each notebook's own install cell unchanged. Pins differ between notebooks, and some use uv while others use plain pip. |
| Kaggle limits | 12 h per session, 20 GB saved in `/kaggle/working`, P100 or T4×2 (32 GB total), about 30 GPU hours per week. Linking Colab Pro adds 15–30 h. The extra accelerators (A100, H100 and others) are for competitions or admins only. | Notebook Settings > Accelerator; Internet on | The idle timeout is 20 min in one Kaggle doc and 60 min in another. Phone verification is probably needed for GPU, but only community posts say so. |
| Core on Kaggle | Detects Kaggle (`KAGGLE_KERNEL_RUN_TYPE` plus `/kaggle/working`), stages pushes in `/tmp`, and deletes the base model to save disk. | Automatic | Side effect on this PC: any `KAGGLE_*` environment variable changes Core's statistics label. Keep Kaggle credentials in a file. |
| Kaggle Secrets to Hub | Secrets are defined only on the website and read with `UserSecretsClient().get_secret()`. `push_to_hub_gguf(..., token=, private=True)`. | Notebook Add-ons > Secrets | The notebooks' save cells ship wrapped in `if False:` with placeholders. |
| Headless Kaggle | `kaggle kernels init`, `push`, `output`. | kaggle CLI | `kernel-metadata.json` defaults to enable_gpu false, enable_internet false, is_private true. Set GPU and internet on and `machine_shape: NvidiaTeslaT4`. |
| Kaggle as a host | `kagglehub.model_upload` and `dataset_upload`; kaggle CLI Models commands. | kagglehub | An optional mirror of the clduab11 repos. |
| Kaggle Jupyter Server | Experimental: VS Code or Colab connect to Kaggle hardware. | kaggle.com/docs/notebooks | — |
| Unsloth app on Kaggle | No user notebook exists, and issue #4944 is still open. Unsloth's own CI runs the current app on a Kaggle T4 (PR #8489). The legacy `Kaggle-Unsloth_Studio.ipynb` clones the 2024 app. | — | On Kaggle, train with Core notebooks rather than the app. |
| Colab | `Unsloth_Studio_Colab.ipynb` runs the whole app, including the training UI, on Colab behind a Cloudflare link. On a free T4, the docs say "most models up to 22B". The VS Code Colab extension runs Core notebooks on Colab GPUs. | colab.research.google.com link | The tunnel URL is public and protected only by the admin password. |
| HF Jobs | Paid rented GPUs. A coding agent with the `hugging-face-model-trainer` skill writes a uv script that ends in `push_to_hub`. Run it with `hf jobs uv run --flavor a10g-small --secrets HF_TOKEN train.py`; `--dry-run` prints the config without launching. The guide lists about $0.40–$3.00/h. | hf CLI | Every job spends money, so each one needs the operator's approval, and the account needs a positive credit balance. |
| Kaggle data into Desktop | `kagglehub.dataset_download(..., output_dir=...)`, then upload the CSV, JSONL or Parquet. Alternatively, use the kagglehub HF adapter to push a private HF dataset, then train by its id. | kagglehub | — |

### 2.5 Agentic features and extras

| Feature | What it does | Where (UI / API) | Notes for this box |
|---|---|---|---|
| Knowledge bases (RAG) | Hybrid search over sqlite-vec, with knowledge-base, per-thread and per-project scopes. Accepts `.pdf .txt .md .markdown .docx .html .htm` up to 200 MB. Small files are injected whole. Scanned PDFs are OCR'd by the loaded vision model. | Composer + > Knowledge base; `/api/rag/*` | The default embedder (bge-small, 384 dims) runs on CPU in-process and uses no VRAM. A GGUF embedder moves to a GPU llama-server when ≥1024 MiB is free; `RAG_EMBED_DEVICE=cpu` keeps it on CPU. This is a third vector store, separate from Msty's and LiteLLM's. |
| Linked folders | Re-scans every 30 s, up to 10,000 files and depth 64. Ingests only the extensions above. Skips symlinks and sensitive folders (.ssh, .aws, .config, .kaggle and similar). | Knowledge-base or project panel | There is no ignore file. `.env` files are never embedded, but every `.md` file is, so do not link praxen-vault/closed or the-array. |
| Auto-compact | Moves older turns into a searchable archive, which the model reads with `search_conversation`. | Settings, "Auto-compact long chats" | In the UI this applies to GGUF chats only. |
| MCP client | Remote MCP servers by URL, with headers or OAuth. Bulk import of an `mcpServers` JSON. Presets: Unsloth Docs, Context7, Hugging Face (no Exa, despite the docs). | Composer MCP > Manage MCP servers; `/api/mcp/servers/*` | Header values such as Bearer tokens are stored in **plaintext** in `studio.db` and returned to API-key callers. OAuth tokens sit in unencrypted files. Prefer OAuth or least-scope tokens, and never paste the LiteLLM master key or Hostinger or Vercel tokens. |
| Local (stdio) MCP | Runs a local command as an MCP server, as the operator's Windows user, outside the tool sandbox. | Manage MCP servers | ON by default on a loopback bind, which is the Desktop's bind. Suspended while LAN or a tunnel is active. `UNSLOTH_STUDIO_ALLOW_STDIO_MCP=0` forces it off, but whether the Desktop passes that variable to its backend is **(unverified)**. Only a UI session can add one. |
| Blender MCP | Built-in and off by default. Uses a pinned, SHA-checked runtime and a loopback bridge on port 9876. | Manage MCP servers > Blender | Project-local MCP servers stay per project, per standing preference. |
| Unsloth's own MCP (`/mcp`) | 11 tools: status, list local models, training start, stop, status and runs, recipe validate, status and dataset, `load_checkpoint`, `export_gguf` (with push). Nothing loads a chat model. | Needs `UNSLOTH_STUDIO_ENABLE_MCP=1` and `UNSLOTH_STUDIO_MCP_TOKEN` | Leave off. It becomes useful when Claude Code should drive training and export. Hub pushes through it need an explicit `hf_token`. The bearer token is static and unscoped. |
| web_search | Server-side metasearch: wikipedia, brave, duckduckgo, mojeek, startpage, then google, yahoo and grokipedia if those return nothing. URL fetch returns Markdown and refuses any non-public address, so LiteLLM, Grafana and Tailscale hosts are unreachable. | Composer Search pill; `enabled_tools: ['web_search']` | Every query leaves the box to several engines, although the docs say "DuckDuckGo". Keep it off for sensitive topics. |
| python and terminal | A per-chat working directory. A whitelist environment strips HF, OpenAI, Anthropic, GitHub and Kaggle tokens. A command blocklist, and path scanning that asks before leaving the sandbox. Output capped at 16,000 characters. | Composer Code pill | The owner gets **no** OS-level confinement on Windows. In "Run automatically" nothing prompts, so reading a file outside the sandbox, such as `the-array/.env`, happens without a prompt. |
| edit_file and Canvas | Exact-text file edits; an HTML canvas panel. | Enabled with the local tools | edit_file prompts on every call in "Approve for me". Settings > Chat, "Allow canvas network access", controls whether a canvas may load external scripts, styles and media. |
| Tool permission modes | Ask for approval, Approve for me, Run automatically, Full access. | Composer permission selector; request field `permission_mode` | Use Ask or Approve for me. See 7.3 for what each one prompts on. |
| Agent Skills | Loads SKILL.md skills from `~/.agents/skills`, `~/.claude/skills` and a bundled folder. Non-bundled skills are enabled by default, and their catalog goes into prompts whenever tools are on. | Settings, Skills list; `GET /api/skills` | This box has 6 + 28 = 34 existing skills, all of which will show as ENABLED. Review them and disable most. `create_skill` appears only after enabling the bundled skill-creator, and it prompts in "Approve for me". |
| Deep Research | Plan, approve, search and fetch rounds, then a cited report. Runs are resumable. | Composer Deep Research; `/api/chat/research-runs` | Accepts local models or saved tool-capable connections (not Anthropic). A Custom connection to LiteLLM should work but is untested. Slow on 8 GB, so raise the first-output timeout. |
| External providers | OpenAI, Anthropic, Gemini, DeepSeek, Mistral, Kimi, Qwen, HF, OpenRouter, ChatGPT/Codex, plus the Custom, vLLM, Ollama and llama.cpp presets. Keys are AES-GCM encrypted. | Settings > Connections | Prefer one Custom connection to LiteLLM at `http://localhost:4000/v1` with a scoped virtual key. Direct vendor keys here would create a billing lane that nothing governs. Output from local python and file tools goes to the cloud model in follow-up turns. |
| ChatGPT/Codex sign-in | Signs in with a ChatGPT account through OpenAI's public Codex client id, with a loopback callback on port 1455. | Settings > Connections | Bills the ChatGPT plan and never appears in SpendLogs. A clash with the Codex CLI login on port 1455 is **(unverified)**. |
| Coding agents | `unsloth start claude` (or codex, opencode, hermes, pi, openclaw, dsh) points an agent CLI at Unsloth. | Terminal | Offers to install missing CLIs; for hermes on Windows that runs a remote PowerShell script. Decline. "hermes" here is NousResearch agent-agent, not the estate's Windows Hermes keeper. It mints an owner API key and caches it in plaintext. |
| YouTube transcripts | Attaches the captions of a pasted YouTube link. | Composer | Sends a request to youtube.com. |
| Speech-to-text and text-to-speech | Dictation with whisper.cpp, llama.cpp audio models or transformers, one STT model resident at a time. TTS returns WAV only. | Settings > Voice; `/v1/audio/*` | Whether these run on GPU or CPU next to a resident chat model is **(unverified)**. |
| Image and video generation | Diffusion families (flux, qwen-image, z-image, sdxl and others) and video families (wan2.2-ti2v-5b, ltx-2 and others). | Image and Video tabs; `/v1/images/generations`, `/v1/videos` | The GPU arbiter evicts the resident chat model. Fit on 8 GB is unmeasured. |
| Prompts, projects, stats | Saved-prompt library; projects with instructions, a root folder and a sandbox; local profile stats. | Chat menu, sidebar, Settings > Profile | Binding a project to a real folder lets tools write there. Do not bind the-array or praxen-vault/closed. |
| Managed accounts | Multiple users with isolated workspaces. | Settings > Accounts | Do not create any. One account disables keyless and Full access for the whole install, and on Windows managed accounts cannot run python or terminal. |

### 2.6 Operations and security

| Feature | What it does | Where (UI / API) | Notes for this box |
|---|---|---|---|
| Desktop updates | Checks a signed GitHub manifest 5 s after start, then hourly, and on window focus. Installs only when you click Update now: it stops the backend, runs `unsloth studio update`, installs the NSIS bundle and relaunches. | Settings > General or About; update banner | The shell's check cannot be switched off. The backend is reinstalled with `unsloth>=2026.9.11` (a floor), so an update pulls the newest PyPI `unsloth`, and probably a new llama.cpp **(inferred)**. Do not quit mid-install. |
| llama.cpp and whisper.cpp updater | A separate banner: checks at +1 s, then hourly, and swaps the binary atomically. | Banner; Settings > General > Notifications | Not in use under the operator's R4 ruling (updates flow freely; G-UPDATE re-runs the gates after each update). If pinning were ever needed, use `LLAMA_SERVER_PATH` or a custom llama.cpp folder (Settings > System); `UNSLOTH_LLAMA_TAG` applies at update time. |
| `UNSLOTH_DISABLE_UPDATE_CHECK=1` | Skips the PyPI check and the llama.cpp freshness and MTP probes, and blocks the in-app llama.cpp and whisper updates. | Windows user environment variable, then a full relaunch | Does not stop the shell's manifest check. Inheritance by the backend follows from the code but was not probed. |
| Versions | The About tab shows the Unsloth, package, Desktop app and llama.cpp versions. | Settings > About | `/api/health` reports versions only to authenticated callers. |
| Rollback | None in-app. Options: reinstall an older signed installer from the GitHub releases (it may keep the newer backend), or pin llama.cpp. | — | Back up `~/.unsloth/studio` with the app quit, and keep the previous installer, before every update. Downgrade is untested. |
| Storage | `~/.unsloth/studio` holds `studio.db` (+ `-wal`, `-shm`), `auth/` (`auth.db`, `.bootstrap_password`, `.desktop_secret`), `rag/`, `outputs/`, `exports/`, `cache/`, `logs/`, `bin/` and `sandbox/`. The engine is in `~/.unsloth/llama.cpp`. Projects are in `<Documents>\Unsloth Studio\Projects`. Webview data is in `%LOCALAPPDATA%\ai.unsloth.studio`. | — | The Desktop ignores the `UNSLOTH_HOME` relocation variables. |
| Logs | Server, llama-server, backend, install and update logs, plus `tauri.log`. 20 files are kept per folder. | Settings > Logs | An engine stats line prints every 10 s by default; `UNSLOTH_STUDIO_ENGINE_STATS=0` silences it. |
| Backup | Chat export and import (JSON). An imported chat cannot switch on tools. No export exists for settings or keys. | Settings > Data | A full-folder copy is a secret in its own right: it contains the AES key, the desktop secret and the bootstrap password. Treat it like `.env`; keep it off cloud-sync and out of the public repo. |
| API keys | `sk-unsloth(-)` + 32 hex characters, shown once, stored PBKDF2-hashed, optional expiry, revocable. No scopes. | Settings > API > Create token | A key acts as its owner (admin) and can opt into server-side tools per request. It cannot add stdio MCP servers, use the ambient `HF_TOKEN`, or change keyless or remote settings. `unsloth studio reset-password` revokes every key. |
| Keyless access | See section 7. | Settings > Remote & LAN (also shown on the API tab) | Not documented anywhere upstream; the source is the only authority. |
| Admin password and desktop auth | First boot seeds the admin `unsloth` with a diceware password, kept in plaintext in `auth/.bootstrap_password`. The shell signs in with `auth/.desktop_secret`. | Settings > General > Account > Password | Both files are present. The desktop secret lets any local process mint an owner session; the only limit is a per-IP rate limit. |
| LAN access | A second HTTP listener on every active IPv4 interface except loopback, link-local and host-only adapters, which includes Tailscale 100.x. | Settings > Remote & LAN | Blocked until an admin password exists. Needs a firewall rule. Starting it suspends the stdio MCP default. |
| Cloudflare tunnel | A public `trycloudflare.com` URL. Off by default. | Settings > Remote & LAN | Blocked without a password. cloudflared is fetched from GitHub `releases/latest` with no checksum check. Keep it off. |
| Preview links (`/p`) | Signed public share links for training previews. **ON by default.** | Settings, preview sharing | Turn off unless a link is actually being shared. `reset-password` does not revoke them. |
| Watchdog | Probes health every 15 s. Kills a hung backend after 3 failures (12 when inference is busy) and offers a restart. | Automatic | Long CPU-offloaded generations get the 12-strike allowance. |
| Port drift | Moves from 8888 up to 8908 if the port is taken. Jupyter also defaults to 8888. | — | Clients pinned to `:8888` break silently when the port moves. |
| Tools policy | The Desktop launch sets no tools default. `unsloth studio run` defaults tools ON for every bind (the docs are out of date). | `--enable-tools` / `--disable-tools` | Always pass `--disable-tools` to `studio run`. |
| CLI | `unsloth studio`, `studio run`, `update`, `stop`, `verify-install`, `reset-password`, plus `train`, `inference`, `chat`, `export`, `start`. | `~/.unsloth/studio/bin/unsloth.exe` | Never run a second server against this install. `studio run` and `start` cache owner keys in plaintext at `auth/.cli_api_key_*` (none exist yet). |
| Telemetry | The app has no analytics SDK. However, the bundled `unsloth` library pings HF on every training, export and safetensors load by downloading the `unslothai/<env>`, `repeat`, `vram-8` and `<gpu-count>` repos. | Environment variable | Set `UNSLOTH_DISABLE_STATISTICS=1`; inheritance is **(unverified)**. |
| Uninstall | Removes the app and keeps `~/.unsloth`, secrets included. | `uninstall.exe` | Deleting `~/.unsloth` is the operator's step, after a backup. |

---

## 3. Using it like LM Studio

### 3.1 LM Studio to Unsloth Desktop, concept by concept

| LM Studio | Unsloth Desktop |
|---|---|
| Per-model default config (My Models) | "Remember for this model" in the Chat load panel, saved per model and per quant |
| JIT load on request | "Switch model by request" (off by default; ON here) |
| Idle TTL / auto-evict | "Idle auto-unload" (off by default; blocked by Keep model in GPU memory) |
| `lms unload` | Chat > Eject model, or `POST /api/inference/unload` |
| `lms ps` | `GET /api/inference/status` |
| Server on :1234, dummy key `lm-studio` | Server on :8888; keyless scope "Chat and inference" accepts no key or `lm-studio` |
| KV-cache offload toggle | `--no-kv-offload` in Extra Arguments |
| Experts on CPU | MoE CPU layers (Manual mode) or `--cpu-moe` in Extra Arguments |
| Speculative decoding draft | Speculative Decoding dropdown, which defaults to auto |

### 3.2 One-time setup (the operator, in the UI)

Current state (ALPHA) is marked "as set" below.

1. **Settings > System > Model memory:**
   - "Keep model in GPU memory" ON (ruling, as set).
   - "Don't reserve system RAM for the model" ON (ruling 2026-09-23, as set). Without it, Keep resident pins the whole model file in host RAM whenever a load does not fit wholly on the GPU (2.1).
   - Both apply from the next load.
2. **VRAM Budget:** 0.95 (as set; the operator 2026-09-23, revisit at the performance evaluation). It keeps ~648 MiB free by the script's total − used measure; 0.904 would keep 1 GiB (2.1). It governs loads without a saved row and Auto spill plans. A saved row that fits pins context and wins (qwen and ministral re-verified at 0.95).
3. **Settings > API > Model auto-switch:**
   - "Switch model by request" ON (as set).
   - "Download missing models" OFF (as set).
   - Idle auto-unload has no effect while Keep resident is on (ruling: unload by hand).
   - With the switch on, a keyed request that names another downloaded model replaces the resident one. A name Unsloth cannot tie to anything is answered by the resident model with HTTP 200, so always check `response.model` **(ALPHA)**.
4. **Settings > Remote & LAN > Keyless API access:** "Chat and inference" ON, "Everything else" OFF, "Allow tools" OFF (ruling, as set).
   - LAN auto-start is also ON. It fires only once an admin password exists, so switch it off BEFORE ever setting one.
5. **Preview sharing:** turn it off.
6. **Optional Windows user environment variables.** Quit from the tray and relaunch after setting them. Whether the Desktop passes them to its backend is **(unverified)**.
   - `UNSLOTH_DISABLE_STATISTICS=1` stops the HF ping from the training library.
   - `UNSLOTH_HELPER_MODEL_DISABLE=1` stops the automatic Qwen3.5-4B-MTP helper.
   - `UNSLOTH_STUDIO_ALLOW_STDIO_MCP=0` blocks local-command MCP servers.
   - `UNSLOTH_DISABLE_UPDATE_CHECK=1` exists, but it is NOT used: the operator's R4 ruling lets updates flow freely.

### 3.3 Pick, download, configure, load

1. **Pick.** Open the Hub page, search, choose a GGUF repo and pick a quant (Q4_K_M or UD-Q4_K_XL). Size it before downloading: weights + mmproj + any separate `mtp-*.gguf` drafter (Gemma 4 ships one, and Unsloth's auto speculative mode loads it) + KV at the target context + ~0.5 GiB compute + at least 1 GiB free. Desktop apps hold 1.0–1.5 GiB of the 8 GiB before any model loads. **Never download a repo that already sits in LM Studio's folder, by any path** (Hub page, `/api/hub/download` or a repo-id load): the HF-cache copy then wins in the resolver, and in ALPHA that duplicate had no mmproj, so qwen lost vision. Configure ministral, qwen3.5-4b and huihui from their LM Studio copies. `GET /api/models/kv-cache-estimate` and `POST /api/inference/estimate-memory` help. For a gated model, accept the license on huggingface.co first.
2. **Download** and watch the progress. The file lands in `~/.cache/huggingface/hub`. **Load nothing until the download finishes.** On 2026-09-23 a model load overlapped a Xet download: the backend stopped answering, the Desktop shell's health watchdog killed it after 3 failed probes, and the download died with it. The shell did not restart the backend.
3. **Baseline VRAM.** Read `nvidia-smi` before the load. Only the change it shows is meaningful.
4. **Configure (recommended: the script, tested in ALPHA).** From `the-array`, with Unsloth empty so the VRAM reading is clean:
   ```bash
   python scripts/unsloth-model-config.py list
   python scripts/unsloth-model-config.py plan "publisher/model-dir:QUANT"
   python scripts/unsloth-model-config.py apply "publisher/model-dir:QUANT" --ctx <N> --kv q8_0 --threads 8 [--gpu-layers N | --n-cpu-moe K]
   python scripts/unsloth-model-config.py show "publisher/model-dir:QUANT"
   python scripts/unsloth-model-config.py verify "publisher/model-dir:QUANT"
   ```
   What each command does:
   - `plan` reads the GGUF header (layers, KV heads, sliding-window and hybrid layers, experts) and proposes a context that leaves ≥1 GiB free. KV is priced the way Unsloth's own estimator prices it: global layers per token, sliding-window layers as a fixed window, shared-KV layers free (Gemma 4's real cost is ~8.5 KiB/token at q8_0, not the 349 KiB a full-attention count gives). It proposes CPU experts (`n_cpu_moe`) only when a MoE model does not fit whole. `apply` writes only the flags you pass, so copy every field from the plan. GPU mode follows Unsloth's source (`auto_fit = gpu_memory_mode == "manual" and gpu_layers < 0`): a model that fits gets **no** GPU flags, which stays Auto and launched `-ngl -1 --fit off` in ALPHA; a dense model that does not fit also gets no GPU flag by default, because Auto then spills weight tensors and keeps the KV cache on the GPU (the source measured 13.63 vs 1.03 t/s against whole-layer offload), while `--gpu-layers N` (Manual, `--gpu-layers N --fit off`, source-read) moves whole layers with their KV; a MoE gets `--n-cpu-moe K` (Manual, every layer requested). Every Auto decision sizes against the global **VRAM budget** (slider in the load panel, `/api/settings/vram-budget`). Unsloth keeps `max((1 − fraction) × card, min(512 MiB, 3% of card))` of nvidia-smi's free memory, which already leaves out the driver's 239 MiB. By the script's total − used measure the stored 0.95 therefore keeps ~648 MiB, and **0.904 matches the estate's 1 GiB** (2.1). `plan` prints the current budget in that measure. `apply` refuses `--gpu-layers -1`, because Manual with -1 turns llama.cpp's fitter back on. With Keep resident ON, CPU experts are mlocked in host RAM, so check host Available and commit first.
   - `apply` saves the row keyed `publisher/model-dir:QUANT`, which the loader matches (verified), then runs `show`.
   - `verify` loads the model through auto-switch, then prints the real llama-server flags, free VRAM, spill and tok/s, and unloads it (`--keep` leaves it loaded).
   - `remove` deletes the row.

   The UI equivalent is Chat > Select model > load panel, set the knobs, tick **Remember for this model**, Load model.
5. **Verify** (built into `verify`): at least 1 GiB still free, the context actually allocated, and tok/s.
6. **Check the saved row:** `python scripts/unsloth-model-config.py show <model>`. It asks Unsloth's own resolver which row a load would apply. The raw API is `GET /api/settings/openai-auto-switch/overrides?model_id=…&alias_id=…&gguf_variant=…`, which needs owner auth (a UI session or an `sk-unsloth` key).

**Rows saved and verified so far (2026-09-23). Re-verified the same evening at budget 0.95, with ~1.5 GiB of desktop VRAM in use:**

| Model | Row | Result (ALPHA) | Result (re-verify at 0.95) |
|---|---|---|---|
| `HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive:Q6_K` | ctx 83,968, q8_0, `--threads 8` | 1,385 MiB free, 33–35 tok/s | `-ngl -1 --fit off`, mmproj on; 1,183 MiB free, 672 MiB shared; 39.5–40.3 tok/s |
| `lmstudio-community/Ministral-3-3B-Instruct-2512-GGUF:Q6_K` | ctx 33,792, q8_0, `--threads 8` | 1,166 MiB free, 44–53 tok/s | `-ngl -1 --fit off`, mmproj on; 1,648 MiB free, 440 MiB shared; 41.1–43.7 tok/s. With the RAM lock off: `--load-mode dio`, 1,384 MiB free, 50–65 tok/s |
| `unsloth/gemma-4-E2B-it-qat-GGUF:UD-Q4_K_XL` | ctx 131,072, q8_0, `--threads 8` | — | Fits whole with its MTP drafter (`--model-draft`), mmproj on, reasoning ON by default; 2,418 MiB free, 113–130 tok/s; vision, tool call and reasoning pass (lock on; re-check with it off) |
| `unsloth/LFM2.5-8B-A1B-GGUF:UD-Q4_K_XL` | ctx 32,768, q8_0, `--threads 8`, `--n-cpu-moe 3` | — | Launched `--n-cpu-moe 5` (2 leading dense layers); 1,322 MiB free, 85–132 tok/s; tool call and reasoning pass, no vision. The lock pinned 5.3 GB of host RAM (re-check with it off) |

qwen's row with the RAM lock off, at a 2.0 GiB desktop load, launched `--fit on` (Unsloth could not prove the fit at budget 0.95) and left 686 MiB free at 40–46 tok/s. Its context gets trimmed if a quieter desktop still leaves under 1 GiB.

At these rows `verify` measured about 380 MiB (qwen) and 790 MiB (ministral) more free VRAM than `plan` predicts, so the planner errs on the safe side. Desktop VRAM moved by up to ~200 MiB during the runs; `verify` decides.

**Which config a load actually uses:**

| How the model gets loaded | Config applied |
|---|---|
| UI Load or Reload | The fields in the load panel, sent in the request |
| A /v1 request naming the model, switch ON | The saved server row. Lookup order: path:QUANT, alias:QUANT, path, path:filelabel, alias. **No row means server defaults: Auto GPU mode and AUTO speculative decoding.** |
| Reload after an idle unload | The saved server row |
| Direct `POST /load` (or `/v1/load`) | Only the request body. Exception: if `llama_extra_args` is omitted, the previous extra args for the same model and quant are reused from memory. **A load by repo id downloads from Hugging Face even with "Download missing models" OFF, which governs `/v1` only (ALPHA incident 1).** The resolver then prefers that HF-cache copy; in ALPHA qwen lost its mmproj and its settings. For files in LM Studio's folder use the absolute path, and never let a second copy of a routed model land in the HF cache. |
| Keyless request | Never loads anything. Uses the resident model. |

Points to remember:
- A save replaces the whole row.
- If the copy to the server fails, the UI warns "Failed to mirror model settings to the server".
- The global fallbacks for GPU mode and speculative decoding live only in localStorage, so save a row for every model.
- Editing a row does not reload a model that is already loaded; click Reload.
- Local files are keyed by their absolute path.
- Upstream fixed #7477 (settings ignored on auto-load) and #9604 (remembered settings erased). Neither fix has been re-tested here.

### 3.4 Recommended rules for the 8 GB card

| Setting | Recommendation | Why |
|---|---|---|
| Headroom | Keep ≥1 GiB of 8188 MiB free after load, measured as total − used (the estate's measure). Measure the change from the baseline. A VRAM Budget of 0.904 keeps 1 GiB by that measure; the stored 0.95 keeps ~648 MiB (it only affects models without a saved row, and Auto spill plans). | Within ~300 MiB of full, a WDDM spill cuts decode speed about 5x with no warning (estate durable rule). The driver reserves 239 MiB of that margin, which nvidia-smi's own "free" figure leaves out. |
| Context | Pin it in the saved row (`max_seq_length`). A row load produced `-c 83968 -ngl -1 --fit off` **(ALPHA)**. Without a row, auto-fit sizes context to whatever VRAM is free at load time (15,872 then 13,056 for ministral; 22,528 to 61,696 for qwen), so the result is not deterministic. | A pinned context makes VRAM use predictable. |
| GPU memory mode | Auto for dense models that fit. Manual with explicit GPU layers to reproduce an OP LOCAL-TUNE placement exactly. | When Auto cannot prove a fit, it emits a tensor-spill plan that keeps KV on the GPU. A source comment measured 13.63 vs 1.03 t/s for that plan against the alternative on a 27B at 128K. |
| KV type | q8_0 is a sensible default for chat models. | It halves the KV size. In the estate, q8_0 alone gave ministral +53%. A quantized V cache makes llama.cpp turn flash attention on by itself. |
| KV location | Decide per model. Add `--no-kv-offload` for granite-style dense models; leave KV on the GPU for ministral-style models. Measure both. | This knob has no UI switch, and the right value inverts between models (estate durable rule). |
| MoE | Manual mode plus MoE CPU layers (counted after any leading dense layers), or `--cpu-moe` in Extra Arguments to put every expert on CPU. | In the estate, all experts on CPU leaves about 1 GiB on the GPU for gpt-oss-20b and gemma4-26b-class models. |
| Threads | Save `--threads 8` in the row. Unsloth forces `--threads 2` on Windows full offload, and qwen3.5-4b loaded by Unsloth went from 34–40 to 45 tok/s with 8 threads at 16K context **(ALPHA)**. At the saved 83,968 row it measured 33–35 tok/s, below the 20% G-PERSIST line; that is accepted while the qwen speed investigation is parked (8.15). The same binary run outside Unsloth showed no thread effect, so why this helps is unexplained. For CPU-offloaded or MoE models, measure 6 vs 8. | Measured on qwen3.5-4b only. |
| Parallel slots | 1–2 for single-user use. The default of 4 is acceptable because the slots share one KV pool, so one request can still use the full context. | The fitter may lower the count anyway, and fewer slots lower the batch floor. |
| Speculative decoding | Leave the default unless a model needs tuning. | The default launch adds `--spec-default` (llama.cpp's default speculative config; no draft model was loaded for the ALPHA GGUFs). ALPHA saw 0–11% draft acceptance on ordinary chat output and no measurable cost. If a model's row pulls in a draft model or sidecar, that costs VRAM, so count it in the ≥1 GiB rule. |
| Reasoning | Leave the reasoning budget at -1 (model default). Qwen3.5/3.6 at 9B or smaller start with thinking off; other reasoning models start with it on. Change it per request with `enable_thinking` or `reasoning_effort`. To make thinking off a model's default, put `--reasoning off` in Extra Arguments **(unverified)**; that flag is dropped if the same row also saves a chat template override. | Field names differ per model. Read the response keys before concluding a model does not think. |
| Prompt cache RAM | Lower it from 8192 MiB to about 2048–4096 MiB while Docker is running. | It uses host RAM, which shares 47.8 GB with the 28 GB WSL allowance. |
| Flash attention | Leave on (the default). | — |
| Extra Arguments | At most 256 tokens and 24 KiB on Windows. Refused flags cover host, port, API key, `--parallel`, model identity and similar. | The last flag given wins over Unsloth's own flags. |
| Sampling | API clients (LiteLLM) should send their own values. | UI presets do not reach API callers. |

### 3.5 Unloading by hand

- **UI:** Chat > Eject model.
- **Script:** `python scripts/unsloth-model-config.py unload` unloads whatever is resident, using the status `model_identifier` (or `active_model`). It then re-reads status and prints `STILL LOADED` if the model survived. `verify` (without `--keep`) does the same at the end.
- **API:** needs a UI session or an `sk-unsloth` key; `/unload` is not on the keyless route list.
  1. `GET /api/inference/status` and read `model_identifier` (use `active_model` when `model_identifier` is empty). For an API-key caller it is a redacted `ref:…` value, which works as-is **(ALPHA)**.
  2. `POST /api/inference/unload` with `{"model_path": "<that value>"}`.
  3. Read status again. Only the status identifier is reliable. In ALPHA p25 the advertised id `…:Q6_K` returned `"status": "unloaded"` and the model stayed loaded. Any name that does not match the resident identifier returns that false "unloaded" (`B/routes/inference.py:18348-18557`). Always confirm `loaded` is empty.
- **Unload first before** Docker image pulls or builds, training, image or video generation, and GGUF export. None of these respects the resident model's needs, and the memory-wedge rule applies.
- **Never serve from both runtimes at once** (plan D2; ALPHA incident 3). The saved rows' ≥1 GiB reserve assumes LM Studio holds nothing. Eject Unsloth's model before Locally uses LM Studio. Restart LM Studio afterwards if it keeps memory. When restarting it, first confirm no `LM Studio.exe` or `lmlink-connector.exe` remains and that :1234 is free (ALPHA incident 5).

---

## 4. Linking Hugging Face (the operator's steps)

Claude never enters tokens. the operator does each step.

1. **Current ambient identity (checked after ALPHA, not in the evidence folder).** `hf auth whoami` returns `user=clduab11`, from the `HF_TOKEN` Windows user environment variable (there is no token file). The Unsloth backend inherits `HF_TOKEN`, so UI-session downloads and model loads use it (gated downloads untested). Its scopes are unknown; if it is read-only, pushes need step 2.
2. **Create a fine-grained token** at https://huggingface.co/settings/tokens with read access and write access to repos under `clduab11`. Add repo-settings write if Unsloth should be able to switch an existing public repo to private.
3. **Paste it in Unsloth:** Settings > General > Account > Hugging Face token. Wait for "Token validated". That check confirms identity only, not write access.
4. **Test a read.** Accept a gated model's license on huggingface.co, then download it from the Hub page.
5. **Test a write.** Export a small LoRA to a new private repo `clduab11/<test>`. The token field is pre-filled from Settings. Confirm the repo on huggingface.co. The token must be in place **before** Start, because the check runs only after the local export finishes.
6. **Optional:** move the HF cache to a larger drive (Settings, owner only), then restart the app. Existing files are not moved.
7. **Optional:** run `hf auth login` for CLI use, remembering that `HF_TOKEN` still wins.

Keep in mind:
- The saved token is one per installation, and any UI session can reveal it.
- API-key callers must send their own token in `X-Unsloth-HF-Token` for gated downloads.
- Export pushes never fall back to the ambient token.

---

## 5. Linking Kaggle

**What exists:** nothing inside Unsloth Desktop. Kaggle supplies free GPUs and data, and the HF Hub carries results back. GRPO and other RL work run there as Unsloth Core notebooks, because the app cannot run them.

**One-time setup (the operator):**
1. On the Kaggle account, verify a phone number if the GPU toggle is greyed out. Only community posts say this is required.
2. kaggle.com/settings/api > Generate New Token. Save it as `~\.kaggle\access_token` (or use the legacy `kaggle.json`). Do not set global `KAGGLE_*` environment variables.
3. Install the tools outside Unsloth's venv: `uv tool install kaggle`, and kagglehub in its own venv (`pip install kagglehub[hf-datasets]` if using the HF adapter). Test with `kaggle datasets list -s llm`.
4. On kaggle.com, add `HF_TOKEN` (an HF write token) as a secret, once. Secrets live at the **account** level, but Kaggle only lets you create or edit them from inside a notebook: open any notebook, then Notebook Editor → Add-ons → Secrets → Add. There is no separate settings page, and the CLI cannot set them. Each notebook must then **attach** the secret (tick it in the same Add-ons → Secrets panel). Changing the value updates every notebook that uses it. Source: Kaggle maintainer in `github.com/Kaggle/kaggle-cli/issues/582`.

**Each run (browser):**
5. Open the Unsloth Kaggle notebook link with accelerator T4 x2, and turn Internet on in notebook Settings.
6. Run the install cell unchanged. Change only the model and dataset cells. Inside Kaggle, kagglehub works without logging in.
7. Edit the save cells: remove `if False:` and fill in the names.
   ```python
   from kaggle_secrets import UserSecretsClient
   tok = UserSecretsClient().get_secret("HF_TOKEN")
   model.push_to_hub_gguf("clduab11/<name>-GGUF", tokenizer,
                          quantization_method=["q4_k_m", "q8_0"],
                          token=tok, private=True)
   ```
   Or push only the LoRA. To reload an adapter, use `FastLanguageModel.from_pretrained(adapter_dir)`, never `PeftModel.from_pretrained`. The second pattern silently exports the base model (issue #11698).
8. Sessions stop after 12 h. For long runs, push the adapter or save checkpoints partway through.

**Back on pc-host:**
9. In Unsloth, go to the Hub page, search `clduab11/<name>-GGUF`, download Q4_K_M, and load it with a saved config (3.3).
   - **LoRA variant:** Export > load checkpoint `clduab11/<adapter>` (a Hub id is accepted) > GGUF > Chat > Fine-tuned tab. Unload the chat model first.

**Headless variant.** Copy the notebook into a folder and run `kaggle kernels init -p <dir>`. Edit `kernel-metadata.json`: `id` = `clduab11/<slug>`, `enable_gpu` true, `enable_internet` true, `machine_shape` `NvidiaTeslaT4`. Then run `kaggle kernels push -p <dir>`, and later `kaggle kernels output clduab11/<slug> -p <local dir>`. The CLI cannot define secrets, so the HF_TOKEN secret must already be attached on the website.

**Kaggle data for a local run.** Either `kagglehub.dataset_download("owner/slug", output_dir="...")` and upload the CSV, JSONL or Parquet on the Train page, or load it with `KaggleDatasetAdapter.HUGGING_FACE`, `.push_to_hub("clduab11/<x>", private=True)`, and train on `clduab11/<x>`.

---

## 6. Fine-tuning roadmap on this box

### 6.1 What fits in 8 GB

Estimates below come from a hand re-implementation of Unsloth's own VRAM formula (`B/utils/hardware/VRAM_ESTIMATION.md`) at LoRA r16, seq 2048, batch 1, all seven target modules. They are in decimal GB and include the 1.4 GiB CUDA overhead.

| Model | QLoRA (4-bit) | LoRA (16-bit) | Full FT |
|---|---|---|---|
| Qwen3-0.6B | 2.1 GB | 2.8 GB | 6.2 GB |
| Qwen3-1.7B | 3.2 GB | 5.1 GB | — |
| Qwen3-4B | 4.9 GB (5.6 at seq 4096, batch 2) | 9.9 GB | — |
| Llama-3.1-8B | 8.5 GB (~8.0 with double-quant; ~7.98 GiB in code units, right at the ceiling) | — | — |
| Qwen3-14B | 13.6 GB | — | — |

The official minimum table is more optimistic. QLoRA: 3B 3.5, 7B 5, 8B 6, 9B 6.5, 11B 7.5, 14B 8.5 GB. LoRA: 3B 8, 7B 19, 8B 22 GB.

**Verdict:** QLoRA up to about 4B is comfortable. 7–9B QLoRA is borderline: batch 1, seq ≤2048, nothing else on the GPU, and one probe run first. 16-bit LoRA fits up to about 1.7B, and full fine-tuning up to about 0.6B. The Windows compositor also uses VRAM. Whether an over-budget run spills into system memory or raises OOM is **(unverified)**; `UNSLOTH_GPU_MEM_FRACTION` is the likely guard.

### 6.2 First recommended experiment

A QLoRA SFT run on `unsloth/Qwen3-4B-Instruct-2507`. It has a bundled preset (batch 2, GA 4, max_steps 30, r32, alpha32, train_on_completions true), and at about 4.9 GB it leaves real headroom. Qwen3-4B is a safer first model than Qwen3.5, which loses the causal-conv1d fast path on Windows.

1. Before starting: eject Unsloth's chat model, unload LM Studio's models, take an `nvidia-smi` baseline, and check free host RAM (Docker's WSL VM shares it).
2. Data: a small chat-format JSONL (a few hundred to a few thousand rows) from the HF Hub or a local upload, with an eval split or at least 32 rows so auto-split works.
3. Settings: seq 2048, batch 1–2, GA 4–8, adamw_8bit, gradient checkpointing 'unsloth'. Set Save Steps well below the total (for example 10 for a 30-step run). Eval Steps above 0.
4. Watch: the first log line ("Triton available — torch.compile enabled", or the warning), the VRAM badge, and the loss and grad-norm charts.
5. For a faster smoke test, use Qwen3-1.7B first.

### 6.3 How results get back into Unsloth Desktop

- **Quick look:** Chat > Fine-tuned tab > load the LoRA. This reloads the base model, so compare it with the base in Model Arena.
- **Deliverable:** Export > training run checkpoint > GGUF (Q4_K_M, optionally Q8_0 in the same load). Save locally to `~/.unsloth/studio/exports`; it appears in the Fine-tuned tab. Load it with a saved config (3.3). Optionally push it to a private `clduab11` repo with the Settings token.
- **Cleanup:** delete any leftover `_tmp_model_*` folder in the save directory.

### 6.4 After that

- 7–9B QLoRA: one probe run with a VRAM baseline and delta.
- Embeddings: the Qwen3-Embedding-0.6B preset (max_seq 512, batch 256; lower the batch here). This fits the 1024-dim `legacy/embed` lane.
- Synthetic data: Data Recipes with LiteLLM (`http://localhost:4000/v1`, scoped key) as the model provider. Spend stays metered.
- RL (GRPO, DPO, ORPO): Kaggle T4×2 notebooks (section 5). Anything above 8 GB goes to Kaggle, Colab or HF Jobs; HF Jobs is paid and needs approval per job.
- Claude Code driving training and export: enable the `/mcp` endpoint with a token, loopback only.

---

## 7. Security posture as ruled by the operator

### 7.1 Rulings and what they mean

| Ruling | What it means | Keep in mind |
|---|---|---|
| **Keyless ON** (scope "Chat and inference") | Callers with no key, or the dummy keys `not-needed`, `lm-studio`, `ollama`, `no-key-required`, may use the chat, completions, responses, messages, embeddings and models routes. Loading, unloading, training, files and settings still need a key. | Any other non-empty key, such as a LiteLLM placeholder, is treated as a real key and gets 401. Keyless callers see the whole catalog in `/v1/models` but can only use the loaded model. Only the owner, from a UI session, can change this setting. |
| **Tools forced off for keyless callers** ("Allow tools" OFF) | A middleware forces server-side tools (python, terminal, web search) off for keyless requests, even under a CLI `--enable-tools`. | Keyed callers, including an `sk-unsloth` key given to LiteLLM, **can** opt into tools per request with `enable_tools: true`. A non-streaming request with no explicit permission mode cannot prompt, so it just runs the tools (ALPHA p12: python ran). LiteLLM forwards 28 of 29 Unsloth tool, permission and `provider_*` fields in `extra_body` (ALPHA p17). Before any route moves (plan §6.7 item 1, §6.8a), a LiteLLM pre-call hook must: keep only standard chat params plus `chat_template_kwargs`; delete every other key at the top level and inside `extra_body`; drop `X-Unsloth-*` headers; inject `enable_tools: false`. Verify through the proxy: no `execute_tool` line in tauri.log. |
| **Keep model resident ON, unload by hand** | Idle unload is vetoed, and CPU-resident parts are mlocked unless "Don't reserve system RAM" is on. | Training, image and video generation, and a switch request all still evict the model. Unload before Docker pulls or builds. |
| **No admin password** | The LAN listener and the Cloudflare tunnel stay blocked, which is good. | The seeded password sits in plaintext in `auth/.bootstrap_password`. `auth/.desktop_secret` is an admin-equivalent credential that any local process can read. Setting a password later through `unsloth studio reset-password` revokes every API key, which would break a LiteLLM binding. |
| **LAN auto-start armed — NOT ruled (open, 8.17)** | Nothing happens today: the boot log skips it only with `admin_password_change_required` (`tauri_log_excerpts.txt`, 17:23Z and 17:59Z). The next time Unsloth starts after a password exists, a plain-HTTP listener comes up on every active IPv4 interface, Tailscale included. | With keyless on, anyone on 192.168.0.x could then chat with the loaded model without a key; tools stay off. Tailscale peers would need a key. Starting LAN also suspends stdio MCP servers. Windows Firewall needs a Private-profile rule, and the PC's IP 192.0.2.11 is not DHCP-reserved. The iPhone does not need this, because Locally uses LM Studio. |

### 7.2 Who actually gets keyless access

Admission requires all of these:
- no Origin header;
- Sec-Fetch-Site absent or `same-origin`;
- the Host header's hostname is `localhost` or a literal IP, with or without a port (ALPHA p27 admitted `localhost`, `localhost:8888` and `127.0.0.1:8888`, and refused `host.docker.internal:8888`);
- loopback on both ends, or a private-LAN peer arriving on the Settings LAN listener;
- no managed accounts exist.

| Client | Keyless? |
|---|---|
| A local app calling `http://127.0.0.1:8888/v1` or `http://localhost:8888/v1` | Yes |
| LiteLLM container via `http://host.docker.internal:8888` | Reachable **(ALPHA p13)**. With the default Host header, keyless is refused (401), so LiteLLM uses an `sk-unsloth` key. That is required anyway, because only keyed callers auto-switch. |
| Any Docker container sending `Host: localhost` or `Host: 127.0.0.1:8888` | **Yes (ALPHA p27).** Docker Desktop's forwarder makes the peer look like loopback. With the keyless ruling, every container can use the loaded model without a key. It cannot use tools or switch models. |
| The llama-server child on its random port | Reachable from containers with **no auth at all (ALPHA p23)**, the same class as LM Studio's :1234 today. |
| Browser or Electron clients that send an Origin header (possibly Msty) | No. Probe each client before relying on keyless. |
| iMac over Tailscale 100.x | Never keyless (not in the private ranges) |
| iPhone (Locally) | Not applicable; it uses LM Studio |

### 7.3 Other things to keep in mind

- **Tool permission mode:** use "Ask for approval" or "Approve for me". Never use "Run automatically", which runs everything without prompts inside the sandbox, including reads outside it; the docs wrongly say it disables tools. Never use "Full access", which removes the sandbox. "Approve for me" prompts for execution, credential and sensitive-path access, destructive, privilege, payment and publish verbs, and MCP tools whose names it does not recognise, plus every `edit_file` and `create_skill`. Plain create and update MCP calls go through without a prompt. The owner's tools have no OS confinement on Windows.
- **Local-command MCP** is on by default and runs with the operator's full user rights. Add only pinned, trusted servers.
- **MCP header tokens** are stored in plaintext in `studio.db`.
- **Skills:** 34 skills from Claude Code and other agents will show as enabled. Prune them.
- **web_search** sends queries to third-party engines.
- **Preview links** are public by default. Turn them off.
- **Backups** of `~/.unsloth/studio` contain the credential encryption key, the desktop secret and the bootstrap password.
- **API keys have no scopes.** An `sk-unsloth` key is admin-equivalent.
- **External providers:** route through a Custom connection to LiteLLM, not direct vendor keys. ChatGPT/Codex sign-in bills outside SpendLogs.
- **Updates flow freely (the operator, R4 relaxed):** no pinning and no off switch. The gate is G-UPDATE: after each update run `verify-stack.py` plus the Unsloth route probes, and roll a failing route back. Unsloth updated five times between 09-17 and 09-23. "Update now" reinstalls `unsloth>=floor` from PyPI and there is no in-app rollback, so a copy of `~/.unsloth/studio` taken with the app quit is the only undo.
- **Telemetry:** the app has none, but the training library pings HF. Set `UNSLOTH_DISABLE_STATISTICS=1`.
- **uvicorn proxy headers:** the server trusts `X-Forwarded-*` from 127.0.0.1. For keyless this fails closed, but do not set `FORWARDED_ALLOW_IPS` anywhere on the box.
- **Port 8888** is also Jupyter's default. If Unsloth drifts to another port, clients pinned to 8888 fail silently.

---

## 8. Open questions and unverified items

**Needs a probe on this box:**
1. ~~The backend port~~ **Answered (ALPHA):** 8888, held across a backend restart. `desktop_backend.json` records the live port if it ever drifts.
2. ~~The LiteLLM path~~ **Answered (ALPHA):** `praxen-litellm` reaches `host.docker.internal:8888`, and keyed calls work. See 7.2 for keyless.
3. **Msty Studio, Gateway and Go headers.** Does each send Origin or Sec-Fetch-Site, or a Host other than localhost or 127.0.0.1? Any of these makes keyless answer 401.
4. **Environment inheritance — partly answered (checked after ALPHA).** The running backend carries `HF_TOKEN` from the user environment, so user variables present when the app launched do reach it. A newly set variable needs a full quit from the tray and a relaunch. Not yet checked: that the llama-server child passes them on.
5. **VRAM budget vs reserve: resolved by source-read, 09-23.** Unsloth's reserve comes off nvidia-smi's free, which excludes the driver's 239 MiB. By total − used, 0.904 keeps ~1 GiB and the stored 0.95 keeps a ~648 MiB floor (2.1). Measured after auto-fit loads at 0.98: 661–689 MiB free **(ALPHA)**, ~190 MiB above that budget's floor. A row-less load at 0.95 is still unmeasured. Moot for models with a saved row that fits.
6. **`--reasoning off` in Extra Arguments** as a saved thinking-off default. Not probed. Per request, `chat_template_kwargs.enable_thinking` or `reasoning_effort` switches thinking on or off **(ALPHA)**.
7. **Real host-RAM use** with Keep resident plus Don't reserve system RAM. A Reddit report of RAM still being used could not be read.
8. **Keep resident and idle unload for safetensors (Transformers) loads.** The code comments mention GGUF only.
9. **Whether localStorage per-model configs survive Desktop updates.** The server row is what API loads read.
10. **Whether 7–9B QLoRA completes**, whether Triton finds the VS 18 toolchain, and whether an over-budget run spills to system memory or raises OOM.
11. **8 GB fit** for diffusion, video, TTS and STT training and generation, and where STT and TTS models are placed next to a resident chat model.
12. ~~Qwen3-Embedding-0.6B GGUF as Unsloth's embedder~~ **Superseded by plan D1:** `legacy/embed` goes to the BRAVO container, not Unsloth.
13. **The `HF_TOKEN` scopes.** The account is `clduab11` (checked after ALPHA); whether the token can write is unknown.

**Settled by the operator (2026-09-23):**
14. Keyless access ON; Keep model resident ON with manual unload; no admin password for now.
15. The qwen speed investigation (why Unsloth-launched qwen decodes 15–25% below the same binary run by hand) is **parked** unless a need appears. It is not about speculative decoding.
16. "Switch model by request" stays ON (as set). Saved per-model rows depend on it, and so does LiteLLM later.

**Still for the operator:**
17. LAN auto-start is armed. Turn it off before ever setting an admin password.
18. Keep the `HF_TOKEN` user variable, or rely on the token saved in Unsloth once it is added. Both can coexist; the saved token wins in the UI.

**Upstream unknowns:**
19. Rollback and downgrade are untested. Does "Update now" also replace llama.cpp (inferred yes)?
20. torchao INT8 export (API only) fix status. Whether Hub uploads use Xet. Whether a fine-grained token without repo-settings write can create a *new* private repo.
21. GRPO in a future Desktop release (PR #9310 closed, #8777 open). A user notebook for the app on Kaggle (#4944 open). Whether `colab.start(cloudflare=True)` works on Kaggle.
22. Kaggle phone verification (community evidence only). Kaggle's idle timeout (20 vs 60 min).
23. Whether the Codex sign-in clashes with the Codex CLI login on port 1455, and whether OpenAI sanctions reuse of that client id.
24. Deep Research through a Custom connection to LiteLLM (accepted by the source, not exercised).
25. Whether any MCP preset is pre-enabled on a fresh install.
26. Whether agent code can read `~/.kaggle/access_token` by absolute path in Ask or Approve mode (only heuristic path scanning stands in the way).

**Where the docs disagree with the installed 0.1.815-beta source (the source wins here):**

| Docs say | Source shows |
|---|---|
| `/v1/models` lists only loaded models | Loaded model plus the full local catalog, with a `loaded` flag |
| LM Studio GGUFs must be moved into the HF cache | LM Studio folders are scanned automatically (a later note on the same page agrees) |
| Tools are on by default | Only for `unsloth studio run`; the Desktop launch sets no default |
| "Off: disable tool calls" | Wire value `off` = "Run automatically", with no prompts |
| Leave the write token empty if logged in via the CLI | An empty token fails the Hub push |
| HTTPS downloads resume | Not on Windows with huggingface_hub 1.31 |
| Train page accepts PDF and DOCX | Training upload accepts CSV, JSON, JSONL, Parquet only |
| Max Steps 0, weight decay 0.01, no DoRA or CPT | maxSteps 60, weight decay 0.001, DoRA and CPT present |
| `/api/train/stream` | `/api/train/progress` |
| MCP presets include Exa | Unsloth Docs, Context7, Hugging Face |
| Deep Research works with local models only | Also tool-capable saved connections (not Anthropic) |
| Keyless access (not documented at all) | Present, with scopes off, inference and full |
| No telemetry | No app telemetry, but the training library pings HF |

---

## Sources

**Prefixes**
- `SP/` = `~/.unsloth/studio/unsloth_studio/Lib/site-packages/`
- `B/` = `SP/studio/backend/`
- `F/` = `SP/studio/frontend/dist/assets/`
- `CLI/` = `SP/unsloth_cli/`
- `GH815/` = `https://github.com/unslothai/unsloth/tree/v0.1.815-beta/`
- `D/` = `https://unsloth.ai/docs/`

**1. Box and runtime.** `B/run.py:872,961,1206-1221,2524-2541,2851`; `B/utils/parent_watchdog.py:20`; `B/utils/paths/storage_roots.py:230-340`; `GH815/studio/src-tauri/src/process.rs:2338-2343,3494-3506,3640-3649`; `GH815/studio/src-tauri/src/desktop_backend_owner.rs:15-28`; `GH815/studio/src-tauri/src/main.rs:45-72`; `GH815/studio/src-tauri/src/preflight/version.rs:176-198`; `GH815/studio/frontend/src/features/settings/settings-dialog.tsx:187-254`; `~/.unsloth/llama.cpp/UNSLOTH_PREBUILT_INFO.json`; `B/utils/transformers_version.py:1-30`.

**2.1 Inference.**
- Hub and download: `F/settings-C5ITOaaY.js`; `B/hub/routes/inventory.py:128-298,317-365`; `B/hub/schemas/downloads.py:13-47`; `B/utils/hf_cache_settings.py:76-78`; `B/core/inference/local_model_resolver.py:437-447,826-827`; `B/models/inference.py:87`.
- Model folders: `B/utils/paths/storage_roots.py:568-617`; `B/hub/services/models/local_inventory.py:728-735,1062-1064`; `B/hub/services/models/common.py:451-455`; `B/routes/inference.py:29710-29801`.
- Chat load: `F/chat-CLoUlTee.js`; `B/routes/inference.py:15555,18171,18348,18998,19084,19347`; `B/main.py:1606,1615`; `B/models/inference.py:54-416`; `B/routes/training_vram.py:558-606`.
- Load knobs: `B/models/inference.py:54-416`; `B/core/inference/llama_server_args.py:1-183,529-540`; `B/core/inference/llama_cpp.py:3767,3817-3875,4490-4529,4664-4705,6396-6470,22766-22778,26320-26682,27061-27125,33523-33575`.
- Override store: `B/utils/openai_auto_switch_settings.py:17-36,172-194,330-644,717-886`; `B/routes/settings.py:191-208,840-940,1625-1711,1863-2000`; `B/routes/inference.py:8186-8230,9749-9860,10146-10213,14763-14803`; `B/storage/studio_db.py:4677`.
- Model memory and VRAM budget: `B/utils/model_memory_settings.py:4-29,95-120`; `B/utils/vram_budget_settings.py:1-30,95-110`.
- API surface: `B/routes/inference.py:24311,29792,29804,29894,30629,32938,33758,34034,34249,19632,19810,19999,40024`; `B/routes/video.py:1501-1830`; `B/routes/llama_compat.py:11,173-200`; `B/models/inference.py:2994`; `~/.unsloth/llama.cpp/tools/server/server-task.cpp:397`.
- Sampling and overflow: `B/utils/inference/inference_config.py:148-221`; `B/models/inference.py:2356-2385`; `B/routes/inference.py:842-885`.
- Embeddings: `B/routes/inference.py:30330-30356,30629-30700`; `B/core/rag/config.py:11-12`; `B/core/rag/embeddings.py:730-754`; `B/core/rag/embed_llama_server.py:668-700`.
- Sizing and delete: `B/routes/models.py:3466,3514,3786`; `B/hub/routes/inventory.py:317-360`.
- Unload by hand: `B/routes/inference.py:7951-7978,15127-15140,18348-18557`.

**2.2 Fine-tuning.**
- Methods and hyperparameters: `B/models/training.py:27-39,136-215,501-674`; `F/training-eyerSWKt.js`; `F/studio-page-DbvsZOpM.js`.
- Trainers and no RL: `B/core/training/trainer.py:89,178,1041-1160,3380-3423,3873,3971,4320,4379`; `B/core/training/worker.py:1045-1066,1586-1633,1693,3934-3960,4010,5146,5237`.
- Diffusion: `B/core/training/diffusion_train_common.py:64-71,460-505`; `B/routes/training.py:3039-4546`.
- Trainable bases: `B/routes/training.py:353-357,474-644,914-930`.
- Presets: `B/assets/configs/model_defaults/**`; `B/utils/models/model_config.py:3979-3987`.
- Datasets and formatting: `B/hub/services/datasets/local.py:32-36,302-318`; `B/utils/upload_limits.py:11-14`; `B/utils/datasets/dataset_utils.py:345-720`; `B/utils/datasets/chat_templates.py:78-107`; `B/utils/datasets/llm_assist.py:19-20,96-151`.
- Data Recipes: `B/core/data_recipe/service.py:139-148`; `B/routes/data_recipe/jobs.py:265-505,896-975`; `B/routes/data_recipe/seed.py:77-81`.
- VRAM: `B/utils/hardware/vram_estimation.py:10-60`; `B/utils/hardware/VRAM_ESTIMATION.md`; `B/routes/training_vram.py:14-23,558-606`.
- Monitoring, resume, eval: `B/routes/training.py:1188-1206,2073-2106,2417-2443`; `B/core/training/training.py:176-183`; `B/core/training/resume.py:199-213`; `B/core/training/eval_dataset.py:10-36`.
- Windows: `B/core/_msvc_env.py:200-233`.
- Docs: `D/new/studio/start.md`; `D/get-started/fine-tuning-for-beginners/unsloth-requirements.md`.
- GitHub: PR #9310, issue #8777.

**2.3 Export and HF.**
- Export: `B/routes/export.py:84-219,273-612`; `B/models/export.py:36-242`; `B/core/export/export.py:86-157,481-600,650-1780`; `F/export-page-CIF2wbeD.js`; `F/index-DIs5kp_B.js`; `F/hf-auth-_YbH3vlC.js`; `SP/unsloth/save.py:135-232,4418-4427,4787-4828`.
- Token: `B/routes/settings.py:549-617,2181-2188`; `B/storage/credential_secrets.py:1-40,256-300`; `B/hub/routes/token.py:28-44`; `B/utils/hf_token_validation.py:30-197`; `B/auth/authentication.py:390-409`; `B/hub/utils/hf_tokens.py:37-42,363-365`.
- Downloads: `B/hub/services/download_lifecycle.py:364-431`; `B/core/inference/openai_auto_download.py:225-235`; `B/utils/hf_cache_settings.py:25-113,290-477`; `B/utils/download_transport_settings.py:1-52`; `B/hub/utils/resumable_partials.py:3-4,222-251`; `B/utils/hf_xet_fallback.py:33-43`; `B/hub/utils/host_paths.py:1-38`.
- Docs: `D/new/studio/export.md`.
- GitHub: PRs #10943, #11350, #11230; issues #9286, #11698, #10147.

**2.4 Kaggle and cloud.**
- Source: `B/core/inference/tools.py:9185-9443`; `B/utils/paths/sensitive.py:19`; `B/hub/storage/scan_folders.py:93-130`; `B/core/rag/folder_sync.py:157-166,983-991`; `SP/unsloth_zoo/disk_utils.py:61-97`; `SP/unsloth/save.py:1144-1222,1929-1972`; `SP/unsloth/models/_utils.py:2819-2972`; `B/colab.py:22-685`; `B/mcp_server.py:82-268`.
- Unsloth docs: `D/get-started/unsloth-notebooks.md`; `D/get-started/install/vs-code.md`; `D/basics/inference-and-deployment/deploying-llms-with-hugging-face-jobs.md`.
- Kaggle: `https://www.kaggle.com/docs/notebooks`; `https://www.kaggle.com/docs/efficient-gpu-usage`; `https://github.com/Kaggle/kaggle-cli/blob/main/docs/kernels.md`; `.../docs/kernels_metadata.md`; `.../docs/README.md`; `https://github.com/Kaggle/kagglehub` README and `src/kagglehub/config.py:17-37`.
- Hugging Face: `https://huggingface.co/docs/huggingface_hub/guides/jobs`; `.../guides/cli`.
- GitHub: issue #4944, PR #8489.
- Community (phone verification): kaggle.com/general/97939, kaggle.com/product-feedback/506377.

**2.5 Agentic features.**
- RAG: `B/routes/rag.py:407-1109`; `B/core/rag/config.py:11-79,224-248`; `B/core/rag/embeddings.py:55-66,730-754`; `B/core/rag/folder_sync.py:51,157-166,983-1023`.
- MCP: `B/routes/mcp_servers.py:1-548`; `B/storage/mcp_servers_db.py:16-40`; `B/core/inference/mcp_client.py:56-368`; `B/utils/host_policy.py:233-281`; `B/integrations/blender/runtime.py:13-43`; `B/main.py:975-988`; `B/mcp_server.py:1-268`; `SP/studio/MCP.md`.
- Tools and permissions: `B/core/inference/tools.py:96-205,2330-2336,2598-2626,6790-6894,8964-9025,12176-12424,14235-14352,15640-15680`; `B/core/inference/tool_confinement.py:1-19`; `B/core/inference/tool_path_approval.py:69-73`; `B/state/tool_policy.py:1-100`; `B/state/tool_approvals.py:21-40,125`; `B/models/inference.py:2093-2106,2320-2342`.
- Skills: `B/core/inference/skills.py:21-35,370-395,614-615`; `B/routes/inference.py:5250-5300,5669-5673`.
- Research, providers, OAuth: `B/routes/research_runs.py:240-555`; `B/core/inference/providers.py:15-475`; `B/routes/openai_codex_auth.py:62-216`; `B/core/inference/openai_codex_auth.py:31-45`.
- Coding agents: `CLI/commands/start.py:56-75,350-362,510-520,1408,2753-2754,3740-3800`; `B/utils/coding_agents.py:31`.
- Media: `B/core/inference/stt_registry.py:1-27`; `B/core/inference/diffusion_families.py:201-607`; `B/core/inference/video_families.py:138-330`; `B/core/inference/gpu_arbiter.py:4-9`.
- Accounts: `B/routes/accounts.py:126-166`.
- Docs: `D/basics/mcp.md`; `D/new/changelog.md`; `D/integrations/connections.md`; `D/integrations/unsloth-start.md`.

**2.6 Operations and security.**
- Shell and updates: `GH815/studio/src-tauri/tauri.conf.json:43-49`; `GH815/studio/src-tauri/src/desktop_update_policy.rs:121-150`; `GH815/studio/src-tauri/src/staged_update.rs:1-63`; `GH815/studio/src-tauri/src/update.rs:25,67-77,262`; `GH815/studio/src-tauri/src/commands.rs:10-64,957-1006,2715-2804`; `GH815/studio/frontend/src/hooks/use-tauri-update.ts:79-80,319-480`.
- Engine and update checks: `B/utils/update_status.py:25-162`; `B/utils/llama_cpp_update.py:4,1014-1026`; `B/core/inference/llama_cpp.py:8526-8545,11908-11918`; `SP/studio/setup.ps1:141,8626-8628`; `SP/studio/install_python_stack.py:11393-11411`.
- Auth, keys and keyless: `B/auth/storage.py:24-32,115-138,925-1049,1260-1335,1541-1800`; `B/routes/auth.py:58-71,554-705,802-859`; `B/auth/authentication.py:139-186,390-493`; `B/utils/keyless_api_access.py:4-606`; `B/routes/settings.py:3190-3520`.
- LAN, tunnel, preview: `B/utils/lan_access_settings.py:18-485`; `B/lan_access.py:4-303`; `B/cloudflare_tunnel.py:4-317`; `B/utils/remote_access_settings.py:16-17,140-243`; `B/utils/preview_sharing_settings.py:10-14`; `B/utils/client_ip.py:4-30`; `SP/uvicorn/config.py:220-527`.
- Logs and backup: `B/utils/debug_log_sources.py:16-24`; `B/utils/log_retention.py:17`; `B/core/inference/llama_stats.py:256-266`; `B/routes/chat_history.py:1709-1720`; `GH815/studio/frontend/src/features/chat/utils/studio-backup-import.ts:30-40`.
- CLI and uninstall: `CLI/commands/studio.py:221-222,803-850,1712-1790,2147,2660-2663,2987,4046-4075,4821-4913`; `GH815/studio/src-tauri/windows/hooks.nsh:22-28`.
- Docs: `D/get-started/install/updating.md`; `D/basics/api.md`; `D/basics/lan.md`; `D/basics/how-to-serve-local-llms-anywhere-secure-remote-access-with-cloudflare-and-unsloth.md`; `D/desktop.md`.

**Estate rules referenced:** `~/Desktop/the-array/CLAUDE.md` durable rules on the VRAM spill cliff, KV-offload inversion, KV cost by architecture, LM Studio memory residue and the memory wedge. The prior evaluation `handoffs/2026-09-09-unsloth-desktop-evaluation.md` was superseded where it said tools are on by default for API callers under the Desktop launch.
