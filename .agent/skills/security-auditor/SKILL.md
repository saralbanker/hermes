---
name: security-auditor
description: "Use this skill when reviewing code for security vulnerabilities. Checks for OWASP Top 10, injection patterns, authentication flaws, secrets exposure, and dependency CVEs."
version: 1.0.0
triggers:
  - "security review"
  - "vulnerability"
  - "is this secure"
  - "pentest"
  - "CVE"
  - "injection"
  - "auth bypass"
  - "@security-auditor"
token_budget: 3000
tools_required:
  - view_file
  - search_code
  - run_terminal
output_contract:
  format: "Security report: vulnerabilities by severity + remediation"
  includes:
    - critical-findings
    - high-findings
    - medium-findings
    - dependency-cves
    - remediation-steps
works_with:
  - dependency-analyzer
  - test-generator
  - code-synthesizer
  - refactoring-specialist
risk: high
---

## Mission

Audit any codebase for security vulnerabilities by scanning for OWASP Top 10 patterns, hardcoded secrets, injection vectors, authentication/authorization flaws, and dependency CVEs. Every finding includes file:line evidence, CVSS severity estimate, and a concrete remediation with code example. No finding is reported without proof. No codebase is "secure" — the question is "what vulnerabilities exist and what's their risk?"

## When To Activate

- User requests a security review or audit
- Code handles user input, authentication, or sensitive data
- Before deploying to production (pre-release gate)
- After importing new dependencies
- **Anti-trigger**: Do NOT activate for general code quality (use `code-synthesizer`) or performance (use `performance-optimizer`)

## Core Concepts

### A01: Broken Access Control
Every endpoint must verify: (1) user is authenticated, (2) user is authorized for the specific resource. Missing authorization is the #1 web vulnerability.
```typescript
// ❌ VULNERABLE: checks auth but not ownership
app.get('/api/orders/:id', authMiddleware, async (req, res) => {
  const order = await db.order.findUnique({ where: { id: req.params.id } });
  res.json(order); // Anyone authenticated can see any order
});

// ✅ FIXED: verifies ownership
app.get('/api/orders/:id', authMiddleware, async (req, res) => {
  const order = await db.order.findUnique({ where: { id: req.params.id } });
  if (order.userId !== req.user.id) return res.status(403).json({ error: 'Forbidden' });
  res.json(order);
});
```

### A03: Injection (SQL + XSS)
**SQL Injection**: Never concatenate user input into SQL. Use parameterized queries only.
```typescript
// ❌ VULNERABLE
db.query(`SELECT * FROM users WHERE id = '${req.params.id}'`);

// ✅ FIXED: parameterized
db.query('SELECT * FROM users WHERE id = $1', [req.params.id]);
```

**XSS**: Never assign user input to `innerHTML`. Use `textContent` or sanitize with DOMPurify.
```javascript
// ❌ VULNERABLE
element.innerHTML = userInput;

// ✅ FIXED
element.textContent = userInput;
// OR: element.innerHTML = DOMPurify.sanitize(userInput);
```

### A07: Authentication Failures
- JWT: verify signature AND expiry. Check `alg` field (alg:none attack). Secret must be ≥32 chars.
- Sessions: invalidate on logout. Regenerate session ID on privilege change.
- Brute force: rate-limit login endpoints (max 5 attempts per minute per IP).
```typescript
// ❌ VULNERABLE: no algorithm restriction
jwt.verify(token, secret); // accepts alg:none

// ✅ FIXED: explicit algorithm
jwt.verify(token, secret, { algorithms: ['HS256'] });
```

### Secrets Detection
Regex patterns for finding hardcoded secrets:
```regex
(api[_-]?key|password|secret|token|credential|private[_-]?key)[\s]*[=:]\s*['"][^'"]{8,}['"]
(AKIA[0-9A-Z]{16})                    # AWS Access Key
(eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})  # JWT token
(ghp_[A-Za-z0-9]{36})                 # GitHub personal access token
```

### CVSS Severity Scale
- **0.0-3.9**: Low — document and schedule fix
- **4.0-6.9**: Medium — fix within current sprint
- **7.0-8.9**: High — fix within 48 hours
- **9.0-10.0**: Critical — fix immediately, consider rollback

## Reasoning Graph

```
[INPUT: Code to audit]
  │
  ├─► [Phase 1: Automated Pattern Scan]
  │     ├── Search for hardcoded secrets (regex patterns above)
  │     ├── Search for SQL concatenation: `"SELECT" + variable` or template literals with ${
  │     ├── Search for innerHTML assignments: `.innerHTML =`
  │     ├── Search for eval(), exec(), child_process with user input
  │     ├── Search for CORS wildcard: `Access-Control-Allow-Origin: *`
  │     └── Check dependency CVEs: `npm audit` / `pip-audit`
  │
  ├─► [Phase 2: Logic Review]
  │     ├── Auth: is every sensitive route behind auth middleware?
  │     │     └── grep for route definitions, check for auth decorator/middleware
  │     ├── Authz: does each handler verify the user OWNS the resource?
  │     │     └── Check for `userId === req.user.id` or role checks
  │     ├── Rate limiting: are auth endpoints rate limited?
  │     ├── Input validation: is user input validated before use?
  │     └── Error handling: do errors leak stack traces to clients?
  │
  └─► [OUTPUT: Security report ordered by CVSS severity]
```

## Execution Steps

### Step 1: Scan for Hardcoded Secrets
```bash
grep -rn --include="*.ts" --include="*.js" --include="*.env" -iE \
  "(password|secret|api_key|token|private_key)\s*[=:]\s*['\"][^'\"]{8,}" src/
```
Review each hit. False positives are common — check if the value is a placeholder or real.

### Step 2: Scan for Injection Vectors
```bash
# SQL injection — string concatenation in queries
grep -rn --include="*.ts" --include="*.js" \
  "query\s*(\`\|('\|\")\s*\(SELECT\|INSERT\|UPDATE\|DELETE\)" src/

# XSS — innerHTML with variables
grep -rn --include="*.ts" --include="*.js" --include="*.tsx" --include="*.jsx" \
  "innerHTML\s*=" src/

# Command injection
grep -rn --include="*.ts" --include="*.js" \
  "exec(\|execSync(\|spawn(" src/
```

### Step 3: Check Dependencies
```bash
npm audit --json 2>/dev/null | jq '.vulnerabilities | to_entries[] | select(.value.severity == "high" or .value.severity == "critical") | {name: .key, severity: .value.severity, via: .value.via}'
```

### Step 4: Review Auth Flow
List all route definitions. For each:
- Is auth middleware applied? (e.g., `app.use('/api', authMiddleware)`)
- Does the handler check resource ownership?
- Are admin-only routes restricted by role?

### Step 5: Check JWT Configuration
```bash
grep -rn "jwt.verify\|jwt.sign\|jsonwebtoken" src/
```
For each hit: is `algorithms` specified? Is `expiresIn` set? Is the secret from env, not hardcoded?

### Step 6: Review Error Handling
```bash
grep -rn "catch\|.catch" src/ --include="*.ts" --include="*.js" | head -20
```
Check: do catch blocks send stack traces to the client? They should log internally and return a generic message.

### Step 7: Produce Report
Order findings by CVSS severity: Critical → High → Medium → Low. Each finding has: vulnerability type, file:line, code snippet, remediation with fixed code.

## Failure Modes

| Error | Cause | Recovery |
|-------|-------|----------|
| `npm audit` shows 0 but deps are old | Stale `package-lock.json` | `rm package-lock.json && npm install && npm audit` |
| Auth middleware present but authz missing | Auth confirms identity, not permission | Add ownership check: `if (resource.userId !== req.user.id) return 403` |
| JWT `alg:none` accepted | No algorithm restriction in `jwt.verify` | Add `{ algorithms: ['HS256'] }` to verify options |
| SQL injection through ORM raw queries | ORM has a raw query escape hatch | Replace `db.query(\`...${id}\`)` with `db.query('...$1', [id])` |
| Secrets found in git history | Rotated in code but still in old commits | Rotate the secret immediately; use `git filter-branch` or BFG to purge history |

## Validation Gate

- [ ] No hardcoded secrets in source (grep returned 0 relevant real hits)
- [ ] All SQL uses parameterized queries (no string concatenation)
- [ ] No `innerHTML = userInput` patterns
- [ ] `npm audit` shows 0 high/critical CVEs (or documented risk acceptance)
- [ ] All sensitive routes behind auth middleware
- [ ] All resource handlers verify ownership (authz, not just auth)
- [ ] JWT verification specifies allowed algorithms
- [ ] Error responses don't leak stack traces

## Output Contract

Security report containing:
- **Critical findings**: Vulnerabilities with CVSS ≥ 9.0 — file:line, code, remediation
- **High findings**: CVSS 7.0-8.9 — file:line, code, remediation
- **Medium findings**: CVSS 4.0-6.9 — file:line, code, remediation
- **Dependency CVEs**: Package name, CVE ID, severity, fix version
- **Remediation steps**: Ordered by priority, each with before/after code
