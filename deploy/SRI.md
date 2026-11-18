# Separate SRI application

Branch: `local/stem-fast-v-SRI`. Intended URL: https://lastrada-sri.web.app.
The original `local/stem-fast` branch and `lastrada-alt.web.app` are retained.

The SRI stack uses its own `lastrada-sri-api` and `lastrada-sri-worker` services,
`lastrada-sri-analysis` queue, three `lastrada-sri-*` runtime identities, and
private `lastrada-64bab-lastrada-sri-cases` upload bucket. Existing analyses are
not copied. Google sign-in uses the existing Firebase project; the setup adds
the two SRI Hosting domains while preserving all existing authorized domains.

The worker scales to zero, with at most one instance (2 CPU / 4 GiB), and the API
has at most two instances (1 CPU / 1 GiB). Uploaded data has a seven-day deletion
lifecycle. This uses existing project billing and may incur usage charges.

## Deployment

Pushes to the SRI branch run the Python and browser checks, then build a distinct
commit-tagged container. They do not deploy to the original services or website.
The existing GitHub deployment credential cannot create service accounts or
Cloud Tasks queues; initial provisioning therefore runs in authenticated Cloud
Shell with the project owner's existing access. No extra role is granted to the
GitHub credential. The setup grants runtime access only on the SRI bucket, queue,
task identity and private worker; it does not modify project-wide IAM.

After **Firebase web validation**, including **build-sri**, succeeds for the exact
commit, run from a clean checkout of the SRI branch in Cloud Shell:

```sh
python3 deploy/sri.py --mode apply \
  --sha EXACT_40_CHARACTER_COMMIT \
  --image ghcr.io/tankr98/lastrada:EXACT_40_CHARACTER_COMMIT
```

Use `deploy/sri.py` for this environment. The older `deploy/redeploy.py` and
`deploy/bootstrap.py` target the original stack and are not SRI deployment tools.
The SRI command also works for subsequent releases. It checks the original
services, traffic, IAM and public configuration before and after deployment,
verifies the new API and Hosting build, and reports the new URL. It fails on
permission errors rather than treating them as missing resources. Interrupted
provisioning can leave SRI resources created; inspect the error before resuming.
New service accounts can take time to become visible to other Google services.
The setup retries a rejected IAM binding only when Google explicitly returns
HTTP 400 saying the intended SRI account does not exist, waiting up to 95 seconds.
Permission denials and unrelated failures stop immediately. Rerunning the setup
reuses its marked SRI resources without deleting them.

Sign in on the new URL and test an upload after the first deployment. Automated
health and configuration checks do not constitute an end-to-end audio analysis.
