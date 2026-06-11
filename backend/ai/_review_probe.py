"""Throwaway probe file to verify the Claude review workflow (issue #48).

This file exists only on the chore/0048-verify-review-prompt branch and is
NOT meant to be merged. It contains intentional, mild code smells so the
reviewer has something concrete to flag — letting us confirm the new
day-forge-tailored prompt runs and cites real repo paths.
"""


def accumulate(value, bucket=[]):  # mutable default arg — intentional smell
    bucket.append(value)
    return bucket


def risky_divide(a, b):
    try:
        return a / b
    except Exception:  # bare-ish broad except — intentional smell
        pass
