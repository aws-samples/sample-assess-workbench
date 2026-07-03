# Analytics Dashboard

The analytics page (`/analytics`) provides insights across all your completed reviews.

## Quality Overview

Radar charts showing average quality scores per agent across your reviews. Each axis represents a scoring criterion (completeness, specificity, actionability). Useful for spotting which agents consistently perform well and which need prompt tuning.

## Review History

Time series chart showing quality score trends over time, one line per agent. Use this to track whether prompt changes or model swaps are improving quality. Each data point represents one review.

## User Feedback

Per-agent bar chart showing the ratio of thumbs up to thumbs down ratings. The agreement rate percentage tells you what proportion of rated findings users found helpful. Agents with low agreement rates may need prompt adjustments.

## Coverage Matrix

Select a completed project to see a heatmap of which document sections each agent covered. Rows are document sections (from finding references), columns are agents. Dark cells mean more findings referencing that section. White cells are coverage gaps — sections no agent flagged.

This helps identify blind spots in your review coverage.
