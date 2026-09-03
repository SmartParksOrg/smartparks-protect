# 0001. Record architecture decisions

Date: 2026-09-03

Status: accepted

## Context

Smart Parks Protect is an open source platform with a long lifetime and several contributors, including AI assistants that work from the written plan. The concept architecture (draft v16) lists thirteen open decisions in section 32. Without a record, a decision is re-argued every time someone new reads the code.

## Decision

Significant technical decisions are written as architecture decision records in `docs/adr/`, following the template in `template.md`. One file per decision, numbered sequentially, never edited after acceptance; a later record supersedes an earlier one. The decisions table in `PROJECT_PLAN.md` links to the record for each decision once it is written.

## Alternatives considered

- Decisions only in the plan's table: too short to hold context and consequences, and the plan changes.
- Decisions in commit messages: not discoverable.

## Consequences

Every architectural choice costs a short document. In return, a reader can find why the code is shaped the way it is, and a change to a decision is a visible event.
