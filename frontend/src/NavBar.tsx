import { useLocation, useNavigate } from 'react-router-dom'

const tabs = [
  { path: '/signal', label: '信号标记' },
  { path: '/factor', label: '因子图表' },
]

export default function NavBar() {
  const loc = useLocation()
  const nav = useNavigate()

  return (
    <div style={{
      display: 'flex', gap: 8, padding: '12px 24px',
      borderBottom: '1px solid #e8e8e8', background: '#fafafa',
    }}>
      {tabs.map(t => (
        <button key={t.path} onClick={() => nav(t.path)}
          style={{
            padding: '8px 20px', borderRadius: 6, border: 'none',
            cursor: 'pointer', fontSize: 14, fontWeight: 600,
            background: loc.pathname === t.path ? '#165DFF' : '#e8e8e8',
            color: loc.pathname === t.path ? '#fff' : '#333',
          }}>
          {t.label}
        </button>
      ))}
    </div>
  )
}
