# Research 1e — Fixed-cost hosting layer (2026-09-01)

**FX:** USD→CAD 1.3896 (Bank of Canada daily average, 2026-09-01, bankofcanada.ca/valet FXUSDCAD). Prices exclude tax. UNVERIFIED = not confirmed on a page I fetched.

## 1. VPS price table

| Provider / region | Spec | Local price/mo | CAD/mo | Bandwidth; backups | Source |
|---|---|---|---|---|---|
| OVH VPS-1 2027, Beauharnois (BHS) | 2 vCPU/4 GB/40 GB | CA$7.30 no-commit (6.20 w/ 12-mo) | 7.30 | 500 Mbps port; daily backup incl. (24 h); 7-day backup +1.80; snapshot +0.50 | OVH VPS catalog API, vps, vps/options |
| OVH VPS-2 2027, BHS | 4 vCPU/8 GB/75 GB | CA$13.70 (11.64 w/ 12-mo) | 13.70 | 1 Gbps; same | same |
| OVH VPS-4 2027, BHS | 8 vCPU/24 GB/200 GB | CA$37.90 (32.21 w/ 12-mo) | 37.90 | 3 Gbps; same | same |
| OVH Public Cloud d2-4 | 2 vCPU/4 GB/50 GB | CA$0.033/h = 18.31 monthly | 18.31 | 250 Mbps; snapshot CA$0.0158/GB-mo | OVH cloud catalog API; specs 3rd-party (UNVERIFIED) |
| OVH Public Cloud d2-8 | 4 vCPU/8 GB/50 GB | CA$0.0596/h = 32.96 monthly | 32.96 | 500 Mbps | same |
| Hetzner CPX21, Ashburn/Hillsboro | 3 vCPU/4 GB/80 GB | US$37.49 (was 13.99 before 15 Jun 2026) | 52.10 | traffic UNVERIFIED (3rd-party: 1 TB); backups +20%; snapshots per GB (price UNVERIFIED) | price-adjustment doc; billing FAQ |
| Hetzner CPX31 | 4 vCPU/8 GB/160 GB | US$73.49 | 102.12 | same | same |
| Hetzner CPX41 | 8 vCPU/16 GB/240 GB | US$141.49 | 196.61 | same | same |
| DigitalOcean Basic, Toronto | 2 vCPU/4 GB/80 GB | US$24 | 33.35 | 4 TB; backups +20% weekly / +30% daily; snapshots $0.06/GB | droplet pricing; regional availability |
| DigitalOcean Basic | 4 vCPU/8 GB/160 GB | US$48 | 66.70 | 5 TB | same |
| DigitalOcean Basic | 8 vCPU/16 GB/320 GB | US$96 | 133.40 | 6 TB | same |
| Vultr vc2-2c-4gb, Toronto | 2 vCPU/4 GB/80 GB | US$20 | 27.79 | 3 TB; backups +20%; snapshots $0.05/GB | api.vultr.com plans; Vultr docs |
| Vultr vc2-4c-8gb | 4 vCPU/8 GB/160 GB | US$40 | 55.58 | 4 TB | same |
| Vultr vhp-8c-16gb-amd | 8 vCPU/16 GB/350 GB | US$96 | 133.40 | 8 TB | same |
| Linode g6-standard-2, Toronto | 2 vCPU/4 GB/80 GB | US$24 (no Toronto markup) | 33.35 | 4 TB; backups $5 | api.linode.com types, regions |
| Linode g6-standard-4 | 4 vCPU/8 GB/160 GB | US$48 | 66.70 | 5 TB; backups $10 | same |
| Fly.io yyz Toronto (no yul) | shared-2x 4 GB / shared-4x 8 GB / perf-4x 16 GB | US$25.67 / 51.33 / 196.75 (iad ~17 % less) | 35.67 / 71.33 / 273.40 | egress $0.02/GB; volumes $0.15/GB | fly pricing, regions |
| Railway, US East VA (no Canada) | 2 vCPU/4 GB always-on | ~US$80 ($20/vCPU + $10/GB) + Hobby $5 | ~111 | egress $0.05/GB | railway pricing, regions |
| Render, OH/VA/OR (no Canada) | Pro 2 CPU/4 GB; Pro Plus 4/8; Pro Max 4/16 | US$85 / 175 / 225 | 118 / 243 / 313 | 100 GB (Hobby) / 500 GB (Professional $19/user); overage $0.15–0.30/GB | render pricing HTML, docs |

Hetzner has no Canadian location (fsn1, nbg1, hel1, ash, hil, sin); its US prices roughly tripled on 15 June 2026, so it no longer undercuts OVH/Vultr/DO.

## 2. Latency note

WonderNetwork (19 Aug–1 Sep 2026): Montreal→Washington 14.2 ms avg RTT; Toronto→Washington 16.1 ms; Toronto↔Montreal 7.9 ms. Ashburn is ~50 km from Washington, so expect ~15–18 ms RTT from Beauharnois or Toronto to US-East: under the 20 ms budget and ~2 % of an 800 ms turn. cloudping.co returned 404.

## 3. Managed Postgres vs self-hosted

| Option | Floor / free tier | Beyond it | Canada? | Source |
|---|---|---|---|---|
| Neon | Free: 100 CU-h/project/mo, 0.5 GB, 5 GB egress; any limit hit suspends compute until next month | Launch: no minimum; $0.106/CU-h, $0.35/GB-mo; 0.25 CU 24/7 ≈ US$19.34 (CA$26.87) | No (us-east-1/2) | neon pricing, plans, regions |
| Supabase | Free: 500 MB, pauses after 1 week idle | Pro US$25 (CA$34.74), 8 GB; PITR US$100/mo per 7 days | Yes, ca-central-1 | supabase pricing, regions |
| Crunchy Bridge | Hobby-0 US$9 + $0.10/GB; backups + PITR included | Standard-8 US$140 | Not listed (UNVERIFIED) | crunchydata pricing |
| DO Managed PG | US$15.15 (CA$21.05) 1 vCPU/1 GB; daily backups, 7 days + PITR | 2 vCPU/4 GB US$60.90 (CA$84.63); HA = matching standby | Yes, Toronto | DO pricing + docs |
| OVH Managed PG | Discovery from CA$87.09/node (48 h backups, no SLA) | Production from CA$110.89 | BHS UNVERIFIED | ovhcloud postgresql page |
| Self-hosted (Compose on VPS) | ~CA$0; WAL archive to R2/B2 free tier | your time | Yes | — |

**Recommendation (solo founder, no babysitting):** at MVP run Postgres in Docker Compose on the app VPS with **WAL-G or pgBackRest archiving to Cloudflare R2** plus a nightly `pg_dump`, and rehearse one restore. By ~10 tenants move to **DigitalOcean Managed PostgreSQL in Toronto (CA$21–42/mo)**: cheap, Canadian, 7-day backups, PITR, optional standby. Neon is the best zero-floor option but has no Canadian region and its free tier suspends compute mid-month; Supabase PITR costs US$100/mo; OVH's CA$87 floor is too high.

## 4. Object storage

| Service | Storage | Egress | Free / minimum | 1 GB | 50 GB | Canada? | Source |
|---|---|---|---|---|---|---|---|
| Cloudflare R2 | US$0.015/GB-mo | Free | 10 GB-mo, 1 M Class A, 10 M Class B free | $0 | US$0.60 (CA$0.83) | jurisdiction only | r2/pricing |
| Backblaze B2 | US$6.95/TB | Free ≤ 3× stored, then $0.01/GB | first 10 GB free; no minimums | $0 | US$0.28 (CA$0.39) | Yes, CA East Toronto | b2 pricing, data-regions |
| OVH Object Storage Standard | CA$0.0095/GB-mo | CA$0 | none | CA$0.01 | CA$0.48 | BHS per product page (flavor-level UNVERIFIED) | cloud catalog API, object-storage page |
| AWS S3 Standard ca-central-1 | US$0.025/GB-mo | ~$0.09/GB after 100 GB/mo free (UNVERIFIED for region) | 5 GB × 12 mo | US$0.03 | US$1.25 (CA$1.74) | Yes | awsstatic s3.json |
| Wasabi | US$7.99/TB | Free if egress ≤ stored | **1 TB minimum; 90-day retention** | US$7.99 (CA$11.10) | US$7.99 | Yes, Toronto | wasabi pricing, FAQ, regions |

Use **R2**, or **B2 CA East** if "stored in Canada" must be nameable. Wasabi's 1 TB minimum rules it out.

## 5. Cloudflare free tier

- Free plan: DNS, CDN/proxy, DDoS, SSL; **Free Managed Ruleset** WAF (Managed/OWASP need Pro); 5 custom WAF rules (Pro 20). Pro = US$20/mo annual or US$25 monthly (CA$34.74).
- Tunnel/Zero Trust: free plan exists; the widely cited **50-user** cap is on third-party pages only (official page is JS-rendered): **UNVERIFIED**. Extra users are blocked once seats run out.
- Turnstile: free; 20 widgets, 10 hostnames each.
- Workers Free: 100,000 requests/day, 10 ms CPU; Paid US$5/mo. KV Free: 100k reads/day, 1 GB. Enough for a status page or SMS-ack fallback.
- Registrar: at-cost; .com and .ca supported (tld-policies). .com ≈ US$10.46/yr (rising ~$0.71 on 1 Nov 2026) and .ca price: **UNVERIFIED** (third-party only).

## 6. Carrier-side failover

- **Telnyx:** Call Control apps have a Failover URL: "If two consecutive delivery attempts to the primary URL fail, Telnyx will attempt delivery to this URL." TeXML apps: failover URL receives webhooks "if we get an error response from your 'Voice URL'"; retries after 2000 ms without response (support 4374050, 4334722). **TeXML Bin** is Telnyx-hosted TeXML; the support article shows `<Record>` voicemail and `<Dial>` forwarding with no server. It does not explicitly say "use a Bin as failover URL", but any https URL is accepted: confirm in the portal.
- **Twilio:** `voice_fallback_url` = "The URL that we call when an error occurs retrieving or executing the TwiML requested by url". Failover best practices: host the fallback in another region/provider or use "serverless Functions, TwiML Bins, or Studio flows", e.g. "redirecting to a support line or saying a message to the caller to try again later"; Twilio retries the primary first, so recovery is automatic.

## 7. Redis / queue

Upstash Redis: free 256 MB / 500K commands/mo; pay-as-you-go US$0.20 per 100K; smallest fixed plan US$10. Not needed here: a `jobs` table drained with `SELECT … FOR UPDATE SKIP LOCKED`, `NOTIFY` as wake-up, backoff retries and a dead-letter status covers post-call processing, SMS and webhooks. Prisma's 2026 writeup names the exit criteria (sustained thousands of jobs/s, fan-out, complex rate-limiting); adriano.fyi's "Choose Postgres queue technology" makes the boring-tech case and flags VACUUM pressure. 25 concurrent calls produce a few jobs per minute.

## Recommended minimal bill of materials (CAD/month)

**1 tenant, 3 concurrent calls (target < 60):**

| Item | CAD |
|---|---|
| OVH VPS-2 2027, BHS (4 vCPU/8 GB): app + VAD + Caddy + Postgres (Compose) | 13.70 |
| OVH 7-day automatic backup | 1.80 |
| Cloudflare R2 (< 10 GB) + Cloudflare Free + Telnyx TeXML Bin failover | 0.00 |
| Domain (.com at cost ≈ CA$14.5/yr, UNVERIFIED) | 1.21 |
| **Total** | **≈ 16.7** (≈ 37.8 with DO Managed PG 1 GB Toronto instead) |

**10 tenants (target < 150):** OVH VPS-4 (37.90) + backup (1.80) + DO Managed PG 1 GB Toronto (21.05) + R2 ~50 GB (0.83) + domain (1.21) ≈ **CA$63**.

**25 tenants, 25 concurrent calls (target < 400):**

| Item | CAD |
|---|---|
| 2 × OVH VPS-4 2027 (8 vCPU/24 GB) app nodes, BHS | 75.80 |
| OVH Load Balancer | 28.99 |
| OVH backups × 2 | 3.60 |
| DO Managed PG 2 vCPU/4 GB, Toronto (HA standby +84.63) | 84.63 |
| R2 ~200 GB recordings | 4.17 |
| Cloudflare Pro (optional) | 34.74 |
| Domain | 1.21 |
| **Total** | **≈ 233** (≈ 318 with HA standby) |

Fixed cost 17 → 63 → 233 CAD for 1 → 10 → 25 tenants is sublinear.

## Sources actually fetched

- https://www.bankofcanada.ca/valet/observations/FXUSDCAD,FXEURCAD/json?recent=1
- https://www.ovhcloud.com/en-ca/vps/ ; https://www.ovhcloud.com/en-ca/vps/options/ ; https://ca.api.ovh.com/1.0/order/catalog/public/vps?ovhSubsidiary=CA ; https://ca.api.ovh.com/1.0/order/catalog/public/cloud?ovhSubsidiary=CA ; https://www.ovhcloud.com/en-ca/public-cloud/general-purpose/ ; https://www.ovhcloud.com/en-ca/public-cloud/object-storage/ ; https://www.ovhcloud.com/en-ca/public-cloud/postgresql/
- https://docs.hetzner.com/cloud/general/locations/ ; https://docs.hetzner.com/general/infrastructure-and-availability/price-adjustment/ ; https://docs.hetzner.com/cloud/billing/faq/ ; https://sparecores.com/server/hcloud/cpx31
- https://www.digitalocean.com/pricing/droplets ; https://www.digitalocean.com/pricing/managed-databases ; https://docs.digitalocean.com/platform/regional-availability/ ; https://docs.digitalocean.com/products/databases/postgresql/details/pricing/ ; https://docs.digitalocean.com/products/databases/postgresql/how-to/restore-from-backups/
- https://api.vultr.com/v2/plans ; https://docs.vultr.com/support/platform/billing/how-much-does-it-cost-to-enable-automatic-backups ; https://docs.vultr.com/support/platform/billing/does-vultr-charge-for-stored-snapshots
- https://api.linode.com/v4/linode/types ; https://api.linode.com/v4/regions ; https://www.akamai.com/cloud/pricing
- https://fly.io/docs/about/pricing/ ; https://fly.io/docs/reference/regions/ ; https://railway.com/pricing ; https://docs.railway.com/reference/regions
- https://render.com/pricing ; https://render.com/docs/compute-plans ; https://render.com/docs/free ; https://render.com/docs/regions
- https://wondernetwork.com/pings/Montreal ; https://wondernetwork.com/pings/Toronto ; https://wondernetwork.com/pings/Montreal/Washington ; https://wondernetwork.com/pings/Toronto/Washington
- https://neon.com/pricing ; https://neon.com/docs/introduction/plans ; https://neon.com/docs/introduction/regions ; https://supabase.com/pricing ; https://supabase.com/docs/guides/platform/regions ; https://www.crunchydata.com/pricing
- https://developers.cloudflare.com/r2/pricing/ ; https://www.backblaze.com/cloud-storage/pricing ; https://www.backblaze.com/docs/cloud-storage-data-regions ; https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/s3/USD/current/s3.json ; https://aws.amazon.com/s3/pricing/ ; https://wasabi.com/pricing ; https://wasabi.com/pricing/faq ; https://docs.wasabi.com/docs/what-are-the-service-urls-for-wasabi-s-different-storage-regions
- https://www.cloudflare.com/plans/ ; https://www.cloudflare.com/plans/free/ ; https://developers.cloudflare.com/waf/managed-rules/ ; https://developers.cloudflare.com/waf/custom-rules/ ; https://developers.cloudflare.com/cloudflare-one/team-and-resources/users/seat-management/ ; https://developers.cloudflare.com/turnstile/plans/ ; https://developers.cloudflare.com/workers/platform/pricing/ ; https://www.cloudflare.com/products/registrar/ ; https://www.cloudflare.com/tld-policies/
- https://support.telnyx.com/en/articles/4374050-configuring-call-control-texml-applications-voice-api ; https://support.telnyx.com/en/articles/4334722-how-to-leverage-webhooks ; https://support.telnyx.com/en/articles/13386198-texml-bin-simple-voicemail-and-call-forwarding
- https://www.twilio.com/docs/phone-numbers/api/incomingphonenumber-resource ; https://www.twilio.com/docs/voice/twilio-voice-failover-best-practices ; https://www.twilio.com/docs/serverless/twiml-bins
- https://upstash.com/pricing/redis ; https://www.prisma.io/blog/you-dont-need-a-job-queue-postgres-already-has-skip-locked ; https://adriano.fyi/posts/2023-09-24-choose-postgres-queue-technology/
