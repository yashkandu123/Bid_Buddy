import { FileCheck2, FileText, Gauge, Layers3, UploadCloud } from "lucide-react";
import { NavLink, Outlet } from "react-router-dom";

const steps = [
  { to: "/", label: "Upload", eyebrow: "01", icon: UploadCloud },
  { to: "/processing", label: "Processing", eyebrow: "02", icon: Gauge },
  { to: "/review", label: "Estimate & Review", eyebrow: "03", icon: Layers3 },
  { to: "/bid", label: "Bid Optimization", eyebrow: "04", icon: FileText },
  { to: "/final", label: "Final Offer", eyebrow: "05", icon: FileCheck2 }
];

export function AppShell() {
  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">Tender pricing assistant</p>
          <h1>From tender to first estimate</h1>
        </div>
        <div className="brand-mark" aria-label="Equans-inspired visual mark">
          <span className="brand-leaf" />
          <span>EQUANS</span>
        </div>
      </header>

      <nav className="workflow" aria-label="Workflow">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <NavLink
              key={step.to}
              to={step.to}
              end={step.to === "/"}
              className={({ isActive }) => `workflow-step${isActive ? " active" : ""}`}
            >
              <span className="step-number">{step.eyebrow}</span>
              <Icon size={22} strokeWidth={1.7} aria-hidden="true" />
              <span>{step.label}</span>
            </NavLink>
          );
        })}
      </nav>

      <main className="page-frame">
        <Outlet />
      </main>
    </div>
  );
}
