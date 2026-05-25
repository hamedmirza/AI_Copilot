import React from 'react';
import { useDrop } from 'react-dnd';
import Card from './Card';

interface ColumnProps {
  title: string;
  status: 'todo' | 'in-progress' | 'review' | 'done';
  tasks: Array<{ id: string; title: string; description: string }>;
  onDrop: (taskId: string, newStatus: 'todo' | 'in-progress' | 'review' | 'done') => void;
}

const Column = ({ title, status, tasks, onDrop }: ColumnProps) => {
  const [{ isOver }, drop] = useDrop(() => ({
    accept: 'card',
    drop: (item: { id: string }) => onDrop(item.id, status),
    collect: (monitor) => ({ isOver: !!monitor.isOver() }),
  }));

  return (
    <div
      className={`kanban-column${isOver ? ' over' : ''}`}
      ref={drop as unknown as React.Ref<HTMLDivElement>}
    >
      <h2>{title}</h2>
      <div className="kanban-cards">
        {tasks.map((task) => (
          <Card key={task.id} task={task} />
        ))}
      </div>
    </div>
  );
};

export default Column;
