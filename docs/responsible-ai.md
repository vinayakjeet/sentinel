# Responsible AI — SENTINEL

How this system treats the people it makes decisions about, what it gets wrong, and what would have
to change before it made a real decision about a real applicant.

Everything here is verifiable against the repository. Where a control is partial, it says so; where
a measurement is unflattering, it is printed unchanged. A responsible-AI document that only lists
things that went well is a marketing document.

---

## 1. The decision this system makes

SENTINEL scores a credit-card application for **application fraud** — is this person who they say
they are — and places it in one of four bands.

| band | what happens to the applicant | automated? |
|---|---|---|
| APPROVE | proceeds normally | yes |
| STEP_UP | additional identity verification is requested | yes |
| REVIEW | a human analyst examines the case before anything happens | no |
| DECLINE | adverse action, with a Reg B-shaped notice | yes, and it is the only such band |

**77.9% of applications are approved straight through and 0.09% are auto-declined.** Everything in
between reaches a person. That ratio is the single most important fact about how this system treats
applicants: it is built so that the overwhelming majority of contested cases are decided by a human
with the reasons in front of them.

This is a fraud model, not a credit model. It must never be used to judge whether someone can afford
credit, and it says so in `docs/model-card.md` §1.

## 2. Data

* **Source** — Feedzai Bank Account Fraud (BAF), NeurIPS 2022: a public research dataset, itself
  generated to be realistic while protecting the privacy of the real portfolio behind it. No real
  applicant data is used anywhere in this project.
* **Synthetic identifiers, disclosed.** BAF ships no device IDs, emails, phones, IPs or addresses.
  We generate them from a seeded RNG and **plant four fraud rings** that share a device and a phone
  (`ml/scripts/prepare_data.py`). The entity-graph demo therefore detects rings that this repository
  created. That is a demonstration that the machinery works — it is **not** evidence of real-world
  ring detection, and no claim in this submission should be read as if it were.
* **Synthetic IPs use RFC 1918 private space only**, so nothing generated here can be mistaken for a
  routable address belonging to someone.
* **Minimisation in the vector store.** Case narratives are embedded and queried by similarity, then
  shown to other analysts. No identifier ever goes into a narrative — not the name, email, phone,
  address, IP or device. Those are the entity graph's job, and putting them in an embedding would be
  a quiet data leak that nothing else in the system would catch.
  `backend/tests/test_semantic_narrative.py::test_narrative_carries_no_personal_data` asserts it.
* **Nothing personal reaches the LLM provider.** Analyst questions are PII-redacted before the call
  (Presidio where installed, regex otherwise) — see §5.
* **The demo database is a subset, and the drift demo is amplified.** Two further places where the
  demo is not the thing itself, stated here so they are not discovered later:
  * The loaded demo database holds **40,000** of the 150,000-row demo sample (plus every planted
    ring member). Every metric quoted in §4 and in `docs/model-card.md` comes from the full
    205,011-row test set, never from this subset.
  * The drift demo replays **real BAF Variant II rows**, but with fraud prevalence raised to about
    **12%** (`REPLAY_SHIFT_FRAUD_RATE`) against roughly 1% naturally — the fraud rows are resampled
    with replacement from the variant file's own fraud rows, not fabricated. A realistic 1% wave
    needs tens of thousands of events before ADWIN can call it, which is not a live demo. The
    detector, the delayed-label error stream and the tightening logic are unmodified; only the
    arrival rate of fraud is amplified. Setting `REPLAY_SHIFT_FRAUD_RATE=0` replays the file as-is.
  * Replayed rows are validated **without** `history`, so no replayed row can set `fraud_flag` on an
    entity. The simulated wave cannot manufacture confirmed-fraud signals in the entity graph.

## 3. Protected attributes

`customer_age`, `employment_status` and `income` are **excluded from the feature set entirely**
(CLAUDE.md invariant 5). They are loaded only so that fairness can be measured.

This is enforced, not merely intended:

* `ml/featurize.py` builds the feature frame from an explicit allow-list that does not contain them.
* `ml/tests/test_reason_codes.py::test_protected_attributes_never_appear_as_features_or_reasons`
  fails the build if one ever becomes a feature, or becomes citable as a reason for a decline.
* `ml/artifacts/features.json` records the exclusions, so the published artifact states them too.

DESIGN §2 originally listed `employment_status` both as a model categorical and as an excluded
protected attribute. The contradiction was resolved in favour of the invariant, and the resolution
is recorded in the model card rather than silently applied.

**Exclusion is necessary but not sufficient.** It prevents direct use. It does not prevent proxies,
and §4 shows that proxies are present.

## 4. Fairness: what we measured, and what it says

Measured on the 205,011 held-out applications by `ml/fairness.py`. Chart:
`docs/charts/fairness.png`. Numbers: `ml/artifacts/metrics_v1.json`.

BAF bands `customer_age` by decade, so DESIGN's literal `<25 / 25–50 / >50` buckets do not exist in
the data. The closest faithful mapping (`≤20`, `30–50`, `≥60`) is used and is printed on the chart
itself, rather than quietly rounded into the DESIGN labels.

| age group | n | fraud rate | approval rate | FPR at DECLINE | TPR at DECLINE |
|---|---|---|---|---|---|
| <25 (≤20) | 51,437 | 0.644% | 85.62% | 0.014% | 1.21% |
| 25–50 (30–50) | 145,471 | 1.504% | 76.07% | 0.052% | 2.83% |
| >50 (≥60) | 8,103 | 4.430% | 61.77% | 0.271% | 3.90% |
| **overall** | 205,011 | 1.404% | 77.90% | 0.050% | 2.78% |

### 4.1 The system does not currently pass a four-fifths test

**Approval-rate ratio: 0.721.** The four-fifths (80%) rule reads this as ≥ 0.80. It is not.
Applicants in the ≥60 band are approved straight through materially less often than those in the
≤20 band.

**FPR disparity ratio: 19.8×.** A *legitimate* applicant aged ≥60 is about twenty times more likely
to be auto-declined than a legitimate applicant aged ≤20. Both rates are small in absolute terms
(0.271% against 0.014%), and the absolute numbers matter — but a 20× gap is not something to report
as a footnote.

### 4.2 What explains it, and what that does and does not excuse

The ≥60 group has a **4.43%** fraud rate against **0.644%** for ≤20 — a factor of about seven. A
model that ranks risk well will decline more often in a group where more applications are genuinely
fraudulent, and the TPR column shows the model is also catching more fraud there. Part of this gap
is the model tracking real risk.

That is an explanation, not a justification. Three things remain true:

1. Age is not a feature, so the model is reconstructing something age-correlated from other
   variables. We have not identified which, and we should have.
2. A legitimate ≥60 applicant experiences a 19.8× higher chance of wrongful auto-decline
   regardless of why the model does it.
3. The ≥60 group is only 8,103 applications (4% of the test set), so these rates rest on a small
   base and are correspondingly noisy. That is a reason for caution in both directions, not comfort.

### 4.3 This is disclosed, not mitigated

**Nothing in this submission fixes it.** We did not want to ship a mitigation we had not measured.
Before this system made a real decision about a real person, it would need at minimum:

* **Per-segment threshold calibration** or an equalised-odds post-processing step, with the
  disparity re-measured after, not assumed.
* **A proxy audit** — inspect the highest-gain features for age correlation, and re-fit without the
  worst offenders to see what accuracy actually costs.
* **Fairness as a release gate**, not a report: the four-fifths ratio computed in CI on every
  retrain, with the build failing below a threshold agreed with compliance.
* **The same evaluation for every other protected characteristic.** We measured age because BAF
  carries it. Real deployment would need the full set, and BAF does not contain it.
* **Ongoing monitoring** with alerting on the disparity ratios, since drift changes them.

## 5. The LLM has no authority

The analyst copilot explains decisions. It cannot make, change or influence one. `CLAUDE.md`
invariant 1 is enforced in four independent ways, so that no single mistake removes the guarantee:

1. **The tool registry refuses to register a tool that is not read-only** (`app/llm/tools.py`).
2. **Unknown tool names are refused, not guessed at** — a model that invents `update_decision` gets
   an error.
3. **Every tool runs inside a Postgres `SET TRANSACTION READ ONLY` transaction that is always rolled
   back.** The database itself refuses a write, whatever the application code does.
4. **The response model has no field a score or band could travel back in.**

A static test additionally fails if any write SQL appears anywhere in `app/llm/`.

Further controls:

* **Prompt injection** is scanned on the **raw** question, before redaction, so an attack cannot
  hide behind a rewrite. A blocked question never reaches the provider at all
  (`test_injection_blocked` asserts the provider was not called).
* **PII redaction** before every provider call (`test_pii_redacted`).
* **Grounded citation.** The model may only cite reason codes that are on *that* decision. If its
  answer names a factor that played no part in the decision, the answer is **discarded** in favour
  of a templated one built from the decision record. That is the failure mode that would make an
  adverse-action notice wrong, so it is not allowed to ship.
* **Graceful degradation.** If the provider is down, the endpoint answers from the reason codes and
  sets `fallback_used: true`. It never fabricates and never fails silently — and the Bedrock stub
  raises rather than returning plausible text, so the fallback path stays honest and testable.

## 6. Explainability and adverse action

* Every decision persists its inputs, score, band, model version, top-4 reason codes, latency and
  request id (invariant 2). A decision that cannot be explained later is a decision that should not
  have been made.
* Reasons come from `shap.TreeExplainer` — the top four features pushing *toward* fraud — mapped
  through `ml/artifacts/reason_codes.yaml` to applicant-facing English plus an ECOA category.
* `GET /decisions/{id}/adverse-action` returns a Reg B-shaped notice built from those reasons.
* The reason text is constrained by test: no raw column names, no model mechanics, no thresholds an
  adversary could tune against, and it must read as a sentence about the applicant's circumstances.
* `ml/tests/test_reason_codes.py` fails the build if any feature lacks applicant-facing text — so a
  declined applicant can never receive a notice with a blank reason.

## 7. Known limitations

1. **The fairness gap in §4 is unmitigated.**
2. **Entity linkage is synthetic** (§2). Ring detection is demonstrated, not evidenced.
3. **The anomaly component is weak** (ROC-AUC 0.586) and slightly dilutes the supervised model; the
   model card reports this rather than presenting the blend as a straight improvement.
4. **One dataset, one institution, eight months.** Results will not transfer unchanged.
5. **Labels are assumed correct and immediate.** Real fraud labels arrive late and incomplete. The
   drift design models the lag; it does not model label noise.
6. **No adversarial evaluation** against an attacker who knows the feature set.
7. **No formal appeal path.** Reg B requires the applicant be able to contest; the notice is
   generated, the process around it is not built.
8. **Retention is not implemented.** Decisions, entity hashes and embeddings accumulate with no
   deletion policy. A real deployment needs one, including erasure propagating to the vector store.

## 8. What we would do before this touched a real applicant

In order of what we would not launch without:

1. Fix and re-measure the fairness gap (§4.3); make it a release gate.
2. A deletion and retention policy, including the embedding store.
3. Replace synthetic identifiers with real entity resolution, and re-validate that ring detection
   works on real linkage rather than planted linkage.
4. An appeals process with a route back into the model's evaluation set.
5. Adversarial testing, and monitoring for feature gaming.
6. Independent model validation and a sign-off owner for threshold changes — a drift event currently
   tightens bands automatically, and nobody is asked.
