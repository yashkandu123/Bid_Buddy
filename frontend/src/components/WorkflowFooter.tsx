import { ArrowLeft, ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";
import { useReviewNavigation } from "../app/ReviewNavigationContext";

export function WorkflowFooter({ previous, next, disabledReason }: {
  previous?: { to: string; label: string };
  next?: { to: string; label: string };
  disabledReason?: string;
}) {
  const { pending } = useReviewNavigation();
  disabledReason = pending ? "Save your estimator changes to continue." : disabledReason;
  return <footer className="workflow-footer">
    {previous ? <Link className="secondary-button" to={previous.to} aria-disabled={pending} onClick={event => { if (pending) event.preventDefault(); }}><ArrowLeft size={18} /> {previous.label}</Link> : <span />}
    <div>
      {disabledReason ? <p className="inline-message">{disabledReason}</p> : null}
      {next && !disabledReason ? <Link className="primary-button" to={next.to}>Proceed to {next.label}<ArrowRight size={18} /></Link> : null}
      {next && disabledReason ? <button className="primary-button" disabled>Proceed to {next.label}<ArrowRight size={18} /></button> : null}
    </div>
  </footer>;
}
