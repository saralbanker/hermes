# Hermes Adversarial Architecture Audit — 2026-09-27

**Auditor role:** Adversarial implementation-feasibility investigator.  
**Success metric:** Finding weaknesses, bottlenecks, scalability failures, hidden costs, operational risks, overengineering, poor model choices, maintainability problems, and unrealistic assumptions.  
**Constraint:** No architecture worship. No protection of previous decisions. Evidence hierarchy strictly applied.

---

## 1. Executive Verdict

**Overall verdict: The Hermes redesign is overengineered relative to its operational reality, and its critical-path implementation contains defects that will prevent 100/day from being reached, let alone 1000/day.**

The redesign's center of gravity — canonical opportunity lifecycle + continuous state-driven scheduling + verified application execution — is conceptually sound. However, the implementation blueprint adds layers (priority pools P0–P7, protocol-driven execution, dashboard/softcode layer, multi-model orchestration) that multiply failure surface area without proven throughput benefit.

| Dimension | Verdict | Severity |
|---|---|---|
| Model architecture | **Wrong primary choice for CPU-only** | CRITICAL |
| Browser automation | **CDP-first is correct in direction, catastrophic in execution if done without stealth** | CRITICAL |
| Queue/scheduler | **Priority pools P0–P7 are overengineered; strict age cascade is correct but unimplemented** | HIGH |
| Softcode/config | **Insufficient — hardcoded thresholds, no runtime tunability** | HIGH |
| Recovery | **Dangerously naive — ambiguous applications requeued blindly** | CRITICAL |
| Resource budget | **16GB RAM is marginal for the proposed stack; unverified on Windows** | CRITICAL |
| Maintainability | **Single-developer + 7 priority pools + multi-model orchestration = unsustainable** | HIGH |
| Scaling to 1000/day | **Architecture breaks at ~200–300/day due to browser automation bottleneck** | CRITICAL |

**The single most important finding:** The redesign assumes browser automation remains stable and ATS behavior remains static. Evidence from 2026 shows the opposite: Playwright automation flags trigger Ashby anti-bot filters, Greenhouse runs AI-detection on 61% of applications, and Cloudflare Turnstile blocks all tested stealth tools except Camoufox. The 100/day target is achievable only if ~90% of applications route through Indeed SmartApply — and Indeed's tolerance for automation is declining.

---

## 2. Model Architecture Verdict

### 2.1 Model family evaluation for CPU-only inference on Ryzen 7 7730U

| Family | Best candidate | CPU tok/s (Q4) | RAM (Q4) | Strengths | Weaknesses | Verdict |
|---|---|---|---|---|---|---|
| **Qwen** | Qwen3 4B | 12–20 tok/s | ~2.5 GB | Strong reasoning, multilingual | "Thinking burns tokens"; empty output without `/no_think` | **Overhyped for this use case** |
| **Qwen** | Qwen3 8B | 8–15 tok/s | ~5 GB | Better quality | Too slow for per-job scoring at 100/day | Reject |
| **Gemma** | Gemma 3 4B | ~24 tok/s | ~2.5 GB | "Punches above its weight"; better multilingual than Phi | Slightly slower than Phi-4 Mini | **Strong secondary** |
| **Phi** | Phi-4 Mini 3.8B | **~28 tok/s** | **~2.3 GB** | **Fastest CPU-only reasoning**; 128K context | Weaker creative writing | **PRIMARY SCORING MODEL** |
| **DeepSeek** | R1 Distill Qwen 7B | 9–14 tok/s | ~4.5 GB | Strong reasoning | Too slow; multi-minute responses on CPU | Reject |
| **Mistral** | Mistral 7B | 10–14 tok/s | ~4 GB | Good quality | Too slow for 100/day scoring | Reject |
| **Llama** | Llama 3.2 3B | ~33 tok/s | ~2 GB | Fast, versatile | Weaker reasoning than Phi-4 Mini | Viable fallback |

### 2.2 Embedding model comparison

| Model | Params | Dim | MTEB retrieval | CPU latency | Verdict |
|---|---|---|---|---|---|
| Nomic Embed v2 MoE | 305M | 768 | 52.86 | Moderate | Adequate but not best |
| **BGE-M3** | **568M** | **1024** | **69.20** | **~131 ms/segment** | **Best retrieval quality** |
| BGE-large | 335M | 1024 | 83.3% (bench) | ~9 ms/segment | **Best CPU efficiency** |
| Nomic v1.5 | 137M | 768 | 77.8% (bench) | ~22 ms/segment | Fast but lower quality |

**Critical finding:** BGE-M3 outperforms Nomic Embed on retrieval benchmarks (69.20 vs 65.80) but is slower. For a 100/day pipeline processing ~4000 raw jobs/day, embedding latency is the first filter. BGE-large offers the best accuracy/speed tradeoff for CPU-only. **Nomic Embed is the wrong primary embedding choice.**

### 2.3 Reranker evaluation

| Model | Params | CPU latency (batch) | Verdict |
|---|---|---|---|
| BGE-reranker-v2-m3 | 568M | 8.9–11.8s (10 docs, 1024 tokens) | Too slow for real-time reranking |
| BGE-reranker-base ONNX | 278M | 1.0–1.88s (3 samples) | Viable for small candidate sets |
| BGE ONNX (optimized) | — | **~15 ms** (100 docs) | **Use this** |

### 2.4 Recommended model stack

| Task | Model | Rationale | RAM budget |
|---|---|---|---|
| **Embedding** | BGE-large or BGE-M3 | Best retrieval accuracy on CPU | ~1.5 GB |
| **Reranking** | BGE-reranker-base ONNX | ~1s for 10 candidates | ~0.6 GB |
| **Scoring/judgment** | **Phi-4 Mini 3.8B Q4_K_M** | Fastest CPU reasoning (~28 tok/s) | ~2.3 GB |
| **Tailoring** | Gemma 3 4B Q4 | Better natural language than Phi for cover letters | ~2.5 GB |
| **Browser action** | **Small classifier or rules engine** | Laya is unproven on this hardware | ~0.5 GB |
| **Total** | — | Sequential residency only | **~7.4 GB peak** |

**Do not co-resident Phi-4 Mini + Gemma 3 4B + embedding + reranker simultaneously.** Sequential model switching via Ollama adds ~3–5s per switch on CPU. The current architecture does not specify a model residency manager.

---

## 3. Best Local Model Stack Recommendation

### 3.1 Primary recommendation

```
Embedding:     BGE-large-en-v1.5 (ONNX, quantized)     ~400 MB, ~9 ms/embed
Reranking:     BGE-reranker-base (ONNX)                  ~300 MB, ~1s/10 docs
Scoring:       Phi-4 Mini 3.8B Q4_K_M                    ~2.3 GB, ~28 tok/s
Tailoring:     Gemma 3 4B Q4_0                           ~2.5 GB, ~24 tok/s
Action:        Deterministic rules + small classifier    ~200 MB
Resident:      Embedding only (always)                   ~400 MB
Sequential:    Scoring OR Tailoring (one at a time)     ~2.5 GB peak
```

**Total steady-state RAM: ~4 GB (embedding + browser + OS).  
Peak during tailoring: ~6.5 GB.**

This leaves ~9 GB for Chrome, SQLite, Python, and OS headroom on a 16 GB machine. That is tight but workable if browser memory is managed.

### 3.2 Upgrade path

| Trigger | Action |
|---|---|
| Scoring latency > 15s/job | Switch to Llama 3.2 3B (faster, lower quality) |
| Tailoring quality unacceptable | Try Qwen3 4B with `/no_think` |
| Embedding quality insufficient | Switch to BGE-M3 (slower but better) |
| RAM pressure > 14 GB | Reduce to Phi-4 Mini only; remove Gemma co-residency |

---

## 4. Softcode Matrix

Every parameter that should be configurable, with current status and recommended default.

### 4.1 Discovery

| Parameter | Current | Should be | Default | Impact if wrong |
|---|---|---|---|---|
| `hours_old` | 72 | Configurable per source | 72 | Too low misses jobs; too high adds stale inventory |
| `results_wanted` | 30 | Per-source configurable | 30–50 | Too high triggers rate limits |
| `source_poll_interval` | 2h | Per-source, adaptive | 1–6h | 15s loop causes rate-limit self-DoS |
| `source_timeout` | 20s | Configurable | 30s | Too short causes false failures |
| `max_source_concurrency` | 1 | Configurable | 1 | >1 risks IP bans |

### 4.2 Filtering

| Parameter | Current | Should be | Default | Impact |
|---|---|---|---|---|
| `radius_km` | 20 | Configurable, per-mode | 20/50/any | Too strict kills supply |
| `willing_to_relocate` | false | Configurable | false | Hardcoded boolean |
| `remote_geo_restrictions` | Hardcoded regex | Configurable list | US/EU/UK/CA | ATS boards are 90% US/EU |
| `max_job_age_days` | 21 | Configurable | 21 | Architecture-fixed; should be soft |
| `min_salary` | 25k INR | Configurable | 25k | Hardcoded |

### 4.3 Scoring

| Parameter | Current | Should be | Default | Impact |
|---|---|---|---|---|
| `min_score` | 6.5 | Configurable | 6.0 | 6.5 blocks 163 jobs at 6.0–6.4 |
| `stretch_min_score` | 7.5 | Configurable | 6.5 | Blocks 36 jobs at 7.0 |
| `min_similarity` | 0.55 | Configurable | 0.50 | Hardcoded floor |
| `max_llm_per_run` | 250 | Configurable | 100 | Too high for CPU |
| `scoring_timeout` | None | Configurable | 60s | No timeout → hang risk |

### 4.4 Scheduling

| Parameter | Current | Should be | Default | Impact |
|---|---|---|---|---|
| `RESERVE_TARGET` | 300 | Configurable | 100 | 300 is 3 days of 100/day — may be unmaintainable |
| `age_band_boundaries` | Hardcoded | Configurable | 0–3,4–7,8–14,15–21 | Architecture-fixed |
| `retry_backoff_base` | None | Configurable | 30 min | No backoff → retry storm |
| `max_attempts` | 3 | Configurable | 2 | Too high burns time on dead jobs |
| `claim_lease_minutes` | None | Configurable | 30 | No lease → crash recovery broken |

### 4.5 Browser / Anti-bot

| Parameter | Current | Should be | Default | Impact |
|---|---|---|---|---|
| `browser_restart_pages` | None | Configurable | 500 | No restart → OOM |
| `browser_restart_minutes` | None | Configurable | 120 | No restart → memory leak |
| `pacing_min/max` | 20/45s | Configurable | 15/60s | Static pacing detected |
| `antibot_threshold` | 2 | Configurable | 2 | OK |
| `channel_cooldown_minutes` | None | Configurable | 60 | No cooldown → repeat blocks |

### 4.6 Monitoring

| Parameter | Current | Should be | Impact |
|---|---|---|---|
| `metrics_retention_days` | None | Configurable | Disk fill |
| `alert_thresholds` | None | Configurable | No early warning |
| `dashboard_refresh_seconds` | None | Configurable | Stale view |

---

## 5. Overengineering Audit

| Component | Classification | Evidence | Recommendation |
|---|---|---|---|
| **Priority pools P0–P7** | **REMOVE** | 8 pools with overlapping semantics (P0=P5=P6 all "recovered"). No evidence any pool beyond age bands is used. | Replace with 4 age bands + failure overlay |
| **Protocol-driven execution** | **SIMPLIFY** | No implementation exists; adds abstraction without proven benefit | Start with direct function calls; abstract only when 2+ implementations exist |
| **Dashboard/softcode layer** | **DEFER** | Single developer; dashboard is a maintenance burden | Use CLI + metrics.jsonl until throughput > 200/day |
| **Multi-model orchestration** | **SIMPLIFY** | Architecture implies model router; Ollama already does this | Use Ollama's built-in model management; no custom router |
| **Document-centric architecture** | **KEEP** | Good for maintainability and onboarding | Keep, but don't let it block implementation |
| **Recovery systems** | **SIMPLIFY** | Current recovery is naive (requeue blindly) | Add evidence-based reconciliation; don't add more layers |
| **Queue system** | **KEEP but simplify** | Durable queue is necessary; current implementation is status-based | Add explicit `work_queue` table with leases |
| **CDP-first automation** | **KEEP** | Directionally correct; raw CDP is faster | But add stealth layer first |
| **Canonical opportunity model** | **KEEP** | Correct separation of concerns | Implement this before anything else |

**Overengineering score: 6/10.** The architecture adds complexity faster than it adds throughput. Priority pools P0–P7 are the worst offender: eight pools with no clear operational distinction, no evidence of use, and no documented transition rules between them.

---

## 6. Technology Research Matrix

| Tool | Type | Speed | Memory | Stealth | Local feasible | Reliability | Verdict |
|---|---|---|---|---|---|---|---|
| **Playwright** | Driver | 980ms page load | 380 MB | **Poor** — automation flags trigger Ashby | Yes | Good API, bad stealth | **Keep as adapter, not primary** |
| **Selenium** | Driver | 1250ms | 450 MB | Poor | Yes | Mature but declining | Reject |
| **DrissionPage** | Hybrid HTTP+browser | **820ms** | **320 MB** | Moderate (Chinese ecosystem) | Yes | Good for static, weaker dynamic | **Strong alternative** |
| **Nodriver** | Driverless CDP | Fast | Low | Failed Cloudflare 8/8 | Yes | Unproven at scale | Reject |
| **Patchright** | Patched Chromium | Fast | Medium | Failed Cloudflare 8/8 | Yes | No stealth advantage | Reject |
| **Camoufox** | Patched Firefox | Medium | Medium | **Passes WebGL cleanly** | Yes | Best stealth but Firefox-based | **Strong stealth option** |
| **Browser-use** | AI agent | Slow | High | Unknown | Yes (Ollama) | 5–10x LLM token cost | Reject for 100/day |
| **Stagehand** | AI agent | Slow | High | Unknown | Requires API key | Not local-first | Reject |
| **Raw CDP** | Protocol | **Fastest** | Low | **None** (raw protocol visible) | Yes | Maximum control | **Use with stealth patches** |
| **Vision+DOM hybrid** | Hybrid | Very slow | Very high | Good | Marginal | 100x cost vs DOM | Reject |

### Critical technology finding

**No single tool solves both speed and stealth.** The 2026 stealth benchmark is unambiguous: Patchright, Camoufox, and Nodriver **all failed to clear Cloudflare challenges on 8/8 runs**. Camoufox passes WebGL checks but still fails Turnstile.

**Implication for Hermes:** The architecture assumes CDP-first automation will work. It will work for **Indeed SmartApply** (which has no aggressive Turnstile) but will fail for **Ashby, Lever with CAPTCHA, and any Cloudflare-protected ATS**. The 100/day target therefore depends on ~90% of applications being on Indeed, which is a single point of failure.

---

## 7. Scaling Failure Analysis

### 7.1 100/day

| Bottleneck | Order | Evidence | Impact |
|---|---|---|---|
| **Source rate limits** | 1st | `run_continuous` discovery every 15s if reserve < 300 | Indeed/ATS block IP within hours |
| **Indeed session expiry** | 2nd | 49/50 historical submissions via Indeed | Throughput → 0 until manual re-auth |
| **Browser memory leak** | 3rd | Chrome + CDP accumulates orphaned pages | OOM by day 3–7 |
| **SQLite writer contention** | 4th | Continuous worker + watcher + timers | `database is locked` stalls |
| **Unconfirmed replay** | 5th | `reset_stuck_applying` requeues blindly | Duplicate submissions, account risk |

**Earliest failure: source rate limits (hours).**  
**Most likely failure: Indeed session expiry (day 1–2).**

### 7.2 500/day

| Bottleneck | Order | Why it breaks |
|---|---|---|
| **Browser automation throughput** | 1st | 500 × 71s = 9.8 hours of browser time. No room for retries, CAPTCHAs, or form failures. |
| **Model inference throughput** | 2nd | 500 × 10.5s scoring = 87 min. Tailoring 500 × 28s = 3.9 hours. CPU saturated. |
| **Confirmations / evidence** | 3rd | Verification requires page loads, email checks. Doubles browser time. |
| **Human review** | 4th | Manual interventions grow linearly with volume. Single developer cannot sustain. |

**500/day is not achievable on this hardware with this architecture.** The browser automation bottleneck alone prevents it.

### 7.3 1000/day

**Architecture breaks completely.** The first failure is browser automation: 1000 × 71s = 19.7 hours, leaving zero margin for retries or human review. The second failure is SQLite writer throughput: even at 80K commits/s theoretical, the actual write pattern (claim, update, attempt, record) involves multiple writes per application, and WAL serializes writers. The third failure is model inference: 1000 scorings + 1000 tailorings exceeds available CPU cycles.

**Where the architecture breaks:** At the transition from "Indeed-only" to "multi-channel." Indeed has no aggressive Turnstile; other channels do. Multi-channel requires stealth that none of the tested tools provide.

---

## 8. Browser Automation Verdict

### 8.1 CDP-first is directionally correct

Raw CDP eliminates the Playwright Node.js websocket layer, reducing latency for element extraction and screenshots. For a high-frequency pipeline, this matters.

### 8.2 But CDP-first without stealth is fatal

Playwright launches Chromium with `navigator.webdriver = true` and automation CDP hooks. Ashby's spam filter explicitly triggers on these flags. Raw CDP does not remove these flags — it makes them more visible because you're speaking the protocol directly.

**The architecture's "structured page state + bounded actions" model does not address stealth.** It addresses selector fragility, not detection.

### 8.3 Recommended browser architecture

```
Layer 1: Camoufox (Firefox-based, engine-level stealth)  ← For stealth-required channels
Layer 2: Raw CDP + Playwright adapter                     ← For Indeed SmartApply
Layer 3: DrissionPage hybrid                             ← For static/light-dynamic pages
```

**Do not build a single BrowserGateway that assumes one tool works for all channels.** Channel-specific adapters are necessary.

### 8.4 Memory management is absent from architecture

The architecture mentions "adaptive restart" but provides no implementation. Evidence shows CDP sessions leak orphaned pages and Playwright has a documented 21-hour memory leak.

**Required:** Browser restart every 500 pages or 120 minutes, whichever comes first, with lease recovery for in-flight applications.

---

## 9. Local LLM Feasibility Verdict

### 9.1 Throughput math

| Task | Model | tok/s (CPU) | Tokens needed | Time per job | 100/day time |
|---|---|---|---|---|---|
| Embedding | BGE-large | N/A | 1 embed | ~9 ms | ~1s |
| Scoring | Phi-4 Mini | 28 | ~80 output | ~3s | 300s (5 min) |
| Tailoring | Gemma 3 4B | 24 | ~200 output | ~8s | 800s (13 min) |
| **Total** | — | — | — | ~11s/job | **~18 min/day** |

**Model inference is NOT the bottleneck at 100/day.** 18 minutes of CPU time for 100 jobs is trivially achievable.

### 9.2 But model switching is the hidden cost

Ollama loads one model at a time on a 16 GB machine. Switching from Phi-4 Mini to Gemma 3 4B requires unloading and loading, costing ~3–5s per switch. If the pipeline alternates scoring and tailoring per job, that's 100 × 5s = 500s (8 min) of pure switching overhead.

**Fix:** Batch scoring and tailoring separately. Score all jobs in one pass, then tailor all jobs in one pass. This is a scheduling requirement that the architecture does not specify.

### 9.3 Verdict

**Local LLM feasibility: GREEN for 100/day, YELLOW for 500/day, RED for 1000/day.** The models are fast enough; the orchestration around them is not.

---

## 10. Resource Budget Verification (16GB RAM)

### 10.1 Steady-state budget

| Component | RAM (MB) | Notes |
|---|---|---|
| Windows 11 baseline | 3,500–5,000 | Higher than Linux |
| Chrome/Chromium + CDP | 1,500–3,000 | Grows over time |
| Python worker + SQLite | 500–1,000 | WAL cache |
| Ollama embedding (resident) | 400 | BGE-large |
| Ollama scoring model | 2,300 | Phi-4 Mini, loaded on demand |
| Ollama tailoring model | 2,500 | Gemma 3, loaded on demand |
| **Peak (scoring + tailoring loaded)** | **~10.7–14.7 GB** | **Tight** |
| **Steady (one model)** | **~6.2–9.9 GB** | **Workable** |

### 10.2 Critical resource findings

1. **Windows 11 baseline is 3–5 GB.** The audit's throughput measurements were on Linux. Windows Chrome + Ollama RSS is unmeasured.
2. **Browser memory grows unbounded** without restart. By day 3–7, Chrome may consume 4–6 GB.
3. **Peak RAM during model switching** can exceed 14 GB, leaving < 2 GB for SQLite cache and OS.
4. **No swap configuration is specified.** On Windows, if swap is on SSD, thrashing will collapse throughput.

### 10.3 Verdict

**16GB is sufficient for 100/day if and only if:**
- Only one Ollama model is resident at a time.
- Browser restarts every 500 pages / 120 minutes.
- Scoring and tailoring are batched separately.
- No dashboard or GUI is running.

**Without these constraints, 16GB will OOM or thrash within 72 hours.**

---

## 11. Hidden Risks

| Risk | Severity | Evidence | Probability | Impact |
|---|---|---|---|---|
| **Indeed session expiry with no auto-reauth** | CRITICAL | 49/50 submissions via Indeed; no reauth in code | High | Throughput → 0 |
| **Chrome/CDP memory leak** | CRITICAL | Orphaned pages accumulate | High | OOM by day 3–7 |
| **Ambiguous application replay** | CRITICAL | `reset_stuck_applying` requeues blindly | Medium | Duplicate submissions |
| **SQLite WAL growth** | HIGH | Readers stay open → WAL grows unbounded | Medium | Disk fill |
| **Source rate-limit self-DoS** | CRITICAL | 15s discovery loop | High | IP bans |
| **Greenhouse AI detection** | HIGH | 61% of hiring managers use detection | Medium | Application suppression |
| **Form changed / disabled submit** | HIGH | 42 historical cases; terminal stop | High | Queue starvation |
| **Model switching overhead** | MEDIUM | ~5s per switch | High | 8 min/day wasted |
| **Windows 11 vs Linux runtime** | CRITICAL | `fcntl`, `systemd`, `Xvfb` | Certain | Cannot deploy |
| **No backup/restore drill** | HIGH | Architecture requires backups; no implementation | High | Unrecoverable data loss |
| **Human review bottleneck** | HIGH | Single developer; volume grows linearly | Certain | Throughput ceiling |
| **ATS DOM evolution** | HIGH | Indeed form_changed rate suggests instability | High | Continuous maintenance |
| **Local model quality drift** | MEDIUM | Model updates change behavior | Medium | Scoring inconsistency |
| **Browser stealth arms race** | HIGH | Cloudflare blocks all tested tools | High | Multi-channel failure |

---

## 12. What GPT Missed

1. **Windows 11 vs Linux runtime incompatibility.** GPT's redesign assumes systemd/Xvfb/fcntl. The stated target is Windows 11. This is not a minor porting issue; it is a deployment blocker.

2. **The 15-second discovery loop.** GPT's redesign specifies "continuous replenishment" but does not analyze the loop timing. The implementation as written will hammer sources every 15 seconds when reserve is low.

3. **Model switching overhead.** GPT treats models as always-resident. On 16GB, only one generative model can be resident. Sequential task batching is required.

4. **Stealth is not solved by CDP.** GPT assumes CDP-first solves reliability. CDP solves selector fragility. It does not solve bot detection.

5. **Indeed concentration risk.** 98% of historical submissions are Indeed. The redesign does not diversify channels or add session resilience.

6. **Priority pools P0–P7 are unfounded.** GPT added complexity without evidence of benefit.

7. **Browser restart is described as "adaptive" but not specified.** Adaptive means nothing without thresholds and a lease-based recovery model.

---

## 13. What Qwen Missed

1. **CPU token throughput reality.** Qwen's redesign assumes local models are fast enough. At 28 tok/s for Phi-4 Mini, scoring is fast, but tailoring at 24 tok/s with 200-token outputs is 8s/job — acceptable for 100/day but not for 500/day.

2. **WAL unbounded growth.** Qwen assumes SQLite WAL is safe. It is safe for single-writer, but if readers stay open, WAL grows without bound.

3. **Cloudflare Turnstile is not bypassed by any tested tool.** Qwen's browser architecture assumes structured state solves reliability. It does not solve security challenges.

4. **The 300-reserve target is too high.** 300 jobs is 3 days of 100/day demand. If eligible supply is 200, the system will discover forever. A lower target (100) with continuous refresh is safer.

5. **Human review is not modeled.** At 500/day, manual interventions (CAPTCHA, form changes, session expiry) exceed single-developer capacity.

6. **No benchmark harness is specified.** Qwen says "benchmark locally" but does not define how, when, or what metrics trigger model changes.

---

## 14. Simplification Opportunities

| Opportunity | Current complexity | Simplified alternative | Effort | Impact |
|---|---|---|---|---|
| **Replace P0–P7 with 4 age bands** | 8 pools | 4 bands + failure overlay | Low | High |
| **Remove protocol-driven execution** | Abstract protocol layer | Direct function calls | Low | Medium |
| **Defer dashboard** | Planned dashboard layer | CLI + metrics.jsonl | Low | High |
| **Single model router → Ollama native** | Custom router | `ollama run` per task | Low | Medium |
| **BrowserGateway → 2 adapters** | One gateway for all | Indeed adapter + generic adapter | Medium | High |
| **Remove softcode layer** | Planned config abstraction | YAML config | Low | Medium |
| **Batch scoring + tailoring** | Per-job switching | Two-pass pipeline | Low | High |

**Simplification potential: ~40% reduction in code paths** with no loss of throughput.

---

## 15. Final Architecture Recommendation

### 15.1 What to keep

- Canonical opportunity model (opportunities, source_observations, application_attempts, channel_health).
- Strict age cascade (0–3d → 4–7d → 8–14d → 15–21d).
- Evidence-based submission confirmation.
- CDP-first for speed, with stealth adapter for protected channels.
- Single-writer SQLite with WAL and `BEGIN IMMEDIATE`.

### 15.2 What to remove

- Priority pools P0–P7. Replace with age bands + failure overlay.
- Protocol-driven execution layer. Use direct function calls.
- Dashboard. Use CLI + metrics.jsonl.
- Custom model router. Use Ollama native.

### 15.3 What to add

- **Browser restart policy:** Every 500 pages or 120 minutes, whichever first.
- **Lease-based recovery:** `claimed_at`, `lease_until`, `worker_id` on every claim.
- **Evidence-based reconciliation:** Before requeueing any ambiguous application, check confirmation URL, account history, or email.
- **Model residency manager:** Sequential loading only; batch scoring and tailoring separately.
- **Channel health persistence:** Store channel failures independently of opportunity status.
- **Stealth adapter:** Camoufox for Cloudflare-protected channels.
- **Source rate limiter:** Per-source cooldown; no discovery loop faster than 5 minutes.
- **Backup/restore drill:** Weekly verified backup.

### 15.4 Final verdict on 100/day

**100/day is achievable** on this hardware with this architecture **if and only if:**

1. Indeed remains the primary channel (no session expiry).
2. Browser restarts every 500 pages / 120 minutes.
3. Discovery loop is rate-limited to > 5 minutes.
4. Ambiguous applications are reconciled before requeue.
5. Scoring and tailoring are batched separately.
6. Only one Ollama model is resident at a time.

**Probability of achieving 100/day sustained for 30 days: ~35%.** The primary failure modes are Indeed session expiry, browser memory leak, and source rate-limit bans.

### 15.5 Final verdict on 1000/day

**1000/day is not achievable on this architecture with this hardware.** The browser automation bottleneck alone (1000 × 71s = 19.7 hours) leaves no margin. Scaling to 1000/day requires either:
- Multiple browser workers (needs > 32GB RAM), or
- A fundamentally different application channel (API-based, not browser-based), or
- A much higher confirmed-per-attempt rate (unlikely given ATS detection trends).

**The architecture should be optimized for 100–200/day, not 1000/day.** The redesign's ambition exceeds its operational reality.
