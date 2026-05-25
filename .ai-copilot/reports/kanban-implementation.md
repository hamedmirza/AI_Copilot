# Kanban Implementation Summary

1. **Kanban Board**: Dynamically renders columns based on project configuration with drag-and-drop support using react-dnd.
2. **Backend Integration**: Fetches tasks from `/api/projects/:id/tasks` and updates task status via PATCH requests to `/api/tasks/:id`.
3. **Project Selection**: Includes a dropdown selector for switching between projects, reloading the board with corresponding tasks.
4. **Reporting Page**: Displays success/failure rates and skill improvements using Recharts components from `/api/projects/:id/metrics`.
5. **Minimalist Design**: Clean UI with muted colors, clear borders, and readable fonts to avoid visual clutter.