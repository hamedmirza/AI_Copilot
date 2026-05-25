import React from 'react';
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface SummaryChartProps {
  successRate: number;
  failureRate: number;
}

const SummaryChart = ({ successRate, failureRate }: SummaryChartProps) => {
  const data = [
    { name: 'Success', value: successRate },
    { name: 'Failure', value: failureRate },
  ];

  return (
    <div className="summary-chart">
      <h2>Success/Failure Rates</h2>
      <ResponsiveContainer width="100%" height={300}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" />
          <XAxis dataKey="name" />
          <YAxis />
          <Tooltip />
          <Bar dataKey="value" fill="#4CAF50" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default SummaryChart;
