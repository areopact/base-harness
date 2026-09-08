---
title: Identity
access: internal
---

Template: this file is a shape, not content. Replace every section with your own text; nothing below is a persona.

# Identity

The identity lane tells the agent who it is when it works in this repository. Keep the whole file under the smallest identity budget your runtimes declare (see `identity_context_limit` in `harness/registry/runtimes.json`); the loader truncates deterministically past that point and says so.

## Role

One paragraph. What the agent is for in this repository: the kind of work it does, the outcomes it is measured on, and who it works with.

## Scope

What is inside the agent's remit and what is outside it. Name the paths it may change without asking and the paths that always need a person.

## Voice

How the agent writes: sentence length, formality, whether it leads with the answer, how it handles uncertainty. Three to six short rules.

## Values

The judgments the agent should make the same way every time. Prefer verifiable behavior ("cite the file and line") over adjectives ("be careful").

## Anti-patterns

Behavior the agent must not exhibit even when asked politely. Each line names the pattern and the replacement.
