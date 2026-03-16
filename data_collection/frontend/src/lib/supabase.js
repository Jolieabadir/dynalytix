/**
 * Supabase client for frontend auth.
 *
 * Handles: login, signup, session management, token refresh.
 * The access token is sent with every API request to the backend.
 */
import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || '';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

export const supabase = supabaseUrl && supabaseAnonKey
    ? createClient(supabaseUrl, supabaseAnonKey)
    : null;

export const isAuthConfigured = () => Boolean(supabase);

/**
 * Get the current session's access token for API requests.
 * Returns null if no session or auth not configured.
 */
export const getAccessToken = async () => {
    if (!supabase) return null;
    const { data: { session } } = await supabase.auth.getSession();
    return session?.access_token || null;
};

/**
 * Sign up a new provider with email and password.
 */
export const signUp = async (email, password) => {
    if (!supabase) throw new Error('Auth not configured');
    const { data, error } = await supabase.auth.signUp({ email, password });
    if (error) throw error;
    return data;
};

/**
 * Sign in with email and password.
 */
export const signIn = async (email, password) => {
    if (!supabase) throw new Error('Auth not configured');
    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    return data;
};

/**
 * Sign out.
 */
export const signOut = async () => {
    if (!supabase) return;
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
};

/**
 * Get the current user.
 */
export const getCurrentUser = async () => {
    if (!supabase) return null;
    const { data: { user } } = await supabase.auth.getUser();
    return user;
};

/**
 * Listen for auth state changes.
 */
export const onAuthStateChange = (callback) => {
    if (!supabase) return { data: { subscription: { unsubscribe: () => {} } } };
    return supabase.auth.onAuthStateChange(callback);
};
