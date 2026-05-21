# About Page Design

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:writing-plans after this spec is approved. Do not implement directly from this document.

**Goal:** Add an admin-side "关于我们" page to the open-source benchmark-platform backend so open-source users can understand the project, discover the GitHub repositories, learn about the WgpSec Agentic ecosystem, and find stable contact information for deployment, competition support, or collaboration.

**Non-goal:** Do not turn the open-source repository into a commercial operations console. Do not add customer-specific运营配置、白标资源上传、或商务化功能对比。

---

## 1. Why this belongs in the open-source repo

The platform should remain clearly open-source and product-led, but it is reasonable for the admin backend to contain a neutral project introduction page. This creates a discoverable place for:

- what benchmark-platform is,
- where the open-source code lives,
- what the broader WgpSec Agentic ecosystem includes,
- and how interested users can contact the team.

This is intentionally different from building a commercial branding or operations center into the OSS core.

---

## 2. Page positioning

The page should be named **“关于我们”** and live in the admin sidebar.

Its role is:

1. **Project introduction page** — explain what the platform is and what it does.
2. **Open-source navigation page** — link to benchmark-platform and benchmark-challenges.
3. **Ecosystem overview page** — introduce related WgpSec Agentic projects.
4. **Contact entry point** — provide stable contact information without aggressive sales language.

The tone should be informational first, commercial second.

Recommended closing sentence near the contact section:

> 如需定制化部署、赛事支持或合作交流，可通过以下方式联系。

Avoid stronger marketing copy such as “购买请联系”, “企业版咨询”, “套餐对比”, or pricing content.

---

## 3. Information architecture

The page should be composed of four top-level sections.

### 3.1 Platform introduction

A lead card or hero-style content block that includes:

- Title: `Benchmark Platform`
- A short description of the platform as a CTF / offensive security / AI Agent evaluation platform
- A compact set of capability tags or bullets, such as:
  - Dynamic Flag
  - Multi-team isolation
  - Web UI / API / MCP
  - Challenge store and lifecycle management
  - Competition analytics

This section answers: “What is this project?”

### 3.2 Open-source repositories

A section with two repository cards or rows:

- `benchmark-platform`
  - one-line description
  - GitHub link button
- `benchmark-challenges`
  - one-line description
  - GitHub link button

This section answers: “Where is the source?”

### 3.3 WgpSec Agentic ecosystem

A card grid or stacked list introducing the related ecosystem projects.

Expected entries:

- AboutSecurity
- context1337
- tchkiller
- benchmark-platform
- PoJun (only if the current project already publicly references it and you still want it visible here)

Each entry should contain:

- project name
- one-line role/positioning
- public link if one exists and should be exposed

This section answers: “What broader ecosystem does this belong to?”

### 3.4 Contact section

Placed at the bottom of the page.

Expected content:

- contact email
- WgpSec public account QR image
- one short contextual sentence that frames contact as collaboration/support, not hard sales

This section answers: “How do I reach the team?”

---

## 4. Layout and visual style

The page should follow the existing admin UI style:

- card-based layout
- same typography scale as the dashboard/settings pages
- same spacing rhythm and border treatment
- no flashy marketing banner style
- no overly promotional CTA buttons

The overall impression should be:

- professional,
- technical,
- informative,
- trustworthy.

The page should feel like part of the admin backend, not a landing page pasted into it.

---

## 5. Fixed content vs configurable content

### 5.1 First version: fixed content

The first implementation should hardcode the about-page content in the OSS repository.

This includes:

- platform introduction text
- GitHub repository URLs
- WgpSec / ecosystem descriptions
- public contact email
- QR image asset path

### 5.2 Do not build configuration support in v1

Do **not** add any of the following in the first version:

- admin-editable about-page fields
- image upload for QR or profile assets
- per-deployment overrides
- multiple about-page variants
- white-label “contact us” systems

Reason: this page is part of the OSS project identity, not a customer运营模块.

### 5.3 Possible future extension

If needed later, a very small configuration layer could be added for:

- contact email
- whether a specific ecosystem card is shown
- QR image path

But this is explicitly out of scope for the initial implementation.

---

## 6. Navigation placement

The admin sidebar should include an entry labeled **“关于我们”**.

Recommended placement:

- under the existing management/system area,
- near “系统设置”,
- but visually separated from operational pages like store/prebuild.

The page is admin-facing only.

---

## 7. Copywriting guidelines

Keep copy concise and factual.

Prefer:

- “是什么”
- “做什么”
- “在哪里获取源码”
- “如何联系”

Avoid:

- sales-heavy phrasing
- enterprise edition claims
- feature comparison tables
- pricing and packaging language
- customer-case style storytelling

If the page mentions collaboration, frame it as support/deployment/cooperation rather than direct selling.

---

## 8. Data and asset expectations

Implementation will likely need:

- one route for `/web/about`
- one page template
- one sidebar link
- one QR image asset placed under the existing static asset system

No database migration is required for the first version.

---

## 9. Testing expectations

Implementation should verify at least:

- admin can load `/web/about` successfully
- sidebar contains the `关于我们` entry
- page contains the expected repository links
- page contains the expected contact section
- observer/non-admin flow is unchanged unless explicitly intended otherwise

---

## 10. Scope boundary

This spec is only for the OSS **About page**.

It is **not** a spec for:

- white-label branding center
-运营设置
- contact form workflow
- CRM capture
- business lead pipeline
- commercial deployment management

Those belong in a separate private/commercial extension track.
