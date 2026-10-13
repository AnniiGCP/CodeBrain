# CodeBrain — Manual Deployment Actions Checklist

This document contains the step-by-step checklist of manual configuration actions that must be performed directly in your cloud provider dashboards (Vercel, Render, Supabase, and GitHub).

> [!IMPORTANT]
> Never paste private passwords, tokens, or API keys into chat. Enter them directly into the respective secure platform dashboards as described below.

---

## Action Checklist

| Step | Platform | Exact Action Required | Why It Is Needed | Verification |
|---|---|---|---|---|
| **1** | **GitHub Actions Secrets** | In `https://github.com/AnniiGCP/CodeBrain/settings/secrets/actions`, add secret `RENDER_DEPLOY_HOOK_URL` | Allows GitHub Actions `Production Deployment` workflow to automatically trigger Render redeployments upon merged commits | GitHub Action step "Trigger Render Deploy Hook" succeeds instead of displaying notice |
| **2** | **Render Dashboard** | In Render Dashboard &rarr; `codebrain-backend` &rarr; **Environment**, verify `CORS_ORIGINS` contains `https://codebrain-dev.vercel.app,https://codebrain.vercel.app` | Ensures FastAPI allows cross-origin requests and cookies from your live Vercel domains without browser `Failed to fetch` errors | Opening `https://codebrain-dev.vercel.app` connects to backend with zero CORS errors in browser DevTools console |
| **3** | **Render Dashboard** | In Render Dashboard &rarr; `codebrain-backend` &rarr; **Environment**, set `FRONTEND_URL` to `https://codebrain-dev.vercel.app` | Ensures OAuth redirects, email verification links, and password resets redirect users back to the live Vercel domain instead of `localhost:5173` | GitHub OAuth callback redirects to your live Vercel app |
| **4** | **Render Dashboard** | In Render Dashboard &rarr; `codebrain-backend` &rarr; **Environment**, ensure `SESSION_SECRET` is set to a long, random 64-character hex string (e.g., generated with `openssl rand -hex 32`) | Protects production session cookies with cryptographically secure signatures and satisfies fail-closed production security gating | Backend starts up without `RuntimeError` and issues signed session cookies |
| **5** | **GitHub Developer Settings** | In GitHub Settings &rarr; **Developer Settings** &rarr; **OAuth Apps** &rarr; Select your CodeBrain app: update **Homepage URL** to `https://codebrain-dev.vercel.app` and **Authorization callback URL** to `https://codebrain-backend.onrender.com/auth/github/callback` | Enables production users to log in with GitHub without being redirected to `localhost:8000` | Clicking "Continue with GitHub" completes the OAuth handshake and logs the user into the workspace |
| **6** | **Vercel Project Settings** | In Vercel Dashboard &rarr; `codebrain-dev` &rarr; **Settings** &rarr; **Environment Variables**, verify `VITE_API_URL` is set to `https://codebrain-backend.onrender.com` for Production and Preview | Guarantees the frontend always routes API requests to your production Render backend rather than falling back to default | Browser network inspection shows API requests targeting `codebrain-backend.onrender.com` |

---

## Detailed Step-by-Step Instructions

### Step 1: Configure Render Deploy Hook in GitHub (Optional for Automated CI Deploy)
1. Open Render Dashboard: `https://dashboard.render.com` &rarr; Web Services &rarr; `codebrain-backend`.
2. Go to **Settings** &rarr; scroll to **Deploy Hook**.
3. Copy the unique URL (e.g. `https://api.render.com/deploy/srv-xxxx?key=yyyy`).
4. Open GitHub: `https://github.com/AnniiGCP/CodeBrain/settings/secrets/actions`.
5. Click **New repository secret**.
6. Set Name: `RENDER_DEPLOY_HOOK_URL`.
7. Set Value: Paste the copied Render deploy hook URL.
8. Click **Add secret**.

### Step 2 & 3: Configure Render Environment Variables
1. Open Render Dashboard &rarr; `codebrain-backend` &rarr; **Environment**.
2. Find or add the following keys:
   - `CORS_ORIGINS`: `https://codebrain-dev.vercel.app,https://codebrain.vercel.app`
   - `FRONTEND_URL`: `https://codebrain-dev.vercel.app`
   - `ENVIRONMENT`: `production`
   - `ALLOW_DEV_LOGIN`: `false`
   - `SECURE_COOKIES`: `true`
3. Click **Save Changes** (Render will automatically redeploy the service).

### Step 4: Verify Strong SESSION_SECRET on Render
1. In the same **Environment** tab on Render:
2. Check `SESSION_SECRET`.
3. If it is currently `codebrain-super-secret-session-key-2026` or empty, replace it with a unique secret (e.g. `cb_prod_sec_` followed by 32+ random characters).
4. Click **Save Changes**.

### Step 5: Update GitHub OAuth App for Production Callback
1. Open GitHub &rarr; Settings &rarr; Developer Settings &rarr; **OAuth Apps**:
   `https://github.com/settings/developers`
2. Select your CodeBrain OAuth application (Client ID: `Ov23liC6gYxoN4xOujLa`).
3. Update fields:
   - **Homepage URL**: `https://codebrain-dev.vercel.app`
   - **Authorization callback URL**: `https://codebrain-backend.onrender.com/auth/github/callback`
4. Click **Update application**.
5. Copy the Client Secret and confirm it matches `GITHUB_OAUTH_CLIENT_SECRET` in Render environment variables.

### Step 6: Verify Vercel Frontend Environment Variable
1. Open Vercel Dashboard: `https://vercel.com/dashboard`.
2. Select project `codebrain-dev` &rarr; **Settings** &rarr; **Environment Variables**.
3. Verify or add:
   - **Key**: `VITE_API_URL`
   - **Value**: `https://codebrain-backend.onrender.com`
   - **Environments**: Production, Preview, Development.
4. Save changes.
