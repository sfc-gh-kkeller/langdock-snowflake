export function Login() {
  const err = new URLSearchParams(location.search).get('error')
  return (
    <div class="login">
      <div class="login-card">
        <div class="logo big">I</div>
        <h1>Welcome to Icedock</h1>
        <p class="muted">Sign in with your company account</p>
        {err && <div class="error-box">Sign-in failed: {err}</div>}
        <a class="btn ms" href="/auth/login">
          <svg width="18" height="18" viewBox="0 0 21 21"><rect x="1" y="1" width="9" height="9" fill="#f25022" /><rect x="11" y="1" width="9" height="9" fill="#7fba00" /><rect x="1" y="11" width="9" height="9" fill="#00a4ef" /><rect x="11" y="11" width="9" height="9" fill="#ffb900" /></svg>
          Continue with Microsoft
        </a>
        <a class="link small" href="/auth/login?prompt=select_account">Use a different account</a>
        <p class="fine">Single sign-on through Microsoft Entra ID. Your session to Snowflake runs as you, with the role granted by your token.</p>
      </div>
    </div>
  )
}
