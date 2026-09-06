# 🌐 Production Deployment Guide: ATS Resume Architect

This guide explains how to run the production Node.js application, generate an instant live public HTTPS URL on the internet, and publish it permanently to free cloud hosting.

---

## 1. Local Production Execution

To run the application locally:

```bash
# 1. Compile the React frontend into web/dist
npm run build

# 2. Start the unified Node.js + Python server
npm start
```

The server serves the compiled frontend from `web/dist`. If that directory is missing it
logs a warning at startup and serves a short instruction page instead of the app.

- **Web Application URL**: [http://localhost:3000](http://localhost:3000)
- The server will automatically launch and orchestrate the Python ATS optimization engine in the background.

---

## 2. Instant Live Internet URL (Share with Anyone Worldwide)

If you want to immediately share the application over the internet with friends, recruiters, or clients without setting up cloud accounts or DNS:

```bash
# Generate a live, secure HTTPS internet link in seconds:
npm run tunnel
```

- This assigns you a secure live HTTPS domain (e.g. `https://ats-resume-architect.loca.lt`).
- It is accessible from any phone, laptop, or browser worldwide.
- **Tip**: On your first visit, localtunnel may ask for your public IP as an anti-abuse password. You can find your IP at [loca.lt/mytunnelpassword](https://loca.lt/mytunnelpassword) or by typing `curl https://loca.lt/mytunnelpassword`.

---

## 3. Permanent Free Cloud Deployment (Render.com)

Render provides free hosting with **automatic HTTPS/SSL certificates** and free custom domains.

### Step-by-Step Instructions:

1. **Push your code to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "feat: production ATS resume architect"
   git remote add origin https://github.com/<YOUR_USERNAME>/<REPO_NAME>.git
   git push -u origin main
   ```

2. **Deploy on Render**:
   - Go to **[render.com](https://render.com)** and sign in with GitHub.
   - Click **"New +"** $\rightarrow$ **"Web Service"**.
   - Select your repository.
   - Choose **"Docker"** as the Environment (it automatically detects the included [`Dockerfile`](../Dockerfile)).
   - In **Environment Variables**, add:
     - `GROQ_API_KEY`: Your Groq API key (`gsk_...`)
     - `NODE_ENV`: `production`
     - `RESUME_BUDDY_DATA_DIR` *(optional)*: path to a mounted disk for the
       SQLite user store. Without a persistent disk the account database is
       wiped on every redeploy, since Render's filesystem is ephemeral.
   - Click **"Create Web Service"**.

Render will automatically build the Docker container and provide a live public HTTPS URL:
`https://ats-resume-architect.onrender.com`.

---

## 4. Railway / Fly.io / Heroku Deployment

The repository includes a standard [`Procfile`](../Procfile):
```procfile
web: node server/index.js
```
You can deploy directly to Railway or Fly.io by connecting your Git repository and setting
`GROQ_API_KEY`.

These platforms run `npm run build` automatically after installing dependencies, which
compiles the frontend. If yours does not, add it to the build command explicitly —
`node server/index.js` alone will start the API but serve no UI. The Docker path handles
this already: the image builds the frontend in a first stage and copies `web/dist` into
the runtime stage, so the build toolchain never ships to production.
