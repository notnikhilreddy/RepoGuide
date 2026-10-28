import React from 'react';
import { createRoot } from 'react-dom/client';
import '@xyflow/react/dist/style.css';
import './styles.css';
import App from './App';
import {AuthGate} from './components/AuthGate';

createRoot(document.getElementById('root')!).render(<React.StrictMode><AuthGate><App /></AuthGate></React.StrictMode>);
