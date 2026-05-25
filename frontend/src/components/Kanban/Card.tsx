import React from 'react';
import { useDrag } from 'react-dnd';

interface CardProps {
  task: {
    id: string;
    title: string;
    description: string;
  };
}

const Card = ({ task }: CardProps) => {
  const [{ isDragging }, drag] = useDrag(() => ({
    type: 'card',
    item: { id: task.id },
    collect: (monitor) => ({ isDragging: !!monitor.isDragging() }),
  }));

  return (
    <div
      ref={drag as unknown as React.Ref<HTMLDivElement>}
      className={`kanban-card ${isDragging ? 'dragging' : ''}`}
    >
      <h3>{task.title}</h3>
      <p>{task.description}</p>
    </div>
  );
};

export default Card;
