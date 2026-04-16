---
task_id: 11
title: "Marketing Readiness Checklist"
type: task
agent: "planner"
phase: 1
depends_on: []
status: "pending"
priority: "high"
board: "[[customer-readiness-audit/README]]"
files:
  - "development/tasks/customer-readiness-audit/sub-reports/11-marketing-readiness.md"
tags:
  - task
  - audit
  - marketing
  - legal
  - onboarding
---

# Task 11: Marketing Readiness Checklist

## Assigned Agent: `planner`

## Objective
Assess all non-code prerequisites needed before inviting customers. This covers legal pages, onboarding flow quality, support infrastructure, and marketing assets. Many launches fail not because the product is broken, but because these "boring" items are missing.

## Context
Current state:
- Domain: tradeready.io (deployed)
- Coming Soon page: live at `/`
- Waitlist: unknown if collecting emails
- Docs site: 50 MDX pages, complete
- Frontend: 23 pages, deployed via Vercel
- SDK: exists but not published to PyPI
- Legal: unknown (no ToS or Privacy Policy seen)
- Support: unknown (no support channel seen)

## Checklist to Evaluate

### Legal & Compliance (MUST HAVE)
| Item | Check How | Status |
|------|-----------|--------|
| Terms of Service | Look for `/terms` page or `terms.md` | ? |
| Privacy Policy | Look for `/privacy` page or `privacy.md` | ? |
| Cookie consent | Check if frontend has cookie banner | ? |
| Financial disclaimer | "Virtual trading only, not financial advice" | ? |
| GDPR compliance | Data deletion request path | ? |

### Onboarding Experience (MUST HAVE)
| Item | Check How | Status |
|------|-----------|--------|
| Registration flow works | Test on production | ? |
| Welcome email or screen | What happens after registration? | ? |
| First-trade guidance | Is there a tutorial or wizard? | ? |
| API key display | Is the key shown clearly? Copy button? | ? |
| Documentation link | Is docs discoverable from dashboard? | ? |
| Error messages helpful | Test invalid inputs | ? |

### Developer Experience (MUST HAVE for API product)
| Item | Check How | Status |
|------|-----------|--------|
| SDK quickstart works | Follow docs/quickstart.md steps | ? |
| API reference accurate | Spot-check 5 endpoints | ? |
| Code examples exist | Check docs for copy-paste examples | ? |
| SDK installable | `pip install agentexchange` works? | ? |
| MCP integration docs | Check docs for LLM integration guide | ? |
| Framework guides | LangChain, CrewAI, etc. guides exist? | ? |

### Support & Communication (SHOULD HAVE)
| Item | Check How | Status |
|------|-----------|--------|
| Support email/form | Is there a way to contact? | ? |
| GitHub issues enabled | Check repo settings | ? |
| Discord/Slack community | Does one exist? | ? |
| Status page | Is there a status.tradeready.io? | ? |
| Changelog | Is there a changelog page? | ? |

### Marketing Assets (NICE TO HAVE)
| Item | Check How | Status |
|------|-----------|--------|
| Landing page compelling | Review /landing | ? |
| Feature screenshots | Are there screenshots in docs/landing? | ? |
| Demo video | Is there a product demo? | ? |
| Blog/launch post | Is there a blog? | ? |
| Social media accounts | Twitter/X, LinkedIn, etc.? | ? |
| Product Hunt listing | Prepared? | ? |
| SEO basics | Sitemap, meta tags, OG images | ? |

### Waitlist & Launch Mechanics
| Item | Check How | Status |
|------|-----------|--------|
| Waitlist form works | Submit email on Coming Soon page | ? |
| Waitlist emails stored | Check `waitlist` DB table | ? |
| Launch email template | Is there a "you're in" email? | ? |
| Invite flow | Can you give specific people access? | ? |
| Feature flags | Can you limit features for free vs paid? | ? |

## Output Format

Write findings to `development/tasks/customer-readiness-audit/sub-reports/11-marketing-readiness.md`:

```markdown
# Sub-Report 11: Marketing Readiness

**Date:** 2026-04-15
**Agent:** planner
**Overall Status:** READY / NOT READY / PARTIALLY READY

## Summary Scorecard

| Category | Items | Ready | Missing | Blockers |
|----------|-------|-------|---------|----------|
| Legal & Compliance | 5 | X | X | X |
| Onboarding | 6 | X | X | X |
| Developer Experience | 6 | X | X | X |
| Support & Comms | 5 | X | X | X |
| Marketing Assets | 7 | X | X | X |
| Waitlist & Launch | 5 | X | X | X |
| **Total** | **34** | **X** | **X** | **X** |

## Launch Blockers (must fix before ANY customers)
1. {blocker}
2. {blocker}

## High Priority (fix before marketing push)
1. {item}
2. {item}

## Nice-to-Have (fix iteratively)
1. {item}
2. {item}

## Recommended Launch Sequence
1. **Week 1:** {what to do}
2. **Week 2:** {what to do}
3. **Week 3:** {what to do}

## Marketing Channel Recommendations
{Where to announce: Product Hunt, Hacker News, Twitter/X, Reddit, Discord communities, etc.}
```

## Acceptance Criteria
- [ ] All 34 checklist items evaluated
- [ ] Launch blockers identified
- [ ] Recommended launch sequence provided
- [ ] Marketing channels suggested
- [ ] Overall readiness verdict given

## Agent Instructions
Research by reading the codebase (check for `/terms`, `/privacy` pages in Frontend), checking the live site, and reviewing documentation completeness. For items that require external checks (social media, PyPI), use web search.

## Estimated Complexity
Medium — checklist-driven assessment with some web research
