# Report 2: Employer-Visible Surface Registry

**Document ID:** HERMES-REGISTRY-02  
**Purpose:** Identify every location and pipeline where an employer, recruiter, ATS, or hiring manager could observe candidate data.  
**Corpus Scanned:** Full repository, SQLite production database ([db/applications.db](file:///mnt/data/rj/hermes/db/applications.db)), compiled PDF resumes ([resumes/](file:///mnt/data/rj/hermes/resumes/)), and cache files ([output/tailored/](file:///mnt/data/rj/hermes/output/tailored/)).

---

## Complete Surface Registry Matrix

| Field | Authoritative Source | Primary Storage / Config | Runtime Generator / Filler | Downstream Employer Surface | Exposure Risk | Drift Detected | Status |
|---|---|---|---|---|---|---|---|
| **NAME** | Authoritative Resume PDF line 1 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.name`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) | Indeed form, ATS forms (Greenhouse/Lever/Ashby), Resume PDF, Cover letter | **CRITICAL** | **YES** (`[Your Name]` leaked in 226 letters, 20 submitted) | **VERIFIED** |
| **PHONE** | Authoritative Resume PDF line 3 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.phone`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_rules`), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py) | Recruiter phone calls, SMS verification, ATS contact fields | **CRITICAL** | **YES** (`9016990136` transposed across 167 letters, 22 submitted) | **VERIFIED** |
| **EMAIL** | Authoritative Resume PDF line 3 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.email`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py) | Recruiter email outreach, ATS auto-confirmations, OTP auth | **CRITICAL** | **YES** (Leaked `[Email Address]`; hardcoded in otp_resolver) | **VERIFIED** |
| **LOCATION** | Authoritative Resume PDF line 3 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.location`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [src/geo.py](file:///mnt/data/rj/hermes/src/geo.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) | ATS candidate profile, location filters, visa/sponsorship questions | **HIGH** | **YES** (Syntax drift: `Ahmedabad, India` vs `Ahmedabad, IND`; `[Your Address]`) | **VERIFIED** |
| **LINKEDIN** | Authoritative Resume PDF line 4 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.linkedin`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) (`urls[LinkedIn]`) | Recruiter candidate inspection, ATS social links | **HIGH** | **YES** (Protocol mismatch: `http://` vs `https://` vs scheme-less) | **VERIFIED** |
| **GITHUB** | Authoritative Resume PDF line 4 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.github`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) | Engineering code review, take-home repo submissions | **HIGH** | **YES** (Personal GitHub submitted for take-home assignment URLs) | **VERIFIED** |
| **PORTFOLIO** | Authoritative Resume PDF line 4 | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.portfolio`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) | ATS portfolio/website fields, Recruiter live demo review | **MEDIUM** | **NO** (Consistent domain `orvion-co.vercel.app` across all files) | **VERIFIED** |
| **SKILLS** | Authoritative Resume PDF (Technical Skills) | [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`skill_years_answer`), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) | Indeed screening questions, ATS custom fields, Cover letter body | **CRITICAL** | **YES** (Claims of AWS, Azure, GCP, K8s in 132 letters, 9 submitted) | **VERIFIED** |
| **PROJECTS** | Authoritative Resume PDF (Projects) | [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) | [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`PROOF_BY_VARIANT`, `validate_letter`) | Cover letters (`output/tailored/`), behavioral screening answers | **CRITICAL** | **YES** (Metric misattribution; `[X] years` / `[Y] hours` placeholders) | **VERIFIED** |
| **EXPERIENCE** | Authoritative Resume PDF (Experience) | [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [config.yaml](file:///mnt/data/rj/hermes/config.yaml) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`YEARS_RE`), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) | ATS experience inputs, Indeed experience radio/text, Cover letters | **CRITICAL** | **YES** (6+ years claimed in letters; 1 yr entered for Amazon Connect) | **VERIFIED** |
| **SALARY** | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`salary` block) | [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`salary`) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_salary_answer`), [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py) | Indeed salary inputs, ATS expected compensation / CTC inputs | **HIGH** | **YES** (Unconditional prose string `₹25,000/month...` in numeric inputs) | **VERIFIED** |
| **EDUCATION** | Authoritative Resume PDF (Education) | [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [config.yaml](file:///mnt/data/rj/hermes/config.yaml) | [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_rules`), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) | ATS education dropdowns, Degree screening questions, Cover letters | **HIGH** | **YES** (Cover letter claimed "degree in Computer Science" vs diploma) | **VERIFIED** |

---

## Detailed Field Inventory (12 Fields)

### 1. NAME
* **FIELD NAME:** NAME
* **AUTHORITATIVE VALUE:** `Saral Banker` (First Name: `Saral`, Last Name: `Banker`)
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [resumes/resume-ai.pdf](file:///mnt/data/rj/hermes/resumes/resume-ai.pdf), [resumes/resume-fullstack.pdf](file:///mnt/data/rj/hermes/resumes/resume-fullstack.pdf)) Line 1; Verified Indeed Profile.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [resumes/resume-ai.pdf](file:///mnt/data/rj/hermes/resumes/resume-ai.pdf), [resumes/resume-fullstack.pdf](file:///mnt/data/rj/hermes/resumes/resume-fullstack.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.cover_letter_path` links to files on disk containing name in signature).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.name`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_rules` extracts `first, *_, last = p["name"].split()`), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py) (`_fill_inputs`), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) (`_fill_greenhouse`, `_fill_lever`, `_fill_ashby`), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) (`_fill_known_fields`).
* **ATS PAYLOADS:** Form DOM elements: `input[name="first_name"]`, `input[name="last_name"]`, `input[name="name"]`, `input[name="job_application[first_name]"]`, `input[name="job_application[last_name]"]`. Multipart uploads: `resumes/resume-*.pdf`.
* **CACHED OUTPUTS:** [output/tailored/Saral_Banker_Cover_Letter.txt](file:///mnt/data/rj/hermes/output/tailored/Saral_Banker_Cover_Letter.txt); 1,482 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/).
* **EXTERNAL SERVICES:** Indeed Candidate Portal, Greenhouse API/Web, Lever Web, Ashby Web, Direct Company Career Portals.
* **EXPOSURE RISK:** CRITICAL
* **DRIFT DETECTED:** YES
  * *Evidence:* 226 cover letters in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) leaked `[Your Name]` into employer-facing text; 20 of these letters were submitted to employers via [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) records.
* **VERIFICATION STATUS:** VERIFIED

---

### 2. PHONE
* **FIELD NAME:** PHONE
* **AUTHORITATIVE VALUE:** `+91 9106990136`
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [resumes/resume-ai.pdf](file:///mnt/data/rj/hermes/resumes/resume-ai.pdf), [resumes/resume-fullstack.pdf](file:///mnt/data/rj/hermes/resumes/resume-fullstack.pdf)) Line 3.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [resumes/resume-ai.pdf](file:///mnt/data/rj/hermes/resumes/resume-ai.pdf), [resumes/resume-fullstack.pdf](file:///mnt/data/rj/hermes/resumes/resume-fullstack.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.cover_letter_path`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.phone`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) line 76: `(r"phone|mobile|contact number", p["phone"])`; [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py) line 541, [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) lines 354, 487, 571, [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) line 235.
* **ATS PAYLOADS:** `input[type="tel"]`, `input[name="phone"]`, `input[name="mobile"]`, `input[name="job_application[phone]"]`.
* **CACHED OUTPUTS:** 167 cover letter files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/); screenshots [screenshots/dryrun-lever-hevodata.png](file:///mnt/data/rj/hermes/screenshots/dryrun-lever-hevodata.png), [screenshots/dryrun-ashby-anyscale.png](file:///mnt/data/rj/hermes/screenshots/dryrun-ashby-anyscale.png), [screenshots/dryrun-greenhouse-anthropic.png](file:///mnt/data/rj/hermes/screenshots/dryrun-greenhouse-anthropic.png).
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby.
* **EXPOSURE RISK:** CRITICAL
* **DRIFT DETECTED:** YES
  * *Evidence:* Transposed digits `+91 9016990136` stored in [config.yaml](file:///mnt/data/rj/hermes/config.yaml) and [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) prior to uncommitted edit; 167 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) contain `9016990136`; 22 submitted applications in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) sent `9016990136`; lines 264 & 1226 of [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md) contain `9016990136`.
* **VERIFICATION STATUS:** VERIFIED

---

### 3. EMAIL
* **FIELD NAME:** EMAIL
* **AUTHORITATIVE VALUE:** `saralbanker1@gmail.com`
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) Line 3; Verified Indeed Profile.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py), [agent-build-plan.md](file:///mnt/data/rj/hermes/agent-build-plan.md), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`responses.from_address`, `jobs.cover_letter_path`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.email`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) line 75: `(r"e-?mail", p["email"])`.
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** `input[type="email"]`, `input[name="email"]`, `input[name="job_application[email]"]`.
* **CACHED OUTPUTS:** [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/), screenshots in [screenshots/](file:///mnt/data/rj/hermes/screenshots/).
* **EXTERNAL SERVICES:** Google Workspace/Gmail IMAP ([src/response_watcher.py](file:///mnt/data/rj/hermes/src/response_watcher.py)), Indeed, ATS providers.
* **EXPOSURE RISK:** CRITICAL
* **DRIFT DETECTED:** YES
  * *Evidence:* Hardcoded string in [src/otp_resolver.py](file:///mnt/data/rj/hermes/src/otp_resolver.py#L33) (`GMAIL_USER = "saralbanker1@gmail.com"`), bypassing config abstraction; raw placeholder `[Email Address]` leaked into [output/tailored/infuse-manual-qa-engineer-junior-middle-remote-contract-cover.txt](file:///mnt/data/rj/hermes/output/tailored/infuse-manual-qa-engineer-junior-middle-remote-contract-cover.txt).
* **VERIFICATION STATUS:** VERIFIED

---

### 4. LOCATION
* **FIELD NAME:** LOCATION
* **AUTHORITATIVE VALUE:** `Ahmedabad, Gujarat, India` (City: `Ahmedabad`, State: `Gujarat`, Country: `India`, Neighborhood: `Shahibaug`; Remote: Open to remote hiring from India or on-site/hybrid within 20 km).
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) Line 3; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) lines 10-11; [config.yaml](file:///mnt/data/rj/hermes/config.yaml) line 8.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [src/geo.py](file:///mnt/data/rj/hermes/src/geo.py).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.location`, `jobs.location_reason`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.location`, `geo.home_name`, `geo.radius_km`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) line 99: `(r"(\bcity\b|\blocation\b|where are you (located|based)|current location)", p["location"])`, line 100: `(r"country", "India")`.
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** `input[name="location"]`, `input[name="city"]`, `input[name="job_application[location]"]`.
* **CACHED OUTPUTS:** [screenshots/dryrun-lever-hevodata.png](file:///mnt/data/rj/hermes/screenshots/dryrun-lever-hevodata.png) (`Ahmedabad, IND`), [screenshots/dryrun-ashby-anyscale.png](file:///mnt/data/rj/hermes/screenshots/dryrun-ashby-anyscale.png) (`Ahmedabad`).
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby.
* **EXPOSURE RISK:** HIGH
* **DRIFT DETECTED:** YES
  * *Evidence:* Inconsistent token representation across platforms (`Ahmedabad, India` vs `Ahmedabad, IND` vs `Ahmedabad`); raw placeholder `[Your Address]` leaked in [output/tailored/infuse-manual-qa-engineer-junior-middle-remote-contract-cover.txt](file:///mnt/data/rj/hermes/output/tailored/infuse-manual-qa-engineer-junior-middle-remote-contract-cover.txt).
* **VERIFICATION STATUS:** VERIFIED

---

### 5. LINKEDIN
* **FIELD NAME:** LINKEDIN
* **AUTHORITATIVE VALUE:** `https://www.linkedin.com/in/saralbanker` (Resume format: `linkedin.com/in/saralbanker`)
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) Line 4; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) Line 14.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [config.yaml](file:///mnt/data/rj/hermes/config.yaml).
  * **DATABASE TABLES:** None directly.
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.linkedin`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) Line 77: `(r"linkedin", p.get("linkedin", ""))`.
* **FORM FILLERS:** [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) lines 490 & 573 (`urls[LinkedIn]`), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) line 238.
* **ATS PAYLOADS:** `input[name="urls[LinkedIn]"]`, `input[name*="linkedin" i]`.
* **CACHED OUTPUTS:** [screenshots/dryrun-lever-hevodata.png](file:///mnt/data/rj/hermes/screenshots/dryrun-lever-hevodata.png), [screenshots/dryrun-ashby-anyscale.png](file:///mnt/data/rj/hermes/screenshots/dryrun-ashby-anyscale.png).
* **EXTERNAL SERVICES:** LinkedIn, ATS platforms.
* **EXPOSURE RISK:** HIGH
* **DRIFT DETECTED:** YES
  * *Evidence:* Insecure protocol generation observed in [screenshots/dryrun-lever-hevodata.png](file:///mnt/data/rj/hermes/screenshots/dryrun-lever-hevodata.png) (`http://linkedin.com/in/saralbanker` instead of `https://`).
* **VERIFICATION STATUS:** VERIFIED

---

### 6. GITHUB
* **FIELD NAME:** GITHUB
* **AUTHORITATIVE VALUE:** `https://github.com/saralbanker` (Resume format: `github.com/saralbanker`)
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) Line 4; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) Line 13.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** None directly.
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.github`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) Line 78: `(r"github", "https://" + p["github"])`; [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py).
* **FORM FILLERS:** [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) lines 492 & 574 (`urls[GitHub]`), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) line 239.
* **ATS PAYLOADS:** `input[name="urls[GitHub]"]`, `input[name*="github" i]`.
* **CACHED OUTPUTS:** [screenshots/dryrun-ashby-anyscale.png](file:///mnt/data/rj/hermes/screenshots/dryrun-ashby-anyscale.png).
* **EXTERNAL SERVICES:** GitHub, ATS platforms.
* **EXPOSURE RISK:** HIGH
* **DRIFT DETECTED:** YES
  * *Evidence:* Rule collision identified in [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py#L125-L133) where take-home repository submission links ("share GitHub repo URL for project") were answered with the personal candidate profile URL.
* **VERIFICATION STATUS:** VERIFIED

---

### 7. PORTFOLIO
* **FIELD NAME:** PORTFOLIO
* **AUTHORITATIVE VALUE:** `https://orvion-co.vercel.app` (Resume format: `orvion-co.vercel.app`)
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) Line 4; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) Line 15.
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [config.yaml](file:///mnt/data/rj/hermes/config.yaml).
  * **DATABASE TABLES:** None directly.
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.portfolio`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) Line 79: `(r"portfolio|website|personal site|other url", "https://" + p["portfolio"])`.
* **FORM FILLERS:** [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py) lines 493 & 575 (`urls[Portfolio]`), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py) line 240.
* **ATS PAYLOADS:** `input[name="urls[Portfolio]"]`, `input[name*="portfolio" i]`, `input[name*="website" i]`.
* **CACHED OUTPUTS:** [screenshots/dryrun-ashby-anyscale.png](file:///mnt/data/rj/hermes/screenshots/dryrun-ashby-anyscale.png), [screenshots/dryrun-greenhouse-anthropic.png](file:///mnt/data/rj/hermes/screenshots/dryrun-greenhouse-anthropic.png).
* **EXTERNAL SERVICES:** Vercel Hosting, ATS platforms.
* **EXPOSURE RISK:** MEDIUM
* **DRIFT DETECTED:** NO
* **VERIFICATION STATUS:** VERIFIED

---

### 8. SKILLS
* **FIELD NAME:** SKILLS
* **AUTHORITATIVE VALUE:**
  * *Languages:* TypeScript, JavaScript, Python, Go, SQL.
  * *Backend:* Node.js, Express, FastAPI, REST APIs, Socket.IO, JWT, RBAC.
  * *Data:* PostgreSQL, Supabase, pgvector, Redis, BullMQ, SQLite, Convex.
  * *AI:* RAG, embeddings, semantic search, prompt engineering, structured output, local LLMs (Ollama).
  * *Frontend:* React, Next.js, Vite, Tailwind CSS, TanStack Query, Zustand.
  * *Infra:* Docker, GitHub Actions, Linux, systemd, Sentry, Prometheus.
  * *Explicit Exclusions:* AWS, GCP, Azure, Kubernetes, Java, Spring, .NET, PHP, iOS, Swift, Blockchain.
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) section "TECHNICAL SKILLS"; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md).
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [src/score.py](file:///mnt/data/rj/hermes/src/score.py), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.cover_letter_path`).
  * **CONFIGS:** [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) (`skills_order`), [config.yaml](file:///mnt/data/rj/hermes/config.yaml).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`skill_years_answer`), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`_llm_body`, `validate_letter`).
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** Screening question inputs for specific technologies ("Years of X experience").
* **CACHED OUTPUTS:** [screenshots/verify-indeed-2295.png](file:///mnt/data/rj/hermes/screenshots/verify-indeed-2295.png); 132 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) claiming AWS/Azure/GCP/Kubernetes.
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby, Ollama local inference endpoint.
* **EXPOSURE RISK:** CRITICAL
* **DRIFT DETECTED:** YES
  * *Evidence:* Live screenshot [screenshots/verify-indeed-2295.png](file:///mnt/data/rj/hermes/screenshots/verify-indeed-2295.png) confirms `1` entered for Amazon Connect and Amazon Lex (candidate has 0); 132 files in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/) cite banned cloud skills; 9 submitted applications in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) include letters with hallucinated skills.
* **VERIFICATION STATUS:** VERIFIED

---

### 9. PROJECTS
* **FIELD NAME:** PROJECTS
* **AUTHORITATIVE VALUE:**
  * **AWIS** (Jul 2026 – present, Go): Local-first workflow engine, YAML DSL, append-only SQLite log, 22-command CLI, REST API, lit-html dashboard, Python SDK plugin system, 25k LOC Go, 773 test functions, race detector CI.
  * **Neuro-Zenith** (2025 – 2026): Local-first AI platform, RAG with BGE embeddings, pgvector HNSW, BullMQ/Redis, Socket.IO, JWT+RBAC, 44 migrations, 70k LOC, 400+ files, public repo `github.com/saralbanker/neuro-zenith`.
  * **Shade Ledger** (Jan 2025 – present): Paid freelance contract (Rs. 60,000) for 220+ shed industrial estate. React/TS/PostgreSQL/Convex. Saves 40+ hours/month.
  * **HeatMax**: Industrial boiler catalog website, React/TS/Supabase.
  * **Hermes** (2026): Job-search automation in Python, Ollama, Playwright, SQLite.
  * **Carbon Compass**: Carbon emission calculator for manufacturing.
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) section "PROJECTS"; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) section "Projects".
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.cover_letter_path`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) line 115 (`why_interested_template`), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml) (`project_order`).
* **GENERATORS:** [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`PROOF_BY_VARIANT`, `PROJECT_NUMBERS`), [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`llm_answer`).
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** Cover letter attachments, textarea fields, behavioral question answers.
* **CACHED OUTPUTS:** 1,482 tailored cover letters in [output/tailored/](file:///mnt/data/rj/hermes/output/tailored/).
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby, GitHub.
* **EXPOSURE RISK:** CRITICAL
* **DRIFT DETECTED:** YES
  * *Evidence:* Metric misattribution documented in [tests/test_truthfulness.py](file:///mnt/data/rj/hermes/tests/test_truthfulness.py#L36-L49); placeholder leakage in [output/tailored/rolls-royce-aerothermal-engineer-cover.txt](file:///mnt/data/rj/hermes/output/tailored/rolls-royce-aerothermal-engineer-cover.txt) claiming `[X] years` on Neuro-Zenith and `[Y] hours` on rental business; 20 submitted applications in [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) contain leaked placeholders.
* **VERIFICATION STATUS:** VERIFIED

---

### 10. EXPERIENCE
* **FIELD NAME:** EXPERIENCE
* **AUTHORITATIVE VALUE:**
  * *Hands-on software development overall:* ~4 years (personal projects, coursework, freelance).
  * *Paid, client-facing professional experience:* ~1+ year (freelance, Jan 2025 – present, part-time while studying until May 2026). Never described as "4 years of professional experience".
  * *Current Employment Status:* Not currently employed in a full-time job / Freelance self-employed.
  * *Leadership Experience:* 0 years.
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) section "EXPERIENCE"; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) section "Experience in years".
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py), [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.required_years`, `jobs.cover_letter_path`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`profile.years_experience: 1`, `screening_answers.years_experience_total: 1`, `screening_answers.years_experience_text`, `screening_answers.currently_employed: 'No'`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) line 96: `str(s["years_experience_total"])` (`1`); line 318: `s["years_experience_text"]`; [src/tailor.py](file:///mnt/data/rj/hermes/src/tailor.py) (`YEARS_CLAIM_RE`).
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** `input[name="years_experience"]`, `input[name="org"]` (`Freelance (self-employed)` on Lever in [screenshots/dryrun-lever-hevodata.png](file:///mnt/data/rj/hermes/screenshots/dryrun-lever-hevodata.png)), `input[name="currently_employed"]`.
* **CACHED OUTPUTS:** [output/tailored/*.txt](file:///mnt/data/rj/hermes/output/tailored/), screenshots in [screenshots/](file:///mnt/data/rj/hermes/screenshots/).
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby.
* **EXPOSURE RISK:** CRITICAL
* **DRIFT DETECTED:** YES
  * *Evidence:* [output/tailored/enfycon-senior-software-engineer-java-and-javascript-ecosyst-cover.txt](file:///mnt/data/rj/hermes/output/tailored/enfycon-senior-software-engineer-java-and-javascript-ecosyst-cover.txt) claims `6+ years of professional`; [output/tailored/unknown-oracle-apex-developer-immediate-joining-cover.txt](file:///mnt/data/rj/hermes/output/tailored/unknown-oracle-apex-developer-immediate-joining-cover.txt) claims `6 years of professional`; [output/tailored/stanbic-bank-tanzania-engineer-software-cover.txt](file:///mnt/data/rj/hermes/output/tailored/stanbic-bank-tanzania-engineer-software-cover.txt) claims `led a team`.
* **VERIFICATION STATUS:** VERIFIED

---

### 11. SALARY
* **FIELD NAME:** SALARY
* **AUTHORITATIVE VALUE:**
  * *India / India Remote Floor:* ₹25,000 / month minimum.
  * *Global Remote Floor:* ₹30,000 / month minimum (~$340–$360 USD / month).
  * *Prose Expectation:* "₹25,000/month minimum, open to a competitive offer in line with the role's published range".
  * *Current CTC:* Not currently employed (freelance).
* **SOURCE OF TRUTH:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) section `salary` (lines 30-35) and `screening_answers` (lines 105, 107).
* **STORAGE LOCATIONS:**
  * **FILES:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) lines 58-64, [src/filters.py](file:///mnt/data/rj/hermes/src/filters.py).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.salary_min`, `jobs.salary_max`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) (`min_inr_per_month_india: 25000`, `min_inr_per_month_global: 30000`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) (`_salary_answer`).
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py) line 541, [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** `input[name="expected_salary"]`, `input[name="desired_salary"]`, `input[name="current_ctc"]`.
* **CACHED OUTPUTS:** Transmitted live to DOM elements during apply runs.
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby, direct ATS hosts.
* **EXPOSURE RISK:** HIGH
* **DRIFT DETECTED:** YES
  * *Evidence:* [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py#L58-L64) returns an unformatted string containing currency symbol `₹` and trailing text into all salary fields; numeric inputs reject non-digits or truncate to `25000` (which reads as annual CTC ₹25,000/year on annual fields); "current CTC" returns non-numeric string `Not currently employed (freelance)`.
* **VERIFICATION STATUS:** VERIFIED

---

### 12. EDUCATION
* **FIELD NAME:** EDUCATION
* **AUTHORITATIVE VALUE:**
  * *Degree:* Diploma in Computer Engineering.
  * *Institution:* LJ Polytechnic, Ahmedabad.
  * *Graduation:* May 2026.
  * *Academic Performance:* CGPA 8.36 / 10, Top 10% of class.
  * *Higher Degrees:* No Bachelor's degree; no B.Tech; no B.E.; no Master's degree.
* **SOURCE OF TRUTH:** Authoritative Resume PDFs ([resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf)) section "EDUCATION"; [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md) section "Education".
* **STORAGE LOCATIONS:**
  * **FILES:** [resumes/resume-backend.pdf](file:///mnt/data/rj/hermes/resumes/resume-backend.pdf), [profile/facts.md](file:///mnt/data/rj/hermes/profile/facts.md), [profile/resume.yaml](file:///mnt/data/rj/hermes/profile/resume.yaml), [config.yaml](file:///mnt/data/rj/hermes/config.yaml), [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py).
  * **DATABASE TABLES:** [db/applications.db](file:///mnt/data/rj/hermes/db/applications.db) (`jobs.cover_letter_path`).
  * **CONFIGS:** [config.yaml](file:///mnt/data/rj/hermes/config.yaml) line 13 (`profile.education`), line 103 (`screening_answers.degree`).
* **GENERATORS:** [src/answers.py](file:///mnt/data/rj/hermes/src/answers.py) line 97: `(r"\bbachelor|\bb\.?tech\b|\bb\.?e\.?\b...|\bmaster'?s\b|computer science degree", "No")`, line 98: `(r"highest (level of )?education|degree|qualification", s["degree"])`.
* **FORM FILLERS:** [src/indeed_apply.py](file:///mnt/data/rj/hermes/src/indeed_apply.py), [src/ats_apply.py](file:///mnt/data/rj/hermes/src/ats_apply.py), [src/direct_form.py](file:///mnt/data/rj/hermes/src/direct_form.py).
* **ATS PAYLOADS:** `select[name*="education" i]`, `input[name*="degree" i]`, `input[name*="school" i]`.
* **CACHED OUTPUTS:** [output/tailored/fullstacktechies-python-developer-web-data-extraction-ai-cover.txt](file:///mnt/data/rj/hermes/output/tailored/fullstacktechies-python-developer-web-data-extraction-ai-cover.txt).
* **EXTERNAL SERVICES:** Indeed, Greenhouse, Lever, Ashby.
* **EXPOSURE RISK:** HIGH
* **DRIFT DETECTED:** YES
  * *Evidence:* Cover letter [output/tailored/fullstacktechies-python-developer-web-data-extraction-ai-cover.txt](file:///mnt/data/rj/hermes/output/tailored/fullstacktechies-python-developer-web-data-extraction-ai-cover.txt) contains the claim `degree in Computer Science` instead of "Diploma in Computer Engineering".
* **VERIFICATION STATUS:** VERIFIED
