import { useState } from 'react'
import FrontendsTab from './FrontendsTab'
import PromptsTab from './PromptsTab'
import LLMTab from './LLMTab'
import GlossaryTab from './GlossaryTab'
import SettingsTab from './SettingsTab'
import RegisteredUsersTab from './RegisteredUsersTab'
import QueueTab from './QueueTab'

interface Props {
  onLogout: () => void
}

const TABS = ['Frontends', 'Prompts', 'LLM', 'Glossary', 'Settings', 'Registered Users', 'Queue'] as const
type Tab = typeof TABS[number]

export default function Dashboard({ onLogout }: Props) {
  const [activeTab, setActiveTab] = useState<Tab>('Frontends')

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-uni-dark text-white shadow-md">
        <div className="px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={`${import.meta.env.BASE_URL}uni-logo.png`} alt="UNI" className="h-8 bg-white/95 rounded px-1" />
            <h1 className="text-xl font-semibold">LAIUNI Translator — Admin Panel</h1>
          </div>
          <button
            onClick={onLogout}
            className="text-sm bg-white/10 hover:bg-white/20 rounded-lg px-3 py-1.5 transition-colors"
          >
            Logout
          </button>
        </div>
        <nav className="px-6 flex gap-1">
          {TABS.map(tab => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-medium transition-colors border-b-2 ${
                activeTab === tab
                  ? 'border-uni-blue text-white'
                  : 'border-transparent text-white/60 hover:text-white/80'
              }`}
            >
              {tab}
            </button>
          ))}
        </nav>
      </header>

      <main className="max-w-6xl mx-auto mt-6 p-6">
        {activeTab === 'Frontends' && <FrontendsTab />}
        {activeTab === 'Prompts' && <PromptsTab />}
        {activeTab === 'LLM' && <LLMTab />}
        {activeTab === 'Glossary' && <GlossaryTab />}
        {activeTab === 'Settings' && <SettingsTab />}
        {activeTab === 'Registered Users' && <RegisteredUsersTab />}
        {activeTab === 'Queue' && <QueueTab />}
      </main>
    </div>
  )
}
