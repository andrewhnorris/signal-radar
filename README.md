# Signal Radar

Monitors competitor earnings calls for signals that shift the view on a concentrated life sciences book, and delivers a ranked digest with every claim traceable to a speaker and a moment in the call.

---

## Run it

```bash
pip install -r requirements.txt
make demo
```

No API key. No network. Opens `out/digest.md` in about two seconds.

```bash
make eval     # precision/recall against a hand-labelled set, plus a threshold sweep
make fetch    # populate data/transcripts/ (see "Data & licensing")
make run      # live extraction; needs ANTHROPIC_API_KEY
```

A pre-generated digest is committed at [`docs/sample_digest.md`](docs/sample_digest.md) — readable without running anything.

**Start here:** [`docs/worked_example.md`](docs/worked_example.md) is the case that justifies the system, written for a readout deck.

---

## The problem, as I framed it

The brief says the research team misses material signals from competing company calls. Two things had to be decided before writing any code.

**What "important" means.** 13F gives dollar value and nothing else. Position size alone is a weak proxy for a concentrated fund, so `config/portfolio.yaml` composites four things: dollar value, weight as a share of the disclosed book, ownership as a percentage of shares outstanding, and near-term catalyst density. A name with a Phase 3 readout next quarter is more sensitive to competitor commentary than a name whose next event is in 2028.

The basis is stale and incomplete and the config says so: 13F is filed 45 days after quarter end, covers long US-listed equity only, and misses the private and venture book entirely. The file is a **curated artefact meant to be edited by an analyst**, not something auto-derived and trusted.

**Precision versus recall — the real design tension.** The brief says two things that pull against each other: the team *misses* signals (recall), and not every mention is worth interrupting an analyst over (precision). Collapsing these into one threshold gets both wrong.

So the pipeline splits them:

- **Extraction runs liberally.** Capture anything plausibly touching the portfolio. Over-capture is cheap.
- **Alerting runs conservatively.** Only high-scoring claims reach the top of the digest.
- **Nothing is deleted.** Below-threshold claims stay in `out/claims/*.json`, so a missed signal can be recovered and used to retune — which is the only honest way to approach recall without labelled ground truth.

At the configured threshold the eval reports **precision 0.71, recall 1.00** on the labelled set. That is a deliberate choice: an analyst dismisses a false positive in five seconds, but a missed competitive signal on a binary readout costs real money. Raising the threshold to 1.60 gives precision 1.00 at recall 0.80 — one line in `config/materiality.yaml` if the team prefers a quieter feed once it is in use.

---

## Design decisions

**Prepared remarks and Q&A are separated and weighted differently.** Prepared remarks are written by IR and reviewed by counsel. Q&A is where hedging, walk-backs, and unscripted competitive commentary live. Every one of the highest-scoring signals in the sample came from Q&A. Collapsing the call into one blob throws this away before the model sees it.

**Novelty is scored, not just materiality.** Companies recite the same talking points every quarter. Material means *what changed*. The diff (`diff.py`) catches figures that moved, dates that shifted, and — most usefully — **hedging that appeared where none was before**. In the sample it flags that Madrigal's F4c guidance acquired a new hedge between Q1 and Q2 while the stated date stayed at 2027. Without this the digest reprints the same five items every quarter and stops being opened.

Matching is lexical and entity-based rather than embedding-based, on purpose. Embeddings smooth over exactly the small edits that carry the signal: "in 2027" and "tracking toward 2027" are near-identical vectors and materially different statements.

**Silence is tracked.** A program discussed last quarter and absent this quarter is often the first observable sign of a deprioritisation, and it is invisible to anything that only reads what was said.

**Linkage is evaluated on mechanism and indication, not company name.** The dangerous competitor is the one not on the list. A company that never says "Madrigal" but reports FGF21 data in liver disease is a signal. This also survives acquisitions — when Novo Nordisk bought Akero, the mechanism rival did not disappear, it moved inside a mega-cap's call.

**Scoring is transparent and config-driven, not learned.** An analyst who disagrees with a ranking can open one YAML file, see which multiplier caused it, and change it. A tuned model that cannot be argued with does not get adopted, however good its AUC.

**Traceability is a hard requirement.** Every rendered signal carries speaker, section, verbatim quote, and passage index. Claims failing the verbatim check are discarded rather than repaired. Nobody acts on a model summary they cannot verify.

**No IR-page scraping.** Verified across the watchlist: IR pages publish webcast players and PDF decks, not transcript text. Ten bespoke scrapers extracting text that is not there is the fastest way to spend the whole build on plumbing.

---

## Delivery

The output is a markdown digest intended to arrive as an email or Slack post before the open on call days. Not a dashboard — nobody logs into a dashboard to find out whether something happened.

The production shape is a scheduled job that runs after the close, commits the digest, and posts it. Roughly **$30 of inference per quarter** for the full competitor universe.

---

## What the eval does and does not measure

`eval/labeled_set.csv` is 20 hand-labelled passages with the labelling rationale committed alongside, so a reader can disagree with a specific call rather than with a number.

It measures whether **ranking** puts alert-worthy claims above the bar. It does **not** measure whether extraction found everything worth finding. That is recall, and 20 rows on one company cannot answer it.

`run_eval.py` prints both false positives and false negatives by name, with the reasoning. The two current false positives are both defensible-but-below-bar items — a repeated timeline guide and a business-development payment.

---

## Known gaps

- **Entity resolution across renaming.** Q1 calls the Arrowhead asset `ARO-PNPLA3`; Q2 calls it `MGL-0795` after in-licensing. The "went quiet" detector reads this as a dropped program. Real gap, not a rough edge.
- **The Q1 2026 fixture is reconstructed** from published summaries, not a parsed transcript. Enough to exercise the diff; explicitly excluded from the eval set.
- **Coverage is asserted, not verified.** The digest lists known blind spots, but the system does not yet check a calendar to know which calls it *should* have ingested.
- **Novo Nordisk-class calls are low signal-to-noise.** Two sentences of MASH commentary inside a call dominated by obesity and diabetes; needs section-targeted retrieval rather than whole-call extraction.

---

## What I would build next

1. **Coverage reconciliation** — pull the earnings calendar for the competitor universe and report which calls happened that were not ingested. A monitoring system that cannot say what it missed invites false confidence.
2. **Analyst feedback loop** — a useful/not-useful control on each signal, feeding few-shot examples back into the extraction prompt. Threshold tuning by hand does not scale past one person's taste.
3. **Entity resolution** — a drug/asset registry keyed on programme identity rather than string, resolving brand/INN/internal-code aliases across quarters and acquisitions.
4. **Backtest against price** — flagged signals versus subsequent 1- and 5-day moves in the affected holding. Deliberately deferred: a sloppy version is worse than none, because the confounders in a single quarter are severe and a spurious hit rate would be quoted back for months.
5. **Broader event coverage** — investor days and medical conferences (AASLD, EASL). Different formats, and in this indication often where the data actually lands.
6. **Real transcript feed** — a licensed source with an SLA, replacing the aggregator.

---

## Layout

```
config/portfolio.yaml      watchlist, importance rationale, mechanism/indication edges
config/materiality.yaml    scoring weights, thresholds, signal taxonomy
prompts/extract_claims.md  the extraction prompt — where domain judgment lives
src/signal_radar/
  parse.py                 speaker tags, prepared/Q&A split, chunking
  extract.py               LLM -> validated structured claims; replay mode
  diff.py                  quarter-over-quarter novelty and hedge detection
  score.py                 materiality scoring, alert/watch/archive partition
  report.py                digest rendering
  fetch.py                 transcript acquisition and cache
  cli.py                   pipeline entrypoint
eval/                      labelled set + evaluation runner
docs/worked_example.md     the case that justifies the system
```

---

## Data & licensing

All inputs are public disclosure — 13F filings and published earnings call transcripts. No MNPI, no expert networks.

**Transcript text is not committed.** It is third-party licensed content; `data/transcripts/` is gitignored and populated by `make fetch`. What ships in the repo is cached *extraction output* — structured claims with short verbatim quotes for audit.
