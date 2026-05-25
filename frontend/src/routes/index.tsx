import React from 'react';
import { Routes, Route } from 'react-router-dom';
import KanbanPage from '../pages/KanbanPage';
import ReportingPage from '../pages/ReportingPage';

const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<KanbanPage />} />
      <Route path="/projects/:projectId/kanban" element={<KanbanPage />} />
      <Route path="/projects/:projectId/reporting" element={<ReportingPage />} />
    </Routes>
  );
};

export default AppRoutes;