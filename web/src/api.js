/**
 * Thin wrapper over the backend API.
 *
 * Every call funnels through `request` so error handling is uniform: the server returns
 * `{ error }` on failure, and anything else (a proxy page, a network drop) becomes a
 * readable message rather than a JSON parse exception surfacing in the UI.
 */

const TOKEN_STORAGE_KEY = 'resume_buddy_token';

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* session-only auth is an acceptable fallback */
  }
}

async function request(path, { method = 'GET', body, isForm = false, auth = false } = {}) {
  let response;
  try {
    const headers = isForm ? {} : { 'Content-Type': 'application/json' };
    if (auth) {
      const token = getToken();
      if (token) headers.Authorization = `Bearer ${token}`;
    }
    response = await fetch(path, {
      method,
      headers,
      body: isForm ? body : body && JSON.stringify(body),
    });
  } catch {
    throw new Error('Could not reach the server. Check your connection and try again.');
  }

  const text = await response.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    throw new Error(`Unexpected response from the server (HTTP ${response.status}).`);
  }

  if (!response.ok) {
    const error = new Error(data.error || `Request failed (HTTP ${response.status}).`);
    error.payload = data;
    throw error;
  }
  return data;
}

export const getSample = () => request('/api/sample');

export const extractFile = (file) => {
  const form = new FormData();
  form.append('file', file);
  return request('/api/upload', { method: 'POST', body: form, isForm: true });
};

export const optimize = (resumeText, jdText) =>
  request('/api/optimize', {
    method: 'POST',
    body: { resume_text: resumeText, jd_text: jdText },
    auth: true,
  });

/** Baseline match score only — no rewrite, no sign-in required. */
export const scoreResume = (resumeText, jdText) =>
  request('/api/score', {
    method: 'POST',
    body: { resume_text: resumeText, jd_text: jdText },
  });

export const validateEmail = (email) =>
  request('/api/auth/validate-email', { method: 'POST', body: { email } });

export const sendOtp = (email, mode) =>
  request('/api/auth/send-otp', { method: 'POST', body: { email, mode } });

export const verifyOtp = (email, otp) =>
  request('/api/auth/verify-otp', { method: 'POST', body: { email, otp } });

export const guestSession = () => request('/api/auth/guest', { method: 'POST' });

/**
 * Ask the server to render the resume and hand the file to the browser.
 *
 * Exports come back as binary, so this one bypasses `request` and drives an object-URL
 * download directly.
 */
export async function downloadExport(format, markdownText) {
  const headers = { 'Content-Type': 'application/json' };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`/api/export/${format}`, {
    method: 'POST',
    headers,
    body: JSON.stringify({ markdown_text: markdownText }),
  });

  if (!response.ok) {
    let message = `Could not generate the ${format.toUpperCase()} file.`;
    try {
      const data = await response.json();
      if (data?.error) message = data.error;
    } catch {
      /* non-JSON error body: keep the generic message */
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = `ATS_Optimized_Resume.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
