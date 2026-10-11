import { FileCheck2, FileText, Layers3, UploadCloud } from "lucide-react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { ReviewNavigationContext } from "../app/ReviewNavigationContext";
import equansLogo from "../assets/equans-reference.jpg";

const steps = [
  { to: "/", label: "Upload", eyebrow: "01", icon: UploadCloud },
  { to: "/review", label: "Estimate & Review", eyebrow: "02", icon: Layers3 },
  { to: "/bid", label: "Bid Optimization", eyebrow: "03", icon: FileText },
  { to: "/final", label: "Final Offer", eyebrow: "04", icon: FileCheck2 }
];

export function AppShell() {
  const [pending, setPending] = useState(false);
  const { pathname } = useLocation();
  const routeJobId = pathname.split("/")[2];
  const jobId = routeJobId ?? window.localStorage.getItem("lastTenderJobId");
  useEffect(() => { if (routeJobId) window.localStorage.setItem("lastTenderJobId", routeJobId); }, [routeJobId]);
  return (
    <ReviewNavigationContext.Provider value={{ pending, setPending }}>
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">BID BUDDY</p>
          <h1>From tender to contender</h1>
        </div>
        <div className="brand-mark">
          <img src={equansLogo} alt="Equans Switzerland" className="equans-logo" />
        </div>
      </header>

      <nav className="workflow" aria-label="Workflow">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <NavLink
              key={step.to}
              to={step.to === "/" ? (jobId ? `/processing/${jobId}` : "/") : (!jobId ? step.to : `${step.to}/${jobId}`)}
              end={step.to === "/"}
              onClick={(event) => { if (pending) event.preventDefault(); }}
              aria-disabled={pending}
              className={() => `workflow-step${(step.to === "/" ? pathname === "/" || pathname.startsWith("/processing") : pathname.startsWith(step.to)) ? " active" : ""}`}
            >
              <span className="step-number">{step.eyebrow}</span>
              <Icon size={22} strokeWidth={1.7} aria-hidden="true" />
              <span>{step.label}</span>
            </NavLink>
          );
        })}
      </nav>
      {pending ? <p className="inline-message" role="status">Save your estimator changes before changing stages.</p> : null}

      <main className="page-frame">
        <Outlet />
      </main>
    </div>
    </ReviewNavigationContext.Provider>
  );
}
