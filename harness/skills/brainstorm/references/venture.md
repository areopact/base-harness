# Venture forcing questions

Six questions that separate a business idea from a wish. Ask one at a time, explain why it matters briefly, and do not re-ask answered questions. Keep answers in working conversation notes; saving follows the parent skill's authorization and hand-off rules. If evidence is absent, name the gap and propose validation instead of inventing it.

#### Q1: Demand Reality

*Why it matters:* "Interest" is not demand. Waitlist sign-ups are not demand. Demand is someone who would be **genuinely upset** if the thing disappeared tomorrow.

**Ask:** "What's the strongest evidence you have that someone actually wants this? Not 'is interested,' not 'signed up for a waitlist,' but would be genuinely upset if it disappeared tomorrow?"

Red flag: "Lots of people I've talked to say it sounds great." Talking is not demand.

#### Q2: Status Quo

*Why it matters:* The real competitor is rarely another startup. It is the cobbled-together spreadsheet, chat threads, and duct-tape workaround the user is already living with. If the answer is "nothing, there's no solution," the problem is probably not painful enough.

**Ask:** "What are your users doing right now to solve this problem, even badly? What does that workaround cost them?"

Red flag: "Nothing, there's no solution, that's why the opportunity is so big."

#### Q3: Desperate Specificity

*Why it matters:* "Users" is not a person. "Product managers" is not a person. **Name a human**: the more specific, the more real.

**Ask:** "Name the actual human who needs this most. What's their title? What gets them promoted? What gets them fired? What keeps them up at night?"

Match the consequence to the domain: B2B tools name career impact; consumer tools name daily pain or a social moment; hobby and open-source tools name the weekend project that gets unblocked. Never let the founder stay at "users."

#### Q4: Narrowest Wedge

*Why it matters:* The smallest version someone will pay real money for **this week** is more valuable than the full platform vision. Wedge first. Expand from strength.

**Ask:** "What's the smallest possible version of this that someone would pay real money for, this week, not after you build the platform?"

Bonus push: "What if the user didn't have to do anything at all to get value? No login, no integration, no setup. What would that look like?"

#### Q5: Observation & Surprise

*Why it matters:* Guided demos teach you nothing about real usage. **Watching someone struggle**, biting your tongue and not helping, teaches you everything. Users doing something the product wasn't designed for is often the real product trying to emerge.

**Ask:** "Have you actually sat down and watched someone use this (or its precursor) without helping them? What did they do that surprised you?"

If the answer is "I haven't watched anyone yet," that is assignment #1 before any more building.

#### Q6: Future-Fit

*Why it matters:* In three years the world looks meaningfully different. Does this product become more essential or less? Time should be on your side, not against it.

**Ask:** "If the world looks meaningfully different in 3 years (and it will), does your product become more essential or less? Why?"

After the questions, summarize the framing, evidence, wedge, open uncertainties, and next validation step. If preserving the result is requested, merge it into the destination's existing schema; never overwrite a main document with a generic spec.

[Source: adapted from gstack office-hours v2.0.0 (MIT), https://github.com/garrytan/gstack/blob/026751e/office-hours/SKILL.md]

## Venture exploration procedure and filing

Use with `brainstorm --venture <idea-or-entity>`. Look up relevant local context, frame the idea in one sentence, then ask only unanswered material questions from the six above. The one-at-a-time format is deliberate; do not add a second mandatory six-hat interview. Hats and permitted peers may help synthesize after the relevant evidence is gathered. Missing evidence is a validation task, not a license to invent answers or an entity.

Summarize demand, the specific customer, wedge, assumptions, and next validation step. Brainstorm itself writes nothing. If the user has requested preservation, hand the summary to the skill or path that owns the destination: the records lane when `harness/registry/structure.json` configures it, otherwise the docs lane or a path the user names. Merge into the existing page's schema where one exists (a thesis page, a product blueprint, a context page); do not create a new entity page until the thesis and its working name are accepted. Unfiled exploration stays in conversation by default. Do not automatically implement, record a decision, or create operational state.

Worked example: the user says `brainstorm --venture a scheduling tool for independent tutors`. Local context has no page for it, so Q1 opens the interview. The user cites eight tutors who already pay for a spreadsheet template (Q1 evidence, Q2 status quo); Q3 names one tutor by role, Q4 lands on a booking page with no login, Q5 finds nobody has been watched yet, and Q6 stays open. The summary states the wedge and names "watch two tutors book a lesson" as the next validation step. Nothing is written unless the user then asks to save it.

When reviewing an existing venture thesis, apply these questions as evidence checks under `/review`; use answers already in the artifact and flag material gaps rather than restarting the discovery interview.
