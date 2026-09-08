# The 33 patterns

Adapted from https://github.com/blader/humanizer (MIT, v2.9.1), itself derived from Wikipedia's WikiProject AI Cleanup "Signs of AI writing". Annotated for this repository: the **Status** column is the local ruling, not upstream's.

| Status | Meaning |
|---|---|
| **LAW** | Already always-on in `harness/rules/output-quality.md` section 2. Applies to every authored surface. Listed here for completeness. |
| **ALL** | Active on every authored surface when this skill runs. |
| **OUT** | Active for authored artifacts intended for a reader. Out of scope for an agent's own conversational replies, which the runtime's interaction rules govern. |

Never flag in isolation. Read [false-positives.md](./false-positives.md) before reporting anything: the unit of evidence is a cluster, not a hit.

---

## Content (1 to 6)

**1. Undue emphasis on significance, legacy, broader trends (ALL)**
Tell: "a pivotal moment", "marking a shift in", "left an indelible mark", "cemented its place as". The model inflates an arbitrary detail into a movement.
Fix: state what happened. Let significance be inferred, or cite someone who actually claimed it.

**2. Undue emphasis on notability and media coverage (ALL)**
Tell: "has been widely covered", "garnered significant attention", "boasts a strong social media presence", with no specific outlet, number, or date.
Fix: name the outlet and date, or cut the claim.

**3. Superficial analyses with -ing endings (ALL)**
Tell: a present participle clause bolted onto a factual sentence to fake depth. "The team moved offices, reflecting the company's commitment to growth."
Fix: delete the clause, or promote it to its own sentence with evidence behind it. High-frequency in business docs.

**4. Promotional and advertisement-like language (ALL)**
Tell: "vibrant", "breathtaking", "nestled", "stunning", "renowned", "seamlessly", "cutting-edge".
Fix: neutral description. Promotional adjectives are AI-tinged, and for a brand whose voice is institutional and cool rather than expressive they are off-brand as well.

**5. Vague attributions and weasel words (ALL)**
Tell: "industry reports suggest", "experts argue", "some critics have noted", "studies show".
Fix: `harness/rules/output-quality.md` already holds a stronger rule. Every claim carries `[Source: ...]` or it does not ship. Name the source or delete the sentence.

**6. Outline-like "Challenges and Future Prospects" sections (ALL)**
Tell: a formulaic closing section headed "Despite these challenges", "Future Outlook", "Looking Ahead".
Fix: merge into the main narrative, or cut. If there are real risks, they belong where the decision is discussed, not quarantined in a template slot.

---

## Language and grammar (7 to 13)

**7. Overused AI vocabulary (LAW)**
Tell: `delve`, `crucial`, `tapestry`, `testament`, `interplay`, `pivotal`, `realm`, `landscape` in the abstract sense, `underscore`, `robust`, `leverage` as a verb.
Fix: the plain word. "Important" beats "crucial". "Area" beats "landscape".

**8. Copula avoidance (LAW)**
Tell: dodging plain "is" and "has" with "serves as", "functions as", "features", "boasts", "stands as a testament to", "represents".
Fix: "is", "has". "The gate is a bash script" beats "The gate serves as a bash-based mechanism".

**9. Negative parallelisms and tailing negations (LAW)**
Tell: "Not only X, but also Y." Trailing fragments: "No config needed. No guessing."
Fix: one positive clause. If both halves matter, two sentences.

**10. Rule of three overuse (LAW)**
Tell: everything arriving in triads. "innovation, inspiration, and industry insights."
Fix: use the real count. Two items is fine. Four is fine. Padding to three is the tell.

**11. Elegant variation (LAW)**
Tell: cycling synonyms to avoid repeating a noun: the protagonist / the character / the figure / our hero, all one person.
Fix: pick one term and repeat it. Repetition reads as clarity, not poverty.

**12. False ranges (LAW)**
Tell: "from X to Y" where the endpoints share no dimension. "from hiring to culture to fundraising."
Fix: a plain list.

**13. Passive voice and subjectless fragments (ALL)**
Tell: "No configuration file is needed", "it was determined that", "mistakes were made". The actor vanishes.
Fix: name the actor. "You do not need a config file." Passive is legitimate when the actor is genuinely unknown or irrelevant; it is a tell when it hides a responsible party.

---

## Style (14 to 19)

**14. Em dashes and en dashes (LAW)**
Tell: any em dash or en dash character.
Fix: comma, colon, parentheses, or two sentences. A spaced hyphen " - " only if a dash is genuinely needed. The hardest single rule upstream, and one `harness/rules/output-quality.md` already carries.
Override: a supplied writing sample that uses em dashes outranks this.

**15. Overuse of boldface (OUT)**
Tell: mechanically bolding a phrase in every bullet.
Fix: let typography stay quiet. Out of scope for an agent's replies, where a short reply may prefer bold lead-ins over headings.

**16. Inline-header vertical lists (OUT)**
Tell: `- **Term**: definition` repeated down a list where flowing prose would read better.
Fix: prose, or plain bullets. Out of scope for rule files and READMEs, where this is the house format and it is deliberate. Active for narrative prose intended for a reader, where it reads as a slide deck pretending to be an essay.

**17. Title case in headings (ALL)**
Tell: "Strategic Negotiations And Global Partnerships".
Fix: sentence case. Low frequency where the repository already writes sentence case.

**18. Emojis (OUT)**
Tell: decorative emoji in headings and bullets.
Fix: plain text. Decorative emoji in an authored artifact get cut. Functional status glyphs an agent uses in its own replies are UI, not decoration, and out of scope here.

**19. Curly quotation marks (ALL)**
Tell: curly quotes where straight `" "` belongs, especially in anything a machine will parse.
Fix: straight quotes. Note this is a lone-signal pattern: curly quotes alone prove nothing (most word processors insert them).

---

## Communication artifacts (20 to 22)

**20. Collaborative communication artifacts (LAW)**
Tell: "I hope this helps", "Let me know if you'd like", "Should I continue?", "Feel free to reach out" inside content prose.
Fix: delete. Chatbot metacommentary has no place in an artifact.

**21. Knowledge-cutoff disclaimers and speculative gap-filling (LAW)**
Tell: "As of my last update", or invented filler where a fact is missing ("maintains a low profile", "details are limited").
Fix: state what is unknown, or omit. Related local rule: no placeholder values (a literal to-be-decided marker, an unfilled date pattern) in committed output.

**22. Sycophantic or servile tone (LAW)**
Tell: "Great question!", "That's an excellent point", "Absolutely!"
Fix: answer directly.

---

## Filler, hedging, and rhetoric (23 to 33)

**23. Filler phrases (LAW)**
Tell: "in order to", "due to the fact that", "at this point in time", "has the ability to", "it is important to note that".
Fix: "to", "because", "now", "can", and delete the last one entirely.

**24. Excessive hedging (LAW)**
Tell: stacked qualifiers. "This could potentially possibly have some effect in certain cases."
Fix: one qualifier maximum. If the uncertainty is real, quantify it. Never hedge a cited fact.

**25. Generic positive conclusions (LAW)**
Tell: "The future looks bright", "an exciting chapter ahead", "the possibilities are endless".
Fix: cut. End on the last concrete fact.
Note: a closing line with genuine charge is not this pattern, provided it is specific and earned. Test: if it could be pasted onto any other document, it is pattern 25.

**26. Hyphenated word pair overuse (ALL)**
Tell: hyphenating compounds regardless of position.
Fix: hyphenate attributively ("a high-quality report"), drop it predicatively ("the report is high quality").

**27. Persuasive authority tropes (ALL)**
Tell: "The real question is", "at its core", "what really matters here", "make no mistake".
Fix: state the point. The ceremony adds authority the sentence has not earned.

**28. Signposting and announcements (LAW)**
Tell: "Let's dive in", "Here's what you need to know", "without further ado", "In this section we will".
Fix: delete and deliver. Matches the local answer-first rule.

**29. Fragmented headers (ALL)**
Tell: a heading followed by one generic restatement sentence before the real content starts.
Fix: cut the padding line. The heading already said it.

**30. Diff-anchored writing (LAW)**
Tell: describing a thing as a narrative of its own changes. "X was added to replace Y", "the former trio moved in wave 2", "this was re-tiered from secret".
Fix: describe the thing as it currently is. Change history belongs in a Timeline section or the commit message. The highest-yield pattern for a prose repository: specs and rule files accumulate this badly, and it makes them unreadable to a fresh session that never saw the before state.

**31. Manufactured punchlines and staccato drama (OUT)**
Tell: consecutive short fragments for artificial weight. "No preference. No aesthetic. No nostalgia."
Fix: consolidate into real sentences. Out of scope for an agent's replies, where a direct register may use short declaratives by design. Active for authored artifacts, where it reads as social-media copy.

**32. Aphorism formulas (ALL)**
Tell: "X is the Y of Z". "Symmetry is the language of trust."
Fix: unpack into a concrete claim, or cut. The formula sounds profound while asserting nothing checkable.

**33. Conversational rhetorical openers (OUT)**
Tell: "Honestly?", "Look,", "Here's the thing:" before an ordinary point, manufacturing intimacy.
Fix: state the claim. Out of scope for an agent's replies, where banter may be deliberate. Active for authored artifacts.

---

## Signs of human writing (preserve these)

Upstream lists these as detection counter-signals. Locally they are also **floors**, per `harness/rules/output-quality.md` section 2: a rewrite must end up with them, not merely avoid destroying them.

- Specific, hard-to-fabricate detail: a number, a date, a name, a path.
- Mixed feelings and unresolved tension left visible.
- Era-bound references that date the text.
- First-person editorial choices ("I'd do X because Y").
- Varied sentence length.
- Genuine asides and self-corrections.
- For existing pages: edits predating November 2022.
