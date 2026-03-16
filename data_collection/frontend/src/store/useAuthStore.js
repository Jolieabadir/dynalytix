/**
 * Auth state management using Zustand.
 *
 * Tracks: current user, session, provider profile, loading state.
 * Listens for Supabase auth state changes and auto-updates.
 */
import { create } from 'zustand';
import { supabase, isAuthConfigured, signIn, signOut, signUp, getCurrentUser } from '../lib/supabase';
import api from '../api/client';

const useAuthStore = create((set, get) => ({
    // State
    user: null,           // Supabase auth user
    provider: null,       // Dynalytix provider profile
    session: null,
    loading: true,
    error: null,
    isAuthenticated: false,
    authConfigured: isAuthConfigured(),

    // Actions
    initialize: async () => {
        if (!isAuthConfigured()) {
            set({ loading: false, authConfigured: false });
            return;
        }

        try {
            const user = await getCurrentUser();
            if (user) {
                // Fetch provider profile from backend
                try {
                    const response = await api.get('/api/auth/me');
                    set({
                        user,
                        provider: response.data,
                        isAuthenticated: true,
                        loading: false,
                    });
                } catch (e) {
                    // User authenticated but no provider profile yet
                    set({ user, isAuthenticated: true, loading: false });
                }
            } else {
                set({ loading: false });
            }
        } catch (e) {
            set({ error: e.message, loading: false });
        }
    },

    login: async (email, password) => {
        set({ loading: true, error: null });
        try {
            const data = await signIn(email, password);
            const response = await api.get('/api/auth/me');
            set({
                user: data.user,
                session: data.session,
                provider: response.data,
                isAuthenticated: true,
                loading: false,
            });
            return data;
        } catch (e) {
            set({ error: e.message, loading: false });
            throw e;
        }
    },

    signup: async (email, password) => {
        set({ loading: true, error: null });
        try {
            const data = await signUp(email, password);
            set({ user: data.user, session: data.session, loading: false });
            return data;
        } catch (e) {
            set({ error: e.message, loading: false });
            throw e;
        }
    },

    logout: async () => {
        try {
            await signOut();
        } catch (e) {
            console.error('Logout error:', e);
        }
        set({
            user: null,
            provider: null,
            session: null,
            isAuthenticated: false,
            error: null,
        });
    },

    clearError: () => set({ error: null }),
}));

// Listen for auth state changes
if (isAuthConfigured() && supabase) {
    supabase.auth.onAuthStateChange((event, session) => {
        if (event === 'SIGNED_OUT') {
            useAuthStore.setState({
                user: null,
                provider: null,
                session: null,
                isAuthenticated: false,
            });
        }
    });
}

export default useAuthStore;
