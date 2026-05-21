# About Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an admin-only `关于我们` page to the backend that introduces benchmark-platform, links the open-source repositories, explains the WgpSec Agentic ecosystem, and provides stable contact information.

**Architecture:** Add one new admin route and one new page template in the existing Jinja/Tailwind admin UI. Keep all content fixed in the repository for v1, add one sidebar entry for navigation, and serve one QR image asset from the existing static file system. Verify behavior primarily through `tests/test_web_routes.py`.

**Tech Stack:** FastAPI, Jinja2 templates, Tailwind CSS, pytest, existing static file serving

---

## File Structure

- **Modify:** `benchmark_platform/web/routes.py` — add `/web/about` admin route using the existing `_render()` helper
- **Modify:** `benchmark_platform/web/templates/components/sidebar.html` — add `关于我们` navigation entry near settings
- **Create:** `benchmark_platform/web/templates/pages/about.html` — render the new about page with the approved sections
- **Create:** `benchmark_platform/static/images/wgpsec-wechat-qrcode.png` — QR image asset referenced by the page
- **Modify:** `tests/test_web_routes.py` — add route, sidebar, repository-link, and contact-section tests

---

### Task 1: Add route and navigation coverage first

**Files:**
- Modify: `tests/test_web_routes.py`
- Modify: `benchmark_platform/web/routes.py:260-287`
- Modify: `benchmark_platform/web/templates/components/sidebar.html`

- [ ] **Step 1: Write the failing tests**

Add these tests to `tests/test_web_routes.py`:

```python
def test_about_page_returns_200_for_admin():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/about")
    assert r.status_code == 200
    assert "关于我们" in r.text
    assert "Benchmark Platform" in r.text


def test_dashboard_sidebar_shows_about_entry_for_admin():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "关于我们" in r.text
    assert '/web/about' in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_web_routes.py::test_about_page_returns_200_for_admin tests/test_web_routes.py::test_dashboard_sidebar_shows_about_entry_for_admin -v
```

Expected:
- `test_about_page_returns_200_for_admin` fails with 404 or missing template/content
- `test_dashboard_sidebar_shows_about_entry_for_admin` fails because the sidebar link does not exist yet

- [ ] **Step 3: Write minimal implementation**

Add the route in `benchmark_platform/web/routes.py` near the other page routes:

```python
@web_router.get("/about")
async def page_about(request: Request):
    return _render(request, "pages/about.html", {"page": "about"})
```

Add the sidebar entry in `benchmark_platform/web/templates/components/sidebar.html` near `系统设置`:

```jinja2
<a href="/web/about"
   class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
          {% if page == 'about' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
  <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
    <path stroke-linecap="round" stroke-linejoin="round" d="M11.25 11.25l.041-.02a.75.75 0 0 1 1.09.852l-.708 2.836a.75.75 0 0 0 1.09.852l.041-.02M12 8.25h.008v.008H12V8.25Z"/>
    <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>
  </svg>
  关于我们
</a>
```

Create a temporary minimal page template `benchmark_platform/web/templates/pages/about.html`:

```jinja2
{% extends "base.html" %}
{% block title %}关于我们 — Benchmark Platform{% endblock %}
{% block content %}
<div class="bg-white rounded-xl border border-gray-100 p-6">
  <h1 class="text-[18px] font-semibold text-gray-900">关于我们</h1>
  <p class="mt-2 text-[13px] text-gray-600">Benchmark Platform</p>
</div>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_web_routes.py::test_about_page_returns_200_for_admin tests/test_web_routes.py::test_dashboard_sidebar_shows_about_entry_for_admin -v
```

Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_routes.py benchmark_platform/web/routes.py benchmark_platform/web/templates/components/sidebar.html benchmark_platform/web/templates/pages/about.html
git commit -m "feat: add admin about page route and navigation"
```

---

### Task 2: Fill the about page with repository and ecosystem content

**Files:**
- Modify: `tests/test_web_routes.py`
- Modify: `benchmark_platform/web/templates/pages/about.html`

- [ ] **Step 1: Write the failing tests**

Extend `tests/test_web_routes.py` with these assertions:

```python
def test_about_page_shows_repository_links_and_ecosystem_content():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/about")
    assert r.status_code == 200
    assert "https://github.com/wgpsec/benchmark-platform" in r.text
    assert "https://github.com/wgpsec/benchmark-challenges" in r.text
    assert "AboutSecurity" in r.text
    assert "context1337" in r.text
    assert "tchkiller" in r.text
    assert "PoJun" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_web_routes.py::test_about_page_shows_repository_links_and_ecosystem_content -v
```

Expected: FAIL because the page only contains the temporary minimal content

- [ ] **Step 3: Write minimal implementation**

Replace `benchmark_platform/web/templates/pages/about.html` with a full page containing these sections:

```jinja2
{% extends "base.html" %}
{% block title %}关于我们 — Benchmark Platform{% endblock %}
{% block content %}
<div class="space-y-6">
  <section class="bg-white rounded-xl border border-gray-100 p-6">
    <h1 class="text-[20px] font-semibold text-gray-900">Benchmark Platform</h1>
    <p class="mt-3 text-[13px] leading-6 text-gray-600">面向 CTF、攻防能力评测与 AI Agent 验证场景的靶场平台，提供动态 Flag、多队伍隔离、Web UI / API / MCP 接入、题库管理与赛事数据统计能力。</p>
    <div class="mt-4 flex flex-wrap gap-2 text-[12px]">
      <span class="px-2.5 py-1 rounded-full bg-gray-100 text-gray-700">Dynamic Flag</span>
      <span class="px-2.5 py-1 rounded-full bg-gray-100 text-gray-700">Multi-team isolation</span>
      <span class="px-2.5 py-1 rounded-full bg-gray-100 text-gray-700">Web UI / API / MCP</span>
      <span class="px-2.5 py-1 rounded-full bg-gray-100 text-gray-700">Challenge store</span>
      <span class="px-2.5 py-1 rounded-full bg-gray-100 text-gray-700">Competition analytics</span>
    </div>
  </section>

  <section class="grid grid-cols-1 md:grid-cols-2 gap-4">
    <div class="bg-white rounded-xl border border-gray-100 p-5">
      <div class="text-[15px] font-semibold text-gray-900">benchmark-platform</div>
      <p class="mt-2 text-[13px] text-gray-600">平台后端、Web 管理界面、API 与 MCP 能力所在仓库。</p>
      <a href="https://github.com/wgpsec/benchmark-platform" target="_blank" class="mt-4 inline-flex text-[13px] font-medium text-rose-600 hover:text-rose-700">查看 GitHub 仓库</a>
    </div>
    <div class="bg-white rounded-xl border border-gray-100 p-5">
      <div class="text-[15px] font-semibold text-gray-900">benchmark-challenges</div>
      <p class="mt-2 text-[13px] text-gray-600">题目数据、题包与挑战内容所在仓库。</p>
      <a href="https://github.com/wgpsec/benchmark-challenges" target="_blank" class="mt-4 inline-flex text-[13px] font-medium text-rose-600 hover:text-rose-700">查看 GitHub 仓库</a>
    </div>
  </section>

  <section class="bg-white rounded-xl border border-gray-100 p-6">
    <h2 class="text-[16px] font-semibold text-gray-900">WgpSec Agentic 生态</h2>
    <div class="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="rounded-lg border border-gray-100 p-4"><div class="text-[14px] font-medium text-gray-900">AboutSecurity</div><p class="mt-2 text-[13px] text-gray-600">结构化安全知识库，沉淀技能、字典、Payload 与漏洞知识。</p></div>
      <div class="rounded-lg border border-gray-100 p-4"><div class="text-[14px] font-medium text-gray-900">context1337</div><p class="mt-2 text-[13px] text-gray-600">将知识资产转为可供 AI Agent 检索与调用的 MCP 服务层。</p></div>
      <div class="rounded-lg border border-gray-100 p-4"><div class="text-[14px] font-medium text-gray-900">tchkiller</div><p class="mt-2 text-[13px] text-gray-600">面向渗透测试任务的自主式 Agent 执行层。</p></div>
      <div class="rounded-lg border border-gray-100 p-4"><div class="text-[14px] font-medium text-gray-900">benchmark-platform</div><p class="mt-2 text-[13px] text-gray-600">用于评估 Agent 攻防能力的靶场与赛事运行平台。</p></div>
      <div class="rounded-lg border border-gray-100 p-4 md:col-span-2"><div class="text-[14px] font-medium text-gray-900">PoJun</div><p class="mt-2 text-[13px] text-gray-600">通用问题求解引擎，用于更广泛的智能决策与任务处理场景。</p></div>
    </div>
  </section>
</div>
{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_web_routes.py::test_about_page_shows_repository_links_and_ecosystem_content -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_routes.py benchmark_platform/web/templates/pages/about.html
git commit -m "feat: add about page project and ecosystem content"
```

---

### Task 3: Add contact section and QR image asset

**Files:**
- Modify: `tests/test_web_routes.py`
- Modify: `benchmark_platform/web/templates/pages/about.html`
- Create: `benchmark_platform/static/images/wgpsec-wechat-qrcode.png`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/test_web_routes.py`:

```python
def test_about_page_shows_contact_section():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/about")
    assert r.status_code == 200
    assert "如需定制化部署、赛事支持或合作交流，可通过以下方式联系。" in r.text
    assert "mailto:" in r.text
    assert "/static/images/wgpsec-wechat-qrcode.png" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python3 -m pytest tests/test_web_routes.py::test_about_page_shows_contact_section -v
```

Expected: FAIL because the contact section and QR asset reference are missing

- [ ] **Step 3: Write minimal implementation**

Create the image file at `benchmark_platform/static/images/wgpsec-wechat-qrcode.png` using the real public account QR image you want to expose.

Append this contact section to `benchmark_platform/web/templates/pages/about.html`:

```jinja2
  <section class="bg-white rounded-xl border border-gray-100 p-6">
    <h2 class="text-[16px] font-semibold text-gray-900">联系交流</h2>
    <p class="mt-2 text-[13px] text-gray-600">如需定制化部署、赛事支持或合作交流，可通过以下方式联系。</p>
    <div class="mt-5 grid grid-cols-1 md:grid-cols-[1fr_220px] gap-6 items-start">
      <div>
        <div class="text-[12px] uppercase tracking-wider text-gray-400">Email</div>
        <a href="mailto:contact@wgpsec.org" class="mt-2 inline-flex text-[14px] font-medium text-rose-600 hover:text-rose-700">contact@wgpsec.org</a>
      </div>
      <div class="rounded-xl border border-gray-100 p-4 bg-gray-50">
        <div class="text-[12px] text-gray-500 mb-3">WgpSec 公众号</div>
        <img src="/static/images/wgpsec-wechat-qrcode.png" alt="WgpSec 公众号二维码" class="w-full rounded-lg border border-gray-200 bg-white">
      </div>
    </div>
  </section>
```

If the real contact email differs, replace `contact@wgpsec.org` with the exact address you want published before implementation.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python3 -m pytest tests/test_web_routes.py::test_about_page_shows_contact_section -v
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_routes.py benchmark_platform/web/templates/pages/about.html benchmark_platform/static/images/wgpsec-wechat-qrcode.png
git commit -m "feat: add about page contact section"
```

---

### Task 4: Final verification

**Files:**
- Verify only

- [ ] **Step 1: Run focused route tests**

Run:

```bash
python3 -m pytest tests/test_web_routes.py -v
```

Expected: all route tests PASS

- [ ] **Step 2: Run full test suite**

Run:

```bash
python3 -m pytest tests/ -q
```

Expected: full suite PASS

- [ ] **Step 3: Manually verify the admin page**

Run the platform and open `/web/about` as an admin. Check:

- sidebar shows `关于我们`
- page looks visually consistent with the rest of the admin backend
- both GitHub links are visible
- ecosystem section is readable
- QR image renders correctly
- contact section tone is informational, not sales-heavy

Suggested command:

```bash
python3 -m benchmark_platform.server --benchmark-folder ./challenges --port 8088 --public-accessible-host localhost
```

Expected: page loads normally in the browser and matches the approved design boundary

- [ ] **Step 4: Commit if verification required changes**

If manual verification required no changes, do not create an extra commit.
If you changed files during manual verification, commit them with a message that describes the final polish.

---

## Self-review checklist

- Spec coverage: route, sidebar entry, information architecture, fixed content, contact section, and tests are all covered.
- Placeholder scan: no TODO/TBD markers remain in the plan. The only implementation-time variable is the exact public email if it differs from `contact@wgpsec.org`.
- Type consistency: route uses existing `_render()` pattern, tests extend `tests/test_web_routes.py`, and static image path matches the template reference.
