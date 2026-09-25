import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './App.css'
import Monitor from './pages/Monitor'
import OBS from './pages/OBS'
import Viewer from './pages/Viewer'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Monitor />} />
        <Route path="/viewer" element={<Viewer />} />
        <Route path="/obs" element={<OBS />} />
      </Routes>
    </BrowserRouter>
  )
}
