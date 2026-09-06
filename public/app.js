/**
 * Client-side application controller for ATS Resume Architect.
 * Handles drag-and-drop file parsing, live word counts, ATS score animations,
 * single-column markdown rendering, and PDF/DOCX downloads.
 */

document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const resumeTextInput = document.getElementById('resume-text');
  const jdTextInput = document.getElementById('jd-text');
  const resumeCount = document.getElementById('resume-count');
  const jdCount = document.getElementById('jd-count');
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('resume-file-input');
  const uploadStatus = document.getElementById('upload-status');
  const jdDropZone = document.getElementById('jd-drop-zone');
  const jdFileInput = document.getElementById('jd-file-input');
  const jdUploadStatus = document.getElementById('jd-upload-status');
  const loadSampleBtn = document.getElementById('load-sample-btn');
  const optimizeBtn = document.getElementById('optimize-btn');
  const loadingIndicator = document.getElementById('loading-indicator');
  const resultsSection = document.getElementById('results-section');
  const actualScoreNum = document.getElementById('actual-score-num');
  const actualScoreBar = document.getElementById('actual-score-bar');
  const updatedScoreNum = document.getElementById('updated-score-num');
  const updatedScoreBar = document.getElementById('updated-score-bar');
  const scoreBoostBadge = document.getElementById('score-boost-badge');
  const resumePreview = document.getElementById('resume-preview');
  const auditDetail = document.getElementById('audit-detail');
  const copyBtn = document.getElementById('copy-btn');
  const downloadPdfBtn = document.getElementById('download-pdf-btn');
  const downloadDocxBtn = document.getElementById('download-docx-btn');
  const toast = document.getElementById('toast');

  // Auth Elements
  const authNavContainer = document.getElementById('auth-nav-container');
  const authModal = document.getElementById('auth-modal');
  const closeModalBtn = document.getElementById('close-modal-btn');
  const tabLoginBtn = document.getElementById('tab-login-btn');
  const tabSignupBtn = document.getElementById('tab-signup-btn');
  const authAlert = document.getElementById('auth-alert');
  const authStepEmail = document.getElementById('auth-step-email');
  const authStepOtp = document.getElementById('auth-step-otp');
  const emailOtpForm = document.getElementById('email-otp-form');
  const authEmailInput = document.getElementById('auth-email-input');
  const emailValidationHint = document.getElementById('email-validation-hint');
  const sendOtpBtn = document.getElementById('send-otp-btn');
  const guestLoginBtn = document.getElementById('guest-login-btn');
  const otpBackBtn = document.getElementById('otp-back-btn');
  const otpTargetEmail = document.getElementById('otp-target-email');
  const otpAlert = document.getElementById('otp-alert');
  const otpVerifyForm = document.getElementById('otp-verify-form');
  const otpInput = document.getElementById('otp-input');
  const submitOtpBtn = document.getElementById('submit-otp-btn');
  const resendOtpBtn = document.getElementById('resend-otp-btn');
  const resendCountdown = document.getElementById('resend-countdown');

  let authMode = 'login'; // 'login' or 'signup'
  let pendingEmail = '';
  let resendTimer = null;
  let currentOptimizedMarkdown = '';

  // 1. Toast Notification Helper
  function showToast(message, duration = 3000) {
    toast.textContent = message;
    toast.classList.remove('hidden');
    setTimeout(() => {
      toast.classList.add('hidden');
    }, duration);
  }

  // 1b. Authentication Manager
  function getAuthUser() {
    return localStorage.getItem('ats_user');
  }

  function setAuthUser(email) {
    localStorage.setItem('ats_user', email);
    updateAuthNavbar();
  }

  function clearAuthUser() {
    localStorage.removeItem('ats_user');
    updateAuthNavbar();
  }

  function updateAuthNavbar() {
    const user = getAuthUser();
    if (user) {
      authNavContainer.innerHTML = `
        <div class="user-badge-wrap">
          <div class="user-badge" title="${escapeHtml(user)}">👤 ${escapeHtml(user)}</div>
          <button id="signout-btn" class="btn btn-secondary btn-sm">Sign Out</button>
        </div>
      `;
      document.getElementById('signout-btn').addEventListener('click', () => {
        clearAuthUser();
        showToast('Signed out successfully.');
      });
    } else {
      authNavContainer.innerHTML = `
        <button id="open-auth-btn" class="btn btn-primary btn-sm">
          <span>🔑 Sign In</span>
        </button>
      `;
      document.getElementById('open-auth-btn').addEventListener('click', () => {
        showAuthModal();
      });
    }
  }

  function showAuthModal(alertMsg = null) {
    // Reset view to step 1
    authStepEmail.classList.remove('hidden');
    authStepOtp.classList.add('hidden');
    otpAlert.classList.add('hidden');

    if (alertMsg) {
      showAuthAlert(alertMsg, 'error');
    } else {
      authAlert.classList.add('hidden');
    }
    authModal.classList.remove('hidden');
    authEmailInput.focus();
  }

  function hideAuthModal() {
    authModal.classList.add('hidden');
    authAlert.classList.add('hidden');
    otpAlert.classList.add('hidden');
    if (resendTimer) {
      clearInterval(resendTimer);
      resendTimer = null;
    }
  }

  function showAuthAlert(msg, type = 'error') {
    authAlert.textContent = msg;
    authAlert.className = `auth-alert ${type}`;
    authAlert.classList.remove('hidden');
  }

  function showOtpAlert(msg, type = 'error') {
    otpAlert.textContent = msg;
    otpAlert.className = `auth-alert ${type}`;
    otpAlert.classList.remove('hidden');
  }

  // Tab switching: Login vs Sign Up
  tabLoginBtn.addEventListener('click', () => {
    authMode = 'login';
    tabLoginBtn.classList.add('active');
    tabSignupBtn.classList.remove('active');
    authStepEmail.classList.remove('hidden');
    authStepOtp.classList.add('hidden');
    authAlert.classList.add('hidden');
    otpAlert.classList.add('hidden');
    sendOtpBtn.querySelector('span').textContent = 'Send Sign In Code ➔';
  });

  tabSignupBtn.addEventListener('click', () => {
    authMode = 'signup';
    tabSignupBtn.classList.add('active');
    tabLoginBtn.classList.remove('active');
    authStepEmail.classList.remove('hidden');
    authStepOtp.classList.add('hidden');
    authAlert.classList.add('hidden');
    otpAlert.classList.add('hidden');
    sendOtpBtn.querySelector('span').textContent = 'Send Verification Code ➔';
  });

  closeModalBtn.addEventListener('click', hideAuthModal);
  authModal.addEventListener('click', (e) => {
    if (e.target === authModal) hideAuthModal();
  });

  // Resend Countdown Manager
  function startResendCountdown(seconds = 45) {
    if (resendTimer) clearInterval(resendTimer);
    let remaining = seconds;
    resendOtpBtn.disabled = true;
    resendOtpBtn.innerHTML = `Resend code in <span id="resend-countdown">${remaining}</span>s`;

    resendTimer = setInterval(() => {
      remaining -= 1;
      const countSpan = document.getElementById('resend-countdown');
      if (countSpan) countSpan.textContent = remaining;

      if (remaining <= 0) {
        clearInterval(resendTimer);
        resendTimer = null;
        resendOtpBtn.disabled = false;
        resendOtpBtn.textContent = 'Resend verification code';
      }
    }, 1000);
  }

  // Real-time Email Verification on Input (Debounced)
  let emailDebounceTimer = null;
  authEmailInput.addEventListener('input', () => {
    clearTimeout(emailDebounceTimer);
    const email = authEmailInput.value.trim();

    if (!email) {
      emailValidationHint.classList.add('hidden');
      return;
    }

    if (!email.includes('@') || email.length < 5) {
      emailValidationHint.className = 'input-hint';
      emailValidationHint.textContent = 'Enter a complete email address (e.g., name@company.com)';
      emailValidationHint.classList.remove('hidden');
      return;
    }

    emailDebounceTimer = setTimeout(async () => {
      try {
        emailValidationHint.className = 'input-hint';
        emailValidationHint.textContent = '🔍 Checking mail server...';
        emailValidationHint.classList.remove('hidden');

        const res = await fetch('/api/auth/validate-email', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        });
        const data = await res.json();

        if (data.isValid) {
          emailValidationHint.className = 'input-hint success';
          emailValidationHint.textContent = '✓ Verified legitimate email domain';
        } else if (data.suggestion) {
          emailValidationHint.className = 'input-hint warning';
          emailValidationHint.textContent = `💡 Did you mean @${data.suggestion}? Click to fix`;
          emailValidationHint.onclick = () => {
            const parts = email.split('@');
            authEmailInput.value = `${parts[0]}@${data.suggestion}`;
            emailValidationHint.className = 'input-hint success';
            emailValidationHint.textContent = '✓ Corrected to valid email domain';
          };
        } else {
          emailValidationHint.className = 'input-hint error';
          emailValidationHint.textContent = `⚠️ ${data.error}`;
        }
      } catch (err) {
        // Silently skip on network error
      }
    }, 400);
  });

  // Step 1: Request OTP Dispatch
  emailOtpForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = authEmailInput.value.trim();

    if (!email) {
      showAuthAlert('Please enter your email address.');
      return;
    }

    try {
      sendOtpBtn.disabled = true;
      sendOtpBtn.innerHTML = '<span>Verifying & Sending OTP...</span>';
      authAlert.classList.add('hidden');

      const res = await fetch('/api/auth/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, mode: authMode })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        if (data.suggestion) {
          showAuthAlert(`${data.error} Did you mean @${data.suggestion}?`);
        } else {
          showAuthAlert(data.error || 'Failed to dispatch verification code.');
        }
        return;
      }

      // Success: Transition to Step 2 (OTP Input)
      pendingEmail = data.email || email;
      authStepEmail.classList.add('hidden');
      authStepOtp.classList.remove('hidden');
      otpTargetEmail.textContent = pendingEmail;
      otpInput.value = '';

      startResendCountdown(45);
      setTimeout(() => otpInput.focus(), 100);
      showToast(data.message || 'Verification code sent to your email!');
    } catch (err) {
      showAuthAlert(`Connection error: ${err.message}`);
    } finally {
      sendOtpBtn.disabled = false;
      sendOtpBtn.innerHTML = `<span>${authMode === 'signup' ? 'Send Verification Code ➔' : 'Send Sign In Code ➔'}</span>`;
    }
  });

  // Step 2: Back to Email Step
  otpBackBtn.addEventListener('click', () => {
    authStepOtp.classList.add('hidden');
    authStepEmail.classList.remove('hidden');
    authAlert.classList.add('hidden');
    otpAlert.classList.add('hidden');
    if (resendTimer) {
      clearInterval(resendTimer);
      resendTimer = null;
    }
  });

  // Step 2: Resend OTP Code
  resendOtpBtn.addEventListener('click', async () => {
    if (resendOtpBtn.disabled || !pendingEmail) return;

    try {
      resendOtpBtn.disabled = true;
      resendOtpBtn.textContent = 'Sending new code...';
      otpAlert.classList.add('hidden');

      const res = await fetch('/api/auth/send-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingEmail, mode: authMode })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        showOtpAlert(data.error || 'Failed to resend code.');
        resendOtpBtn.disabled = false;
        resendOtpBtn.textContent = 'Resend verification code';
        return;
      }

      showToast('A fresh verification code has been dispatched to your email!');
      startResendCountdown(45);
    } catch (err) {
      showOtpAlert(`Network error: ${err.message}`);
      resendOtpBtn.disabled = false;
      resendOtpBtn.textContent = 'Resend verification code';
    }
  });

  // Step 2: Verify OTP Code
  otpVerifyForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const otp = otpInput.value.trim();

    if (!otp || otp.length !== 6) {
      showOtpAlert('Please enter the complete 6-digit verification code.');
      return;
    }

    try {
      submitOtpBtn.disabled = true;
      submitOtpBtn.innerHTML = '<span>Verifying code...</span>';
      otpAlert.classList.add('hidden');

      const res = await fetch('/api/auth/verify-otp', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: pendingEmail, otp })
      });
      const data = await res.json();

      if (!res.ok || !data.success) {
        showOtpAlert(data.error || 'Invalid or expired code.');
        return;
      }

      // Verification Success: Authenticate user
      setAuthUser(data.email);
      hideAuthModal();
      showToast(`🎉 Verified! Welcome, ${data.email}`);
    } catch (err) {
      showOtpAlert(`Connection error: ${err.message}`);
    } finally {
      submitOtpBtn.disabled = false;
      submitOtpBtn.innerHTML = '<span>Verify & Continue 🚀</span>';
    }
  });

  // Guest / Demo Access
  guestLoginBtn.addEventListener('click', () => {
    setAuthUser('guest@ats-architect.local');
    hideAuthModal();
    showToast('Signed in as Guest (Demo Mode).');
  });

  // Initialize Auth Navbar State
  updateAuthNavbar();

  // 2. Word Count Update
  function updateWordCounts() {
    const resumeWords = resumeTextInput.value.trim() ? resumeTextInput.value.trim().split(/\s+/).length : 0;
    const jdWords = jdTextInput.value.trim() ? jdTextInput.value.trim().split(/\s+/).length : 0;
    resumeCount.textContent = `${resumeWords} words`;
    jdCount.textContent = `${jdWords} words`;
  }

  resumeTextInput.addEventListener('input', updateWordCounts);
  jdTextInput.addEventListener('input', updateWordCounts);

  // 3. Generic File Upload Handler
  async function handleFileUpload(file, targetInput, statusElem, label) {
    statusElem.classList.remove('hidden', 'success', 'error');
    statusElem.textContent = `Extracting ${label} from ${file.name}...`;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || 'Failed to extract text');
      }

      const data = await res.json();
      targetInput.value = data.text;
      updateWordCounts();

      statusElem.classList.add('success');
      statusElem.textContent = `✓ Successfully extracted ${data.word_count} words from ${file.name}`;
      showToast(`Loaded ${label}: ${file.name}`);
    } catch (err) {
      statusElem.classList.add('error');
      statusElem.textContent = `⚠️ Error: ${err.message}`;
    }
  }

  function setupDropZone(dropElement, fileInputElement, targetInput, statusElem, label) {
    if (!dropElement || !fileInputElement) return;

    dropElement.addEventListener('click', () => fileInputElement.click());

    ['dragenter', 'dragover'].forEach(eventName => {
      dropElement.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropElement.classList.add('dragover');
      });
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropElement.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropElement.classList.remove('dragover');
      });
    });

    dropElement.addEventListener('drop', (e) => {
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFileUpload(files[0], targetInput, statusElem, label);
      }
    });

    fileInputElement.addEventListener('change', (e) => {
      if (e.target.files.length > 0) {
        handleFileUpload(e.target.files[0], targetInput, statusElem, label);
      }
    });
  }

  // Setup Resume drop zone
  setupDropZone(dropZone, fileInput, resumeTextInput, uploadStatus, 'Resume');

  // Setup Job Description drop zone
  setupDropZone(jdDropZone, jdFileInput, jdTextInput, jdUploadStatus, 'Job Description');

  // 4. Load Sample Profile
  loadSampleBtn.addEventListener('click', async () => {
    try {
      loadSampleBtn.disabled = true;
      loadSampleBtn.textContent = 'Loading sample...';

      const res = await fetch('/api/sample');
      const data = await res.json();

      resumeTextInput.value = data.resume;
      jdTextInput.value = data.jd;
      updateWordCounts();

      showToast(`Loaded '${data.profile_name}' demo profile!`);
    } catch (err) {
      showToast(`Failed to load sample: ${err.message}`);
    } finally {
      loadSampleBtn.disabled = false;
      loadSampleBtn.innerHTML = '<span>⚡ Load Sample Profile</span>';
    }
  });

  // 5. Lightweight ATS Markdown Renderer
  function renderATSMarkdown(markdown) {
    if (!markdown) return '';

    const lines = markdown.split('\n');
    let html = '';
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
      let line = lines[i].trim();

      if (!line) {
        if (inList) {
          html += '</ul>';
          inList = false;
        }
        continue;
      }

      // Title # Full Name
      if (line.startsWith('# ')) {
        if (inList) { html += '</ul>'; inList = false; }
        const name = line.substring(2).trim();
        html += `<h1>${escapeHtml(name)}</h1>`;
        continue;
      }

      // Contact Line (e.g. phone | email | linkedin)
      if (i <= 3 && (line.includes('|') || line.includes('@'))) {
        if (inList) { html += '</ul>'; inList = false; }
        html += `<div class="contact-line">${escapeHtml(line)}</div>`;
        continue;
      }

      // Heading 2 ## Section
      if (line.startsWith('## ')) {
        if (inList) { html += '</ul>'; inList = false; }
        const sectionTitle = line.substring(3).trim();
        html += `<h2>${escapeHtml(sectionTitle)}</h2>`;
        continue;
      }

      // Heading 3 ### Subtitle / Role
      if (line.startsWith('### ')) {
        if (inList) { html += '</ul>'; inList = false; }
        const roleTitle = line.substring(4).trim();
        html += `<h3>${formatInline(roleTitle)}</h3>`;
        continue;
      }

      // Bullet points - ... or * ...
      if (line.startsWith('- ') || line.startsWith('* ')) {
        if (!inList) {
          html += '<ul>';
          inList = true;
        }
        const bulletText = line.substring(2).trim();
        html += `<li>${formatInline(bulletText)}</li>`;
        continue;
      }

      // Standard text paragraph
      if (inList) { html += '</ul>'; inList = false; }
      html += `<p>${formatInline(line)}</p>`;
    }

    if (inList) {
      html += '</ul>';
    }

    return html;
  }

  /**
   * Show the evidence behind the score: which job-description terms the rewrite picked
   * up, which are still absent, and any ATS formatting problems the scorer flagged.
   *
   * Without this the user sees a bare number and has to take it on trust.
   */
  function renderAuditDetail(audit) {
    if (!auditDetail) return;
    if (!audit) {
      auditDetail.classList.add('hidden');
      return;
    }

    const chips = (items) => items
      .map((k) => `<span class="kw-chip">${escapeHtml(k)}</span>`)
      .join('');

    const injected = Array.isArray(audit.injected_keywords) ? audit.injected_keywords : [];
    const alerts = Array.isArray(audit.format_alerts) ? audit.format_alerts : [];
    const blocks = [];

    blocks.push(`
      <div class="audit-row">
        <span class="audit-label">Score breakdown</span>
        <span class="audit-value">
          Keywords ${audit.keyword_score}% &middot;
          Semantic ${audit.semantic_score}% &middot;
          Impact ${audit.impact_score}% &middot;
          Format ${audit.format_score}%
        </span>
      </div>
    `);

    blocks.push(`
      <div class="audit-row">
        <span class="audit-label">Keyword coverage</span>
        <span class="audit-value">${audit.matched_count} matched, ${audit.missing_count} still missing</span>
      </div>
    `);

    if (injected.length) {
      blocks.push(`
        <div class="audit-row">
          <span class="audit-label">Newly covered</span>
          <span class="audit-value">${chips(injected)}</span>
        </div>
      `);
    }

    if (alerts.length) {
      blocks.push(`
        <div class="audit-row">
          <span class="audit-label">Formatting</span>
          <span class="audit-value">${alerts.map((a) => escapeHtml(a)).join(' ')}</span>
        </div>
      `);
    }

    if (audit.engine_used && audit.engine_used.startsWith('structural')) {
      blocks.push(`
        <div class="audit-row audit-note">
          <span class="audit-label">Note</span>
          <span class="audit-value">
            Formatting was cleaned up, but no AI rewrite ran (${escapeHtml(audit.engine_used)}).
            Wording and keyword coverage are unchanged from your original.
          </span>
        </div>
      `);
    }

    auditDetail.innerHTML = blocks.join('');
    auditDetail.classList.remove('hidden');
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function formatInline(text) {
    let formatted = escapeHtml(text);
    // Bold **text**
    formatted = formatted.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    return formatted;
  }

  // 6. Number Counter Animation
  function animateScore(element, target, duration = 1200) {
    let start = 0;
    const startTime = performance.now();

    function update(time) {
      const elapsed = time - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // Ease out quad
      const easeProgress = 1 - (1 - progress) * (1 - progress);
      const current = Math.round(easeProgress * target);
      element.textContent = `${current}%`;

      if (progress < 1) {
        requestAnimationFrame(update);
      } else {
        element.textContent = `${target}%`;
      }
    }

    requestAnimationFrame(update);
  }

  // 7. Optimize Resume Action
  optimizeBtn.addEventListener('click', async () => {
    // Authentication Check
    if (!getAuthUser()) {
      showAuthModal('Please sign in or continue as guest to optimize your resume.');
      return;
    }

    const resumeText = resumeTextInput.value.trim();
    const jdText = jdTextInput.value.trim();

    if (!resumeText || !jdText) {
      showToast('⚠️ Please provide both a Resume and a Job Description.');
      return;
    }

    try {
      optimizeBtn.disabled = true;
      loadingIndicator.classList.remove('hidden');

      const response = await fetch('/api/optimize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          resume_text: resumeText,
          jd_text: jdText
        })
      });

      if (!response.ok) {
        const errData = await response.json().catch(() => ({ error: 'Optimization request failed' }));
        throw new Error(errData.error || `HTTP ${response.status}`);
      }

      const data = await response.json();
      currentOptimizedMarkdown = data.optimized_resume;

      // Show Results Section
      resultsSection.classList.remove('hidden');

      // Animate Actual ATS Score vs Updated ATS Score.
      // These are measurements, not targets: report whatever the scorer returned,
      // including a flat or negative movement.
      const actual = Math.round(data.actual_score);
      const updated = Math.round(data.updated_score);
      const boost = updated - actual;

      animateScore(actualScoreNum, actual);
      actualScoreBar.style.width = `${actual}%`;

      animateScore(updatedScoreNum, updated);
      updatedScoreBar.style.width = `${updated}%`;

      if (boost > 0) {
        scoreBoostBadge.textContent = `+${boost}% ATS score`;
        scoreBoostBadge.classList.remove('is-neutral', 'is-negative');
      } else if (boost === 0) {
        scoreBoostBadge.textContent = 'No score change';
        scoreBoostBadge.classList.add('is-neutral');
        scoreBoostBadge.classList.remove('is-negative');
      } else {
        scoreBoostBadge.textContent = `${boost}% ATS score`;
        scoreBoostBadge.classList.add('is-negative');
        scoreBoostBadge.classList.remove('is-neutral');
      }

      // Render Result Resume
      resumePreview.innerHTML = renderATSMarkdown(data.optimized_resume);
      renderAuditDetail(data.optimized_audit);

      // Smooth scroll to results
      resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
      showToast(
        boost > 0
          ? `Resume rewritten. ATS score ${actual}% → ${updated}%.`
          : `Resume rewritten. ATS score is ${updated}%.`
      );
    } catch (err) {
      console.error('Optimization error:', err);
      showToast(`⚠️ Optimization failed: ${err.message}`);
    } finally {
      optimizeBtn.disabled = false;
      loadingIndicator.classList.add('hidden');
    }
  });

  // 8. Result Action Handlers (Copy, Download PDF, Download DOCX)
  copyBtn.addEventListener('click', async () => {
    if (!currentOptimizedMarkdown) return;
    try {
      await navigator.clipboard.writeText(currentOptimizedMarkdown);
      showToast('📋 Optimized resume markdown copied to clipboard!');
    } catch (err) {
      showToast('Failed to copy to clipboard.');
    }
  });

  downloadPdfBtn.addEventListener('click', async () => {
    if (!currentOptimizedMarkdown) return;
    try {
      downloadPdfBtn.disabled = true;
      downloadPdfBtn.textContent = 'Generating PDF...';

      const res = await fetch('/api/export/pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown_text: currentOptimizedMarkdown })
      });

      if (!res.ok) throw new Error('PDF generation failed');

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'ATS_Optimized_Resume.pdf';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      showToast('📥 Downloaded ATS PDF!');
    } catch (err) {
      showToast(`⚠️ PDF download failed: ${err.message}`);
    } finally {
      downloadPdfBtn.disabled = false;
      downloadPdfBtn.innerHTML = '<span>📥 Download ATS PDF</span>';
    }
  });

  downloadDocxBtn.addEventListener('click', async () => {
    if (!currentOptimizedMarkdown) return;
    try {
      downloadDocxBtn.disabled = true;
      downloadDocxBtn.textContent = 'Generating DOCX...';

      const res = await fetch('/api/export/docx', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ markdown_text: currentOptimizedMarkdown })
      });

      if (!res.ok) throw new Error('DOCX generation failed');

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'ATS_Optimized_Resume.docx';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      showToast('📄 Downloaded ATS DOCX!');
    } catch (err) {
      showToast(`⚠️ DOCX download failed: ${err.message}`);
    } finally {
      downloadDocxBtn.disabled = false;
      downloadDocxBtn.innerHTML = '<span>📄 Download ATS DOCX</span>';
    }
  });

  // Initial word counts
  updateWordCounts();
});
