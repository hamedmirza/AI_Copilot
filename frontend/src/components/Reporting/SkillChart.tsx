import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

interface SkillChartProps {
  data: { date: string; score: number }[];
}

const SkillChart = ({ data }: SkillChartProps) => {
  return (
    <div className="skill-chart">
      <h2>Skill Improvement Over Time</h2>
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={data}>
          <XAxis dataKey="date" />
          <YAxis />
          <Tooltip />
          <Line 
            type="monotone" 
            dataKey="score" 
            stroke="#2196F3" 
            activeDot={{ r: 8 }} 
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
};

export default SkillChart;
