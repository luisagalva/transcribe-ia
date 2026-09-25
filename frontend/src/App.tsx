import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './App.css'
import Dashboard from './pages/Dashboard'
import OBS from './pages/OBS'
import Transcribe from './pages/Transcribe'
import Viewer from './pages/Viewer'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Viewer />} />
        <Route path="/transcribe" element={<Transcribe />} />
        <Route path="/obs" element={<OBS />} />
        <Route path="/dashboard" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  )
}
