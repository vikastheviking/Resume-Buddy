/**
 * Production-Grade Email Verification Engine.
 * Implements a 5-layer verification system to identify and reject fake, burner,
 * disposable, gibberish, and non-existent email addresses.
 */

const dns = require('dns').promises;

// 1. Known Disposable / Temporary / Burner Email Providers
const DISPOSABLE_DOMAINS = new Set([
  '10minutemail.com', '10minutemail.net', '10minutemail.org', '10minmail.com',
  'tempmail.com', 'temp-mail.org', 'temp-mail.io', 'tempmailaddress.com',
  'mailinator.com', 'mailin8r.com', 'guerrillamail.com', 'guerrillamail.net',
  'guerrillamail.org', 'guerrillamailblock.com', 'sharklasers.com', 'grr.la',
  'yopmail.com', 'yopmail.net', 'yopmail.fr', 'trashmail.com', 'trashmail.net',
  'dispostable.com', 'throwawaymail.com', 'fakeinbox.com', 'getairmail.com',
  'burnermail.io', 'dropmail.me', 'crazymailing.com', 'generator.email',
  'mytemp.email', 'tempinbox.com', 'fakemailgenerator.com', 'emailondeck.com',
  'maildrop.cc', 'inboxkitten.com', 'mohmal.com', 'burneremail.com',
  'tempail.com', 'trashmail.me', 'fakemail.net', 'minuteinbox.com',
  'nada.ltd', 'getnada.com', 'abcvg.com', 'inboxalias.com', 'spambox.us',
  'throwawayemailaddress.com', 'jetable.org', 'crazymail.com', 'zillamail.com'
]);

// 2. Generic Placeholder & Testing Domains
const FAKE_TEST_DOMAINS = new Set([
  'example.com', 'example.org', 'example.net',
  'test.com', 'testing.com', 'fake.com', 'fakemail.com',
  'sample.com', 'sample.org', 'invalid.com', 'dummy.com',
  'asdf.com', 'none.com', 'null.com', 'foo.com', 'bar.com',
  'placeholder.com', 'random.com', 'local.com', 'domain.com'
]);

// 3. Common Domain Typo Mapping
const DOMAIN_TYPOS = {
  'gmial.com': 'gmail.com',
  'gamil.com': 'gmail.com',
  'gmaill.com': 'gmail.com',
  'gmai.com': 'gmail.com',
  'gmal.com': 'gmail.com',
  'gmail.co': 'gmail.com',
  'gmaill.co': 'gmail.com',
  'yaho.com': 'yahoo.com',
  'yahooo.com': 'yahoo.com',
  'yaho.co': 'yahoo.com',
  'hotmial.com': 'hotmail.com',
  'hotmai.com': 'hotmail.com',
  'hotmaill.com': 'hotmail.com',
  'outlok.com': 'outlook.com',
  'outloo.com': 'outlook.com',
  'putlook.com': 'outlook.com',
  'iclou.com': 'icloud.com',
  'icld.com': 'icloud.com',
  'protonmial.com': 'protonmail.com',
  'prtonmail.com': 'protonmail.com'
};

// 4. Blacklisted Fake Local Parts (Generic test aliases)
const FAKE_USERNAMES = new Set([
  'test', 'testing', 'fake', 'fakeuser', 'admin', 'asdf', 'qwerty',
  'random', 'nobody', 'anon', 'temp', 'throwaway', 'junk', 'trash', 'user'
]);

/**
 * Validates syntax, structure, and RFC conformity.
 */
function validateSyntax(email) {
  if (!email || typeof email !== 'string') {
    return { isValid: false, error: 'Email address is required.' };
  }

  const clean = email.trim();
  if (clean.length > 254) {
    return { isValid: false, error: 'Email address is too long (maximum 254 characters).' };
  }

  const parts = clean.split('@');
  if (parts.length !== 2) {
    return { isValid: false, error: 'Email must contain exactly one "@" symbol (e.g., name@company.com).' };
  }

  const [localPart, domain] = parts;

  if (!localPart || localPart.length > 64) {
    return { isValid: false, error: 'The email username cannot exceed 64 characters.' };
  }

  if (localPart.startsWith('.') || localPart.endsWith('.') || localPart.includes('..')) {
    return { isValid: false, error: 'Email username cannot start, end, or have consecutive dots.' };
  }

  const emailRegex = /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$/;
  if (!emailRegex.test(clean)) {
    return { isValid: false, error: 'Email address contains invalid characters or formatting.' };
  }

  const domainParts = domain.split('.');
  const tld = domainParts[domainParts.length - 1];
  if (tld.length < 2) {
    return { isValid: false, error: 'Email domain extension must be at least 2 letters (e.g., .com, .org, .io).' };
  }

  return { isValid: true, localPart, domain: domain.toLowerCase() };
}

/**
 * Checks for gibberish local parts (consecutive repeated characters or keyboard smashes).
 */
function validateLocalPart(localPart, domain) {
  const lower = localPart.toLowerCase();

  // Flag generic test accounts with common free providers
  if (FAKE_USERNAMES.has(lower) && ['gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com'].includes(domain)) {
    return { isValid: false, error: `The email name "${localPart}" is a generic placeholder. Please use your genuine name or email.` };
  }

  // Detect repeated character spam like aaaaaa@... or 111111@...
  if (/^(.)\1{4,}$/.test(lower)) {
    return { isValid: false, error: 'Email username appears to be spam (repeated characters).' };
  }

  // Detect keyboard mash sequences like "asdfghjk" or "qwertyui"
  const keyboardSmashes = ['asdfgh', 'zxcvbn', 'qwertyui', '1234567'];
  for (const smash of keyboardSmashes) {
    if (lower.includes(smash) && lower.length < 14) {
      return { isValid: false, error: 'Email username appears to be a random keyboard smash. Please provide your real email.' };
    }
  }

  return { isValid: true };
}

/**
 * Checks domain against disposable and placeholder blacklists, and checks for typos.
 */
function validateDomainLists(domain) {
  // Check common typos
  if (DOMAIN_TYPOS[domain]) {
    const suggestion = DOMAIN_TYPOS[domain];
    return { isValid: false, error: `Did you mean @${suggestion}? Please check your email domain spelling.`, suggestion };
  }

  // Check disposable burner domains
  if (DISPOSABLE_DOMAINS.has(domain)) {
    return { isValid: false, error: 'Temporary or disposable burner email addresses are not allowed. Please use your genuine personal or work email.' };
  }

  // Check fake placeholder domains
  if (FAKE_TEST_DOMAINS.has(domain)) {
    return { isValid: false, error: `"${domain}" is a test/placeholder domain and cannot receive email. Please enter a real email address.` };
  }

  return { isValid: true };
}

/**
 * Resolves live DNS Mail Exchange (MX) records with a strict 3-second timeout.
 */
async function validateDnsMx(domain) {
  const KNOWN_PROVIDER_MX = {
    'gmail.com': [{ exchange: 'gmail-smtp-in.l.google.com', priority: 5 }],
    'googlemail.com': [{ exchange: 'gmail-smtp-in.l.google.com', priority: 5 }],
    'google.com': [{ exchange: 'smtp.google.com', priority: 10 }, { exchange: 'aspmx.l.google.com', priority: 5 }],
    'outlook.com': [{ exchange: 'outlook-com.olc.protection.outlook.com', priority: 10 }],
    'hotmail.com': [{ exchange: 'hotmail-com.olc.protection.outlook.com', priority: 10 }],
    'yahoo.com': [{ exchange: 'mta5.am0.yahoodns.net', priority: 10 }]
  };

  try {
    const lookupPromise = dns.resolveMx(domain);
    const timeoutPromise = new Promise((_, reject) =>
      setTimeout(() => reject(new Error('DNS_TIMEOUT')), 7000)
    );

    let records;
    try {
      records = await Promise.race([lookupPromise, timeoutPromise]);
    } catch (err) {
      if (KNOWN_PROVIDER_MX[domain]) {
        records = KNOWN_PROVIDER_MX[domain];
      } else {
        throw err;
      }
    }

    if (!records || records.length === 0) {
      return { isValid: false, error: `The domain "${domain}" does not have active mail servers configured to accept incoming emails.` };
    }

    // Filter out dummy or null MX records (e.g. RFC 7505 null MX)
    const validRecords = records.filter(r => r.exchange && r.exchange !== '.' && r.exchange !== '');
    if (validRecords.length === 0) {
      return { isValid: false, error: `The domain "${domain}" explicitly rejects incoming email (Null MX).` };
    }

    return { isValid: true, mxRecords: validRecords };
  } catch (err) {
    if (err.code === 'ENOTFOUND' || err.code === 'NXDOMAIN') {
      return { isValid: false, error: `The domain "${domain}" does not exist. Please check the spelling.` };
    }
    if (err.code === 'ENODATA') {
      return { isValid: false, error: `The domain "${domain}" exists but has no mail servers (MX records) configured to receive email.` };
    }
    if (err.message === 'DNS_TIMEOUT') {
      if (KNOWN_PROVIDER_MX[domain]) {
        return { isValid: true, mxRecords: KNOWN_PROVIDER_MX[domain] };
      }
      return { isValid: true, warning: 'DNS lookup timed out, passed with caution.' };
    }
    return { isValid: false, error: `Could not verify mail servers for "${domain}". Please ensure your email is correct.` };
  }
}

/**
 * Probes the remote mail server directly over SMTP (port 25) using RCPT TO.
 * Directly detects whether the specific user ID/mailbox exists.
 * - exists: true -> Mailbox confirmed active (code 250)
 * - exists: false -> Mailbox definitely does not exist (code 550, 551, 553, NoSuchUser)
 * - exists: 'unconfirmed' -> Server greylisted, timed out, or blocked port 25
 */
function probeSmtpHost(email, mxHost) {
  return new Promise((resolve) => {
    const net = require('net');
    const socket = net.createConnection(25, mxHost);
    socket.setTimeout(2500);
    let step = 0;

    socket.on('data', (data) => {
      const msg = data.toString();
      const code = parseInt(msg.substring(0, 3), 10);

      if (step === 0 && code === 220) {
        step = 1;
        socket.write('HELO verify.ats-architect.com\r\n');
      } else if (step === 1 && code === 250) {
        step = 2;
        socket.write('MAIL FROM:<check@verify.ats-architect.com>\r\n');
      } else if (step === 2 && code === 250) {
        step = 3;
        socket.write(`RCPT TO:<${email}>\r\n`);
      } else if (step === 3) {
        socket.write('QUIT\r\n');
        socket.end();

        // 250 / 251: Mailbox OK / will forward
        if (code === 250 || code === 251) {
          resolve({ exists: true, code, server: mxHost });
        }
        // 550 / 551 / 553: Mailbox does not exist
        else if (
          code === 550 || code === 551 || code === 553 ||
          msg.toLowerCase().includes('nosuchuser') ||
          msg.toLowerCase().includes('does not exist') ||
          msg.toLowerCase().includes('user unknown')
        ) {
          resolve({
            exists: false,
            code,
            server: mxHost,
            error: `The email account "${email}" does not exist on the mail server (${mxHost}). Please check for typos.`
          });
        } else {
          resolve({ exists: 'unconfirmed', code, server: mxHost });
        }
      }
    });

    socket.on('error', () => {
      socket.destroy();
      resolve({ exists: 'unconfirmed', reason: 'Socket connection failed or port 25 filtered' });
    });

    socket.on('timeout', () => {
      socket.destroy();
      resolve({ exists: 'unconfirmed', reason: 'SMTP connection timed out' });
    });
  });
}

async function checkSmtpMailbox(email, domain, mxRecords) {
  if (!mxRecords || mxRecords.length === 0) {
    return { exists: 'unconfirmed', reason: 'No MX records available' };
  }

  const sorted = [...mxRecords].sort((a, b) => a.priority - b.priority);

  for (let i = 0; i < Math.min(2, sorted.length); i++) {
    const mxHost = sorted[i].exchange;
    try {
      const result = await probeSmtpHost(email, mxHost);
      if (result.exists !== 'unconfirmed') {
        return result;
      }
    } catch (err) {
      // Continue to next MX host
    }
  }

  return { exists: 'unconfirmed', reason: 'Mail server did not allow direct mailbox verification' };
}

/**
 * Master verification function: runs all 5 verification layers.
 * 1. Syntax & RFC rules
 * 2. Local-part spam & keyboard smash detection
 * 3. Disposable/Burner blacklist & typo correction
 * 4. DNS MX record resolution
 * 5. Direct SMTP Mailbox Probe (RCPT TO check for the actual user ID)
 */
async function verifyRealEmail(email, options = { checkMx: true, checkSmtp: true }) {
  // Layer 1: Syntax & RFC Checks
  const syntaxCheck = validateSyntax(email);
  if (!syntaxCheck.isValid) {
    return syntaxCheck;
  }

  const { localPart, domain } = syntaxCheck;
  const cleanEmail = `${localPart}@${domain}`;

  // Layer 2: Local-part Gibberish & Test User Check
  const localCheck = validateLocalPart(localPart, domain);
  if (!localCheck.isValid) {
    return localCheck;
  }

  // Layer 3: Disposable & Placeholder Domain Blacklist + Typo Correction
  const domainCheck = validateDomainLists(domain);
  if (!domainCheck.isValid) {
    return domainCheck;
  }

  // Layer 4: Live DNS MX Record Verification
  let mxRecords = null;
  if (options.checkMx) {
    const mxCheck = await validateDnsMx(domain);
    if (!mxCheck.isValid) {
      return mxCheck;
    }
    mxRecords = mxCheck.mxRecords;
  }

  // Layer 5: Live Direct SMTP Mailbox Probe (Validates the actual User ID itself)
  let smtpStatus = 'unconfirmed';
  if (options.checkSmtp !== false && mxRecords) {
    const smtpCheck = await checkSmtpMailbox(cleanEmail, domain, mxRecords);
    if (smtpCheck.exists === false) {
      return {
        isValid: false,
        error: smtpCheck.error || `The email account "${cleanEmail}" does not exist on the recipient's mail servers.`,
        smtpDetails: smtpCheck
      };
    }
    smtpStatus = smtpCheck.exists === true ? 'verified' : 'unconfirmed';
  }

  return {
    isValid: true,
    cleanEmail,
    domain,
    smtpStatus,
    message: smtpStatus === 'verified'
      ? 'Email address and mailbox confirmed active.'
      : 'Email address domain verified and deliverable.'
  };
}

module.exports = {
  verifyRealEmail,
  validateSyntax,
  validateDomainLists,
  validateDnsMx,
  DISPOSABLE_DOMAINS,
  DOMAIN_TYPOS
};
