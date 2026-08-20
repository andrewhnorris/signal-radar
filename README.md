# Signal Radar

Monitors competitor earnings calls for signals that shift the view on a concentrated life sciences book, and delivers a ranked digest with every claim traceable to a speaker and a moment in the call.

---

## What an analyst receives

```
### IVA

#### 1. IVA, MDGL — Madrigal's CEO cited proprietary market research claiming
        80% of prescribers would not use lanifibranor because of weight gain.

**Competitive** · score 2.204 · named asset · NEW

> 80% of prescribers said they wouldn't use lanifibranor because of the weight gain
> — Bill Sibold, Madrigal Pharmaceuticals Q2 2026, QA [passage 47]

**Why it matters:** A direct, quantified attack on IVA's only asset weeks before
its Phase 3 topline. Whether or not the research is representative, it is the
incumbent's stated launch playbook against IVA and sets the commercial bar
lanifibranor must clear even on positive data.
```

Both sides of that trade are in the book. The analyst covering MDGL was on the call; the question is whether the analyst covering IVA heard it. Full digest: [`docs/sample_digest.md`](docs/sample_digest.md).

## Results

| | |
|---|---|
| Precision / recall at the configured threshold (1.10) | **0.71 / 1.00** |
| At threshold 1.60 | 1.00 / 0.80 |
| Labelled set | 20 hand-labelled passages — 5 alert, 7 watch, 8 noise |
| Digest volume | 7 alerts, 8 watch, 1 archived across 3 calls |

Recall is held at 1.00 deliberately: an analyst dismisses a false positive in five seconds, but a missed competitive signal on a binary readout costs real money. Moving to a quieter feed is one line in `config/materiality.yaml`.

**What this does not measure:** whether extraction found everything worth finding. That is recall on the extractor, and 20 rows on one company cannot answer it. See [Known gaps](#known-gaps).

## Run it

```bash
pip install -r requirements.txt
make demo
```

No API key. No network. Writes `out/digest.md` in about two seconds.

```bash
make eval     # precision/recall against the labelled set, plus a threshold sweep
make test     # 16 tests, runs without pytest installed
make seed     # parse a 13F information table into a ranked portfolio seed
make run      # live extraction; needs ANTHROPIC_API_KEY and cached transcripts
```

**Start here:** [`docs/worked_example.md`](docs/worked_example.md) — the case that justifies the system, written for a readout deck.

---

## The problem, as I framed it

Two things had to be decided before writing any code.

**What "important" means.** 13F gives dollar value and nothing else, and position size alone is a weak proxy for a concentrated fund. The watchlist in `config/portfolio.yaml` is tiered on four things: dollar value, weight as a share of the disclosed book, ownership as a percentage of shares outstanding, and near-term catalyst density — a name with a Phase 3 readout next quarter is more sensitive to competitor commentary than one whose next event is in 2028.

The basis is stale and incomplete and the config says so: 13F is filed 45 days after quarter end, covers long US-listed equity only, and misses the private and venture book. The tier is hand-assigned and those four factors are the stated rationale for it — a curated artefact meant to be edited by an analyst, not auto-derived and trusted.

**Precision versus recall.** The brief says two things that pull against each other: the team *misses* signals, and not every mention is worth interrupting an analyst over. Collapsing them into one threshold gets both wrong, so the pipeline splits them — extraction runs liberally, alerting runs conservatively, and nothing is deleted. Below-threshold claims stay scored in `out/claims/*.json`, so a missed signal can be recovered and used to retune.

## What it deliberately ignores

The brief's sharpest line is that not every mention of a drug name is a signal. These are real claims the system extracted, scored, and held below the alert bar:

| Claim | Score | What held it down |
|---|---|---|
| European contribution negligible, expected to stay so | 0.341 | `novelty: repeated` ×0.5 — said last quarter too. Halves the score even though it is Q&A commentary on a named asset |
| Rezdiffra Q2 net sales $364.3M, +71% YoY | 0.639 | The model scored it 0.45 on its own merits and `commercial_trajectory` weights ×0.7. A strong in-line print establishes a baseline; it does not shift the view |
| US addressable F2/F3 MASH population grew 315k → 460k | 0.753 | `shared_indication` ×1.15 rather than a named-asset link, and the same ×0.7 commercial weight. Market-size framing, not a competitive event |
| Three additional patents, one covering unapproved F4c | 1.021 | New, prepared, named asset — everything pointing up, but a base materiality of 0.55 leaves it just under the 1.10 bar. Real, and still not worth an interruption |

The two false positives the eval reports at the configured threshold are both of this kind — a repeated timeline guide and a business-development payment. `run_eval.py` prints them by name with the labelling rationale, so a reader can disagree with a specific call rather than with a number.

---

## Design decisions

**Prepared remarks and Q&A are separated and weighted differently.** Prepared remarks are written by IR and reviewed by counsel; Q&A is where hedging and unscripted competitive commentary live. Every one of the highest-scoring signals in the sample came from Q&A.

**Novelty is scored, not just materiality.** Material means *what changed*. `diff.py` catches figures that moved, dates that shifted, and most usefully **hedging that appeared where none was before** — it flags that Madrigal's F4c guidance acquired a new hedge between Q1 and Q2 while the stated date stayed at 2027. It also tracks silence: a programme discussed last quarter and absent this quarter is often the first sign of a deprioritisation, and is invisible to anything that only reads what was said. Without this the digest reprints the same five items every quarter and stops being opened.

Matching is lexical and entity-based rather than embedding-based, on purpose: embeddings smooth over exactly the small edits that carry the signal. "In 2027" and "tracking toward 2027" are near-identical vectors and materially different statements.

**Linkage is evaluated on mechanism and indication, not company name.** The dangerous competitor is the one not on the list. A company that never says "Madrigal" but reports FGF21 data in liver disease is a signal — and it is what keeps the system working after an acquisition. When Novo Nordisk bought Akero, the mechanism rival did not disappear, it moved inside a mega-cap's call.

**A drug is not a string.** `config/aliases.yaml` resolves asset identity across internal codes, generic names, brand names, and licensor codes before any comparison. Not theoretical: Madrigal called the Arrowhead siRNA `ARO-PNPLA3` in Q1 and `MGL-0795` in Q2 after in-licensing, and the diff reported a renamed asset as a dropped programme until the alias map existed.

**Scoring is transparent and config-driven, not learned.** An analyst who disagrees with a ranking can open one YAML file, see which multiplier caused it, and change it. A tuned model that cannot be argued with does not get adopted, however good its AUC.

**Traceability is a hard requirement.** Every rendered signal carries speaker, section, verbatim quote, and passage index. Claims failing the verbatim check are discarded rather than repaired, and reconstructed fixtures say so instead of printing an index that clicks through to nothing.

**Not every company reports quarterly.** Inventiva is a French issuer and reports **semi-annually** — there is no "IVA Q2 2026". A scheduler assuming four calls a year per name under-covers every European holding and reports full coverage while doing it. Quarter labels are the company's own reporting period.

**Vendor diarization fails quietly.** In the Inventiva transcript the operator's turns carry an analyst label with a numeric suffix (`**Name, Analyst, Firm**0:`). The digits sit *outside* the bold markers, so the speaker regex missed the line and it was appended to the previous speaker's turn — worse than a wrong label, because it corrupts the quote provenance everything else rests on. Operator turns are therefore detected on **content**, not on the speaker label.

**Scope: biopharma depth over medtech breadth.** The watchlist carries PODD and ISRG, but every worked signal here is biopharma — with limited time, one indication cluster covered properly demonstrates more than two covered thinly. The machinery is not sector-specific; what changes is the shape of the signal. Device competition surfaces as procedure volumes, installed base, reimbursement and recall commentary, so `commercial_trajectory` and `competitive_positioning` would carry the weight and `clinical_readout` little. That is a second labelled eval set and per-sector weights, not new code.

### Acquiring transcripts

**No IR-page scraping.** Verified across the watchlist: IR pages publish webcast players and PDF decks, not transcript text.

The aggregator used to identify the seed transcripts returns **HTTP 403** to automated requests, and its terms prohibit programmatic reproduction. I did not work around it. Spoofing a user agent to defeat bot detection is not a data pipeline a fund should depend on, and the licensing question does not disappear because the request starts succeeding. The manifest URLs in `fetch.py` are **provenance** — they record which document produced each cached extraction — not a supported automated path.

| | Path | Notes |
|---|---|---|
| 1 | **Licensed API** — set `TRANSCRIPT_API_BASE` and `TRANSCRIPT_API_KEY` | What production should use. Terms permit storage. |
| 2 | **Manual import** — `python scripts/import_transcript.py saved.html --ticker MDGL --quarter "Q2 2026"` | Save the page in a browser; the script normalises vendor speaker formats. Adequate for a prototype. |
| 3 | **SEC EDGAR 8-K Ex-99** | Public domain, automated access permitted. Prepared remarks only — never the Q&A, which is where most of this system's signal comes from. |

That last caveat is the argument for paying for a feed: the free, unambiguously licensed source is missing the half of the call that matters. `make demo` needs none of this.

---

## How it runs

`fetch → parse → extract → diff → score → report`. The model does one job — read passages and emit structured claims with a materiality score for each claim *in isolation*. It is never asked to rank, compare quarters, or decide what interrupts an analyst; everything downstream of extraction is deterministic and config-driven. Diagrams and the full stage-by-stage breakdown: [`docs/architecture.md`](docs/architecture.md).

**Ops.** `claude-sonnet-4-6`, one call per passage batch, roughly **$30 of inference per quarter** for the full competitor universe. A call takes about a minute end to end; `make demo` runs in two seconds because it replays cached extraction. Re-runs are idempotent — claims are keyed by ticker and quarter and overwritten in place, so a failed run is fixed by running it again. A missing transcript degrades to a coverage line rather than a crash, and a malformed model response drops that batch rather than the digest.

The production shape is a scheduled job that runs after the close, commits the digest, and posts it as an email or Slack message before the open. Not a dashboard — nobody logs into a dashboard to find out whether something happened.

---

## Known gaps

- **Two of four fixtures are reconstructed.** The IVA and NVO calls, and the MDGL Q1 baseline, are assembled from published disclosure rather than parsed transcripts. They exercise the diff and cross-company linkage; the digest labels them `reconstructed` rather than citing a passage index, and they are excluded from the eval set. Only MDGL Q2 is a parsed transcript.
- **Coverage is asserted, not verified.** The digest lists known blind spots, but the system does not check a calendar to know which calls it *should* have ingested.
- **Novo Nordisk-class calls are low signal-to-noise.** Two sentences of MASH commentary inside a call dominated by obesity and diabetes; needs section-targeted retrieval rather than whole-call extraction.
- **The eval is one company.** 20 rows, MDGL only. It measures ranking, not extraction recall.

## What I would build next

1. **Coverage reconciliation** — pull the earnings calendar for the competitor universe and report which calls happened that were not ingested. A monitoring system that cannot say what it missed invites false confidence.
2. **Analyst feedback loop** — a useful/not-useful control on each signal, feeding few-shot examples back into the extraction prompt. Threshold tuning by hand does not scale past one person's taste.
3. **Extend the alias map into a real registry** — resolve programme identity from a reference dataset rather than a hand-maintained YAML file.
4. **Backtest against price** — flagged signals versus subsequent 1- and 5-day moves. Deliberately deferred: the confounders in a single quarter are severe, and a spurious hit rate would be quoted back for months.
5. **Broader event coverage** — investor days and medical conferences (AASLD, EASL), where in this indication the data often actually lands.
6. **Real transcript feed** — a licensed source with an SLA.

---

## Layout

```
config/portfolio.yaml         watchlist, importance rationale, mechanism/indication edges
config/materiality.yaml       scoring weights, thresholds, signal taxonomy
config/aliases.yaml           asset/indication/mechanism identity resolution
prompts/extract_claims.md     the extraction prompt — where domain judgment lives
scripts/ingest_13f.py         EDGAR 13F -> ranked portfolio seed
scripts/import_transcript.py  normalise a saved transcript into the cache
src/signal_radar/             parse · extract · diff · score · report · fetch · cli
eval/                         labelled set + evaluation runner
docs/worked_example.md        the case that justifies the system
docs/architecture.md          pipeline diagrams, where judgment sits, data boundaries
```

## Data & licensing

All inputs are public disclosure — 13F filings and published earnings call transcripts. No MNPI, no expert networks.

**Transcript text is not committed.** It is third-party licensed content; `data/transcripts/` is gitignored. What ships in the repo is cached *extraction output* — structured claims with short verbatim quotes for audit.
