# Third-party notices

Code and assets copied into this repository, rather than installed as a
dependency, with the licence each one came under.

## shadcn-admin

- Repository: <https://github.com/satnaing/shadcn-admin>
- Commit vendored from: `e16c87f213a5ba5e45964e9b67c792105ec74d26`
- Vendored on: 2026-09-03

What was taken, and where it now lives:

| From the kit | Here |
| --- | --- |
| `src/styles/theme.css` (`:root`, `.dark`, radius, the chart and sidebar tokens) | `src/client/Main.css` |
| `src/styles/index.css` (the base layer: border and ring colour, thin scrollbars, the pointer cursor on buttons, the `faded-bottom` utility) | `src/client/Main.css` |
| `src/components/layout/main.tsx` | `src/client/components/layout/main.tsx` |
| `src/components/layout/header.tsx` | `src/client/components/layout/header.tsx` |
| `src/components/layout/app-sidebar.tsx` | `src/client/components/layout/app-sidebar.tsx` |
| `src/components/layout/nav-group.tsx` | `src/client/components/layout/sidebar-nav.tsx` |
| `src/components/theme-switch.tsx` | `src/client/components/layout/theme-switch.tsx` |
| `src/components/profile-dropdown.tsx` | `src/client/components/layout/profile-dropdown.tsx` |
| `src/components/search.tsx` | `src/client/components/layout/search.tsx` |
| `src/components/command-menu.tsx` | `src/client/components/layout/command-menu.tsx` |
| `src/context/search-provider.tsx` | `src/client/components/layout/search-provider.tsx` |
| `src/components/data-table/*` | `src/client/components/data-table/*` |
| `src/features/tasks/components/tasks-table.tsx` (the table itself) | `src/client/components/data-table/data-table.tsx` |
| `src/tanstack-table.d.ts` | `src/client/components/data-table/tanstack-table.d.ts` |
| `src/lib/utils.ts` (`getPageNumbers`) | `src/client/utils.ts` |

Each vendored file says at the top which file it came from and how it was
changed. The changes throughout are: TanStack Router's `Link`, `useNavigate`
and `useLocation` swapped for react-router's; Radix's and Lucide's icons
swapped for Tabler's; the kit's demo data and Clerk wiring replaced by props
and by `src/client/nav.ts`.

```
MIT License

Copyright (c) 2024 Sat Naing

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## shadcn/ui

The components under `src/client/components/ui` come from the shadcn/ui
registry (<https://ui.shadcn.com>), MIT, copied in by `npx shadcn add` and
edited in place afterwards. The kit uses the same registry, which is why the
two agree.

## Inter

- Files: `public/fonts/inter-*.woff2`
- Source: Google Fonts, from the Inter project (<https://github.com/rsms/inter>)
- Licence: SIL Open Font License 1.1, in `public/fonts/OFL.txt`

Only the latin and latin-extended subsets are here, upright and italic, as
variable fonts covering weights 100 to 900. They are served from `public/` so
the app never asks a font CDN for anything.
