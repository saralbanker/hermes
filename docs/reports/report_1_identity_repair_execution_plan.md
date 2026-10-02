# Report 1: Employer-Visible Identity Integrity Repair Execution Plan

**Document ID:** HERMES-EXEC-PLAN-01  
**Target:** Hermes Automated Application Engine  
**Evidence Hierarchy:**
1. Authoritative Resume PDF ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf))
2. Verified Indeed Profile Data
3. Production Database Records ([db/applications.db](file:///mnt/data/rj/hermes/db/applications.db))
4. Current Config Files ([config.yaml](file:///mnt/data/rj/hermes/config.yaml), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml))
5. Generated Cover Letters ([output/tailored/](file:///mnt/data/rj/hermes/output/tailored/))
6. Tests ([tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py), [tests/test_adversarial.py](file:///mnt/data/rj/hermes/tests/test_adversarial.py))
7. Historical Planning Documents ([agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md))

---

## SECTION A — Confirmed Corruptions

| Finding ID | Corruption Description | Ground Truth (Evidence Hierarchy) | Corrupted State / Evidence | Severity | Employer Exposure | Verification Status |
|---|---|---|---|---|---|---|
| **CORR-01** | **Incorrect Phone Number Propagation** | **Tier 1 (Authoritative Resume PDF):** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf) line 3 reads `+91 9106990136`. | **Evidence:**<br>1. 167 generated cover letters in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) contain `+91 9016990136` (e.g. [output/tailored/aapkapainter-software-intern-6491-cover.txt](file:///mnt/data/rj/hermes/output/tailored/aapkapainter-software-intern-6491-cover.txt) line 7).<br>2. 22 submitted applications in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`status = 'submitted'`) link to cover letters with `9016990136`.<br>3. Form fill screenshots verify live transmission: [screenshots/dryrun-lever-hevodata.png](file:///mnt/data/rj/hermes/screenshots/dryrun-lever-hevodata.png), [screenshots/dryrun-ashby-anyscale.png](file:///mnt/data/rj/hermes/screenshots/dryrun-ashby-anyscale.png), [screenshots/dryrun-greenhouse-anthropic.png](file:///mnt/data/rj/hermes/screenshots/dryrun-greenhouse-anthropic.png).<br>4. [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md) lines 264 & 1226 retain `9016990136`. | **CRITICAL** | **Active & Historical.** 22 live submitted applications contain this corrupted number; recruiters calling candidate fail to connect. | **CONFIRMED** |
| **CORR-02** | **Placeholder Leakage into Employer Materials** | **Tier 1 & Tier 2:** Candidate identity is fully resolved; no unfilled bracketed `[...]` or template tokens `{...}` may appear in employer text. | **Evidence:**<br>1. 226 cover letters in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) contain unparsed tokens (`[Your Name]`, `[Company Name]`, `[Your Address]`, `[Email Address]`, `[Phone Number]`, `[X] years`, `[Y] hours per month`, `[percentage]`, `{devlogic}`).<br>2. 20 submitted applications in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) link to cover letters containing raw placeholders.<br>3. Examples: [output/tailored/infuse-manual-qa-engineer-junior-middle-remote-contract-cover.txt](file:///mnt/data/rj/hermes/output/tailored/infuse-manual-qa-engineer-junior-middle-remote-contract-cover.txt) lines 5–13; [output/tailored/devlogic-founding-engineer-cover.txt](file:///mnt/data/rj/hermes/output/tailored/devlogic-founding-engineer-cover.txt) lines 3 & 9 (`{devlogic}`); [output/tailored/infosys-software-developer-java-python-golang-cover.txt](file:///mnt/data/rj/hermes/output/tailored/infosys-software-developer-java-python-golang-cover.txt) line 26.<br>4. Missing validation check: [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) `validate_letter` lacks a regex gate for bracketed/curly placeholders. | **CRITICAL** | **Active & Historical.** 20 submitted employers received cover letters with obvious template markers (`[Your Name]`, `[X] years`), discrediting candidate authenticity. | **CONFIRMED** |
| **CORR-03** | **Hallucinated Experience & Credential Claims** | **Tier 1 (Authoritative Resume PDF) & Tier 4 ([profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md)):** 1+ year paid freelance; 4 years hands-on development overall; no bachelor's degree; zero production AWS/Kubernetes/GCP/Azure/Java; zero team-lead experience. | **Evidence:**<br>1. Screenshot [screenshots/verify-indeed-2295.png](file:///mnt/data/rj/hermes/screenshots/verify-indeed-2295.png) proves live form autofill entered `1` for "How many years of amazon connect experience do you have?" and `1` for "How many years of amazon Lex experience do you have?" (candidate has 0).<br>2. 132 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) claim AWS, Azure, GCP, or Kubernetes.<br>3. Specific files: [output/tailored/enfycon-senior-software-engineer-java-and-javascript-ecosyst-cover.txt](file:///mnt/data/rj/hermes/output/tailored/enfycon-senior-software-engineer-java-and-javascript-ecosyst-cover.txt) claims `6+ years of professional`; [output/tailored/fullstacktechies-python-developer-web-data-extraction-ai-cover.txt](file:///mnt/data/rj/hermes/output/tailored/fullstacktechies-python-developer-web-data-extraction-ai-cover.txt) claims `degree in Computer Science`; [output/tailored/stanbic-bank-tanzania-engineer-software-cover.txt](file:///mnt/data/rj/hermes/output/tailored/stanbic-bank-tanzania-engineer-software-cover.txt) claims `led a team`.<br>4. 9 submitted applications in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) link to cover letters containing fabricated claims. | **CRITICAL** | **Active & Historical.** 9 submitted employers received cover letters with fabricated credentials, degrees, and seniority levels; active forms on Indeed risk autofilling non-zero years for absent skills. | **CONFIRMED** |
| **CORR-04** | **Company-Name Corruption ("Unknown")** | **Tier 3 (Production DB) & Tier 5 (Cover Letters):** Employer name must reflect verified company identity; cover letters must never address an employer as "Unknown". | **Evidence:**<br>1. 297 rows in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) `jobs` table have `company = 'Unknown'` or empty.<br>2. 14 submitted applications were delivered to employers as company `Unknown`.<br>3. 1 active job queued in `status = 'tailored'` (job id 9677) is company `Unknown`.<br>4. 20 cover letters in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) literally open with `"I'm applying for the ... role at Unknown."` (e.g. `unknown-qa-testing-engineer-cover.txt`, `unknown-auth0-developer-1850-cover.txt`).<br>5. 118 files on disk are named `unknown-*-cover.txt`. | **HIGH** | **Active & Historical.** 14 submitted jobs addressed companies as "Unknown"; 1 queued job in `tailored` will be submitted on next timer run unless intervened. | **CONFIRMED** |
| **CORR-05** | **Salary-Answer Corruption** | **Tier 4 ([config.yaml](file:///mnt/data/rj/hermes/config.yaml)):** Monthly floors ₹25,000 (India) / ₹30,000 (global). Forms asking for numeric salaries, annual CTC, or foreign currencies must receive valid, non-breaking answers. | **Evidence:**<br>1. [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) `_salary_answer` unconditionally returns the verbose string `₹{amount:,}/month minimum, open to a competitive offer in line with the role's published range`.<br>2. On numeric input fields (`<input type="number">` or annual CTC inputs on ATS/Indeed), this string causes input rejection, form stall, or truncation to `25000` (which on an annual form reads as ₹25,000/year instead of per month).<br>3. For "current CTC", [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) returns `s["current_ctc"]` = `Not currently employed (freelance)`, causing failure on numeric salary fields. | **HIGH** | **Active.** Affects any active ATS or Indeed application form requiring numeric salary fields or annual compensation figures. | **CONFIRMED** |
| **CORR-06** | **Hardcoded Profile Drift & Uncommitted State** | **Tier 1 (Authoritative Resume PDF) & Tier 4 ([config.yaml](file:///mnt/data/rj/hermes/config.yaml)):** All runtime systems must source identity deterministically without uncommitted drift or conflicting hardcoded values. | **Evidence:**<br>1. Working tree drift: [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [tests/test_adversarial.py](file:///mnt/data/rj/hermes/tests/test_adversarial.py), and [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py) were modified in the working copy but uncommitted.<br>2. Summary drift: [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf) includes `(Claude Code)` in its summary line, whereas uncommitted edits in [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) removed `(Claude Code)`.<br>3. Hardcoded values in source code: [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py) hardcodes `GMAIL_USER = "saralbanker1@gmail.com"`; [src/score.py](file:///mnt/data/rj/hermes/src/score.py) hardcodes `SARAL_CORE_SKILLS`; [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) and [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) hardcode `Saral_Banker_Cover_Letter.txt`. | **MEDIUM** | **Internal & Downstream.** Causes divergence between what local tests expect, what config dictates, and what background processes execute. | **CONFIRMED** |

---

## SECTION B — Repair Order

Ranked by:
1. **Employer Impact:** Direct disqualification or reputational damage with recruiters.
2. **Probability of Active Exposure:** Likelihood of corruption leaking in the next automated application batch (`hermes.timer` fires every scheduled window; next run in ~4 hours).
3. **Ease of Correction:** Scope, isolation, and verification complexity.

| Rank | Fix Target | Primary Justification | Active Risk if Delayed |
|---|---|---|---|
| **1** | **Pipeline Ingestion & Apply Freeze** | Mandatory prerequisite: Hermes runs via systemd timer and is currently active. | Background worker will submit queued corrupt applications (e.g. Job 9677 to "Unknown") during remediation. |
| **2** | **CORR-01: Phone Number Unification** | Highest employer impact: 100% of contact attempts fail if phone is transposed (`9016` vs `9106`). | Next application batch will continue transmitting wrong phone number across Indeed, Lever, Ashby, Greenhouse. |
| **3** | **CORR-04: "Unknown" Company Filter & Purge** | Immediate active exposure: Job 9677 is already sitting in `status = 'tailored'` addressing company as "Unknown". | Next apply run will submit a letter beginning "I'm applying for the role at Unknown." |
| **4** | **CORR-02: Placeholder Elimination & Gate** | Immediate disqualification: Recruiters immediately discard letters containing `[Your Name]` or `[X] years`. | 20 historical submitted letters already exhibit this; unvalidated template fallbacks will generate more. |
| **5** | **CORR-03: Hallucination Cleansing & Skill Gate** | High legal/credibility risk: False claims of 6+ years experience, degrees, or false skill counts on screening forms. | Forms requesting skill years (e.g. Amazon Connect) risk entering non-zero values on live postings. |
| **6** | **CORR-05: Salary Answer Formatting** | High functional impact: Form submission stalls or enters incorrect numbers on annual CTC/numeric fields. | Numeric fields on ATS platforms reject string answers or truncate to absurd figures. |
| **7** | **CORR-06: Profile Alignment & Code Cleanliness** | Integrity foundation: Reconcile resume YAML with compiled PDF, eliminate hardcoded drifts, commit verified state. | Future configuration changes fail to propagate to hardcoded scripts. |
| **8** | **Pipeline Unpause & Dry-Run Sanity** | Verification completion: Validates all fixes in dry-run mode before unattended execution resumes. | Unverified launch risks unnoticed regression. |

---

## SECTION C — Detailed Execution Plan

### Step 0: Immediate Operations Pause (Pre-Condition)
* **Files Affected:** None (process management).
* **Systems Affected:** `systemd` user service and timers ([scripts/run_hermes.sh](file:///mnt/data/rj/hermes/scripts/run_hermes.sh), `hermes.timer`, `hermes.service`).
* **Dependencies:** None.
* **Action Plan:**
  1. Stop timer: `systemctl --user stop hermes.timer` and `systemctl --user stop hermes.service`.
  2. Verify no active worker holds [output/hermes.lock](file:///mnt/data/rj/hermes/output/hermes.lock).
  3. Create safety backup of database: copy [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) to `db/backups/applications.db.pre_identity_repair_<timestamp>.bak`.
* **Validation Steps:**
  * `systemctl --user is-active hermes.timer` returns `inactive`.
  * Database backup file exists and matches size/checksum of original.
* **Rollback Steps:**
  * `systemctl --user start hermes.timer`.

### Fix 1: Repair Phone Number Propagation (CORR-01)
* **Source of Truth:** Authoritative Resume PDF ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) -> `+91 9106990136`.
* **Files Affected:**
  * [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (line 7)
  * [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) (line 12)
  * [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) (line 6)
  * [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md) (lines 264, 1226)
  * [tests/test_adversarial.py](file:///mnt/data/rj/hermes/tests/test_adversarial.py) (line 584)
  * [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py) (line 84)
  * 167 cover letter files on disk in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/)
* **Systems Affected:**
  * Form filling engine: [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_rules`, `_profile`).
  * Cover letter generation: [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).
  * All ATS appliers: [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py), [src/engine_apply.py](file:///mnt/data/rj/hermes/src/engine_apply.py).
* **Dependencies:** None.
* **Action Plan:**
  1. Commit working tree corrections in [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [tests/test_adversarial.py](file:///mnt/data/rj/hermes/tests/test_adversarial.py), and [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py) to secure `+91 9106990136`.
  2. Update [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md) lines 264 and 1226 to replace `+91 9016990136` with `+91 9106990136`.
  3. Execute automated disk remediation across [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/): perform exact string substitution replacing `9016990136` with `9106990136` across all 167 affected files.
* **Validation Steps:**
  * `grep -rn "9016990136" output/tailored/ | wc -l` equals `0`.
  * `grep -rn "9016990136" config.yaml profile/ tests/ agent-build-plan.md` returns 0 matches.
  * `pytest tests/test_truthfulness.py tests/test_adversarial.py` passes.
* **Rollback Steps:**
  * Restore modified files from git stash or pre-repair database backup.

### Fix 2: Purge "Unknown" Company Queued Jobs & Add Ingestion Gate (CORR-04)
* **Source of Truth:** Clean opportunity contract — company must be a valid, identified organization.
* **Files Affected:**
  * [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs` and `opportunities` tables)
  * [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`select_jobs`, `template_letter`, `validate_letter`)
  * [src/filters.py](file:///mnt/data/rj/hermes/src/filters.py)
  * 118 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) named `unknown-*-cover.txt`
* **Systems Affected:**
  * Application queue pipeline: [src/pipeline.py](file:///mnt/data/rj/hermes/src/pipeline.py), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py), [src/apply.py](file:///mnt/data/rj/hermes/src/apply.py).
* **Dependencies:** Fix 1.
* **Action Plan:**
  1. Purge active corrupt queue in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db): Update `jobs` table where `company = 'Unknown'` and `status IN ('tailored', 'scored')` to `status = 'filtered'`, setting `status_reason = 'corrupt_company_unknown'`. Specifically cancel job `id=9677`.
  2. Quarantine disk artifacts: Move all 118 `output/tailored/unknown-*-cover.txt` files to `output/quarantine/unknown_companies/`.
  3. Implement hard filter in [src/filters.py](file:///mnt/data/rj/hermes/src/filters.py) and [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py):
     * In `select_jobs`, exclude any job where `not j['company']` or `j['company'].strip().lower() in ('unknown', '', 'n/a')`.
     * In `validate_letter`, reject any letter containing the phrase `at Unknown` or `for Unknown`.
* **Validation Steps:**
  * Query [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db): `SELECT count(*) FROM jobs WHERE company = 'Unknown' AND status IN ('tailored', 'scored');` returns `0`.
  * Job `id=9677` status is `filtered`.
  * Grep `at Unknown` in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) returns `0`.
* **Rollback Steps:**
  * Restore archived files from quarantine; revert DB status from backup.

### Fix 3: Eradicate Placeholder Leakage & Add Rejection Gate (CORR-02)
* **Source of Truth:** Authoritative Resume PDF & [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) — 100% concrete evaluated text.
* **Files Affected:**
  * [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`validate_letter`, `template_letter`)
  * [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py)
  * [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) (226 affected files on disk)
  * [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db)
* **Systems Affected:**
  * Cover letter validation pipeline: [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).
  * Dry-run and live application attachment: [src/apply.py](file:///mnt/data/rj/hermes/src/apply.py), [src/engine_apply.py](file:///mnt/data/rj/hermes/src/engine_apply.py).
* **Dependencies:** Fix 1, Fix 2.
* **Action Plan:**
  1. Add strict placeholder validation to [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) `validate_letter`:
     * Compile pattern `PLACEHOLDER_RE = re.compile(r"\[[A-Za-z0-9_ /'’\.-]+\]|\{[a-zA-Z0-9_]+\}")`.
     * Reject any draft containing matches for `PLACEHOLDER_RE`.
  2. Quarantine all 226 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) containing bracketed/curly placeholders by moving them to `output/quarantine/placeholders/`.
  3. In [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db), reset any non-submitted job (`status = 'tailored'`) whose `cover_letter_path` points to a quarantined file back to `status = 'scored'`.
  4. Add unit test in [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py) verifying that letters containing `[Your Name]`, `[Company]`, `[X] years`, or `{devlogic}` fail `validate_letter`.
* **Validation Steps:**
  * `grep -lE '\[[A-Za-z0-9_ /’\.-]+\]|\{[a-z_]+\}' output/tailored/*` returns `0` matching files.
  * `pytest tests/test_truthfulness.py` placeholder rejection tests pass.
* **Rollback Steps:**
  * Restore files from `output/quarantine/placeholders/` to `output/tailored/`; git checkout [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).

### Fix 4: Purge Hallucinated Claims & Strengthen Skill Gate (CORR-03)
* **Source of Truth:** Authoritative Resume PDF ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) & [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md).
* **Files Affected:**
  * [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`skill_years_answer`, `rule_answer`, `YEARS_RE`, `_rules`)
  * [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`BANNED_CLAIM_RE`, `YEARS_CLAIM_RE`)
  * [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/)
  * [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py)
* **Systems Affected:**
  * Screening question answerer: [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py).
  * Cover letter validator: [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).
  * Indeed / ATS form fill: [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py).
* **Dependencies:** Fix 1, Fix 2, Fix 3.
* **Action Plan:**
  1. Fix screening question precedence bug in [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py):
     * In `rule_answer`, ensure any question containing both a skill keyword and "years" is intercepted by `skill_years_answer` BEFORE generic experience rules match.
     * Ensure questions matching `r"years of amazon connect experience"` return `"0"`, not `"1"`.
  2. Expand `BANNED_CLAIM_RE` in [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py):
     * Add explicit bans for `blockchain`, `crypto`, `smart contracts`, `team lead`, `led a team`, `managed a team`, and `degree in computer science`.
     * In `YEARS_CLAIM_RE`, ensure `6+ years` and any figure `> 4 years` triggers rejection.
  3. Quarantine contaminated cover letters on disk:
     * Identify letters in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) claiming absent technologies or exaggerated years and move to `output/quarantine/hallucinations/`.
  4. Reset any pending `status = 'tailored'` job whose letter was quarantined back to `status = 'scored'`.
* **Validation Steps:**
  * `python -c 'from answers import answer_question; assert answer_question("How many years of amazon connect experience do you have?", kind="text") == "0"'`.
  * `pytest tests/test_truthfulness.py` all cases pass.
* **Rollback Steps:**
  * Revert [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) and [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py); restore quarantined files.

### Fix 5: Salary-Answer Input & Type Harmonization (CORR-05)
* **Source of Truth:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) salary block (₹25k India / ₹30k global) & `screening_answers` block.
* **Files Affected:**
  * [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_salary_answer`, `rule_answer`, `answer_question`)
  * [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py)
* **Systems Affected:**
  * Form filling engine across Indeed, Greenhouse, Lever, Ashby: [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **Dependencies:** Fix 1.
* **Action Plan:**
  1. Refactor `_salary_answer` in [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) to accept field `kind`:
     * When `kind == "text"` or field is a numeric `<input type="number">`: return strictly numeric integer representation as string (e.g. `25000` for India, `30000` for global) without currency symbols or prose.
     * When field label queries "annual", "per annum", or "ctc": convert monthly floor to annual (`amount * 12`).
     * When `kind == "textarea"`: return truthful prose explanation.
  2. Handle "current salary / current CTC":
     * When queried in numeric format, return empty / `None` (or `0`) rather than injecting `Not currently employed (freelance)`.
  3. Add test coverage in [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py) verifying numeric vs textarea salary answers.
* **Validation Steps:**
  * `python -c 'from answers import answer_question; assert answer_question("Expected monthly salary", kind="text").isdigit()'`.
  * `python -c 'from answers import answer_question; assert "minimum" in answer_question("Expected salary", kind="textarea")'`.
* **Rollback Steps:**
  * Revert changes to [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py).

### Fix 6: Profile Alignment & Code Cleanliness (CORR-06)
* **Source of Truth:** Authoritative Resume PDF ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) & [config.yaml](file:///mnt/data/rj/hermes/config.yaml).
* **Files Affected:**
  * [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml)
  * [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py)
  * [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py)
  * [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md)
* **Systems Affected:**
  * Authentication resolver: [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py).
  * Appliers: [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py).
* **Dependencies:** Fixes 1–5.
* **Action Plan:**
  1. Reconcile [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml): ensure `(Claude Code)` is consistently represented in source YAML lines 19, 29, 39 to match Authoritative Resume PDFs.
  2. Decouple hardcoded strings:
     * In [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py), load email from `config.yaml` with fallback.
     * In [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) and [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), derive cover letter filename dynamically from `config.yaml` profile name.
  3. Git working tree synchronization: stage and commit all verified changes.
* **Validation Steps:**
  * `git diff` shows 100% alignment with Authoritative Resume PDF.
  * `pytest tests/` runs with 100% pass rate.
* **Rollback Steps:**
  * `git restore` specific files if validation fails.

### Step 7: End-to-End Pipeline Verification & Unfreeze
* **Files Affected:** None.
* **Systems Affected:** Hermes scheduler & apply pipeline.
* **Dependencies:** Fixes 1–6 complete and verified.
* **Action Plan:**
  1. Execute controlled dry-run: `python src/pipeline.py --dry-run --limit 3`.
  2. Inspect output logs in `output/hermes_cron.log` and verify generated letters, form fill values, and phone numbers.
  3. Re-enable production scheduler: `systemctl --user start hermes.timer`.
* **Validation Steps:**
  * `systemctl --user is-active hermes.timer` returns `active`.
  * Next scheduled run registered in `systemctl --user list-timers`.
* **Rollback Steps:**
  * `systemctl --user stop hermes.timer`.

---

## SECTION D — Verification Checklist

### 1. Source-of-Truth & Configuration Integrity
* [ ] **CONF-01:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) line 7 contains exact string `phone: +91 9106990136`.
* [ ] **CONF-02:** [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) line 12 contains exact string `- Phone: +91 9106990136`.
* [ ] **CONF-03:** [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) line 6 contains exact string `+91 9106990136`.
* [ ] **CONF-04:** [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md) lines 264 & 1226 contain `+91 9106990136` (zero occurrences of `9016990136`).
* [ ] **CONF-05:** [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) summary text matches Authoritative Resume PDF verbatim.

### 2. Disk & Queue Artifacts Hygiene
* [ ] **ARTI-01:** `grep -rn "9016990136" output/tailored/` returns exactly 0 results.
* [ ] **ARTI-02:** `grep -rnE '\[[A-Za-z0-9_ /’\.-]+\]|\{[a-z_]+\}' output/tailored/` returns exactly 0 results.
* [ ] **ARTI-03:** `grep -rn "at Unknown" output/tailored/` returns exactly 0 results.
* [ ] **ARTI-04:** Zero files matching `output/tailored/unknown-*-cover.txt` remain in active tailored directory.
* [ ] **ARTI-05:** All corrupt or placeholder-bearing historical letters relocated to `output/quarantine/`.

### 3. Database State Integrity
* [ ] **DB-01:** `SELECT count(*) FROM jobs WHERE company = 'Unknown' AND status IN ('tailored', 'scored');` returns `0`.
* [ ] **DB-02:** Job ID 9677 status is `filtered` with reason `corrupt_company_unknown`.
* [ ] **DB-03:** Zero jobs in `status = 'tailored'` link to cover letters containing `9016990136`, `[Your Name]`, or `at Unknown`.
* [ ] **DB-04:** Verified SQLite backup file exists in `db/backups/`.

### 4. Logic & Gate Enforcement
* [ ] **GATE-01:** `python -c 'from tailor import validate_letter; assert validate_letter("Role at [Company] for [Your Name]")'` flags unresolved placeholders.
* [ ] **GATE-02:** `python -c 'from tailor import validate_letter; assert validate_letter("Applying for role at Unknown.")'` flags corrupt company name.
* [ ] **GATE-03:** `python -c 'from tailor import validate_letter; assert validate_letter("I have 6 years of professional experience")'` flags overstated experience.
* [ ] **GATE-04:** `python -c 'from answers import answer_question; assert answer_question("How many years of amazon connect experience do you have?", kind="text") == "0"'`.
* [ ] **GATE-05:** `python -c 'from answers import answer_question; assert answer_question("How many years of amazon Lex experience do you have?", kind="text") == "0"'`.
* [ ] **GATE-06:** `python -c 'from answers import answer_question; assert answer_question("Desired salary", kind="text").isdigit()'`.

### 5. Test Suite & Operational Execution
* [ ] **TEST-01:** `pytest tests/test_truthfulness.py` runs with 100% passes.
* [ ] **TEST-02:** `pytest tests/test_adversarial.py` runs with 100% passes.
* [ ] **TEST-03:** `pytest tests/test_engine_identity.py` runs with 100% passes.
* [ ] **OPS-01:** Controlled pipeline dry run completes with exit code 0.
* [ ] **OPS-02:** `systemctl --user is-active hermes.timer` confirms scheduler safely re-engaged.

---

## SECTION E — Final Repair Sequence

1. **EMERGENCY STOP:** Freeze `systemd` service & timer (`systemctl --user stop hermes.timer hermes.service`).
2. **SAFETY BACKUP:** Snapshot SQLite database (`cp db/applications.db db/backups/applications.db.$(date +%Y%m%dT%H%M%S)_pre_repair.bak`).
3. **SOURCE UNIFICATION:** Correct and commit phone, config, facts, YAML across [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), and [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md).
4. **QUEUE PURGE:** Cancel job 9677; update all queued "Unknown" company jobs to `status = 'filtered'`.
5. **DISK REMEDIATION:** Scrub 167 phone numbers; quarantine 226 letters containing placeholders and 118 letters referencing "Unknown".
6. **GATE STRENGTHENING:** Add placeholder, company, and skill gates to [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) and [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py).
7. **REGRESSION TESTING:** Run `pytest tests/test_truthfulness.py tests/test_adversarial.py tests/test_engine_identity.py`.
8. **DRY-RUN AUDIT:** Execute `python src/pipeline.py --dry-run --limit 3` and verify clean log output.
9. **PRODUCTION RE-ENTRY:** Restart `hermes.timer` for passive submission.
