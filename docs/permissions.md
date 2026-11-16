# Source permissions

Checked 16 November 2026.

## ISW (understandingwar.org)

**Status: written permission required. Request sent 16 November 2026 to press@understandingwar.org (text in [isw_permission_email.md](isw_permission_email.md)). Collection stays disabled until a reply grants permission.**

Fair Use and Attribution Policy (https://understandingwar.org/fair-use-and-attribution-policy/, last revised 8 January 2026), section 1:

> Any modification, commercial exploitation, redistribution, or incorporation of ISW Materials into other datasets, mapping platforms, analytic products or systems requires prior written permission from ISW.

The Claimline ledger and map fall under "incorporation into other datasets, mapping platforms". Section 3 also forbids redistribution "in bulk, via API, or through automated means". Required attribution: "Source: Institute for the Study of War".

Access:
- `www.understandingwar.org/robots.txt`: generic agents allowed outside `/wp-json/`, `/wp-admin/`, `/cdn-cgi/`. AI crawlers (GPTBot, ClaudeBot, CCBot, PerplexityBot, Bytespider) get `Crawl-delay: 600`.
- `www` redirects to `understandingwar.org`, which returns a Cloudflare 403 block to scripted requests (curl). Not bypassed.
- Mirror `www.criticalthreats.org` serves a Cloudflare JavaScript challenge to scripted requests. Not usable for automated collection. Same policy applies (ISW & AEI Critical Threats Project section).

Reply from ISW: _pending_. Paste it here verbatim when it arrives, with the date.

## ArmyInform (armyinform.com.ua), General Staff reports

**Status: usable under CC BY 4.0.**

Site footer: content is licensed under Creative Commons Attribution 4.0 International unless stated otherwise. A link to armyinform.com.ua is mandatory when content is used; online media must put a direct hyperlink to the cited material in the first paragraph.

robots.txt: all agents allowed except `/wp-admin/`, `/wp-json/`, `/wp-login.php`, `/wp-register.php`, `*/embed`, `/cgi-bin`, `*?s=`. Sitemap at `/sitemap.xml`. The collector must not use the WordPress REST API (`/wp-json/`).

Obligation for Claimline: every published record from this source carries its `source_url`, and the README credits ArmyInform with a link.
