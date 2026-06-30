import { Database, FileText, Search } from "lucide-react";
import { NavLink } from "react-router-dom";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">Research Agent</div>
      <NavLink to="/" className={({ isActive }) => (isActive ? "active" : "")}>
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
    </aside>
  );
}
