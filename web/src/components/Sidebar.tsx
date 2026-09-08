import { Database, FileText, Search, Settings } from "lucide-react";
import { NavLink } from "react-router-dom";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">Inkwell</div>
      <NavLink to="/" className={({ isActive }) => (isActive ? "active" : "")} end>
        <Search size={18} />
        Research
      </NavLink>
      <NavLink to="/tasks" className={({ isActive }) => (isActive ? "active" : "")}>
        <FileText size={18} />
        Tasks
      </NavLink>
      <NavLink to="/kb" className={({ isActive }) => (isActive ? "active" : "")}>
        <Database size={18} />
        Knowledge Base
      </NavLink>
      <NavLink to="/settings" className={({ isActive }) => (isActive ? "active" : "")}>
        <Settings size={18} />
        Settings
      </NavLink>
    </aside>
  );
}
