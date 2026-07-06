# Landing module

Self-contained marketing landing page. **Isolated by design** — edits here
never touch the in-app tool/dashboard pages or the API.

## Where things live
| Concern | File |
|---|---|
| Copy / content (edit this to change text) | `app/landing/content.py` |
| Page shell + section order | `app/templates/landing/index.html` |
| One section = one partial | `app/templates/landing/sections/*.html` |
| Dark premium design tokens + styles | `app/static/landing/landing.css` |
| Route (`GET /`) | `app/routes.py` → `index()` |

## Rules for future edits
- To change a section's copy: edit only its block in `content.py`.
- To restyle: edit only `landing.css` (all tokens are `--lp-*`, scoped to `.lp`).
- To add/reorder sections: add a partial under `sections/` and an `{% include %}`
  line in `index.html`. Nothing else needs to change.
- Never edit the light `ds-*` design system or tool templates from here.

## Design system
Dark, violet-accent, glassmorphism. All values are tokens in the `.lp` scope
at the top of `landing.css` — no hardcoded colors/spacing below the token block.
The in-app pages keep their own light `design-system.css`; the two never collide.
