import { Routes, Route, Navigate } from 'react-router-dom'
import FactorChart from './FactorChart'
import SignalChart from './SignalChart'
import NavBar from './NavBar'

function App() {
  return (
    <div style={{ width: '100%', minHeight: '100vh', boxSizing: 'border-box' }}>
      <NavBar />
      <div style={{ padding: '0 24px 24px 24px' }}>
        <Routes>
          <Route path="/factor" element={<FactorChart />} />
          <Route path="/signal" element={<SignalChart />} />
          <Route path="*" element={<Navigate to="/signal" replace />} />
        </Routes>
      </div>
    </div>
  )
}

export default App
