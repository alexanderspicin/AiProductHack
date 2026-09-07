import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { TextApp } from './TextApp'
import './text.css'

createRoot(document.getElementById('root')!).render(<StrictMode><TextApp /></StrictMode>)
