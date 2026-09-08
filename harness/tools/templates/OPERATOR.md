---
title: Operator
access: internal
---

Template: this file is a shape, not content. Replace every section with your own text; nothing below describes a real person.

# Operator

The operator profile tells the agent how the person it works with prefers to work. It lives in the local lane by default (`brain/local/`), which is untracked unless `structure.json` opts in, so it never reaches a shared branch by accident.

## Working style

How the operator likes to run a session: plan first or act first, how much to batch, when to stop and ask.

## Preferences

Formatting, tooling, and output preferences that hold across tasks (tables versus prose, which shell, which editor, what "done" looks like).

## Communication

How the operator wants questions asked and results reported: lead with the outcome, number the questions, what counts as a decision worth interrupting for.

## Do not

Things the operator has corrected before. State each as the rule that now applies, never as the story of the correction.
