/**
 * Browser Supabase client, used for authentication only (signInWithOtp / verifyOtp /
 * signInAnonymously / session refresh). It talks to Supabase directly rather than
 * through the Node server - the anon key is designed to be public.
 *
 * VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are inlined into the bundle at build time
 * (see the Dockerfile's web build stage), not read at runtime.
 */
import { createClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // eslint-disable-next-line no-console
  console.error(
    'VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are missing from this build - ' +
      'sign-in will not work. Set them as build-time environment variables.',
  );
}

export const supabase = createClient(url, anonKey);
