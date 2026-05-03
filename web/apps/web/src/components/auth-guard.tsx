import { useEffect } from 'react'
import { Outlet, Navigate } from 'react-router'
import { supabase } from '@/lib/supabase'
import { useAuthStore } from '@/stores/auth'

export function AuthGuard() {
  const { user, loading, setAuth, setLoading } = useAuthStore()

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setAuth(session?.user ?? null, session)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        setAuth(session?.user ?? null, session)
      },
    )

    return () => subscription.unsubscribe()
  }, [setAuth, setLoading])

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="animate-spin h-8 w-8 border-2 border-primary border-t-transparent rounded-full" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}
