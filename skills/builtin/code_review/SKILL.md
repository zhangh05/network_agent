---
id: code_review
name: Code Review
description: Search the codebase for a specific pattern, analyze the results, and suggest improvements.
version: "1.0"
category: code
tools: [code.search, workspace.file.read]
example: "Find all places where we import X and check if they follow our convention"
---

# Code Review

## Step 1
Goal: Search the codebase for the pattern or module the user wants to review.
Tools: code.search

## Step 2
Goal: Read the most relevant files to understand the context.
Tools: workspace.file.read

## Step 3
Goal: Summarize findings and suggest any issues or improvements.
Tools: (no tool - LLM analysis)
