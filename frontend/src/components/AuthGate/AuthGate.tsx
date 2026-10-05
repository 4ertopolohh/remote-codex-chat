import { useEffect, useState, type FormEvent } from 'react'
import { App } from '../App/App'
import { ActionButton } from '../ActionButton/ActionButton'
import styles from './AuthGate.module.scss'

type AuthState = { status: 'checking' | 'signed-out' | 'signed-in'; csrf: string | null; error: string | null }

export function AuthGate() {
  const [auth, setAuth] = useState<AuthState>({ status: 'checking', csrf: null, error: null })
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    fetch('/auth/session', { credentials: 'same-origin', cache: 'no-store', signal: controller.signal })
      .then(response => response.ok ? response.json() as Promise<{ csrf: string }> : null)
      .then(session => setAuth({ status: session ? 'signed-in' : 'signed-out', csrf: session?.csrf ?? null, error: null }))
      .catch(() => { if (!controller.signal.aborted) setAuth({ status: 'signed-out', csrf: null, error: 'Не удаётся связаться с сервером. Проверьте подключение и повторите попытку.' }) })
    return () => controller.abort()
  }, [])

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy || !password) return
    setBusy(true)
    try {
      const response = await fetch('/auth/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) })
      if (!response.ok) {
        setAuth({ status: 'signed-out', csrf: null, error: response.status === 401 ? 'Неверный пароль. Попробуйте ещё раз.' : 'Не удалось войти. Попробуйте ещё раз.' })
        return
      }
      const session = await response.json() as { csrf: string }
      setPassword('')
      setAuth({ status: 'signed-in', csrf: session.csrf, error: null })
    } catch {
      setAuth({ status: 'signed-out', csrf: null, error: 'Не удаётся связаться с сервером. Проверьте подключение и повторите попытку.' })
    } finally {
      setBusy(false)
    }
  }

  async function logout() {
    if (!auth.csrf || busy) return
    setBusy(true)
    try {
      const response = await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin', headers: { 'X-CSRF-Token': auth.csrf } })
      if (!response.ok) throw new Error('Logout failed')
      setAuth({ status: 'signed-out', csrf: null, error: null })
    } catch {
      setAuth(current => ({ ...current, error: 'Не удалось выйти. Попробуйте ещё раз.' }))
    } finally {
      setBusy(false)
    }
  }

  if (auth.status === 'signed-in') return <App onLogout={logout} onAuthRequired={() => setAuth({ status: 'signed-out', csrf: null, error: 'Сессия завершилась. Войдите снова.' })} authError={auth.error} />

  return <main className={styles.page}>
    <section className={styles.card} aria-labelledby="auth-title">
      <span className={styles.mark} aria-hidden="true">✳</span>
      <span className={styles.eyebrow}>УДАЛЁННОЕ РАБОЧЕЕ ПРОСТРАНСТВО</span>
      <h1 id="auth-title">Codex</h1>
      {auth.status === 'checking' ? <p role="status">Проверяем сессию…</p> : <>
        <p>Войдите в рабочее пространство</p>
        <form onSubmit={login}>
          <label htmlFor="auth-password">Пароль</label>
          <input id="auth-password" type="password" autoComplete="current-password" autoFocus value={password} onChange={event => setPassword(event.target.value)} disabled={busy} required />
          {auth.error && <p className={styles.error} role="alert">{auth.error}</p>}
          <ActionButton className={styles.submit} tone="secondary" type="submit" disabled={busy}>{busy ? 'Входим…' : 'Войти'}</ActionButton>
        </form>
      </>}
    </section>
  </main>
}
