# Rental Tracker — Outstanding Data Checklist

*Status as of 20 Jul 2026, after ingesting the MSHB annual-statement archive:
79 statements, 148 property-month records, 27 properties, ~$1.4M of lifetime
income tracked across the five portfolios.*

## What's already covered

| Portfolio | Annual coverage | Missing years |
|---|---|---|
| David Mascari | 2012–2025 complete | — |
| Dunwich Properties LLC | 2012–2025 complete | — |
| Miskatonic Properties LLC | 2014–2025 complete | 2012–2013 (entity may not have existed) |
| Torgo Properties LLC | 2013–2025 | **2014, 2020** (see below), 2012 |
| Walter Mascari | 2014–2025 complete | 2012–2013 (may predate entity) |

Per-property detail exists from roughly 2016 on; 2012–2015 statements are
portfolio totals only (those years' statements have no property pages).
Monthly detail exists Dec 2025 – May 2026 (complete only for Dunwich).
The daily cron ingests anything arriving at mascariproperties@gmail.com.

**Reconciliation check that validates the data:** Torgo's 2025 statement
($20,022) + Walter's pre-transfer 2025 statement ($13,342) = $33,364, which
matches Torgo's 2025 1099 ($33,363.50) to within rounding — the mid-2025
Ladue/Melwood transfer is fully accounted for. Miskatonic's 2025 statement
($12,760) matches its 1099 exactly.

## To source

### 1. Torgo mailbox access — highest value
- [ ] **App password for torgoproperties@gmail.com** (myaccount.google.com/apppasswords while signed into that account). Torgo's monthly statements for 2025–2026 — including 3403 Ladue and 4333 Melwood after the mid-2025 transfer — went there, not to the mailboxes I can read. Torgo's 2025 rents were $33,363 (per its 1099), almost none of which has monthly detail in the tracker.

### 2. Missing 2026 monthly statements
- [ ] **Jan 2026** — missing for every portfolio.
- [ ] **Mar–May 2026 for Torgo** — probably in the Torgo mailbox (item 1).
- [ ] **Mar–May 2026 for the David/Miskatonic portfolio** (1743 Warner, 2615 Wellons, 3404 Ladue, 3934 Argonne, 501 Sullivan — only Feb 2026 exists). Where do these statements go?
- [ ] **Jun 2026 (all portfolios)** — published on the Propertyware portal 9 Jul, but the notification emails no longer attach the PDFs. Download from the [owner portal](https://app.propertyware.com/pw/portals/midsouthbestrentals/owner.action) and forward to mascariproperties@gmail.com (keep "Owner Statement" in the subject), or fix delivery (item 3).

*(Walter's and Patrizia's $0 statements for these months are expected — empty
shells after consolidation into Torgo / Dunwich. Nothing to source.)*

### 3. Fix delivery going forward — so next month has no gaps
Pick one:
- [ ] Reply to Sarah at Mid South asking that statement **PDFs be attached** to the "Owner Statement Published" emails going to mascariproperties@gmail.com (Claude can draft this), **or**
- [ ] Provide Propertyware owner-portal login via the password-manager flow so the tracker can fetch PDFs from the portal automatically.

### 4. 2025 monthly statements — optional
- [ ] Jan–Nov 2025 monthlies for all portfolios, **only if monthly-level 2025 trends matter** — the 2025 annual totals are already loaded, so nothing is missing at the yearly level. Likely sources: the Propertyware portal or the Torgo mailbox.

### 5. Torgo 2014 and 2020 annual statements — misfiled in the archive
- [ ] The files named "Torgo 2014 Annual Statement.pdf" and "Torgo 2020 Annual
  Statement.pdf" are actually **Form 1098 mortgage-interest statements**, not
  owner statements. The real 2014 and 2020 Torgo annuals need sourcing (or
  confirm they don't exist).

### 6. Confirm entity start dates — probably not gaps
The archive has no annuals for: Miskatonic 2012–2013, Torgo 2012, Walter 2012–2013.
- [ ] Confirm those entities simply didn't exist / had no activity in those years. If they did, source those statements.

## Known caveats — no action needed, just awareness

- **Jun 2025 Melwood rent (~$1,000)** is genuinely absent from all statements: per Mid South, the tenant paid late (applied to July) and the June rent was still unpaid when they moved out in Dec 2025.
- **Aug 2023**: one stray monthly statement is in the data (visible only in "All time").
- **Statement periods vary** — some annuals run Dec–Nov, some Jan–Dec. The dashboard treats anything longer than a month as a multi-month statement and keeps it out of monthly aggregates, so nothing double-counts.
- **Patrizia Coletti** is not a separate owner (her house is held through Dunwich); her $0 statements are ignored by the dashboard.

## Archive ingest results (final)

- 65 PDFs processed: **61 loaded**, 2 skipped as already-loaded duplicates
  (Walter 2024 and 2025), 2 rejected correctly (the misfiled Torgo 1098s —
  item 5 above). Dunwich 2017 needed one retry (transient LLM failure), then
  loaded with 4 properties of detail.
