# Arteamis — UX Design Document

| | |
|---|---|
| Document Type | UX Design Specification |
| Based On | Arteamis PRD (July 2026) & 0710 User Feedback Optimization |
| Version | v1.1 |
| Design Scope | Governed Studio Brain — Web Application |

---

> [!TIP]
> **[Terminology Localization / User-Centric Adjustments]**
> The following table maps system-centric terms to user-friendly equivalents to lower the cognitive barrier for Makers. The main text has been updated to reflect these user-centric terms.
>
> | Former System Term | Updated User Term | Contextual Explanation |
> |---|---|---|
> | `Source` | **`Reference Docs`** (or `Docs`) | Users are more accustomed to calling uploaded PDFs/URLs "reference docs" rather than abstract "data sources". |
> | `Lesson` | **`Draft Rules`** or `Insights` | Directly indicates that it is an unapproved rule draft, sounding more professional than "lesson". |
> | `Context Pack` | **`Playbooks`** (or `Agent Profiles`) | Borrowed from agile development; e.g., a "Frontend Dev Playbook" packages necessary docs and rules. |
> | `Work Handoff` | **`Tasks`** (or `Agent Tasks`) | Minimalist concept: Create a task, select a playbook, and dispatch it to the Agent. |
> | `Trace` | **`Task History`** (or `Executions`) | Replaces the microservice monitoring term "trace" with a straightforward "task history" concept. |

---

## I. Design Principles

Before diving into page layouts, let's clarify the core principles driving all design decisions:

1. **Progressive Disclosure**: Novice users only see core objects, while advanced mechanisms are hidden in secondary entry points. For users not in an organization, group functions are grayed out to avoid confusion.
2. **Human-First Gate & Fast-tracks**: Every critical action (promote, approve, review) cannot be bypassed. However, to adapt to agile team rhythms, we provide legal "fast-tracks" (e.g., 1-click publish, auto-templates) for high-privilege roles (Leader/Checker) and frequent operations.
3. **Trust Signal First**: Every piece of information displays its origin and confidence level (AI-drafted / human-asserted / doc-backed).
4. **Scoped Context Visibility**: The three tiers (Private / Shared / Agent-context) are color-coded consistently across the product: Blue=Private, Green=Shared/Team, Orange=Agent-context.
5. **Audit Always Present**: After any high-impact operation, a permanent visual indicator states "Logged to Audit Log" (not a modal pop-up, but a permanent UI state).

---

## II. Core Concept Clarification

To avoid confusion in the UI and workflows, we strictly define the following entities:

- **Reference Docs (Docs)**: The raw material carriers (e.g., PDF audit reports, URLs).
- **Draft Rules (Insights)**: **Descriptive** knowledge points manually extracted from Docs (e.g., "This report points out a reentrancy vulnerability in withdraw()"). Divided into Personal Drafts (visible only to you) and Group Drafts (visible to the team after review).
- **Rule**: A **normative** constraint elevated from a Draft Rule (e.g., "Must use ReentrancyGuard"). Agents are forced to comply. Divided into:
  - **Team Rule**: Reviewed by the team; all team Agents must comply.
  - **Personal Rule**: Takes effect without approval; constrains only personal Agent tasks. If a Personal Rule conflicts with a Team Rule, the system notifies specific personnel and clearly logs it in the Task History.
- **Denied Context**: Materials explicitly blocked by the system during Agent execution (e.g., files containing secrets, unshared private notes). This will be explicitly listed in the Task creation with blocking reasons, ensuring system trust.

---

## III. Global Architecture — Page Map

```text
Arteamis Web App
│
├── [Public] Landing / Login
│
├── [First Login] Onboarding
│   ├── Step 1: Create / Join a Group (Skippable)
│   └── Step 2: Role Assignment (Displays Leader-assigned role, or shows none)
│
├── [Authenticated] App Shell (Global Navigation + Tenant Context)
│   │
│   ├── 🏠 Home / Dashboard                    ← Studio module is grayed out if no Group
│   │
│   ├── 🧠 Brain (Company & Personal Brain)
│   │   ├── Docs List Page (Separates Personal/Team permissions)
│   │   │   └── Doc Details Page
│   │   ├── Ask (Private Q&A & Extraction) Page
│   │   ├── Personal Rules List Page
│   │   └── Team Rules List Page
│   │       └── Rule Details Page
│   │
│   ├── 📥 Review Queue                        ← Only visible to Checker / Leader
│   │   └── Proposals List Page
│   │       └── Proposal Details Page (Review Operations)
│   │
│   ├── 🤖 Agent Context                       ← Core Workflow for Maker / Leader
│   │   ├── Playbooks List Page (Supports dynamic/preset playbooks)
│   │   │   └── Playbook Details Page
│   │   └── Tasks List Page
│   │       ├── Create Task (Work Handoff) Page (Supports 1-click templates)
│   │       └── Task History (Trace) Details Page (Supports inline review)
│   │
│   ├── 📊 Measurement                         ← Only visible to Leader
│   │   └── Loop Metrics Dashboard
│   │
│   ├── 👋 Onboarding View                     ← Dedicated entry for New Hires
│   │
│   └── ⚙️  Settings
│       ├── Group Management (Create/Join/Leave/Disband)
│       ├── Studio Settings
│       ├── Members & Permissions
│       ├── Integrations
│       └── Audit Log
```

---

## IV. Detailed Page Design

---

### P-00 · Landing / Login

**Path:** Public Access
**Purpose:** Product storefront + authentication entry.
**Target Users:** Visitors · All Members

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│  [Logo: Arteamis]                    [Log In] [→]   │
├─────────────────────────────────────────────────────┤
│                                                     │
│   HERO SECTION                                      │
│   One place to build group judgment,                │
│   ready for every agent.                            │
│                                                     │
│   [ Get Early Access ]   [ See how it works ↗ ]    │
│                           (Redirect to Tutorial)    │
├─────────────────────────────────────────────────────┤
│  Core Value 3-Columns                               │
│  [Stop re-explaining] [Trust agent output] [Audit]  │
├─────────────────────────────────────────────────────┤
│  Loop Diagram:                                      │
│  Add docs → ask privately → share only              │
│  reviewed insights → turn the useful part into work.│
├─────────────────────────────────────────────────────┤
│  [Log In with Google]  [Log In with GitHub]         │
│  or                                                 │
│  [Email ___________]  [Password _______]  [Sign In] │
│  [Forgot password?]   [Create account]              │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role | Status (Pre-Beta) |
|---|---|---|---|---|
| `Get Early Access` | CTA Button (Primary) | Submit email to join Waitlist | Visitors | Available |
| `See how it works ↗` | Ghost Button | External link to tutorial page | Visitors | Available |
| `Log In with Google/GitHub` | OAuth Button | Authorize login. Only accounts configured as test users in the backend can successfully enter. | Visitors | If not a test user, intercepts and redirects to Waitlist / Under Construction page, or disabled pre-beta. |
| `Sign In` | Primary Button | Email/Password login. Only test users can enter. | Visitors | Disabled/grayed out, or prompts "Invite-only". |
| `Forgot password? / Create` | Text Link | Recover password / Register | Visitors | Registration is hidden or disabled. |

---

### P-01 · Home / Dashboard

**Path:** Home
**Purpose:** The common starting point after login.
**Target Users:** All Members

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ App Shell Top Bar                                   │
│ [Arteamis Logo] [Group: MorcaLabs ▾]               │
│                    [🔔 Notifications] [Avatar ▾]    │
├──────────┬──────────────────────────────────────────┤
│ Left Nav │ Main Content Area                        │
│          │                                          │
│ 🏠 Home  │  GREETING + QUICK ACTIONS                │
│ 🧠 Brain │  "Good morning, [Name]. Here's what      │
│  ├ Docs  │   needs your attention."                 │
│  ├ Ask   │                                          │
│  ├ P-Rule│  ┌──────────┬──────────┬──────────┐    │
│  └ T-Rule│  │ + Add    │ 🔍 Ask   │ 📋 Review│    │
│ 📥 Review│  │ Doc      │  Brain   │  Queue   │    │
│  └ Propos│  └──────────┴──────────┴──────────┘    │
│ 🤖 Agent │                                          │
│  ├ Playbk│  ── SPECIAL STATE: Users w/o Group ──    │
│  └ Tasks │  ┌─────────────────────────────────────┐ │
│          │  │ ⚠️ You are in Personal Mode         │ │
│ 📊 Metric│  │ To unlock Brain & Team Rules,       │ │
│ 👋 Onbrd │  │ please connect to a team.           │ │
│ ⚙️ Sttng │  │                                     │ │
│          │  │  [ ➕ Create or Join a Group Tab ]  │ │
│          │  └─────────────────────────────────────┘ │
│          │  (Review/Rules nav links disabled here)  │
│          │                                          │
│          │  ── PENDING (Role-based) ──              │
│          │  [Checker View]                          │
│          │  📥 3 Proposals awaiting review          │
│          │                                          │
│          │  [Maker View]                            │
│          │  🤖 2 Task Histories ready to review     │
│          │                                          │
│          │  ── RECENT ACTIVITY ──                   │
│          │  [Activity Feed: Timeline list]          │
│          │                                          │
│          │  ── BRAIN HEALTH STATUS ──               │
│          │  Docs: 14  Rules: 7  Playbooks: 4        │
│          │  Pending proposals: 3                    │
└──────────┴──────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `+ Add Doc` | Primary Action Card | Opens Add Doc modal | All |
| `🔍 Ask Brain` | Action Card | Jumps to Ask page | All |
| `📋 Review Queue` | Action Card (w/ badge) | Jumps to Review Queue. Hidden for Makers. | Checker / Leader Only |
| `[Group: MorcaLabs ▾]` | Dropdown | Organization switcher. Switching also changes Global Rules. | All |
| `[Create or Join a Group]` | Primary Button | Onboarding prompt | All |
| `[🔔 Notifications]` | Icon Button | Opens notification sidebar | All |
| `[Avatar ▾]` | Dropdown Menu | Profile / Logout | All |

---

### P-02 · Docs (Reference Docs) List Page

**Path:** Brain → Docs
**Purpose:** Manage and search all raw documents injected into the system.
**Target Users:** All Members
**Permission Control:**
- **Maker / Checker**: Full CRUD for Private Docs; Read-only for Shared Docs.
- **Leader**: Global CRUD permissions for all Private and Shared Docs in the Group.

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ HEADER                                              │
│ Reference Docs                  [ + Add Doc ]       │
│ 14 docs · 3 private · 11 shared by you              │
├─────────────────────────────────────────────────────┤
│ FILTERS                                             │
│ [All ▾]  [Type: PDF / URL / Text / Repo ▾]         │
│ [Visibility: Private / Shared ▾]                   │
│ [🔍 Search docs...]                                 │
├─────────────────────────────────────────────────────┤
│ DOC LIST                                            │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🔵 [Private]  📄 security-audit-2025.pdf        │ │
│ │ Added: Jul 10 · by You                          │ │
│ │ "Arweave smart contract audit results..."        │ │
│ │            [Ask]  [Share →]  [···]              │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟢 [Shared]   🔗 client-rules-stellar.url       │ │
│ │ Added: Jul 8 · by Alice · Reviewed by Bob        │ │
│ │ "Stellar client delivery requirements..."        │ │
│ │            [Ask]  [View Rule →]  [···]          │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ [Infinite Scroll Supported]                         │
└─────────────────────────────────────────────────────┘
```

#### Add Doc Sidebar Drawer

```text
┌──────────────────────────────────┐
│ Add Reference Doc       [✕ Close]│
├──────────────────────────────────┤
│ Type                             │
│ ○ Upload File (PDF/DOCX/TXT)     │
│ ○ Paste URL                      │
│ ○ Paste Text                     │
│ ○ Repo Document (path)           │
│                                  │
│ [Drag & drop file here]          │
│  or [Browse files]               │
│                                  │
│ Visibility                       │
│ 🔵 Private (default)             │
│   (Only you can see this)        │
│                                  │
│ ── AI Extraction ──              │
│ <mark>☑ Extract draft rules async</mark> [Discuss]  │
│ *Note: AI auto-summary may impact quality*          │
│ [Cancel]      [Upload & Index →] │
└──────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `+ Add Doc` | Primary Button | Opens Add Doc drawer | All |
| `[All ▾]` | Dropdown Filter | Toggle All / Mine / Shared | All |
| `[Type ▾]` | Dropdown Filter | Filter by file type | All |
| `[Visibility ▾]` | Dropdown Filter | Filter by Private / Shared | All |
| `[🔍 Search...]` | Search Input | Full-text search on doc name/content | All |
| `Ask` (Item) | Ghost Button | Enter Ask page using this doc as context | All |
| `Share →` (Private) | Secondary Button | Open Share Proposal flow | All |
| `View Rule →` (Shared) | Secondary Button | Jump to associated Team Rule | All |
| `···` (Item) | Icon Dropdown | Rename / Delete / View Details (Maker restricted to Private) | All |
| `[Infinite Scroll]` | Interaction | List supports infinite scrolling to load more | All |

---

### P-03 · Doc Details Page

**Path:** Docs → [Doc Title]
**Purpose:** View doc details, citations, Q&A history. Core hub for extracting/sharing knowledge.
**Target Users:** Maker · Checker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ ← Back to Docs                                      │
│                                                     │
│ 📄 security-audit-2025.pdf            🔵 Private    │
│ Added Jul 10 by You · 2.4 MB                        │
│ Status: ✅ Indexed                                   │
│                                                     │
│ [Ask this doc]  [Share →]  [Download]  [Delete]    │
├─────────────────────────────────────────────────────┤
│ TABS: [Preview]  [Q&A History]  [Proposals]         │
├─────────────────────────────────────────────────────┤
│ TAB: Preview                                        │
│ [Document preview area]                             │
│ ── Doc spans used in answers ──                     │
│ [List of highlighted citations]                     │
├─────────────────────────────────────────────────────┤
│ TAB: Q&A History                                    │
│ Q: "What are the reentrancy findings?"              │
│ A: "Three high-severity..." [doc span: p.14 §3]     │
│ [Jul 10 · Private · cited]                          │
│ [Share this answer →]                               │
├─────────────────────────────────────────────────────┤
│ TAB: Proposals                                      │
│ [List of share proposals generated from this doc]   │
│ → 2 proposals · 1 accepted · 1 pending              │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `← Back to Docs` | Breadcrumb | Return to list | All |
| `Ask this doc` | Primary Button | Enter Ask page, pre-selecting this doc | All |
| `Share →` | Secondary Button | **Global Proposal**: Create Share Proposal based on entire Doc | All |
| `Download` | Ghost Button | Download original file | All |
| `Delete` | Danger Ghost Btn | Delete doc (confirm modal) | All (Role-restricted) |
| Tab: `Preview` | Tab | Document preview | All |
| Tab: `Q&A History` | Tab | Q&A history for this doc | All |
| Tab: `Proposals` | Tab | Associated proposals | All |
| `Share this answer →` | Inline Button | **Contextual Shortcut**: Auto-fill Q, A, and exact spans into Proposal | All |

---

### P-04 · Ask (Q&A & Extraction) Page

**Path:** Brain → Ask
**Purpose:** Makers query the system without disturbing others and extract Draft Rules from cited answers. (WF-1 & WF-6 core).
> [!NOTE]
> **Design Philosophy: Multiplayer NotebookLM for AI Agents**
> The initial experience is similar to Google's NotebookLM (hallucination-free Q&A on selected Docs). The difference: NotebookLM is a personal knowledge terminus, while here, personal insights can be submitted for approval in 1-click, converting personal drafts into Team Rules for all Agents.

**Target Users:** Maker · Checker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ Ask Your Brain                        🔵 Private    │
│ Answers are private by default.                     │
│ Your question and answer stay with you.             │
├─────────────────────────────────────────────────────┤
│ Docs in scope (Clickable/Multi-select)              │
│ ┌────────────────────────────────────────────────┐  │
│ │ ☑ security-audit-2025.pdf  🔵                  │  │
│ │ ☑ client-rules-stellar.url 🟢                  │  │
│ │ ☐ onboarding-guide.docx    🟢                  │  │
│ │ [+ Add doc to scope]                           │  │
│ └────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────┤
│ Q&A Chat Area                                       │
│                                                     │
│ [Q] "What are the reentracy vulnerabilities         │
│      in the Stellar audit?"                         │
│                                                     │
│ [A] Based on security-audit-2025.pdf:               │
│      Three reentrancy vulnerabilities were          │
│      identified in §3.2 (p.14)...                   │
│      ── Doc spans ──                                │
│      📄 security-audit-2025.pdf · p.14 §3.2        │
│                                                     │
│      [Make this a Draft Rule ↓]                     │
├─────────────────────────────────────────────────────┤
│ EXTRACTION FORM (Expands upon clicking above btn)   │
│                                                     │
│ Your Takeaway (Draft Rule):                         │
│ [ Audit highlights high reentrancy risk in...  ]    │
│                                                     │
│ Destination:                                        │
│ ○ 🔵 Keep as personal insight (Just for me)         │
│   ↳ [Save as Personal Rule] (Instant effect)        │
│ ◉ 🟢 Share to group (Requires Checker review)       │
│                                                     │
│   Tradeoffs: [ Fix might affect gas fee... ]        │
│   Owner:     [ Alice ]                              │
│   Next step: [ Fix in next sprint ]                 │
│                                                     │
│   [ Submit to Review Queue ]                        │
│   ⚡ [Save & Publish as Team Rule] (Ldr/Chk only)   │
├─────────────────────────────────────────────────────┤
│ [______ Ask a question about these docs _______ ]   │
│                                              [Ask→] │
└─────────────────────────────────────────────────────┘
```

---

### P-05 · Review Queue — Proposals List Page

**Path:** Review Queue
**Purpose:** Checker's workbench. Centralized processing of knowledge proposals (WF-2).
**Target Users:** Checker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ Review Queue                                        │
│ 3 proposals pending · 1 accepted · 2 rejected       │
├─────────────────────────────────────────────────────┤
│ FILTERS                                             │
│ [Pending ▾]  [Author ▾]  [Sensitivity ▾]           │
│ [🔍 Search proposals...]                            │
├─────────────────────────────────────────────────────┤
│ PENDING PROPOSALS                                   │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ⚠️  Doc check required                          │ │
│ │ "Reentrancy in withdraw() is high risk"         │ │
│ │ Proposed by: Alice · Jul 10                     │ │
│ │ Doc: security-audit-2025.pdf · p.14 §3.2        │ │
│ │ Sensitivity: 🔴 Confidential                    │ │
│ │ Trust level: AI-drafted                         │ │
│ │ Impact: Would update Team Rule: "No reentrancy" │ │
│ │                                                 │ │
│ │ [Review →]                     [Quick Reject ✕] │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

---

### P-06 · Proposal Details Page (Review Operations)

**Path:** Review Queue → [Proposal Title]
**Purpose:** Forces Checker to verify the reference doc. Realization of Human-first gate (WF-2).
**Target Users:** Checker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ ← Back to Queue                                     │
│                                                     │
│ Proposal: "Reentrancy in withdraw() is high risk"  │
│ By Alice · Jul 10 · Status: 🟡 Pending Review       │
├─────────────────────────────────────────────────────┤
│ SECTION 1: Proposed Knowledge                       │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Claim: "The withdraw() function has a..."       │ │
│ │ Trust level: ⚠️ AI-drafted / Human-asserted      │ │
│ │ Sensitivity: 🔴 Confidential                    │ │
│ │ Redacted fields: [client-name] [contract-addr]  │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ SECTION 2: Doc Verification (Mandatory)             │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Doc: security-audit-2025.pdf                    │ │
│ │ Span: p.14 §3.2 — "withdraw() reentrancy..."   │ │
│ │                                                 │ │
│ │ [📄 Open Reference Doc]                         │ │
│ │                                                 │ │
│ │ ☑ I have read the doc and it supports this      │ │
│ │   claim ← Unlocks Accept button                 │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ SECTION 3: Impact Assessment                        │
│ This would:                                         │
│ • Create / update Team Rule: "No reentrancy in..."  │
│ • Become available in Agent Playbooks               │
│ • Be permanently logged in Audit Trail              │
├─────────────────────────────────────────────────────┤
│ SECTION 4: Reviewer Notes                           │
│ [______________________________________]            │
│ Add your review notes (optional)                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│ [Reject with reason]          [Accept & Promote ✓] │
│                               (Disabled if doc      │
│                                check is unmarked)   │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `Open Reference Doc` | Secondary Button | Opens raw document to cited span | Checker / Leader |
| `Doc confirmation checkbox` | Checkbox | **Mandatory** to unlock Accept button | Checker / Leader |
| `Reviewer Notes` | Text Area | Optional notes, saved to audit log | Checker / Leader |
| `Reject with reason` | Danger Ghost Btn | Opens Reject reason modal | Checker / Leader |
| `Accept & Promote ✓` | Primary Button | **Opens "Create Rule" form (refine body, set category/owner), takes effect as Active upon submission** | Checker / Leader |

---

### P-07 · Rules List Page (Includes Personal / Team Rules)

**Path:** Brain → Personal Rules or Brain → Team Rules
**Purpose:** The "constitution" for individuals and teams. The contextual library (WF-3) Agents must follow during execution. Both have independent entries in the left navigation.
**Target Users:** All Members

**Page Layout:** (Using Team Rules as an example)

```text
┌─────────────────────────────────────────────────────┐
│ Team Rules                     [+ Create quick Rule]│
│ 7 active rules · 2 draft · 1 archived               │
├─────────────────────────────────────────────────────┤
│ [Active ▾]  [Category ▾]  [🔍 Search rules...]     │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟢 Active  SECURITY  [🌐 Global Pack Auto-add]  │ │
│ │ "No reentrancy in withdraw() functions"         │ │
│ │ Evidence: security-audit-2025.pdf · p.14        │ │
│ │ Owner: Alice  · Review by: Aug 2026             │ │
│ │ Used in: 3 playbooks                            │ │
│ │                [View Details]  [Edit]  [···]    │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟡 Draft  CLIENT                                │ │
│ │ "Stellar delivery: all APIs must have SLA docs" │ │
│ │ Evidence: [missing] ← Blocks submission         │ │
│ │ Owner: —   · Missing: tradeoff, owner           │ │
│ │                     [Complete Rule →] [Delete]  │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `+ Create quick Rule` | Primary Button | Manually create rule directly (unbound to Doc, tagged `Human-asserted` for quick effect) | Leader / Checker Only (Makers cannot create unreviewed Team Rules) |
| `[Active ▾]` | Dropdown Filter | Active / Draft / Archived | All |
| `[Category ▾]` | Dropdown Filter | Security / Client / Codebase / Process, etc. | All |
| `View Details` | Ghost Button | Jump to Rule Details page | All |
| `Edit` (Active rule) | Ghost Button | Opens edit sidebar (Modifications require re-review for Makers) | All |
| `Complete Rule →` | Primary Button | Fill in missing fields for drafts | All |
| `Delete` (Draft) | Danger Ghost Btn | Delete draft | Owner / Leader Only |
| `···` (Item) | Icon Button | **Archive** (invalidate for new tasks) / **View Audit** (lifetime log) / **Link to Work Item** (tie to task fixing this gap) | Archive / Audit only for Leader/Checker |
| `[🌐 Global Pack Auto-add]` | Tag | ⚡ Shortcut: Auto-injects into relevant Playbooks | Leader / Checker |

---

### P-08 · Rule Details Page

**Path:** Brain → Rules → [Rule Title]
**Purpose:** View a complete rule (Team / Personal), including evidence chain, history, linked Work Items, and Playbooks. Ensures traceability.
**Target Users:** All Members

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ ← Back to Rules                                     │
│                                                     │
│ Rule: "No reentrancy in withdraw() functions"       │
│ 🟢 Active · SECURITY · Since Jul 10 2026            │
│                                                     │
│ [Edit Rule]  [Archive]  [View Audit Trail]          │
├─────────────────────────────────────────────────────┤
│ RULE BODY                                           │
│ [Detailed textual description of the rule]          │
│                                                     │
│ Tradeoff: May require pattern refactor in legacy... │
│ Owner: Alice Kim                                    │
│ Next review: August 2026                            │
├─────────────────────────────────────────────────────┤
│ EVIDENCE                                            │
│ Doc: security-audit-2025.pdf · p.14 §3.2            │
│ Proposal accepted by: Bob · Jul 10 2026             │
│ [View Doc] [View Proposal]                          │
├─────────────────────────────────────────────────────┤
│ LINKED WORK ITEMS                                   │
│ → WI-023: "Refactor withdraw in token contract"    │
│   Status: In Progress · Agent: Claude Code          │
│   [View Work Item]                                  │
├─────────────────────────────────────────────────────┤
│ AGENT PLAYBOOKS USING THIS RULE                     │
│ → Playbook: "Token Contract Review" · Used 3x       │
│ → Playbook: "Security Preflight Standard" · Used 7x │
│ [Manage Playbooks]                                  │
└─────────────────────────────────────────────────────┘
```

---

### P-09 · Playbooks (Context Packs) List Page

**Path:** Agent Context → Playbooks
**Purpose:** Dynamically manage context boundaries sent to Agents.
**Target Users:** Maker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ Agent Playbooks                 [+ New Playbook]    │
├─────────────────────────────────────────────────────┤
│ [🔍 Search playbooks...]   [Status ▾]               │
├─────────────────────────────────────────────────────┤
│ 💡 Dynamic & Template Playbooks                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟠 [Auto] Security Standard Playbook            │ │
│ │ Automatically includes all rules tagged Security│ │
│ │ [Use in Task →]                                 │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ Custom Playbooks                                    │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟠 "Token Contract Review"                      │ │
│ │ Docs: 3 · Rules: 2 · Last used: Jul 10          │ │
│ │ Used 3 times · Avg cost: $0.24/run              │ │
│ │ [View Playbook]  [Use in Task →]  [Export MCP]  │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

#### Create Playbook Sidebar Drawer

```text
┌─────────────────────────────────────────────────────┐
│ Create Playbook                         [✕ Close]   │
├─────────────────────────────────────────────────────┤
│ 1. BASIC INFO                                       │
│ Playbook Name: [ Frontend Security Audit _______ ]  │
│ Description:   [ For scanning UI components... _ ]  │
├─────────────────────────────────────────────────────┤
│ 2. ALLOWED DOCS (2 selected)                        │
│ 🔍 [Search docs...]                                 │
│ ☑ 📄 ui-design-system-2026.pdf                      │
│ ☑ 🔗 React-Best-Practices.url                       │
│ ☐ 📄 backend-architecture.docx                      │
├─────────────────────────────────────────────────────┤
│ 3. ALLOWED RULES (3 selected)                       │
│ 🔍 [Search rules...]                                │
│ ☑ [🌐 Global] "No secrets in code" (Auto-included) │
│ ☑ [Team] "Use TailwindCSS"                          │
│ ☑ [Personal] "Always comment complex logic"         │
│ ☐ [Team] "Use GraphQL for data fetching"            │
├─────────────────────────────────────────────────────┤
│ 4. DENIED CONTEXT (Blacklist)                       │
│ Explicitly block agent from reading these files:    │
│ 1. [ **/.env ___________________________________ ] ✕│
│ 2. [ src/private_keys/* ________________________ ] ✕│
│ [+ Add path to block]                               │
├─────────────────────────────────────────────────────┤
│                                                     │
│ [Cancel]                     [Create Playbook ✓]    │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `+ New Playbook` | Primary Button | Open Create Playbook wizard | All |
| `View Playbook` | Ghost Button | View details | All |
| `Use in Task →` | Secondary Button | Create Work Task (Handoff) using this Playbook | All |
| `Export MCP` | Ghost Button | Export to MCP format for Claude Code / Cursor | All |
| `Denied Context` | Dynamic Input | Enter regex/paths (e.g., `**/.env`) to block sensitive files | All |

---

### P-10 · Playbook Details Page

**Path:** Agent Context → Playbooks → [Playbook Name]
**Purpose:** View complete playbook contents: allowed docs, allowed rules, denied context (with reasons). The bridge between WF-3 and WF-4.
**Target Users:** Maker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ ← Back to Playbooks                                 │
│                                                     │
│ 🟠 Playbook: "Token Contract Review"                │
│ Created Jul 8 · Modified Jul 10                     │
│                                                     │
│ [Edit Playbook]  [Use in Task →]  [Export MCP]      │
├─────────────────────────────────────────────────────┤
│ TABS: [Allowed]  [Denied]  [Rules]  [Usage History] │
├─────────────────────────────────────────────────────┤
│ TAB: Allowed Context                                │
│ ✅ security-audit-2025.pdf · Spans: §3–§5           │
│ ✅ client-rules-stellar.url · Full                  │
│ ✅ Rule: "No reentrancy in withdraw()"              │
│                                                     │
│ TAB: Denied Context                                 │
│ 🚫 onboarding-guide.docx                           │
│    Reason: 🔵 Private — not promoted to shared      │
│ 🚫 wallet-seed-phrases.txt                         │
│    Reason: 🔴 Secrets detected — redacted           │
│                                                     │
│ TAB: Rules                                          │
│ → "No reentrancy in withdraw()"                     │
│ → "Always include SLA docs in API delivery"         │
│                                                     │
│ TAB: Usage History                                  │
│ [Tasks list: Date, Engineer, Task, Cost, Link]      │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `Edit Playbook` | Secondary Button | Modify allowed/denied scope | All (Makers can only edit their own) |
| `Use in Task →` | Primary Button | Enter Task creation page | All |
| `Export MCP` | Ghost Button | Export JSON in MCP format | All |
| Allowed/Denied/Rules/Usage Tabs | Tab Nav | Switch playbook content views | All |
| Denied items `Reason` | Info Chip | Displays why it was excluded (expandable) | All |

---

### P-11 · Tasks List Page

**Path:** Agent Context → Tasks
**Purpose:** Manage and track all tasks assigned to Agents (running, pending review, completed).
**Target Users:** Maker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ Agent Tasks                     [+ New Task]        │
│ 3 active runs · 15 completed · 2 paused             │
├─────────────────────────────────────────────────────┤
│ [Status ▾]  [Playbook ▾]  [Agent Engine ▾]          │
│ [🔍 Search tasks...]                                │
├─────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🔄 Running  |  Task: "Refactor token.sol"       │ │
│ │ Playbook: "Security Audit" · Agent: Claude Code │ │
│ │ Started: 2 mins ago · Est. Budget: $5.00        │ │
│ │ ⏳ Processing: Analyzing withdraw() function... │ │
│ │                            [Pause]  [View Live] │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ⚠️ Review Needed | Task: "Update SLA docs"      │ │
│ │ Playbook: "Client Delivery" · Agent: Cursor     │ │
│ │ Finished: 1 hr ago · 2 writes proposed          │ │
│ │                            [Review History →]   │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ ┌─────────────────────────────────────────────────┐ │
│ │ 🟢 Completed | Task: "Add UI components"        │ │
│ │ Playbook: "Frontend UI" · Agent: Claude Code    │ │
│ │ Finished: Jul 10 · Cost: $1.20                  │ │
│ │                            [View History →]     │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `+ New Task` | Primary Button | Opens New Task form | All |
| Filters | Dropdowns | Filter by Status (Running/Completed/Review Needed), Playbook, etc. | All |
| `Pause` / `Cancel` | Ghost Button | Pause or cancel a running Agent task | Task Owner / Leader |
| `View Live` | Secondary Button | View real-time output of a running task | All |
| `Review History →` | Primary Button | Jump to Task History details to review proposed writes | Task Owner / Checker / Leader |

---

### P-11.1 · Create Task (Work Handoff) Page

**Path:** Agent Context → Tasks or via Playbook
**Purpose:** Maker completes the "Preflight Contract" before handing the work over to the Agent. WF-4 core.
**Target Users:** Maker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ New Task                                            │
├─────────────────────────────────────────────────────┤
│ ⚡ 1-Click Templates:                               │
│ [Code Review] [Security Audit] [Docs Generation]    │
│ (Clicking a template autofills the 4 steps below)   │
├─────────────────────────────────────────────────────┤
│ STEP 1: Objective                                   │
│ [_________________________________________________] │
│ Describe the task in plain language                 │
├─────────────────────────────────────────────────────┤
│ STEP 2: Playbook                                    │
│ [Select or create a Playbook ▾]                     │
│ → Preview: 3 docs · 2 rules · 2 denied              │
├─────────────────────────────────────────────────────┤
│ STEP 3: Agent Settings                              │
│ Write mode:  ○ Propose-only   ○ Direct-write        │
│ Budget:      [$____] max spend per run              │
│ Agent runtime: [Claude Code ▾]                      │
├─────────────────────────────────────────────────────┤
│ STEP 4: Preflight Check                             │
│ ┌─────────────────────────────────────────────────┐ │
│ │ ✅ Objective, Playbook, Mode, Budget defined     │ │
│ │                                                 │ │
│ │ Denied context: (2 items — visible to reviewer) │ │
│ │ 🚫 wallet-seed-phrases.txt (Reason: Secrets)    │ │
│ │ 🚫 onboarding-guide.docx (Reason: Private)      │ │
│ └─────────────────────────────────────────────────┘ │
│                                                     │
│ Approved by: [Self-approve (Leader)]                │
│                                                     │
│ [Save Draft]          [Approve & Launch Agent →]    │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `1-Click Templates` | Action Cards | ⚡ Shortcut: Clicking auto-fills all preset values below | All |
| `[Select or create a Playbook ▾]` | Dropdown + Create | Select existing Playbook or create a new one | All |
| Write mode Radio | Radio Group | Propose-only / Direct-write | All |
| `Agent runtime [▾]` | Dropdown | Claude Code / Cursor / MCP Client etc. | All |
| `Save Draft` | Ghost Button | Save as draft, do not execute | All |
| `Approve & Launch Agent →` | Primary Button (Conditional) | Enabled when all Preflight checks pass; requires confirmation modal before execution | All |
| Preflight checklist | Status Indicators | ✅/⚠️ statuses, clicking jumps to the corresponding step | All |

---

### P-12 · Task History (Trace) Details Page

**Path:** Agent Context → Tasks → [Trace ID]
**Purpose:** View complete tracking record of Agent execution. Core of WF-5. Checker decides whether to save Learnings here.
**Target Users:** Checker · Maker · Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ ← Back to Task History                              │
│                                                     │
│ Trace: WI-023 — "Refactor withdraw in token..."    │
│ Agent: Claude Code · Run: Jul 10 · Cost: $1.24      │
│ Status: ✅ Completed · 3 proposed writes             │
├─────────────────────────────────────────────────────┤
│ TABS: [Summary] [Context Used] [Actions] [Proposed Writes] [Learning] │
├─────────────────────────────────────────────────────┤
│ TAB: Context Used                                   │
│ ✅ Read: security-audit-2025.pdf §3.2               │
│ ✅ Read: Rule "No reentrancy in withdraw()"         │
│ 🚫 Blocked: onboarding-guide.docx (Private)        │
│ 🚫 Blocked: wallet-seed.txt (Secrets)              │
├─────────────────────────────────────────────────────┤
│ TAB: Actions                                        │
│ [Timeline: Agent's step-by-step actions]            │
│ 09:01 Read file: contracts/token.sol               │
│ 09:02 Analyzed withdraw() function                 │
│ 09:04 Proposed: add reentrancy guard               │
├─────────────────────────────────────────────────────┤
│ TAB: Proposed Writes                                │
│ ┌─────────────────────────────────────────────────┐ │
│ │ WRITE 1 of 3                                    │ │
│ │ File: contracts/token.sol                       │ │
│ │ Change: Add ReentrancyGuard to withdraw()       │ │
│ │ Diff: [View diff]                               │ │
│ │                                                 │ │
│ │ [Reject ✕]          [Approve Write ✓]          │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ TAB: Learning                                       │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Agent proposed adding this to brain memory:     │ │
│ │ "ReentrancyGuard pattern works for token..."    │ │
│ │                                                 │ │
│ │ ⚠️ Cannot auto-learn — requires human review    │ │
│ │                                                 │ │
│ │ [Quarantine Memory]                               │ │
│ │ [Submit as Proposal →] (Maker View)             │ │
│ │ ⚡ [Approve and add to Brain ✓] (Checker View)   │ │
│ └─────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| Tabs (5 total) | Tab Nav | Switch views of the Task History | All |
| `Approve Write ✓` | Primary Button | Approve the Agent's file modification | Task Owner / Checker / Leader Only |
| `Reject ✕` | Danger Button | Reject this modification | Task Owner / Checker / Leader Only |
| `View diff` | Text Link | Expand code diff view | All |
| `Quarantine Memory` | Danger Ghost Button | Mark this memory as untrusted, isolating it from future playbooks | Checker / Leader Only |
| `Submit as Proposal →` | Secondary Button | Maker View: Convert agent-suggested learning into a Share Proposal | All |
| `Approve and add to Brain ✓` | Primary Button | ⚡ Shortcut (Checker View): Approve inline directly, converting to a Rule | Checker / Leader Only |

---

### P-13 · Measurement Dashboard

**Path:** Metrics
**Purpose:** Founder/CTO views quantitative proof of product value. Visualization of WF-10.
**Target Users:** Leader

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ Measurement                  [Date: This Month ▾]   │
│ Proving the loop is working.                        │
├─────────────────────────────────────────────────────┤
│ TOP METRICS (KPI Cards)                             │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ │
│ │ Cost/Loop    │ │ Playbooks    │ │ Explanations │ │
│ │ $1.24 avg    │ │ Reused       │ │ Saved: ~8h   │ │
│ │ ↓ 15% vs     │ │ 12 times     │ │ Est. from    │ │
│ │ last month   │ │              │ │ reuse rate   │ │
│ └──────────────┘ └──────────────┘ └──────────────┘ │
├─────────────────────────────────────────────────────┤
│ LOOP HEALTH                                         │
│ Docs added: 14  →  Proposals: 8  →                 │
│ Accepted: 5  →  Rules active: 7  →                 │
│ Playbooks used: 12  →  Tasks reviewed: 9           │
│ [Funnel Chart Visualization]                        │
├─────────────────────────────────────────────────────┤
│ COST BREAKDOWN                                      │
│ [Line Chart: Daily/Weekly cost per loop]            │
│ [Breakdown by Agent / Project]                      │
├─────────────────────────────────────────────────────┤
│ KNOWLEDGE QUALITY                                   │
│ Doc-backed accepted updates: 95%                    │
│ Restricted context leakage: 0                       │
│ Rejected updates mutating brain: 0                  │
│                                                     │
│ [Export Report]  [View Raw Audit Log]               │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `[Date ▾]` | Dropdown/Date Picker | Switch time range (This week / Month / Custom) | Leader Only |
| `Export Report` | Ghost Button | Export PDF / CSV report | Leader Only |
| `View Raw Audit Log` | Text Link | Jump to Settings → Audit Log | Leader / Checker Only |

---

### P-14 · Onboarding View

**Path:** Onboarding or auto-appears on first login
**Purpose:** New Hire quickly grasps the current state of the project without interrupting anyone. Matches F-13 requirements.
**Target Users:** New Hire

**Page Layout:**

```text
┌─────────────────────────────────────────────────────┐
│ 👋 Welcome to Arteamis                              │
│ Here's where [Group: MorcaLabs] stands today.       │
├─────────────────────────────────────────────────────┤
│ WHAT WE BELIEVE NOW                                 │
│ Current active rules (doc-backed):                  │
│ • "No reentrancy in withdraw() functions"           │
│   ← Evidence: security-audit-2025.pdf [view]       │
│ • "All APIs must have SLA docs"                     │
│   ← Evidence: client-rules-stellar.url [view]      │
│                                                     │
│ [See all rules →]                                   │
├─────────────────────────────────────────────────────┤
│ RECENT DECISIONS                                    │
│ [Decision timeline with source citations]           │
│ Jul 10 — Accepted: "Reentrancy is HIGH risk" [Bob]  │
│ Jul 9  — New rule: "SLA docs required" [Alice]      │
├─────────────────────────────────────────────────────┤
│ WHERE TO START                                      │
│ ┌─────────────────────────────────────────────────┐ │
│ │ Suggested first task:                           │ │
│ │ → WI-024: "Set up local dev environment"        │ │
│ │   Playbook ready · [View task]                  │ │
│ └─────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────┤
│ HAVE A QUESTION?                                    │
│ [Ask the Studio Brain →]                            │
│ "Your question cites proof. Private by default."    │
└─────────────────────────────────────────────────────┘
```

**Buttons & Interactive Elements:**

| Element | Type | Description | Visible Role |
|---|---|---|---|
| `[view]` (Rule) | Text Link | Jump to Rule Details and evidence | New Hire / All |
| `See all rules →` | Text Link | Jump to Team Rules List | New Hire / All |
| `View task` | Secondary Button | Jump to Work Item details | New Hire / All |
| `Ask the Studio Brain →` | Primary Action | Jump to Ask page | New Hire / All |

---

### P-15 · Settings

**Path:** Settings
**Purpose:** Global system, team member, Agent integration configurations, and security audit log.
**Target Users:** Leader · All Members (Partial visibility)

Contains five sub-modules, adding Group Management specifically:

#### 1. Settings → Group Management

```text
┌─────────────────────────────────────────────────────┐
│ Group Management                                    │
├─────────────────────────────────────────────────────┤
│ CURRENT GROUP                                       │
│ 🏢 MorcaLabs (ID: org_12345)                        │
│ Your Role: 👑 Leader                                │
│                                                     │
│ [Leave Group]                  [Delete Group ✕]     │
├─────────────────────────────────────────────────────┤
│ JOIN OR CREATE                                      │
│ Want to switch context?                             │
│                                                     │
│ [Create New Group]   or   [Join with Invite Code]   │
└─────────────────────────────────────────────────────┘
```

| Element | Function | Visible Role |
|---|---|---|
| Current Group Status | Show current organization name and personal Role | All |
| `Create a new group` | Create new organization (Name, invites) | All |
| `Join a group` | Enter invite code to join | All |
| `Leave Group` | Danger: Exit, requires transferring Leader role | All |
| `Delete Group` | Danger: Disband org (Leader only) | Leader Only |

#### 2. Settings → Studio Settings

```text
┌─────────────────────────────────────────────────────┐
│ Studio Settings                                     │
├─────────────────────────────────────────────────────┤
│ GENERAL                                             │
│ Studio Name:                                        │
│ [ MorcaLabs ______________________________ ] [Save] │
│                                                     │
│ Language:                                           │
│ [ English ▾ ]                                       │
│                                                     │
│ Timezone:                                           │
│ [ UTC-8 (Pacific Time) ▾ ]                          │
└─────────────────────────────────────────────────────┘
```

| Element | Function | Visible Role |
|---|---|---|
| Studio name input | Edit name | Leader Only |
| Timezone / Language | Basic settings | All |

#### 3. Settings → Members & Permissions

```text
┌─────────────────────────────────────────────────────┐
│ Members & Permissions               [Invite Member] │
├─────────────────────────────────────────────────────┤
│ 4 active members                                    │
│                                                     │
│ 👤 Alice (You) · alice@morca.com                    │
│    Role: [Leader ▾]                                 │
│                                                     │
│ 👤 Bob · bob@morca.com                              │
│    Role: [Checker ▾]                    [Remove ✕]  │
│                                                     │
│ 👤 Carol · carol@morca.com                          │
│    Role: [Maker ▾]                      [Remove ✕]  │
│                                                     │
│ 👤 Dave · dave@morca.com                            │
│    Role: [New Hire ▾]                   [Remove ✕]  │
└─────────────────────────────────────────────────────┘
```

| Element | Function | Visible Role |
|---|---|---|
| `Invite Member` Button | Send email invite | Leader / Checker Only |
| Role Dropdown | Leader / Maker / Checker / New Hire | Leader / Checker Only |
| `Remove` Button | Remove member | Leader Only |

#### 4. Settings → Integrations

```text
┌─────────────────────────────────────────────────────┐
│ Integrations                                        │
├─────────────────────────────────────────────────────┤
│ AGENT RUNTIMES                                      │
│ ☐ Claude Code                                       │
│   [Connect]  — Export MCP context automatically     │
│ ☐ Cursor                                            │
│   [Connect]  — Ingest cursor rules on promotion     │
│ ☐ MCP Client (custom)                               │
│   [Add endpoint URL]                                │
├─────────────────────────────────────────────────────┤
│ MODEL KEYS                                          │
│ ○ Use Arteamis hosted (pay per token)               │
│ ○ Bring your own key (BYOK)                         │
│   [API Key: ____________________] [Save]            │
└─────────────────────────────────────────────────────┘
```

| Element | Function | Visible Role |
|---|---|---|
| `Connect` (Runtimes) | Configure Claude Code / Cursor / MCP Client | Leader / Maker Only |
| BYOK radio + API Key | Input custom LLM API key | Leader Only |

#### 5. Settings → Audit Log

```text
┌─────────────────────────────────────────────────────┐
│ Audit Log                   [Export CSV]  [Export JSON] │
├─────────────────────────────────────────────────────┤
│ [Date Range ▾]  [Actor ▾]  [Event Type ▾]           │
│ [🔍 Search events...]                               │
├─────────────────────────────────────────────────────┤
│ Jul 10 09:04 · Bob · PROPOSAL_ACCEPTED              │
│ Proposal: "Reentrancy in withdraw() HIGH risk"      │
│ Doc verified: ✅ · Audit ID: #a7f3...               │
│ [View Full Event]                                   │
│                                                     │
│ Jul 10 09:01 · Alice · AGENT_LAUNCHED               │
│ Playbook: "Token Contract Review" · Budget: $5      │
│ [View Full Event]                                   │
└─────────────────────────────────────────────────────┘
```

| Element | Function | Visible Role |
|---|---|---|
| List & Filters | Filter by Date, Actor, Event Type and read system logs | Leader / Checker Only |
| `Export CSV/JSON` | Export logs | Leader / Checker Only |

---

## V. Global UI Elements & Design Specifications

### 5.1 Color Semantics System (Product-Wide)

| Color | Meaning | Usage Context |
|---|---|---|
| 🔵 Blue | Private — Visible only to you | Private doc badge, private answer area |
| 🟢 Green | Shared / Team / Active | Shared doc, active rule, accepted proposal |
| 🟠 Orange | Agent-visible | Agent playbook, task history context |
| 🟡 Yellow | Pending / Draft / Warning | Pending proposal, draft rule, incomplete preflight |
| 🔴 Red | Confidential / Danger | High sensitivity doc, danger actions (delete/archive) |
| ⚫ Gray | Archived / Inactive | Archived rule, closed task history |

### 5.2 Trust Level Badges (Product-Wide)

| Badge | Meaning |
|---|---|
| `AI-drafted` | Generated by AI, no human assertion yet |
| `Human-asserted` | Explicitly asserted by human |
| `Doc-backed` | Supported by reference document citation |

All proposals, answers, and rules must display these badges.

### 5.3 Notification System

Notification Types (Top Right 🔔):

| Event | Notified User | Copy Example |
|---|---|---|
| New Proposal awaiting review | Checker | "Alice proposed a new draft rule — needs your review" |
| Proposal accepted/rejected | Proposal Author | "Your proposal was accepted by Bob" |
| Task History completed | Maker who launched Agent | "Agent completed — 3 writes proposed, review needed" |
| Doc indexing complete | Uploader | "security-audit-2025.pdf is ready to ask" |
| Rule due for review | Rule Owner | "Rule 'No reentrancy' is due for review in 7 days" |
| Rule Conflict (Personal vs Team) | Specific Personnel | "Conflict detected between Personal Rule and Team Rule in Task History #123" |

### 5.4 Beginner Mode (Progressive Disclosure)

Simplified navigation for novice users (New Hire or first-time users):

```text
Simplified Navigation (Beginner Mode):
• Add a Doc
• Ask a Question
• Propose to Team
• See Team Rules
• Launch Agent
• Review Task History
```

Advanced features (e.g., Audit Log, Governance settings, BYOK, Quarantine Memory) are hidden under Expert Mode, unlockable via `Enable Expert Mode` toggle in Settings. The names do not change, they are merely hidden.

### 5.5 Empty States

Dedicated empty states for every list page:

| Page | Empty State Copy | CTA |
|---|---|---|
| Docs | "No docs yet. Start by adding a document or URL." | `+ Add Doc` |
| Review Queue | "You're all caught up! No proposals waiting." | — |
| Team Rules | "No rules yet. Rules come from accepted proposals." | `View Proposals` |
| Playbooks | "No playbooks yet. Create one to give agents context." | `+ New Playbook` |

---

## VI. Key User Flows — Complete Story (The Governed Loop)

Taking a Web3 contract development scenario as an example to demonstrate the full chain for Alice (Maker), Bob (Checker), and Carol (Maker):

1. **Doc → Ask → Draft Rule**
   - Alice uploads `stellar-audit.pdf`.
   - She asks about the `withdraw` function on the Ask page and gets an answer citing p.14.
   - Alice clicks `Make this a Draft Rule` and refines it: "withdraw() has a reentrancy risk". She fills in Tradeoffs and submits it as a Group Draft Rule.
2. **Review → Rule**
   - Bob (Checker) gets a notification in the Review Queue. He compares it with the original text and clicks Accept. This knowledge enters the Company Brain.
   - Leader elevates it to a strict **Rule**: "All transfer functions must use ReentrancyGuard", and tags it `Global`.
3. **Playbook → Task**
   - Carol needs to review a new contract. She opens Tasks and selects the preset `[Security Audit]` template.
   - The system auto-injects the global Rule into the Allowed Context. It also detects local files with private keys and adds them to **Denied Context** (Reason: Contains Secrets).
4. **Agent Run → Task History**
   - Carol clicks Launch. The Agent finishes running.
   - Carol reviews the Task History: She sees clearly that the Agent read the rule, did not touch private key files, and proposed adding a modifier in the code. Carol clicks `Approve Write`.
   - The Agent proposes new knowledge (Learning). Because Carol is a Maker, she can only click `Submit as Proposal`; if Bob (Checker) were reviewing this history, he could directly click `Approve and add to Brain` in the Task History, completing the knowledge loop.

---

## VII. Design Notes — Critical Constraints

1. **Accept Button Disabled Rule**: The Accept button remains `disabled` until the Checker explicitly checks "I have read the reference doc".
2. **Launch Agent Disabled Rule**: If any item in the Preflight checklist is ⚠️, `Approve & Launch` is disabled.
3. **Memory cannot auto-learn**: Task History Learnings can never be auto-accepted; they must pass human review.
4. **Audit event visual feedback**: After an action, a toast appears at the bottom for 5 seconds: `"Action recorded in Audit Log · #a7f3"`.
5. **Denied context always visible**: The Denied list and reasons are permanently displayed in Playbooks and Task Histories.

---
*Document Version v1.1 · Complete exhaustive version optimized for daily efficiency*
