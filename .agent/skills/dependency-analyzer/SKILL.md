---
name: dependency-analyzer
description: "Use this skill when auditing project dependencies for security vulnerabilities, license compliance, outdated packages, and transitive risk."
version: 1.0.0
triggers:
  - "dependencies"
  - "npm audit"
  - "outdated packages"
  - "license check"
  - "CVE"
  - "supply chain"
  - "@dependency-analyzer"
token_budget: 2000
tools_required:
  - run_terminal
  - view_file
output_contract:
  format: "Dependency audit: CVEs + outdated + license risks + action list"
  includes:
    - critical-cves
    - outdated-list
    - license-violations
    - action-list
works_with:
  - security-auditor
  - research-engine
  - task-planner
risk: medium
---

## Mission

Audit all project dependencies for security vulnerabilities (CVEs), license compliance risks, outdated packages, and transitive dependency exposure. Produce a prioritized action list: fix critical CVEs immediately, schedule high CVE fixes, review license conflicts, and plan major version upgrades. Every finding includes the affected package, severity, and a specific remediation action.

## When To Activate

- Before deploying to production (pre-release dependency gate)
- After running `npm install` with new packages
- When `npm audit` reports vulnerabilities
- When evaluating whether to add a new dependency
- Periodic dependency health checks (weekly/monthly)
- **Anti-trigger**: Do NOT activate for application-level security logic (use `security-auditor`). This skill is about the dependency supply chain, not the application code.

## Core Concepts

### 1. SemVer Rules
`MAJOR.MINOR.PATCH` — three numbers, three contracts:
- **MAJOR** (1.x.x → 2.0.0): Breaking changes. API contract may change. Read migration guide before upgrading.
- **MINOR** (1.1.x → 1.2.0): New features, backward compatible. Safe to upgrade.
- **PATCH** (1.1.1 → 1.1.2): Bug/security fix only. Always upgrade.

Version ranges in `package.json`:
```json
"^1.2.3"  // Allows 1.2.3 to <2.0.0 (minor + patch updates)
"~1.2.3"  // Allows 1.2.3 to <1.3.0 (patch updates only)
"1.2.3"   // Pinned — no updates. Must maintain manually.
```
Caret (`^`) is the npm default and is usually correct. Pin only when a specific version is confirmed stable and updates are risky.

### 2. Transitive Dependency Risk
Your project uses Library A. A uses Library B. B has a CVE. **You are affected** even though you never imported B. The fix: upgrade your direct dependency A to a version that includes a fixed B.

```
your-app → express@4.18.2 → qs@6.11.0 (CVE-2022-24999)
Fix: npm update express (which pulls fixed qs)
```

`npm audit` shows transitive vulnerabilities. `npm ls <package>` traces the dependency chain.

### 3. License Compatibility Matrix
| License | Commercial Use | Must Open-Source Your Code? | Notes |
|---------|---------------|---------------------------|-------|
| MIT | ✅ Yes | ❌ No | Most permissive, use freely |
| Apache 2.0 | ✅ Yes | ❌ No | Patent grant included |
| BSD 2/3 | ✅ Yes | ❌ No | Similar to MIT |
| ISC | ✅ Yes | ❌ No | Simplified MIT |
| GPL-2.0/3.0 | ⚠️ Conditional | ✅ Yes (if distributed) | Copyleft — your code must be GPL too |
| AGPL-3.0 | ⚠️ Conditional | ✅ Yes (even SaaS) | Network copyleft — most restrictive |
| LGPL | ✅ Yes | ⚠️ For the library only | Dynamic linking usually OK |
| Unlicensed/None | ❌ No | N/A | Cannot legally use |

**Rule**: GPL/AGPL in a commercial closed-source project = legal risk. Review with legal before using.

### 4. CVSS v3 Severity Scale
| Score | Severity | Action |
|-------|----------|--------|
| 0.0-3.9 | Low | Document, schedule for next maintenance cycle |
| 4.0-6.9 | Medium | Fix within current sprint |
| 7.0-8.9 | High | Fix within 48 hours |
| 9.0-10.0 | Critical | Fix immediately — consider rollback if in prod |

### 5. Supply Chain Attack Vectors
Attackers compromise dependencies via:
- **Typosquatting**: `lodahs` instead of `lodash` — check name carefully
- **Maintainer account takeover**: Legitimate package, compromised publisher
- **Dependency confusion**: Internal package name published publicly

Before adding any new dependency, check:
- Weekly download count (>1000/week = reasonable)
- GitHub stars and recent commit activity
- First publish date (brand new packages = higher risk)
- Publisher identity (known maintainer?)

## Reasoning Graph

```
[INPUT: Project with dependencies]
  │
  ├─► [Phase 1: Security Scan]
  │     ├── Run `npm audit --json` (or pip-audit, cargo audit)
  │     ├── Extract Critical + High CVEs
  │     ├── For each CVE: affected package, fix version, dependency chain
  │     └── Priority: Critical → immediate, High → 48h
  │
  ├─► [Phase 2: License Scan]
  │     ├── Run `npx license-checker --summary`
  │     ├── Flag GPL, AGPL, unlicensed, or unknown
  │     ├── Check: is GPL dep used in commercial/closed-source project?
  │     └── Decision: swap dep, comply with license, or get legal review
  │
  ├─► [Phase 3: Currency Check]
  │     ├── Run `npm outdated`
  │     ├── Flag packages >1 MAJOR version behind
  │     │     └── Major behind = missing security fixes + breaking change debt
  │     ├── Flag packages with available PATCH updates
  │     │     └── Patch available = security/bug fix available NOW
  │     └── Prioritize: security patches first, then minor, then major
  │
  └─► [OUTPUT: Dependency audit with action list]
```

## Execution Steps

### Step 1: Security Scan
```bash
# npm projects
npm audit --json 2>/dev/null | jq '[.vulnerabilities | to_entries[] | {
  package: .key, 
  severity: .value.severity, 
  fixAvailable: .value.fixAvailable
}] | sort_by(.severity) | reverse'

# Or simplified
npm audit 2>/dev/null

# Python projects
pip-audit --format=json

# Rust projects
cargo audit
```

### Step 2: License Scan
```bash
# npm projects
npx license-checker --production --summary
# For detailed check (with flags for problematic licenses)
npx license-checker --production --failOn "GPL-2.0;GPL-3.0;AGPL-3.0"
```

### Step 3: Currency Check
```bash
npm outdated
# Output: Package | Current | Wanted | Latest
# "Wanted" respects semver range in package.json
# "Latest" is the newest version available
```

### Step 4: Trace Vulnerable Dependency Chain
```bash
# Find WHY a vulnerable package is installed
npm ls <vulnerable-package>
# Shows: your-app → direct-dep → transitive-dep@vulnerable-version
```

### Step 5: Fix Critical CVEs
```bash
# Auto-fix what's safely fixable
npm audit fix

# For breaking changes (major version bumps)
npm audit fix --force  # Review changes carefully after this

# Manual fix: upgrade the direct dependency that pulls the vulnerable transitive
npm install <direct-dep>@latest
```

### Step 6: Produce Action List
Categorize all findings:
- **Fix NOW**: Critical CVEs (CVSS ≥ 9.0)
- **Fix this sprint**: High CVEs (CVSS 7.0-8.9)
- **Review**: License issues (GPL in commercial project)
- **Schedule**: Outdated majors (plan migration)
- **Accept**: Low CVEs with documented risk acceptance

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| `npm audit` shows 0 but deps feel outdated | Stale lockfile | `rm package-lock.json && npm install && npm audit` |
| Upgrade breaks the app | Major version with breaking changes | Read CHANGELOG.md or GitHub releases for migration guide |
| `license-checker` shows 1000+ entries | Includes all transitive deps | Add `--production` flag to filter dev dependencies |
| Can't upgrade due to peer dependency conflict | Package A requires B@1.x, C requires B@2.x | Check if A has a newer version supporting B@2.x; else use `npm install --legacy-peer-deps` |
| New dependency has 12 downloads/week | Potential supply chain risk | Evaluate: is it a niche but legitimate package, or a typosquat? Check publisher, repo, code. |

## Validation Gate

- [ ] 0 Critical CVEs in production dependencies
- [ ] 0 High CVEs (or each has documented risk acceptance)
- [ ] No GPL/AGPL in commercial project without legal review
- [ ] No unlicensed dependencies in production
- [ ] All packages with known fix versions have been upgraded or scheduled
- [ ] Action list produced with clear priority and timeline

## Output Contract

Dependency audit containing:
- **Critical CVEs**: Package name, CVE ID, CVSS score, fix version, dependency chain
- **High CVEs**: Same format, with sprint-level fix timeline
- **License violations**: Package name, license type, risk, recommended action
- **Outdated packages**: Package name, current version, latest version, breaking changes noted
- **Action list**: Prioritized by severity with specific commands to run
