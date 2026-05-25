import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import SummaryChart from '../components/Reporting/SummaryChart';
import SkillChart from '../components/Reporting/SkillChart';

interface ProjectMetrics {
  successRate: number;
  failureRate: number;
  skillImprovements: { date: string; score: number }[];
}

const ReportingPage = () => {
  const { projectId } = useParams();
  const [metrics, setMetrics] = useState<ProjectMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchMetrics = async () => {
      if (!projectId) {
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        const response = await fetch(`/api/projects/${projectId}/metrics`);
        if (!response.ok) {
          throw new Error(`Failed to fetch metrics: ${response.status}`);
        }
        const data: ProjectMetrics = await response.json();
        setMetrics(data);
      } catch (err) {
        console.error('Failed to fetch metrics:', err);
        setError('Failed to load metrics');
      } finally {
        setLoading(false);
      }
    };

    fetchMetrics();
  }, [projectId]);

  if (loading) {
    return <div className="reporting-page">Loading metrics...</div>;
  }

  if (error) {
    return <div className="reporting-page">Error: {error}</div>;
  }

  if (!metrics) {
    return <div className="reporting-page">No metrics available</div>;
  }

  return (
    <div className="reporting-page">
      <h1>Project Reporting</h1>
      <div className="reporting-content">
        <SummaryChart successRate={metrics.successRate} failureRate={metrics.failureRate} />
        <SkillChart data={metrics.skillImprovements} />
      </div>
    </div>
  );
};

export default ReportingPage;
