"""
Supabase client initialization.

Provides two clients:
- supabase_client: Uses anon key, respects RLS (for user-facing requests)
- supabase_admin: Uses service_role key, bypasses RLS (for backend admin ops)

If SUPABASE_URL is not set, both clients are None and the app falls back to SQLite.
"""
import os
from typing import Optional

try:
    from supabase import create_client, Client
    HAS_SUPABASE = True
except ImportError:
    HAS_SUPABASE = False
    Client = None


def get_supabase_client() -> Optional[Client]:
    """Get the anon Supabase client (respects RLS)."""
    if not HAS_SUPABASE:
        return None
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


def get_supabase_admin() -> Optional[Client]:
    """Get the service role Supabase client (bypasses RLS)."""
    if not HAS_SUPABASE:
        return None
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        return None
    return create_client(url, key)


def is_supabase_configured() -> bool:
    """Check if Supabase environment variables are set."""
    return bool(
        os.environ.get("SUPABASE_URL")
        and os.environ.get("SUPABASE_ANON_KEY")
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )


# Singleton instances (lazy — only created when first accessed)
_client: Optional[Client] = None
_admin: Optional[Client] = None


def get_client() -> Optional[Client]:
    global _client
    if _client is None and is_supabase_configured():
        _client = get_supabase_client()
    return _client


def get_admin() -> Optional[Client]:
    global _admin
    if _admin is None and is_supabase_configured():
        _admin = get_supabase_admin()
    return _admin
