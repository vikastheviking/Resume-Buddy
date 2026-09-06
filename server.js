/**
 * Production Web Server for ATS Resume Architect.
 * Node.js (Express) with native HTTPS support, file upload handling,
 * and high-performance Python ASGI backend orchestration.
 */

const express = require('express');
const cors = require('cors');
const path = require('path');
const fs = require('fs');
const http = require('http');
const https = require('https');
const multer = require('multer');
const { spawn } = require('child_process');
const { verifyRealEmail } = require('./email_validator');
const { createAndSendOtp, verifyOtp } = require('./otp_service');
require('dotenv').config();

const app = express();
const PORT = process.env.PORT || 3000;
const PYTHON_PORT = process.env.PYTHON_PORT || 5001;
const PYTHON_BASE_URL = `http://127.0.0.1:${PYTHON_PORT}`;

// 1. Production Middleware
app.use(cors());
app.use(express.json({ limit: '15mb' }));
app.use(express.urlencoded({ extended: true, limit: '15mb' }));

// Multer memory storage for resume uploads
const upload = multer({
  storage: multer.memoryStorage(),
  limits: { fileSize: 15 * 1024 * 1024 } // 15MB
});

// Serve frontend static assets from /public
app.use(express.static(path.join(__dirname, 'public'), {
  maxAge: process.env.NODE_ENV === 'production' ? '1h' : '0'
}));

// 2. Python Backend Lifecycle Management
let pythonProcess = null;

async function checkPythonHealth() {
  try {
    const res = await fetch(`${PYTHON_BASE_URL}/api/health`, { method: 'GET' });
    if (res.ok) {
      const data = await res.json();
      return data.status === 'healthy';
    }
  } catch (err) {
    return false;
  }
  return false;
}

function startPythonBackend() {
  return new Promise(async (resolve) => {
    const alreadyRunning = await checkPythonHealth();
    if (alreadyRunning) {
      console.log(`[Python Engine] Already active on port ${PYTHON_PORT}`);
      return resolve(true);
    }

    console.log(`[Python Engine] Launching api_backend.py on port ${PYTHON_PORT}...`);
    const scriptPath = path.join(__dirname, 'api_backend.py');
    pythonProcess = spawn('python', [scriptPath], {
      env: { ...process.env, PYTHON_PORT: String(PYTHON_PORT) },
      stdio: 'pipe'
    });

    pythonProcess.stdout.on('data', (data) => {
      console.log(`[Python] ${data.toString().trim()}`);
    });

    pythonProcess.stderr.on('data', (data) => {
      console.error(`[Python Err] ${data.toString().trim()}`);
    });

    pythonProcess.on('close', (code) => {
      console.log(`[Python Engine] Process exited with code ${code}`);
    });

    // Poll for readiness
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      const isHealthy = await checkPythonHealth();
      if (isHealthy) {
        clearInterval(interval);
        console.log(`[Python Engine] Successfully connected and ready!`);
        resolve(true);
      } else if (attempts > 30) {
        clearInterval(interval);
        console.warn(`[Python Engine] Failed to confirm readiness after 15 seconds.`);
        resolve(false);
      }
    }, 500);
  });
}

// 3. API Routes

// Health Check
app.get('/api/health', async (req, res) => {
  const pythonOk = await checkPythonHealth();
  res.json({
    status: 'ok',
    server: 'Node.js Express',
    port: PORT,
    engine: pythonOk ? 'online' : 'reconnecting'
  });
});

// Sample Profile Data
app.get('/api/sample', async (req, res) => {
  try {
    const key = req.query.key || '';
    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/sample?key=${encodeURIComponent(key)}`);
    const data = await pyRes.json();
    res.json(data);
  } catch (err) {
    res.status(500).json({ error: 'Failed to fetch sample data', details: err.message });
  }
});

// Pre-flight Real Email Validation
app.post('/api/auth/validate-email', async (req, res) => {
  try {
    const { email } = req.body;
    if (!email) {
      return res.status(400).json({ isValid: false, error: 'Email is required.' });
    }
    const result = await verifyRealEmail(email);
    res.json(result);
  } catch (err) {
    res.status(500).json({ isValid: false, error: err.message });
  }
});

// OTP: Send Verification Code
app.post('/api/auth/send-otp', async (req, res) => {
  try {
    const { email, mode = 'signup' } = req.body;
    if (!email) {
      return res.status(400).json({ success: false, error: 'Email address is required.' });
    }

    // 1. Strict Real Email Verification Check
    const verification = await verifyRealEmail(email);
    if (!verification.isValid) {
      return res.status(400).json({
        success: false,
        error: verification.error,
        suggestion: verification.suggestion
      });
    }

    const cleanEmail = verification.cleanEmail || email.trim().toLowerCase();

    // 2. Dispatch 6-digit OTP
    const otpResult = await createAndSendOtp(cleanEmail, mode);
    if (!otpResult.success) {
      return res.status(429).json(otpResult);
    }

    res.json({
      success: true,
      message: otpResult.message || `Verification code sent to ${cleanEmail}. Check your inbox!`,
      email: cleanEmail,
      mode
    });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// OTP: Verify Code and Activate Account / Sign In
app.post('/api/auth/verify-otp', async (req, res) => {
  try {
    const { email, otp } = req.body;
    if (!email || !otp) {
      return res.status(400).json({ success: false, error: 'Both email and 6-digit verification code are required.' });
    }

    const verification = verifyOtp(email, otp);
    if (!verification.isValid) {
      return res.status(400).json({ success: false, error: verification.error });
    }

    // Ensure user record exists in database
    try {
      await fetch(`${PYTHON_BASE_URL}/api/auth/signup`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: verification.email, password: 'OTP_VERIFIED_SECURE_AUTH' })
      });
    } catch (err) {
      // User may already exist, ignore
    }

    res.json({
      success: true,
      message: 'Email successfully verified!',
      email: verification.email,
      mode: verification.mode
    });
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Authentication: Sign Up with Strict 5-Layer Real Email Verification
app.post('/api/auth/signup', async (req, res) => {
  try {
    const { email, password } = req.body;

    // Strict Real Email Verification Check
    const verification = await verifyRealEmail(email);
    if (!verification.isValid) {
      return res.status(400).json({
        success: false,
        error: verification.error,
        suggestion: verification.suggestion
      });
    }

    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/auth/signup`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email: verification.cleanEmail || email, password })
    });
    const data = await pyRes.json();
    res.status(pyRes.status).json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Authentication: Login
app.post('/api/auth/login', async (req, res) => {
  try {
    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req.body)
    });
    const data = await pyRes.json();
    res.status(pyRes.status).json(data);
  } catch (err) {
    res.status(500).json({ success: false, error: err.message });
  }
});

// Upload & Extract Resume File
app.post('/api/upload', upload.single('file'), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No resume file uploaded.' });
    }

    const formData = new FormData();
    const blob = new Blob([req.file.buffer], { type: req.file.mimetype || 'application/octet-stream' });
    formData.append('file', blob, req.file.originalname);

    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/extract`, {
      method: 'POST',
      body: formData
    });

    if (!pyRes.ok) {
      const errData = await pyRes.json();
      return res.status(pyRes.status).json(errData);
    }

    const data = await pyRes.json();
    res.json(data);
  } catch (err) {
    console.error('Upload handler error:', err);
    res.status(500).json({ error: 'Extraction service error', details: err.message });
  }
});

// ATS Optimization (Actual Score + Llama-3.3-70B Star Metrics + Updated Score)
app.post('/api/optimize', async (req, res) => {
  try {
    const { resume_text, jd_text } = req.body;
    if (!resume_text || !jd_text) {
      return res.status(400).json({ error: 'Both resume_text and jd_text are required.' });
    }

    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/optimize`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ resume_text, jd_text })
    });

    if (!pyRes.ok) {
      const errText = await pyRes.text();
      return res.status(pyRes.status).json({ error: errText });
    }

    const data = await pyRes.json();
    res.json(data);
  } catch (err) {
    console.error('Optimization error:', err);
    res.status(500).json({ error: 'Optimization service error', details: err.message });
  }
});

// Export PDF
app.post('/api/export/pdf', async (req, res) => {
  try {
    const { markdown_text } = req.body;
    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/export/pdf`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown_text })
    });

    if (!pyRes.ok) {
      return res.status(pyRes.status).send('Failed to generate PDF');
    }

    res.setHeader('Content-Type', 'application/pdf');
    res.setHeader('Content-Disposition', 'attachment; filename="ATS_Optimized_Resume.pdf"');
    const buffer = Buffer.from(await pyRes.arrayBuffer());
    res.send(buffer);
  } catch (err) {
    res.status(500).json({ error: 'PDF export failed', details: err.message });
  }
});

// Export DOCX
app.post('/api/export/docx', async (req, res) => {
  try {
    const { markdown_text } = req.body;
    const pyRes = await fetch(`${PYTHON_BASE_URL}/api/export/docx`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ markdown_text })
    });

    if (!pyRes.ok) {
      return res.status(pyRes.status).send('Failed to generate DOCX');
    }

    res.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    res.setHeader('Content-Disposition', 'attachment; filename="ATS_Optimized_Resume.docx"');
    const buffer = Buffer.from(await pyRes.arrayBuffer());
    res.send(buffer);
  } catch (err) {
    res.status(500).json({ error: 'DOCX export failed', details: err.message });
  }
});

// Fallback to index.html for SPA routing
app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

// 4. Server Initialization (HTTP & HTTPS)
async function startServer() {
  await startPythonBackend();

  // Standard HTTP Server
  const httpServer = http.createServer(app);
  httpServer.listen(PORT, () => {
    console.log(`====================================================`);
    console.log(`🚀 ATS Resume Architect Web Application`);
    console.log(`📡 Local Web URL:  http://localhost:${PORT}`);
    console.log(`⚙️  Python Engine:  http://127.0.0.1:${PYTHON_PORT}`);
    console.log(`🌐 Public Tunnel:  Run 'npm run tunnel' for live internet link`);
    console.log(`====================================================`);
  });

  // Optional HTTPS Server
  const sslKeyPath = process.env.SSL_KEY_PATH || path.join(__dirname, 'cert', 'key.pem');
  const sslCertPath = process.env.SSL_CERT_PATH || path.join(__dirname, 'cert', 'cert.pem');
  const HTTPS_PORT = process.env.HTTPS_PORT || 3443;

  if (fs.existsSync(sslKeyPath) && fs.existsSync(sslCertPath)) {
    try {
      const httpsOptions = {
        key: fs.readFileSync(sslKeyPath),
        cert: fs.readFileSync(sslCertPath)
      };
      const httpsServer = https.createServer(httpsOptions, app);
      httpsServer.listen(HTTPS_PORT, () => {
        console.log(`🔒 Local HTTPS URL: https://localhost:${HTTPS_PORT}`);
      });
    } catch (err) {
      console.warn(`[HTTPS] Failed to initialize SSL certificates:`, err.message);
    }
  }
}

// Graceful Shutdown
function handleShutdown() {
  console.log('\nShutting down ATS Resume Architect server...');
  if (pythonProcess) {
    pythonProcess.kill();
  }
  process.exit(0);
}

process.on('SIGINT', handleShutdown);
process.on('SIGTERM', handleShutdown);

startServer();
