# Customer UI Visibility Design

## Goal

Allow the same `benchmark-platform` and `benchmark-challenges` codebase to serve both open-source deployments and customer-facing deployments without maintaining separate challenge versions. Customer-facing deployments should hide public/open-source links and hide challenge import/authoring entry points in the challenge management UI.

## Scope

This design only changes presentation in the platform web UI.

It does:
- hide public repository links in customer-facing deployments
- hide challenge import controls in the store/challenge management page in customer-facing deployments
- hide challenge authoring and import guidance content in customer-facing deployments
- keep the default open-source experience unchanged

It does not:
- create a second challenge repository or forked platform UI
- change challenge data, manifests, download behavior, prebuild behavior, or dynamic flag behavior
- introduce a new authorization model
- guarantee that determined operators cannot discover project origins outside the UI

## Requirements

### Functional requirements

1. The platform must support a deployment-level UI visibility profile.
2. The default profile must preserve today's open-source behavior.
3. A customer-facing profile must hide:
   - the benchmark-platform GitHub link in the sidebar
   - the benchmark-challenges repository link in the store page header
   - the import button in the store page header
   - the store page's challenge authoring/import guidance section, including spec and AI-generation links
4. Existing download, refresh, bulk download, bulk delete, prebuild, and challenge runtime actions must continue to work unchanged.
5. The visibility decision must be computed centrally and passed into templates, rather than having templates read environment variables or infer mode themselves.

### Non-functional requirements

1. The change should be low-risk and localized to presentation logic.
2. New visibility controls should be easy to extend later if additional UI elements need per-profile treatment.
3. Existing deployments that do not opt into customer mode should require no config changes.

## Recommended approach

Use a single deployment-level UI profile with centralized template context.

### Configuration model

Add a deployment setting representing the UI visibility profile:
- `open_source` — current behavior
- `customer` — hide public links and import/authoring UI

The setting name should describe presentation rather than permissions. A name such as `ui_profile` is preferred over `customer_mode` because it leaves room for future profiles without implying business logic or security boundaries.

### Context model

When rendering templates, the backend should inject one canonical profile value plus derived booleans, for example:
- `ui_profile`
- `show_public_links`
- `show_import_actions`
- `show_authoring_docs`

Templates should only consume these values. They should not contain duplicated profile mapping rules.

### Page behavior

#### Sidebar

In `benchmark_platform/web/templates/components/sidebar.html`, hide the benchmark-platform GitHub link when `show_public_links` is false.

#### Store / challenge management page

In `benchmark_platform/web/templates/pages/store.html`:
- hide the benchmark-challenges repository button when `show_public_links` is false
- hide the import button when `show_import_actions` is false
- hide the authoring/import guidance block when `show_authoring_docs` is false

The rest of the page remains unchanged.

## Architecture and boundaries

This feature is intentionally presentation-only.

The backend remains the single source of truth for visibility profile interpretation. Templates are responsible only for conditional rendering. This keeps the behavior coherent across pages and avoids scattering mode logic across Alpine and Jinja code.

This feature is not an access-control system. In customer profile, hidden actions are removed from normal UI presentation, but underlying APIs are not re-scoped by this change. If stricter separation is needed later, that should be a separate design effort for role/permission enforcement.

## Rollout behavior

1. Existing deployments continue using `open_source` implicitly.
2. Customer-facing deployments opt in by setting the new profile to `customer`.
3. No challenge re-download, prebuild invalidation, or data migration is required.

## Testing strategy

### Open-source profile

Verify that the current experience remains intact:
- sidebar GitHub link is visible
- store page repository button is visible
- import button is visible
- authoring/import guidance block is visible

### Customer profile

Verify that customer-facing presentation hides only the intended elements:
- sidebar GitHub link is hidden
- store page repository button is hidden
- import button is hidden
- authoring/import guidance block is hidden
- refresh, download, bulk download, delete, prebuild, and challenge runtime workflows still work

### Regression checks

- confirm hidden sections do not leave broken spacing or layout artifacts
- confirm no template errors occur when the new context variables are present
- confirm default profile works without any explicit configuration

## Alternatives considered

### 1. Separate open-source and customer branches

Rejected because it duplicates maintenance work and guarantees drift between deployments.

### 2. Role-based visibility only

Rejected as the first step because it conflates deployment presentation with operator permissions. Customer deployments may still have admins, but those admins should not necessarily see open-source/productization affordances.

### 3. Hard-coded customer-only template edits

Rejected because one-off conditional hiding would spread logic across templates and become brittle as more customer-facing presentation adjustments are added.

## Recommended next step

Implement the profile-driven visibility layer first, limited to sidebar and store page presentation. Keep the implementation small and reversible. If future customer deployments need stronger separation, design API- and role-level enforcement separately rather than folding it into this UI change.