# Streamlit Community Cloud deployment

Deploy the code from GitHub, not this cloud workspace's private filesystem. `requirements.txt` pins production Python dependencies and installs the local `lastrada` package. `packages.txt` declares FFmpeg and libsndfile. The root entrypoint is `app.py`; Python 3.12 is the tested runtime. `requirements.lock` remains the development/test installation file.

## Create the deployment

1. Sign in at https://share.streamlit.io and connect the GitHub account that can access the repository.
2. Select **Create app**, then deploy an existing app from GitHub.
3. Repository: `tankr98/Lastrada`.
4. Branch: `feat/lastrada-v0` (contains the app; the initial `main` does not). After PR merge, a deployment can use `main` instead.
5. Main file path: `app.py`.
6. Open **Advanced settings**, choose Python **3.12**, and deploy. No API keys or app secrets are required for the core app.
7. After deployment, open app settings → **Sharing** → **Only specific people can view this app**. The repository is public, so the app is public by default. Restrict viewers before uploading client recordings or historical data. Community Cloud allows one private app per workspace; if that slot is occupied, resolve hosting/privacy before uploading client content.

The account owner performs the authenticated creation step in their browser unless a Streamlit account session is explicitly available to the deployment tooling. GitHub authentication in Codex is not a Streamlit login. Do not request account passwords or tokens in chat.

## What is hosted

Paired audio intake and playback, experimental PF-NMF measurement, separate rights findings, expert correction and JSON/HTML export are available. Publishing localization remains manual. The optional Sony checkpoint and PyTorch are intentionally excluded from this lightweight hosted environment: they are large, checkpoint-backed matching is not yet calibrated, and this app has no validated Community Cloud resource profile for that workload. No synthetic inference is substituted for missing weights.

Confidential documents, spreadsheets, recordings, embeddings and real outputs remain outside Git. They are not deployed. Uploads/reviews are session-local; download reports before leaving. Do not use local disk as a persistent case database. The Cloud runtime has not been tested until the actual deployed URL and build logs are available.

## Check the deployment

- Confirm the build logs show successful installation of the package and the app opens its intake screen.
- Try the synthetic demonstration first, then a permitted original/new MP3 pair after configuring private viewers.
- Verify playback, rights scope, measurement, correction saving and report export. Results remain experimental, not clearance decisions.
- Inspect startup logs for import failures, missing native decoders or resource errors. Confirm `app.py` and Python 3.12 were selected.
- Share the actual deployed URL for verification. Do not manufacture a `streamlit.app` URL before it exists.

Production dependency installation and the synthetic intake/analysis flow were validated in a clean local Python 3.12 environment without Torch. This does not establish a successful remote deployment.

Official references: [Deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy), [dependencies](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/app-dependencies), [sharing/privacy](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app).
