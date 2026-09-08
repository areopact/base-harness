# Analysis Lenses Reference

Six structured lenses for comprehensive perspective coverage. Read this file during Full Explore (step 2 of the method in `SKILL.md`, working the selected hats) for detailed guidance on each lens. Hat names on the command line are `facts`, `stakeholders`, `opportunities`, `risks`, `alternatives`, and `intuition`, or `all`.

The lenses are inspired by Edward de Bono's Six Thinking Hats, pre-mortem analysis (Gary Klein), SCAMPER, and the Advocate-Critic-Synthesizer pattern from multi-agent research. The key insight from all of these: people naturally gravitate toward 1 or 2 thinking modes and skip the rest. Structured rotation forces coverage.

---

## Lens 1: Facts & Data

**Core question:** What do we actually know vs. what are we assuming?

This lens grounds the conversation in evidence before opinions take over. It is the foundation: everything else builds on what is actually true.

**Questions to explore:**
- What does the codebase, data, or documentation tell us?
- What metrics or evidence do we have?
- What has been tried before? What happened?
- What don't we know that we need to find out?
- Are there benchmarks, case studies, or prior art?
- What would we need to measure to validate this?

**Techniques:**
- Evidence audit: for every claim, ask "how do we know this?"
- Data gap analysis: list what is unknown and how to fill it
- Reference class forecasting: compare to similar past situations rather than building estimates from scratch

**Watch for:** Opinions disguised as facts ("users want X" without data), outdated information presented as current, survivorship bias (only looking at successes).

---

## Lens 2: Stakeholders

**Core question:** Who is affected, and what does each party need?

Decisions look very different depending on whose shoes you're wearing. This lens prevents the common failure of optimizing for one group while blindly impacting others.

**Questions to explore:**
- Who are the direct users, customers, or beneficiaries?
- Who else is affected? (team members, other teams, partners, end users)
- What does each stakeholder care most about?
- Are there conflicting needs between stakeholders? How do we prioritize?
- Who has to live with this decision day-to-day?
- What are the second-order effects? (e.g., if we build this, what does the support team deal with?)

**Techniques:**
- Perspective rotation: systematically step into each stakeholder's viewpoint
- Impact mapping: trace who is affected and how, including indirect effects
- "Day in the life": walk through how each stakeholder experiences the change

**Watch for:** Forgetting the maintainer (who keeps this running after launch?), ignoring downstream teams, assuming all users are the same.

---

## Lens 3: Opportunities

**Core question:** What's the upside? What doors does this open?

It is easy to get so focused on risks that you miss the potential. This lens explicitly looks for compounding benefits, strategic positioning, and non-obvious upside.

**Questions to explore:**
- What's the best-case outcome?
- What future options does this create or preserve?
- Are there compounding effects? (Does this get more valuable over time?)
- What adjacent opportunities does this unlock?
- Is there a version of this that's 10x more valuable with only 2x more effort?
- What would we build on top of this if it succeeds?

**Techniques:**
- Upside mapping: trace positive ripple effects beyond the immediate goal
- Option value analysis: what future flexibility does this preserve?
- "What would make this a home run?": push past satisfactory to exceptional

**Watch for:** Anchoring on the minimum viable version without exploring the ceiling, dismissing ambitious ideas too quickly, undervaluing strategic positioning.

---

## Lens 4: Risks & Failure

**Core question:** How could this fail, and what would that look like?

This is where pre-mortem thinking and devil's advocacy live. Humans are naturally better at identifying problems than solutions; this lens harnesses that strength.

**Questions to explore:**
- If this fails in a year, what's the most likely reason?
- What are the technical risks? (Scalability, security, complexity, dependencies)
- What are the execution risks? (Team capacity, timeline, skill gaps)
- What are the market or business risks? (Timing, competition, demand)
- What's the worst-case scenario? How bad is it?
- What early warning signs would tell us this is going wrong?

**Techniques:**
- Pre-mortem: imagine failure has already happened, then reason backward to causes. This surfaces risks people "feel" but won't voice in normal discussion.
- Failure mode analysis: for each component, ask "what happens when this breaks?"
- Risk and mitigation pairing: for every risk identified, ask "what would we do about it?" Some risks are acceptable; some aren't.

**Watch for:** Optimism bias (assuming things will go as planned), normalizing known risks ("we'll figure it out"), confusing unlikely with impossible.

---

## Lens 5: Alternatives

**Core question:** What else could we do? Including nothing?

The most common brainstorming failure is converging too early on the first reasonable approach. This lens forces genuine exploration of alternatives, not strawmen set up to lose.

**Questions to explore:**
- What are fundamentally different approaches to this problem?
- What would a different industry or domain do?
- What if we did nothing? What happens naturally?
- What if we did the opposite of our instinct?
- Is there a simpler version that solves 80% of the problem?
- Can we buy, borrow, or adapt instead of build?
- What would we do if we had half the time? Twice the budget? Neither constraint?

**Techniques:**
- SCAMPER: Substitute, Combine, Adapt, Modify, Put to other use, Eliminate, Reverse. Apply each to the current idea to generate variations.
- Lateral thinking: pick a random constraint or domain and force-connect it to the problem
- Inversion: "How could we make this problem worse?" Then invert each answer.
- "Do nothing" analysis: seriously evaluate the status quo as a baseline

**Watch for:** Strawman alternatives (options designed to lose so the preferred one wins), anchoring on the first idea, dismissing unconventional approaches without real consideration.

---

## Lens 6: Intuition

**Core question:** What feels right or wrong that we haven't articulated?

This is the lens most likely to be skipped, and often the most valuable. Experienced practitioners frequently have valid intuitions they can't fully articulate. This lens creates space for those signals.

**Questions to explore:**
- What feels off about the current direction?
- Is there something we're avoiding talking about?
- What would you do if the data were ambiguous and you had to decide on gut feel?
- Are there "sacred cows": assumptions everyone treats as given but nobody has tested?
- What's the thing you'd say if this were a private conversation with a trusted friend?
- Does this pass the "sleep test": would you feel good about this decision tomorrow morning?

**Techniques:**
- Gut check: ask directly, "setting aside the analysis, what feels right?"
- Sacred cow hunt: identify beliefs the group treats as unquestionable, then question them
- Comfort and discomfort mapping: what parts of this plan feel solid vs. uneasy?

**Watch for:** Dismissing intuition as "not data-driven" (it is pattern recognition from experience), confusing discomfort with wrongness (sometimes the right choice is uncomfortable), groupthink masquerading as consensus.

---

## Using the Lenses

**Order:** Start with Facts & Data (ground the discussion), then Stakeholders (who cares), then Opportunities and Risks (upside and downside), then Alternatives (other paths), and finish with Intuition (what's unspoken). But be flexible: if a lens naturally connects to the current discussion, follow that thread.

**Depth:** Not every lens needs equal depth on every decision. A purely technical architecture choice might get heavy coverage on Facts, Risks, and Alternatives but light coverage on Stakeholders. That's fine; the point is to consciously decide what to skip, not to skip it by accident.

**Integration:** Don't present the lenses as six separate reports. Weave findings together into a coherent analysis. The lenses are a thinking tool, not an output format.
