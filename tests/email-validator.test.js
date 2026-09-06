/**
 * Unit Test Suite for server/email-validator.js
 */

const { verifyRealEmail } = require('../server/email-validator');

async function runTests() {
  console.log('=== Running Email Verification Tests ===\n');

  const testCases = [
    // 1. Valid Real Emails
    { email: 'satya.developer@gmail.com', shouldPass: true, desc: 'Real Gmail address' },
    { email: 'recruiter.contact@outlook.com', shouldPass: true, desc: 'Real Outlook address' },
    { email: 'engineering@yahoo.com', shouldPass: true, desc: 'Real Yahoo address' },

    // 2. Fake / Non-Existent Domains (Caught by DNS MX resolution)
    { email: 'person@nonexistentdomain99882233.org', shouldPass: false, desc: 'Non-existent fake domain (DNS MX fails)' },
    { email: 'john@fakemailboxrandom1239847129847.com', shouldPass: false, desc: 'Random non-existent domain' },

    // 3. Disposable / Burner Emails (Caught by Disposable Blacklist)
    { email: 'throwaway@mailinator.com', shouldPass: false, desc: 'Mailinator burner email' },
    { email: 'tester@tempmail.com', shouldPass: false, desc: 'Tempmail burner email' },
    { email: 'user@10minutemail.com', shouldPass: false, desc: '10MinuteMail burner email' },
    { email: 'random@yopmail.com', shouldPass: false, desc: 'Yopmail burner email' },

    // 4. Test / Placeholder Domains (Caught by Fake Domain Blacklist)
    { email: 'someone@example.com', shouldPass: false, desc: 'example.com placeholder' },
    { email: 'someone@test.com', shouldPass: false, desc: 'test.com placeholder' },

    // 5. Common Domain Typos (Caught by Typo Detector)
    { email: 'user@gmial.com', shouldPass: false, desc: 'gmial.com typo' },
    { email: 'user@outlok.com', shouldPass: false, desc: 'outlok.com typo' },

    // 6. Keyboard Smash / Repeated Spam Local Part
    { email: 'aaaaaaa@gmail.com', shouldPass: false, desc: 'Repeated spam characters' },
    { email: 'asdfghjkl@gmail.com', shouldPass: false, desc: 'Keyboard smash local part' },

    // 7. Live SMTP Mailbox Check (Validating the User ID itself!)
    { email: 'thisuserdefinitelydoesnotexist9988771122@gmail.com', shouldPass: false, desc: 'Fake user ID on real domain (SMTP RCPT TO rejects with 550)' },
    { email: 'press@google.com', shouldPass: true, desc: 'Real user ID on real domain (SMTP RCPT TO confirms with 250)' },

    // 8. Malformed Syntax
    { email: 'invalid-email-no-at', shouldPass: false, desc: 'No @ symbol' },
    { email: 'user..name@gmail.com', shouldPass: false, desc: 'Consecutive dots' },
    { email: '@nodomain.com', shouldPass: false, desc: 'Missing username' }
  ];

  let passed = 0;
  let failed = 0;

  for (const tc of testCases) {
    const result = await verifyRealEmail(tc.email);
    const success = result.isValid === tc.shouldPass;

    if (success) {
      passed++;
      console.log(`[PASS] ${tc.desc}: "${tc.email}" -> ${result.isValid ? 'ACCEPTED' : 'REJECTED' + (result.error ? ` (${result.error})` : '')}`);
    } else {
      failed++;
      console.error(`[FAIL] ${tc.desc}: "${tc.email}" Expected ${tc.shouldPass} but got ${result.isValid}. Error: ${result.error}`);
    }
  }

  console.log(`\n========================================`);
  console.log(`Results: ${passed} Passed, ${failed} Failed out of ${testCases.length} tests.`);
  console.log(`========================================\n`);

  if (failed > 0) {
    process.exit(1);
  }
}

runTests().catch(err => {
  console.error('Test execution error:', err);
  process.exit(1);
});
