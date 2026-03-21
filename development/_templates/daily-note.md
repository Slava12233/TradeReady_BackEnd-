---
type: daily-note
date: <% tp.date.now("YYYY-MM-DD") %>
tags:
  - daily
---

# <% tp.date.now("YYYY-MM-DD dddd") %>

## Human Notes

> Write your observations, decisions, and plans here.

<% tp.file.cursor() %>

## Agent Activity

> Auto-populated by agents. Do not edit below this line manually.

### Changes Made

### Decisions

### Issues Found

## Links

- Previous: [[<% tp.date.now("YYYY-MM-DD", -1) %>]]
- Next: [[<% tp.date.now("YYYY-MM-DD", 1) %>]]
- Context: [[context]]
