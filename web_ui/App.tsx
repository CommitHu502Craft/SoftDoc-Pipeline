import React, { createContext, useState, useEffect } from 'react';
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom';
import { Layout } from './components/Layout';
import { ProjectsPage } from './pages/Projects';
import { ProjectDetailPage } from './pages/ProjectDetail';
import { SubmitPage } from './pages/Submit';
import { SignaturesPage } from './pages/Signatures';
import { SettingsPage } from './pages/Settings';
import { AccountsPage } from './pages/AccountsPage';
import { SubmitQueuePage } from './pages/SubmitQueuePage';
import { SignaturePage } from './pages/SignaturePage';
import { LlmUsagePage } from './pages/LlmUsage';

export const ThemeContext = createContext({
  isDark: true,
  toggleTheme: () => {},
});

const App: React.FC = () => {
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    if (isDark) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDark]);

  const toggleTheme = () => setIsDark(!isDark);

  return (
    <ThemeContext.Provider value={{ isDark, toggleTheme }}>
      <HashRouter>
        <Routes>
          <Route path="/" element={<Layout />}>
            <Route index element={<ProjectsPage />} />
            <Route path="projects" element={<Navigate to="/" replace />} />
            <Route path="projects/:id" element={<ProjectDetailPage />} />
            <Route path="submit" element={<SubmitPage />} />
            <Route path="signatures" element={<SignaturesPage />} />
            <Route path="accounts" element={<AccountsPage />} />
            <Route path="submit-queue" element={<SubmitQueuePage />} />
            <Route path="signature-process" element={<SignaturePage />} />
            <Route path="llm-usage" element={<LlmUsagePage />} />
            <Route path="settings" element={<SettingsPage />} />
          </Route>
        </Routes>
      </HashRouter>
    </ThemeContext.Provider>
  );
};

export default App;
