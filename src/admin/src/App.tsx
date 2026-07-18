import { useState, useEffect } from 'react'
import { getAdminStatus, verifyToken } from './api'
import SetupPage from './SetupPage'
import LoginPage from './LoginPage'
import Dashboard from './Dashboard'

type Phase = 'loading' | 'setup' | 'login' | 'dashboard'

function App() {
  const [phase, setPhase] = useState<Phase>('loading')

  useEffect(() => {
    checkState()
  }, [])

  async function checkState() {
    try {
      const { setup_complete } = await getAdminStatus()
      if (!setup_complete) {
        setPhase('setup')
        return
      }

      const token = localStorage.getItem('hrdd_admin_token')
      if (token) {
        try {
          await verifyToken()
          setPhase('dashboard')
          return
        } catch {
          localStorage.removeItem('hrdd_admin_token')
        }
      }

      setPhase('login')
    } catch {
      setPhase('login')
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('hrdd_admin_token')
    setPhase('login')
  }

  switch (phase) {
    case 'loading':
      return (
        <div className="min-h-screen bg-gray-50 flex items-center justify-center">
          <p className="text-gray-400">Loading...</p>
        </div>
      )
    case 'setup':
      return <SetupPage onComplete={() => setPhase('login')} />
    case 'login':
      return <LoginPage onLogin={() => setPhase('dashboard')} />
    case 'dashboard':
      return <Dashboard onLogout={handleLogout} />
  }
}

export default App
