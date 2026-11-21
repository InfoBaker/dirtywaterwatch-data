# Security

## Reporting a problem

If you find a security problem in this repository, or personal details in the data we publish, tell us through
the contact form at <https://dirtywaterwatch.org/contact/>. Please do not open a public issue for it. Say where
you found it (a file, a record, a page) and, if you can, how to reproduce it. We read every message and fix what
we confirm.

## What this repository holds

- The pipeline that collects public records of sewage discharges, beach advisories and algal blooms, and the
  registries behind them: outfalls, operators, water bodies, public-notice channels and reporting rules.
- Public records only. Each record carries its source, the source's own times and our fetch time.
- No secrets. Credentials live in the repository's encrypted settings and are given only to the workflow steps
  that use them. Workflow logs leave out account details, keys and the query strings of addresses.

Personal details are removed from what we publish: a private person's name, phone number, e-mail address and
house number. The sources are public records, so a detail can slip through. When we find one, or someone reports
one, we remove it and add a rule so it is removed from then on.

## What the pipeline can reach

The pipeline's storage credentials reach one storage bucket, its own, and nothing else in the account. They read
and write the pipeline's state and the files the site is built from.
