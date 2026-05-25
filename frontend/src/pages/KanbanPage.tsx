import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import { DndProvider } from 'react-dnd';
import { HTML5Backend } from 'react-dnd-html5-backend';
import Column from '../components/Kanban/Column';

interface Task {
  id: string;
  title: string;
  description: string;
  status: 'todo' | 'in-progress' | 'review' | 'done';
}

interface Project {
  id: string;
  name: string;
}

const KanbanPage = () => {
  const { projectId } = useParams();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(projectId || null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchProjects = async () => {
      try {
        const response = await fetch('/api/projects');
        const data = await response.json();
        setProjects(data);
        if (!projectId && data.length > 0) {
          setSelectedProjectId(data[0].id);
        }
      } catch (error) {
        console.error('Failed to fetch projects:', error);
      }
    };

    fetchProjects();
  }, [projectId]);

  useEffect(() => {
    const fetchTasks = async () => {
      if (!selectedProjectId) {
        setLoading(false);
        return;
      }
      try {
        setLoading(true);
        const response = await fetch(`/api/projects/${selectedProjectId}/tasks`);
        const data = await response.json();
        setTasks(data);
      } catch (error) {
        console.error('Failed to fetch tasks:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchTasks();
  }, [selectedProjectId]);

  const moveTask = async (taskId: string, newStatus: Task['status']) => {
    try {
      const response = await fetch(`/api/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });

      if (!response.ok) {
        throw new Error(`Failed to update task: ${response.status}`);
      }

      setTasks((prev) =>
        prev.map((task) => (task.id === taskId ? { ...task, status: newStatus } : task)),
      );
    } catch (error) {
      console.error('Failed to move task:', error);
    }
  };

  const columns: { id: Task['status']; title: string; status: Task['status'] }[] = [
    { id: 'todo', title: 'To Do', status: 'todo' },
    { id: 'in-progress', title: 'In Progress', status: 'in-progress' },
    { id: 'review', title: 'Review', status: 'review' },
    { id: 'done', title: 'Done', status: 'done' },
  ];

  if (loading && selectedProjectId) {
    return <div className="kanban-page">Loading board...</div>;
  }

  return (
    <DndProvider backend={HTML5Backend}>
      <div className="kanban-page">
        <h1>Kanban Board</h1>

        {projects.length > 0 && (
          <div className="project-selector">
            <label htmlFor="project-select">Select Project: </label>
            <select
              id="project-select"
              value={selectedProjectId || ''}
              onChange={(e) => setSelectedProjectId(e.target.value)}
            >
              <option value="">-- Select a Project --</option>
              {projects.map((project) => (
                <option key={project.id} value={project.id}>
                  {project.name}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="kanban-board">
          {columns.map((column) => (
            <Column
              key={column.id}
              title={column.title}
              status={column.status}
              tasks={tasks.filter((task) => task.status === column.status)}
              onDrop={moveTask}
            />
          ))}
        </div>
      </div>
    </DndProvider>
  );
};

export default KanbanPage;
