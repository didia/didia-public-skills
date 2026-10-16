# GitHub review mechanics

How to gather PR context and post inline comments reliably with the `gh` CLI. The failure mode this reference exists to prevent: spending an hour on a careful review, then losing the findings to a 422 on the posting step.

## Prerequisites

`gh auth status` should show an authenticated account with write access to the repo. Reviews can be posted from a clone or from anywhere with `--repo owner/name`.

## Gathering context

```bash
PR="https://github.com/owner/repo/pull/123"   # a URL, a number, or a branch name all work

gh pr view "$PR" --json number,title,body,url,state,isDraft,mergeable,\
baseRefName,headRefName,headRefOid,files,commits,labels

gh pr diff "$PR" > /tmp/pr.diff        # the patch under review
gh pr diff "$PR" --name-only           # changed file list
gh pr checks "$PR"                     # CI status
```

Existing discussion — read both, they're different endpoints:

```bash
gh api "repos/{owner}/{repo}/pulls/123/comments" --paginate   # inline review comments
gh api "repos/{owner}/{repo}/issues/123/comments" --paginate  # top-level PR comments
gh api "repos/{owner}/{repo}/pulls/123/reviews"   --paginate  # review summaries
```

To read the code as it exists at the head (rather than as hunks):

```bash
gh pr checkout "$PR"      # in a clone; then read files normally
# or, without checking out:
gh api "repos/{owner}/{repo}/contents/path/to/file.ts?ref=<headRefOid>" \
  --jq '.content' | base64 -d
```

Reviewing the diff alone is the single biggest cause of wrong review comments — the hunk hides the caller that makes the change safe, or the one that makes it fatal.

## Posting: batch into one review

Post one review containing all inline comments. Separate comments generate separate notifications and lose the connection between findings.

Build a JSON payload and pass it with `--input`. Never try to inline multi-paragraph comment bodies as shell arguments — quoting will corrupt them.

```json
{
  "commit_id": "<headRefOid>",
  "event": "COMMENT",
  "body": "Summary of the review: scope, method, headline findings.",
  "comments": [
    {
      "path": "src/api/orders.ts",
      "line": 142,
      "side": "RIGHT",
      "body": "**High** — ..."
    },
    {
      "path": "db/migrations/0042_add_status.sql",
      "start_line": 10,
      "start_side": "RIGHT",
      "line": 14,
      "side": "RIGHT",
      "body": "**Critical** — ..."
    }
  ]
}
```

```bash
gh api --method POST "repos/{owner}/{repo}/pulls/123/reviews" --input /tmp/review.json
```

The response includes `html_url` — that's the review link for the final report.

### Line and side semantics

- `line` is a **line number in the file**, not a diff offset. (`position` is the legacy diff-offset field; don't mix the two.)
- `side: "RIGHT"` means the line number in the file *after* the change — use it for added and unchanged lines. `side: "LEFT"` means the line number *before* the change — the only way to comment on a deleted line.
- Multi-line comments need `start_line` + `line` (and `start_side` + `side`), where `start_line < line` and both are on the same side.
- File-level comments (no line at all): `{"path": "...", "subject_type": "file", "body": "..."}`.

### The 422 and how to avoid it

`pull_request_review_thread.line must be part of the diff` means the target line isn't in a hunk of this PR's diff. **One bad comment rejects the entire review**, so validate before posting.

Only lines inside a hunk are commentable. Parse `/tmp/pr.diff` hunk headers (`@@ -old,count +new,count @@`) to compute the commentable ranges for each side, and check every finding's target line against them. `scripts/post_review.py --dry-run` does this for you.

When a finding lands outside the diff — a bug in code the PR calls but doesn't change — don't force it. Either anchor the comment to the nearest changed line that introduces the problem and name the real location in the body, or make it a file-level comment, or put it in the review body.

### Choosing the event

- `COMMENT` — the safe default. Works whether or not you're the PR author.
- `REQUEST_CHANGES` / `APPROVE` — only when the user asked for a verdict. GitHub rejects both on your own PR, so for self-review, `COMMENT` is the only option.
- Omit `event` to leave the review pending as a draft the user submits manually. Useful when they want to read the comments before the author sees them.

## Recovering from a failed post

If the batched review is rejected, don't retry blindly — the failure is almost always one or two comments:

1. Post the review with `body` only (no `comments`) so the summary lands.
2. Post each inline comment individually against `repos/{owner}/{repo}/pulls/123/comments` with `commit_id`, `path`, `line`, `side`.
3. For each one that still 422s, retry it as `subject_type: "file"`.
4. Report anything that still fails, with the finding text, so it isn't silently lost.

`scripts/post_review.py` implements exactly this fallback chain.

## Helper script

```bash
python3 scripts/post_review.py findings.json --dry-run   # validate lines against the diff
python3 scripts/post_review.py findings.json             # post
```

`findings.json`:

```json
{
  "pr": "https://github.com/owner/repo/pull/123",
  "event": "COMMENT",
  "body": "Review summary...",
  "comments": [
    {"path": "src/x.ts", "line": 42, "side": "RIGHT", "body": "**High** — ..."}
  ]
}
```

`commit_id` is resolved from the PR head automatically unless you set it. The script prints the review URL and a per-comment status line for each finding.

## Comment body template

```markdown
**<Severity>** — <one-line statement of the defect>

**Scenario:** <concrete steps, inputs, or interleaving that triggers it>

**Impact:** <what breaks, for whom, whether it's recoverable>

**Why this isn't caught:** <the constraint that doesn't apply / the test that mocks past it>

**Suggested direction:** <what to change; a code block if it's short>
```

Use a GitHub suggestion block when the fix is a small, literal edit — the author can apply it in one click:

````markdown
```suggestion
  const total = items.reduce((a, b) => a + b.cents, 0);
```
````

The suggestion must reproduce the entire target line range exactly as it should appear, including indentation.
