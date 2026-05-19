# Tag Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add tag-based filtering UI (pill buttons, AND logic) to challenges, prebuild, and store pages.

**Architecture:** Pure frontend filtering. Backend changes minimal: add `tags` field to `_challenge_to_card()` return dict, add `tags` to `PrebuildManager.get_status()`, and add `tags` to `ChallengeStore.get_local_challenges()`. Each page renders a tag bar from collected tags and filters items client-side.

**Tech Stack:** Jinja2 templates, Alpine.js, Tailwind CSS

---

### Task 1: Add tags to _challenge_to_card() and prebuild get_status()

**Files:**
- Modify: `benchmark_platform/web/context.py:67-89`
- Modify: `benchmark_platform/web/prebuild_manager.py:15-23` (ChallengeStatus dataclass)
- Modify: `benchmark_platform/web/prebuild_manager.py:56-76` (init loop)
- Modify: `benchmark_platform/web/prebuild_manager.py:141-153` (get_status)
- Modify: `benchmark_platform/web/store.py:45-76` (get_local_challenges)

- [ ] **Step 1: Add `tags` to `_challenge_to_card()` return dict**

In `benchmark_platform/web/context.py`, add `"tags": bm.tags,` to the return dict at line 89 (before the closing `}`):

```python
        "started_at": started_at,
        "expires_at": expires_at,
        "tags": bm.tags,
    }
```

- [ ] **Step 2: Add `tags` field to `ChallengeStatus` dataclass**

In `benchmark_platform/web/prebuild_manager.py`, add a `tags` field to the `ChallengeStatus` dataclass:

```python
@dataclass
class ChallengeStatus:
    code: str
    benchmark_id: str
    name: str
    source_path: Path = field(repr=False)
    status: str = "pending"
    log_lines: list[str] = field(default_factory=list)
    unsupported_reason: str = ""
    tags: list[str] = field(default_factory=list)
```

- [ ] **Step 3: Populate tags in PrebuildManager.__init__**

In the init loop (around line 69), pass `tags=bm.tags` when creating `ChallengeStatus`:

```python
            self._statuses[bm_id] = ChallengeStatus(
                code=bm_id,
                benchmark_id=bm_id,
                name=bm.name,
                source_path=source_path,
                status=status,
                unsupported_reason=c.unsupported_reason if c.unsupported else "",
                tags=bm.tags,
            )
```

- [ ] **Step 4: Include tags in get_status() output**

In `get_status()`, add `"tags"` to the returned dict:

```python
    def get_status(self) -> list[dict]:
        """Return status list for all challenges."""
        result = []
        for cs in self._statuses.values():
            result.append({
                "code": cs.code,
                "benchmark_id": cs.benchmark_id,
                "name": cs.name,
                "status": cs.status,
                "log_lines": cs.log_lines[-200:],
                "unsupported_reason": cs.unsupported_reason,
                "tags": cs.tags,
            })
        return result
```

- [ ] **Step 5: Add tags to ChallengeStore.get_local_challenges()**

In `benchmark_platform/web/store.py`, inside `get_local_challenges()`, add `"tags": []` to the initial `ch` dict and read it from benchmark.json:

```python
                ch = {
                    "category": category_dir.name,
                    "name": challenge_dir.name,
                    "description": "",
                    "difficulty": "",
                    "flag_count": 1,
                    "size": 0,
                    "asset": "",
                    "downloaded": True,
                    "has_update": False,
                    "source": "local",
                    "tags": [],
                }
```

And inside the `benchmark_json.exists()` block, add:

```python
                        ch["tags"] = meta.get("tags", [])
```

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/web/context.py benchmark_platform/web/prebuild_manager.py benchmark_platform/web/store.py
git commit -m "feat: expose tags field in challenge card, prebuild status, and store APIs"
```

---

### Task 2: Add tag filter to challenges page

**Files:**
- Modify: `benchmark_platform/web/templates/pages/challenges.html`

- [ ] **Step 1: Add `data-tags` attribute to challenge cards**

Change line 145-150 to include `data-tags`:

```html
      <div data-challenge-card
           data-solved="{{ 'true' if card.solved else 'false' }}"
           data-status="{{ card.instance_status }}"
           data-name="{{ card.name }}"
           data-benchmark-id="{{ card.benchmark_id }}"
           data-enabled="{{ 'true' if card.enabled else 'false' }}"
           data-tags="{{ card.tags | tojson }}">
```

- [ ] **Step 2: Add tag filter bar HTML**

Insert tag filter bar between the filter bar (line 21) and the level groups div (line 24). Collect all tags from `level_groups` in Jinja, sorted by frequency:

```html
<!-- Tag filter bar -->
{% set ns = namespace(tag_counts={}) %}
{% for lg in level_groups %}
  {% for card in lg.challenges %}
    {% for tag in card.tags %}
      {% if tag in ns.tag_counts %}
        {% set _ = ns.tag_counts.update({tag: ns.tag_counts[tag] + 1}) %}
      {% else %}
        {% set _ = ns.tag_counts.update({tag: 1}) %}
      {% endif %}
    {% endfor %}
  {% endfor %}
{% endfor %}
{% set all_tags = ns.tag_counts.items() | sort(attribute='1', reverse=true) %}
{% if all_tags %}
<div class="flex items-center gap-2 mb-4 overflow-x-auto pb-1" x-data="{selectedTags: []}" @tag-filter-change.window="$dispatch('filter-change', {filter: document.querySelector('[x-model=filter]')?.value || 'all', search: document.querySelector('[x-model=search]')?.value || ''})">
  {% for tag, count in all_tags %}
  <button @click="selectedTags.includes('{{ tag }}') ? selectedTags = selectedTags.filter(t => t !== '{{ tag }}') : selectedTags.push('{{ tag }}'); $dispatch('tag-filter-change')"
          :class="selectedTags.includes('{{ tag }}') ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'"
          class="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap cursor-pointer transition-colors">
    {{ tag }}
  </button>
  {% endfor %}
  <button x-show="selectedTags.length > 0" x-cloak
          @click="selectedTags = []; $dispatch('tag-filter-change')"
          class="text-[11px] px-2.5 py-1 rounded-full text-red-500 hover:bg-red-50 whitespace-nowrap cursor-pointer transition-colors">
    清除筛选
  </button>
</div>
{% endif %}
```

- [ ] **Step 3: Integrate tag filtering into existing filter-change handler**

Update the `@filter-change.window` handler in the level groups div to also check tags. The tag bar dispatches `tag-filter-change` which triggers `filter-change`. We need a unified approach — move to a shared Alpine scope. Replace the entire structure from line 5 through line 37 with a unified approach:

Replace the existing filter bar `x-data` at line 5:
```html
<div class="flex items-center justify-between mb-6" x-data>
```

And replace the level groups div filter handler. The new combined approach:

```html
<!-- Level groups -->
<div class="space-y-8" x-data
     @filter-change.window="
       const f = $event.detail.filter;
       const s = $event.detail.search.toLowerCase();
       const tags = $event.detail.tags || [];
       document.querySelectorAll('[data-challenge-card]').forEach(el => {
         const d = el.dataset;
         let show = true;
         if(f === 'solved' && d.solved !== 'true') show = false;
         if(f === 'unsolved' && d.solved === 'true') show = false;
         if(f === 'running' && d.status !== 'running') show = false;
         if(s && !d.name.toLowerCase().includes(s) && !d.benchmarkId.toLowerCase().includes(s)) show = false;
         if(tags.length > 0) {
           const cardTags = JSON.parse(d.tags || '[]');
           if(!tags.every(t => cardTags.includes(t))) show = false;
         }
         el.style.display = show ? '' : 'none';
       });
     ">
```

The filter bar and tag bar both dispatch `filter-change` with the current state. Consolidate into a single top-level Alpine component wrapping everything:

Actually, the cleanest approach: wrap the entire page content in a single Alpine component that holds `filter`, `search`, and `selectedTags`, and a single `applyFilter()` method.

Replace the entire `{% block content %}` with:

```html
{% block content %}
<div x-data="{filter: 'all', search: '', selectedTags: []}" x-effect="applyFilter(filter, search, selectedTags)">

<!-- Filter bar -->
<div class="flex items-center justify-between mb-6">
  <div class="text-[13px] text-gray-500">
    共 {{ total_challenges }} 题 · {{ total_flags }} flags
  </div>
  <div class="flex items-center gap-3">
    <select x-model="filter"
            class="h-9 px-3 text-[12px] bg-gray-50 border-0 rounded-lg text-gray-900 focus:ring-2 focus:ring-gray-900 cursor-pointer">
      <option value="all">全部</option>
      <option value="unsolved">未解决</option>
      <option value="solved">已解决</option>
      <option value="running">运行中</option>
    </select>
    <input type="text" x-model="search" @input.debounce.300ms=""
           placeholder="搜索题目..."
           class="h-9 w-48 px-3 text-[12px] bg-gray-50 border-0 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-gray-900 transition-shadow">
  </div>
</div>

<!-- Tag filter bar -->
{% set ns = namespace(tag_counts={}) %}
{% for lg in level_groups %}
  {% for card in lg.challenges %}
    {% for tag in card.tags %}
      {% if tag in ns.tag_counts %}
        {% set _ = ns.tag_counts.update({tag: ns.tag_counts[tag] + 1}) %}
      {% else %}
        {% set _ = ns.tag_counts.update({tag: 1}) %}
      {% endif %}
    {% endfor %}
  {% endfor %}
{% endfor %}
{% set all_tags = ns.tag_counts.items() | sort(attribute='1', reverse=true) %}
{% if all_tags %}
<div class="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
  {% for tag, count in all_tags %}
  <button @click="selectedTags.includes('{{ tag }}') ? selectedTags = selectedTags.filter(t => t !== '{{ tag }}') : selectedTags.push('{{ tag }}')"
          :class="selectedTags.includes('{{ tag }}') ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'"
          class="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap cursor-pointer transition-colors">
    {{ tag }}
  </button>
  {% endfor %}
  <button x-show="selectedTags.length > 0" x-cloak
          @click="selectedTags = []"
          class="text-[11px] px-2.5 py-1 rounded-full text-red-500 hover:bg-red-50 whitespace-nowrap cursor-pointer transition-colors">
    清除筛选
  </button>
</div>
{% endif %}

<!-- Level groups -->
<div class="space-y-8">
  ... (existing level group HTML unchanged) ...
</div>

</div>

<script>
function applyFilter(filter, search, selectedTags) {
  const s = search.toLowerCase();
  document.querySelectorAll('[data-challenge-card]').forEach(el => {
    const d = el.dataset;
    let show = true;
    if(filter === 'solved' && d.solved !== 'true') show = false;
    if(filter === 'unsolved' && d.solved === 'true') show = false;
    if(filter === 'running' && d.status !== 'running') show = false;
    if(s && !d.name.toLowerCase().includes(s) && !d.benchmarkId.toLowerCase().includes(s)) show = false;
    if(selectedTags.length > 0) {
      const cardTags = JSON.parse(d.tags || '[]');
      if(!selectedTags.every(t => cardTags.includes(t))) show = false;
    }
    el.style.display = show ? '' : 'none';
  });
}
</script>

{% include "components/modal_submit.html" %}
{% endblock %}
```

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/web/templates/pages/challenges.html
git commit -m "feat: add tag filter bar to challenges page"
```

---

### Task 3: Add tag filter to prebuild page

**Files:**
- Modify: `benchmark_platform/web/templates/pages/prebuild.html`

- [ ] **Step 1: Add tag state and computed properties to prebuildPage()**

In the `prebuildPage()` function, add `selectedTags: []` to the data, and add an `allTags` computed property and a `filteredChallenges` computed property:

```javascript
    selectedTags: [],

    get allTags() {
      const counts = {};
      this.challenges.forEach(c => {
        (c.tags || []).forEach(t => { counts[t] = (counts[t] || 0) + 1; });
      });
      return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(e => e[0]);
    },

    get filteredChallenges() {
      if (this.selectedTags.length === 0) return this.challenges;
      return this.challenges.filter(c => {
        const tags = c.tags || [];
        return this.selectedTags.every(t => tags.includes(t));
      });
    },

    toggleTag(tag) {
      const idx = this.selectedTags.indexOf(tag);
      if (idx >= 0) this.selectedTags.splice(idx, 1);
      else this.selectedTags.push(tag);
    },
```

- [ ] **Step 2: Replace `challenges` with `filteredChallenges` in the template x-for**

Change line 89:
```html
        <template x-for="item in filteredChallenges" :key="item.code">
```

- [ ] **Step 3: Update `allSelected` and `toggleSelectAll` to work with filteredChallenges**

Update the computed properties:
```javascript
    get allSelected() {
      const pending = this.filteredChallenges.filter(c => c.status !== 'cached' && c.status !== 'unsupported');
      return pending.length > 0 && pending.every(c => this.selected[c.code]);
    },

    toggleSelectAll() {
      const pending = this.filteredChallenges.filter(c => c.status !== 'cached' && c.status !== 'unsupported');
      const allSel = this.allSelected;
      pending.forEach(c => { this.selected[c.code] = !allSel; });
    },
```

- [ ] **Step 4: Add tag filter bar HTML**

Insert the tag filter bar between the stats bar and the table (after line 71, before line 73):

```html
  <!-- Tag filter bar -->
  <template x-if="allTags.length > 0">
    <div class="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
      <template x-for="tag in allTags" :key="tag">
        <button @click="toggleTag(tag)"
                :class="selectedTags.includes(tag) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'"
                class="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap cursor-pointer transition-colors"
                x-text="tag">
        </button>
      </template>
      <button x-show="selectedTags.length > 0" x-cloak
              @click="selectedTags = []"
              class="text-[11px] px-2.5 py-1 rounded-full text-red-500 hover:bg-red-50 whitespace-nowrap cursor-pointer transition-colors">
        清除筛选
      </button>
    </div>
  </template>
```

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/templates/pages/prebuild.html
git commit -m "feat: add tag filter bar to prebuild page"
```

---

### Task 4: Add tag filter to store page

**Files:**
- Modify: `benchmark_platform/web/templates/pages/store.html`

- [ ] **Step 1: Add tag state and filtering to storePage()**

Add `selectedTags: []` and tag-related methods to the `storePage()` function:

```javascript
    selectedTags: [],

    get allTags() {
      const counts = {};
      this.challenges.forEach(c => {
        (c.tags || []).forEach(t => { counts[t] = (counts[t] || 0) + 1; });
      });
      return Object.entries(counts).sort((a, b) => b[1] - a[1]).map(e => e[0]);
    },

    get filteredChallenges() {
      if (this.selectedTags.length === 0) return this.challenges;
      return this.challenges.filter(c => {
        const tags = c.tags || [];
        return this.selectedTags.every(t => tags.includes(t));
      });
    },

    toggleTag(tag) {
      const idx = this.selectedTags.indexOf(tag);
      if (idx >= 0) this.selectedTags.splice(idx, 1);
      else this.selectedTags.push(tag);
    },
```

- [ ] **Step 2: Update `categories` and `challengesByCategory` to use filteredChallenges**

```javascript
    get categories() {
      return [...new Set(this.filteredChallenges.map(c => c.category))].sort();
    },
    get downloadedCount() {
      return this.filteredChallenges.filter(c => c.downloaded).length;
    },
    get updateCount() {
      return this.filteredChallenges.filter(c => c.has_update).length;
    },
    challengesByCategory(cat) {
      return this.filteredChallenges.filter(c => c.category === cat);
    },
```

- [ ] **Step 3: Add tag filter bar HTML**

Insert between the header div (after the closing `</div>` of the header section at line 53) and the error div (line 56):

```html
  <!-- Tag filter bar -->
  <template x-if="allTags.length > 0">
    <div class="flex items-center gap-2 mb-4 overflow-x-auto pb-1">
      <template x-for="tag in allTags" :key="tag">
        <button @click="toggleTag(tag)"
                :class="selectedTags.includes(tag) ? 'bg-gray-900 text-white' : 'bg-gray-100 text-gray-600 border border-gray-200 hover:bg-gray-200'"
                class="text-[11px] px-2.5 py-1 rounded-full whitespace-nowrap cursor-pointer transition-colors"
                x-text="tag">
        </button>
      </template>
      <button x-show="selectedTags.length > 0" x-cloak
              @click="selectedTags = []"
              class="text-[11px] px-2.5 py-1 rounded-full text-red-500 hover:bg-red-50 whitespace-nowrap cursor-pointer transition-colors">
        清除筛选
      </button>
    </div>
  </template>
```

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/web/templates/pages/store.html
git commit -m "feat: add tag filter bar to store page"
```

---

### Task 5: Final verification

- [ ] **Step 1: Verify all changes compile/parse correctly**

Run: `python -c "from benchmark_platform.web.context import challenges_context; print('OK')"`

Run: `python -c "from benchmark_platform.web.prebuild_manager import PrebuildManager; print('OK')"`

Run: `python -c "from benchmark_platform.web.store import ChallengeStore; print('OK')"`

- [ ] **Step 2: Run existing tests**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/ -v`

- [ ] **Step 3: Final commit if tests required fixes**

Only if fixes were needed.
