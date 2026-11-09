# ROI research for the Recall Campaign Tracker

Nov 9, 2026 · @Julian Marchington

Three core sources, each checked at the source, plus one bonus. Each one backs a different part of the pitch: the problem is big (NHTSA, CARFAX), spreadsheets are where it goes wrong (Panko), and every missed repair is money left on the table (NADA via WardsAuto).

## 1. NHTSA: about 4 in 10 recalled vehicles never get fixed

**Source:** NHTSA, *Report on Vehicle Safety Recall Completion Rates*, January 2025. [PDF](https://www.nhtsa.gov/sites/nhtsa.gov/files/2025-01/recall-completion-rates-report-update-01172025.pdf)

**Exact quotes:**

- "61% of vehicles recalled by major light vehicle manufacturers between 2010 and 2022 were remedied" by the fifth reporting quarter (p. 19).
- 62.1% combined weighted average annual completion rate for major manufacturers, 2018 to 2022 (p. 9).

**Careful wording:** the report does not state "39% unrepaired". That is our own subtraction (100% minus 61%), so say "about 4 in 10 recalled vehicles were not repaired within five quarters, per NHTSA data".

**Slide idea (Problem slide):** a big "61%" with the line "Only 61% of recalled vehicles are repaired within 15 months (NHTSA, 2025)." Then link it to our two flags: an unnotified owner cannot come in, and a notified-but-overdue vehicle is the gap between 61% and 100%.

## 2. CARFAX: 58.1 million US vehicles have an unfixed recall

**Source:** CARFAX research published 22 January 2025, as reported by FOX 26 Houston, 6 February 2025. [Article](https://www.fox26houston.com/news/1-5-vehicles-us-roads-unresolved-recall-how-to-check)

**Exact quotes:**

- "58.1 million vehicles on the road have an automotive recall that remains unfixed, CARFAX found."
- "An estimated one in five vehicles on the road have an unresolved recall."
- "a 16% increase over the past two years"; "more than 14 million have two or more unresolved recalls."

**Caveat:** CARFAX is an industry data company, not a government body, and this is a news report of their release. Good for scale and urgency; pair it with NHTSA for authority.

**Slide idea (Problem slide, second stat):** "1 in 5 cars on US roads has an unfixed recall: 58.1 million vehicles (CARFAX, 2025)." Works well next to the NHTSA number.

## 3. Panko: most audited spreadsheets contain errors

**Source:** Raymond R. Panko (University of Hawaii), "Spreadsheet Errors: What We Know. What We Think We Can Do", Proceedings of the EuSpRIG Spreadsheet Risk Symposium, Greenwich, July 2000. [arXiv PDF](https://arxiv.org/pdf/0802.3457). This is the most-cited academic work on spreadsheet error.

**Exact quotes:**

- Recent field audits "found errors in at least 86% of the spreadsheets audited"; Table 1 gives 91% for audits from 1997 onward (54 spreadsheets).
- Cell error rates in large spreadsheets of 1.1% to 2.5% (Hicks 1995, Lukasik 1998).
- Confirmed by Computerworld (24 May 2004): "recent audits of 54 spreadsheets found that 49 (or 91%) had errors". [Article](https://www.computerworld.com/article/1704893/sidebar-oops.html)

**Caveat:** the data is old (1990s audits). It is still the standard reference, but say "research shows" rather than presenting it as a 2025 figure. Avoid the popular "88%" figure: it comes from a later Panko summary that we did not verify at the source.

**Slide idea (Why the current process fails):** "9 in 10 audited spreadsheets contain errors (Panko)." Then show what the tool does instead: it matches the five files automatically, flags missing or bad data with a reason, and keeps a dated history of every check.

## Bonus: each missed repair costs the dealer about $440

**Source:** Mark Allen, "Auto Retailers: Take the Lead in Resolving Vehicle Recalls", WardsAuto, 22 June 2023, citing NADA. [Article](https://www.wardsauto.com/retail/auto-retailers-take-the-lead-in-resolving-vehicle-recalls)

**Exact quotes:**

- "According to NADA, the average recall parts and service repair reimbursement is $440."
- "More than 20% of customers' vehicles have an open recall."

**Caveat:** the author runs a recall software company, and the $440 is NADA's figure quoted second-hand. Label it "NADA, via WardsAuto".

**Slide idea (ROI slide):** this is the one stat that turns the tool into money. A worked example, clearly labelled as illustrative: a dealership with 500 affected vehicles that gets 5% more of them repaired (25 vehicles) earns about 25 × $440 = **$11,000** in extra manufacturer reimbursement per campaign, before counting coordinator time saved. Change the numbers to match our demo data.

## Time spent today: about 200 hours a year per coordinator (estimate)

No published study measures a recall coordinator's time, so this is our own model. Every assumption is listed so the team can change it to match the demo data.

| Task (manual today) | Assumption | Hours per year |
| --- | --- | --- |
| Full check of every affected vehicle | 500 affected VINs, about 1 minute each to find it in the notices and repairs sheets and count the days; once a month | 100 |
| Answering a manager's "what did we flag, and when?" | No history kept, so about 2 hours to rebuild each answer; twice a month | 48 |
| Cleaning bad rows (typos, missing dates, duplicates) | About 1 hour a week | 52 |
| **Total** |  | **about 200 (5 working weeks)** |

**Cost of that time:** the BLS median wage for general office clerks is "$21.64 per hour" (May 2025, [BLS](https://www.bls.gov/ooh/Office-and-Administrative-Support/General-office-clerks.htm)). Adding about 30% for benefits (our assumption) gives about $28 an hour, so roughly **$5,600 a year** per coordinator.

**With the tool:** a check runs in seconds and the coordinator reviews only the flagged vehicles, so the same work drops to perhaps 20 to 30 hours a year. That saves about **170 hours (about $4,800) a year**, and the history answer becomes instant.

**Cross-check (vendor survey, use with care):** a July 2025 survey of 500 US professionals by Parseur with QuestionPro found people spend "an average of more than 9 hours per week transferring data" and that manual data entry costs "an average of $28,500 per employee annually". It also found "50.4% ... admitted that manual data entry leads to costly errors". [Parseur](https://parseur.com/blog/manual-data-entry-report). Parseur sells automation, so treat this as support for our estimate, not proof.

## Cost of missing something

A miss costs money in three ways: lost repair revenue, regulatory penalties, and safety and liability.

**1. Lost repair revenue (dealer).** Panko's audits found 1.1% to 2.5% of cells wrong in large spreadsheets. On 500 VINs, that is roughly **5 to 12 vehicles tracked wrongly per check**. If each becomes a missed repair at NADA's $440 average reimbursement, that is **$2,200 to $5,500 per check** left unclaimed. This is an upper-bound illustration, not a measured figure.

**2. Regulatory penalties.** NHTSA's maximum civil penalty for a Safety Act violation is **$27,874 per violation**, up to **$139,356,994 for a related series**, effective 30 December 2024 ([Federal Register, 30 Dec 2024](https://www.govinfo.gov/content/pkg/FR-2024-12-30/html/2024-30608.htm)). The Safety Act also bars a dealer from selling or leasing a new vehicle with an unrepaired recall (49 U.S.C. 30120(i)). Two real cases show regulators punish exactly the gaps our tool flags:

- **Fiat Chrysler, July 2015: $105 million**, then a record. FCA admitted it "didn't fulfill the legal requirements for notifying owners, dealers and the NHTSA" across "23 safety recalls affecting more than 11 million vehicles". It also had to offer buybacks on more than 500,000 vehicles. [KPBS / NPR, 26 Jul 2015](https://www.kpbs.org/news/2015/07/26/fiat-chrysler-hit-with-record-105-million-fine)
- **Ford, November 2024: $165 million**, "the second-largest civil penalty in NHTSA's history", for recalling vehicles too slowly and failing to give accurate and complete recall information. [CollisionWeek, 15 Nov 2024](https://collisionweek.com/2024/11/15/nhtsa-fines-ford-165-million-failing-comply-recall-requirements/)

Both are manufacturer cases, and a single dealership would face far smaller sums. On a slide, use them to show that notification gaps and inaccurate recall records are what regulators punish.

**3. Safety and liability.** An unrepaired recall can kill. NHTSA says "27 people in the U.S. have been killed by defective Takata air bags that exploded" and "at least 400" were injured. In August 2024, "more than 457,000 vehicles" with recalled Takata air bags were still unrepaired. [NHTSA, 13 Aug 2024](https://www.nhtsa.gov/press-releases/consumer-alert-ford-mazda-issue-do-not-drive-warnings-more-457000-vehicles-recalled). Every unnotified owner the tool finds is one fewer vehicle in that group.

## What incorrect data does in the first place

Gartner estimates that "every year, poor data quality costs organizations an average $12.9 million" ([via Business Insider India](https://www.businessinsider.in/tech/enterprise/news/how-do-data-analytics-leaders-ensure-data-quality-and-success-of-their-data-projects/articleshow/92029802.cms)). That is a large-company average, so use it only as context. We could not open Gartner's original page, which is behind a paywall. The table shows what bad data does inside a recall process, and how our tool handles each case.

| Bad data | What goes wrong when it is missed | What the tool does |
| --- | --- | --- |
| VIN typo in the notices file | The real notice is not matched, so a notified owner looks unnotified. That causes a false alarm or a duplicate letter, and staff stop trusting the flags. | Flags a bad VIN as a data issue with a reason, and keeps it out of the rule checks |
| Missing or bad notice date | The 60-day clock cannot start, so an overdue repair is never caught | Quarantines the row with a reason |
| Repair dated before the notice | Day counts go negative and the vehicle looks fine when it may not be | Flags it as a data issue |
| Same VIN with two different dates | Two people get two different answers | Flags a date conflict and uses the earliest date |
| Repair logged on a vehicle not in the campaign | Reimbursement may be claimed for the wrong vehicle, or the real affected vehicle stays open | Flags "Repair on an unaffected vehicle" |
| Notices file missing or unreadable | Every vehicle would look unnotified, so the coordinator gets hundreds of false flags | Stops with a clear error, as the client asked |

**The knock-on effects:** time is wasted chasing false alarms, real gaps stay hidden under the noise, the dealer cannot answer a manager or auditor about what was known and when, and repair revenue goes unclaimed. The tool's dated history of every check is the answer to the last point.

## Suggested ROI story for the deck

1. **The problem is big:** only 61% repaired (NHTSA); 58.1M unfixed in the US (CARFAX).
2. **Spreadsheets cause misses:** about 9 in 10 audited spreadsheets have errors (Panko).
3. **Our tool closes the gap:** it finds unnotified owners and overdue repairs, and keeps a history of what was flagged and when.
4. **It pays back:** each recovered repair is worth about $440 to the dealer (NADA), plus hours of manual matching saved.

## Sources we looked at and dropped

- Vendor blogs claiming reconciliation automation cuts time by 50% to 80% (Resolve, SolveXia and similar). They are marketing, not research, so they are weak for a graded deck.
- CARFAX Canada's January 2026 release (about 1 in 4 used vehicles searched had an open recall). Canada-only, so it does not fit a US dealership story.

## Sources

1. NHTSA, [Report on Vehicle Safety Recall Completion Rates](https://www.nhtsa.gov/sites/nhtsa.gov/files/2025-01/recall-completion-rates-report-update-01172025.pdf), January 2025.
2. FOX 26 Houston (reporting CARFAX research of 22 Jan 2025), [1 in 5 vehicles on US roads have an unresolved recall](https://www.fox26houston.com/news/1-5-vehicles-us-roads-unresolved-recall-how-to-check), 6 Feb 2025.
3. Raymond R. Panko, [Spreadsheet Errors: What We Know. What We Think We Can Do](https://arxiv.org/pdf/0802.3457), EuSpRIG Spreadsheet Risk Symposium, July 2000.
4. Computerworld, [Sidebar: Oops (spreadsheet audits)](https://www.computerworld.com/article/1704893/sidebar-oops.html), 24 May 2004.
5. Mark Allen, WardsAuto (citing NADA), [Auto Retailers: Take the Lead in Resolving Vehicle Recalls](https://www.wardsauto.com/retail/auto-retailers-take-the-lead-in-resolving-vehicle-recalls), 22 Jun 2023.
6. U.S. Bureau of Labor Statistics, [Occupational Outlook Handbook: General Office Clerks](https://www.bls.gov/ooh/Office-and-Administrative-Support/General-office-clerks.htm), May 2025 wage data.
7. Parseur with QuestionPro, [Manual Data Entry Costs U.S. Companies $28,500 Per Employee Each Year](https://parseur.com/blog/manual-data-entry-report), survey July 2025 (vendor).
8. Federal Register Vol. 89 No. 249, [Civil Penalties inflation adjustment (DOT/NHTSA)](https://www.govinfo.gov/content/pkg/FR-2024-12-30/html/2024-30608.htm), 30 Dec 2024.
9. KPBS / NPR, [Fiat Chrysler Hit With Record $105 Million Fine](https://www.kpbs.org/news/2015/07/26/fiat-chrysler-hit-with-record-105-million-fine), 26 Jul 2015.
10. CollisionWeek, [NHTSA Fines Ford $165 Million for Failing to Comply with Recall Requirements](https://collisionweek.com/2024/11/15/nhtsa-fines-ford-165-million-failing-comply-recall-requirements/), 15 Nov 2024.
11. NHTSA, [Consumer Alert: Ford, Mazda Issue "Do Not Drive" Warnings for More Than 457,000 Vehicles with Recalled Takata Air Bags](https://www.nhtsa.gov/press-releases/consumer-alert-ford-mazda-issue-do-not-drive-warnings-more-457000-vehicles-recalled), 13 Aug 2024.
12. Business Insider India (citing Gartner), [How do data and analytics leaders ensure data quality and success of their data projects](https://www.businessinsider.in/tech/enterprise/news/how-do-data-analytics-leaders-ensure-data-quality-and-success-of-their-data-projects/articleshow/92029802.cms), date not shown on page.
